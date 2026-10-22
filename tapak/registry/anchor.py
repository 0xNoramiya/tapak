"""Optional external anchor log: entries deleted from the end of the registry become visible.

A hash chain cannot show that its newest entries were removed: a shorter chain is still a
valid chain. Someone who edits ``registry.db`` outside TAPAK and drops the newest ``trace``
entries hands the next trace of that document the same number k, and so the same larger
share eps * 6 / (pi^2 k^2), again. The anchor log closes that gap, provided it lives where
the person editing the registry cannot write:

* After every registry commit, TAPAK appends one line per new entry to an append-only text
  file outside the registry (``TAPAK_ANCHOR_LOG`` or ``tapak --log-jangkar``): the entry's
  ``seq``, ``entry_hash``, ``kind`` and ``created_at``, signed with the registry signing key
  when the entry itself was signed by it. Nothing else: no payload, no document text, no
  recipient data, only what the chain already exposes.
* At the start of every write transaction (so before every recorded trace and issuance),
  and in ``tapak verify``, every ``(seq, entry_hash)`` named by the log must still be in the
  registry, unchanged. An anchored entry that is gone (truncation), replaced (a fork: the
  tail dropped and other entries appended) or edited is an alarm, and the write is refused.
* A missing or unreadable log, while configured, is refused as well: deleting the log must
  not switch the check off. Recovery is always explicit and recorded in both the registry
  and the log: ``tapak jangkar mulai --ulang`` starts a new log after a loss and
  ``tapak jangkar akui`` acknowledges anchored entries that cannot be restored. Every later
  result (trace, berita acara, ``tapak verify``, web) names the acknowledgement or restart,
  since either can also hide a deletion made just before it.
* The registry records that a log is in use (an ``anchor_log`` entry), so a TAPAK process
  without the log configured refuses to write to such a registry instead of silently
  skipping the check.

Crash windows. Lines are written only after the registry transaction has committed, so a
line can never name an entry that a rollback took back: a log AHEAD of the registry head is
always an alarm. A crash between the commit and the line leaves the log behind by the entries
of that transaction; the next write completes them (they are committed and chain to the
anchored ones). A trace reads its evidence only after its own line is written, so an entry
lost in that window belongs to a trace that never decoded anything. A crash in the middle of
a line leaves a torn last line: it is ignored with a warning, and the next append starts on a
new line. Readers take a shared lock and writers an exclusive one, and a reader outside the
registry's write lock reads the log before the registry, so a line written meanwhile by
another process never looks like a line ahead.

File format: UTF-8, one canonical JSON object per line (sorted keys, no spaces) with
``v`` (1), ``type``, ``log_id`` (32 hex, fixed for the life of the file), ``created_at`` and
optionally ``sig``:

* ``start``: the first line, with ``restart`` (true when this log replaces a lost one) and the
  operator's ``reason`` (null for a first start). It anchors nothing itself;
* ``entry``: one per registry entry, with ``seq``, ``entry_hash`` and ``kind``;
* ``ack``: an acknowledged alarm, written after the matching ``anchor_log`` entry (event
  ``ack``) has committed. It anchors that entry like an ``entry`` line and carries
  ``released`` (the ``[seq, entry_hash]`` pairs that are no longer required to be in the
  registry) and ``reason``.

``sig`` is an Ed25519 signature (hex) over :data:`SIGN_CONTEXT` followed by the canonical JSON
of the line without ``sig``. The protection comes from where the file lives, not from the
signature: the signature only tells a genuine line from one added by someone without the key.

A ``start`` line written by this version also carries ``media``: the id in the marker file
(:data:`MEDIA_MARKER`) of the folder the log was started in. Every check requires that marker
next to the log, and a restart or rotation only creates a log in a folder that already holds
one (or with an explicit ``--tandai-media``), so a separate storage that is not mounted is not
silently replaced by the empty mount point folder on the local disk.

Segments. A log is refused above :data:`MAX_LOG_BYTES`. Before that, ``tapak jangkar rotasi``
continues it in a new file (a segment): its ``start`` line carries ``previous`` (the old log's
id, its length and SHA-256 at the rotation, the registry head it anchored, the acknowledgements
in force and how many trace entries they released) and its second line anchors that head again.
The registry records the rotation (``anchor_log`` event ``rotate``). Entries before the head are
then covered through the hash chain: the head is required, and the chain below it is checked.
A segment that does not anchor its head, or whose rotation is not recorded right after it, is
refused. Whoever can write the registry and create files on the log's medium can still forge a
rotation after a deletion; only the earlier segment exposes that (:func:`segment_chain`), so
every result names the rotation and the old log asks for that check before the switch.

Checks inside one process are incremental: the parsed lines and signature results of the
log's complete lines are kept with the SHA-256 of those bytes and reused only while the file
still starts with exactly those bytes; registry rows whose content hash was checked are kept
by a digest of the whole row. Anything else is a full check, so every result equals a full check.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import sys
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tapak.registry.chain import (
    KIND_ANCHOR,
    KIND_LABELS,
    KIND_TRACE,
    ZERO_HASH,
    Entry,
    Registry,
    RegistryError,
    anchor_payload_problems,
    canonical_json,
    entry_content_problems,
    parse_time,
    utc_now,
)
from tapak.registry.signing import Signer, verify_signature

ENV_VAR = "TAPAK_ANCHOR_LOG"
LINE_VERSION = 1
SIGN_CONTEXT = b"TAPAK-LOG-JANGKAR-1\n"
MAX_REASON = 300
# A larger file is refused (never read into memory): about 700,000 signed lines. Rotate first.
MAX_LOG_BYTES = 256 * 1024 * 1024
ROTATE_WARN_BYTES = MAX_LOG_BYTES * 3 // 4   # from here every check warns: rotate now
ROTATE_READ_LIMIT = MAX_LOG_BYTES * 2        # tapak jangkar rotasi may still read an oversized log
MEDIA_MARKER = ".tapak-jangkar-media"
# Why a configured log could not be read (AnchorStatus.unavailable), as the CLI states it.
UNAVAILABLE_LABELS = {"not_started": "BELUM DIMULAI", "missing": "HILANG", "too_large": "TERLALU BESAR",
                      "unreadable": "TIDAK TERBACA"}
LOCK_TIMEOUT_S = 10.0
_HEX = frozenset("0123456789abcdef")
_ANCHORED_KEYS = frozenset({"v", "type", "log_id", "seq", "entry_hash", "kind", "created_at"})
_LINE_KEYS = {
    "start": frozenset({"v", "type", "log_id", "created_at", "restart", "reason"}),
    "entry": _ANCHORED_KEYS,
    "ack": _ANCHORED_KEYS | {"released", "reason"},
}
_START_OPTIONAL = frozenset({"media", "previous"})
_PREVIOUS_KEYS = frozenset({"log_id", "bytes", "sha256", "seq", "entry_hash", "acks", "released_traces"})
LINE_TYPES = tuple(_LINE_KEYS)
RECOVERY_HINT = ("Pemulihan: kembalikan registri dari cadangan yang masih memuat entri itu, lalu ulangi. Bila entri itu "
                 "memang tidak dapat dikembalikan, catat pengakuan secara sadar dengan tapak jangkar akui --alasan '...' "
                 "(tercatat di registri dan di log jangkar; lihat docs/operasi.md)")


class AnchorError(RegistryError):
    """The anchor log refuses an operation or cannot be used (message in Indonesian)."""


class AnchorUnavailable(AnchorError):
    """The anchor log is missing (``missing``), larger than the limit (``too_large``, with its
    ``size`` in bytes), or cannot be read or written."""

    def __init__(self, message: str, missing: bool = False, too_large: bool = False, size: int = 0) -> None:
        super().__init__(message)
        self.missing = missing
        self.too_large = too_large
        self.size = size


class AnchorRefused(AnchorError):
    """The anchor log does not match the registry (or is missing): the write is refused."""

    def __init__(self, status: AnchorStatus) -> None:
        super().__init__(status.refusal())
        self.status = status


class AnchorWriteError(AnchorError):
    """The registry committed ``entries``, but their anchor lines could not be written."""

    def __init__(self, message: str, entries: Sequence[Entry]) -> None:
        super().__init__(message)
        self.entries = list(entries)


# --- lines -----------------------------------------------------------------------------------


def _is_hex(value: object, n: int) -> bool:
    return isinstance(value, str) and len(value) == n and set(value) <= _HEX


def _is_seq(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def reason_digest(reason: str | None) -> str | None:
    """SHA-256 (hex) of an operator's reason as stored in the registry, or None without one."""
    return None if reason is None else hashlib.sha256(reason.encode("utf-8")).hexdigest()


def clean_reason(reason: str | None, required: bool) -> str | None:
    """The operator's reason on one line (whitespace collapsed); AnchorError if it is required
    and missing, or longer than :data:`MAX_REASON` characters."""
    text = " ".join((reason or "").split())
    if not text:
        if required:
            raise AnchorError("alasan wajib diisi (--alasan): tulis singkat apa yang terjadi dan siapa yang memeriksa, "
                              "tanpa isi dokumen dan tanpa nama penerima")
        return None
    if len(text) > MAX_REASON:
        raise AnchorError(f"alasan terlalu panjang ({len(text)} karakter, paling banyak {MAX_REASON})")
    return text


@dataclass(frozen=True, slots=True)
class Previous:
    """What the first line of a segment commits to: the log it continues (``tapak jangkar rotasi``).

    ``bytes`` and ``sha256``: length and SHA-256 of the old log at the rotation; ``seq`` and
    ``entry_hash``: the registry head it anchored then; ``acks``: entry numbers of the
    acknowledgements in force; ``released_traces``: trace entries they released.
    """

    log_id: str
    bytes: int
    sha256: str
    seq: int
    entry_hash: str
    acks: tuple[int, ...] = ()
    released_traces: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON form, as written in the ``start`` line."""
        return {"log_id": self.log_id, "bytes": self.bytes, "sha256": self.sha256, "seq": self.seq,
                "entry_hash": self.entry_hash, "acks": list(self.acks), "released_traces": self.released_traces}


@dataclass(frozen=True, slots=True)
class AnchorLine:
    """One valid line of the anchor log (``number`` counts the file's lines from 1)."""

    number: int
    type: str
    log_id: str
    created_at: str
    seq: int = 0
    entry_hash: str = ""
    kind: str = ""
    released: tuple[tuple[int, str], ...] = ()
    reason: str | None = None
    restart: bool = False
    signature: str | None = None
    media: str | None = None
    previous: Previous | None = None

    @property
    def anchors(self) -> bool:
        """True if the line names a registry entry (``entry`` and ``ack`` lines)."""
        return self.type != "start"

    def body(self) -> dict[str, Any]:
        """The line as an object without ``sig``: what the signature covers."""
        if self.type == "start":
            return start_body(self.log_id, self.created_at, self.restart, self.reason, self.media, self.previous)
        body = entry_body(self.log_id, self.seq, self.kind, self.created_at, self.entry_hash)
        if self.type == "ack":
            body.update(type="ack", released=[list(p) for p in self.released], reason=self.reason)
        return body


def start_body(log_id: str, created_at: str, restart: bool, reason: str | None, media: str | None = None,
               previous: Previous | None = None) -> dict[str, Any]:
    """The ``start`` line of a new log (without signature). ``media`` and ``previous`` are left
    out when None, so lines written before they existed keep their form."""
    body: dict[str, Any] = {"v": LINE_VERSION, "type": "start", "log_id": log_id, "created_at": created_at,
                            "restart": bool(restart), "reason": reason}
    if media is not None:
        body["media"] = media
    if previous is not None:
        body["previous"] = previous.to_dict()
    return body


def entry_body(log_id: str, seq: int, kind: str, created_at: str, entry_hash: str) -> dict[str, Any]:
    """The ``entry`` line of one registry entry (without signature): identifiers and its hash only."""
    return {"v": LINE_VERSION, "type": "entry", "log_id": log_id, "seq": int(seq), "entry_hash": entry_hash,
            "kind": kind, "created_at": created_at}


def line_text(body: dict[str, Any], signer: Signer | None = None) -> str:
    """One line of the log: canonical JSON of ``body``, signed by ``signer`` if given, and a newline."""
    obj = dict(body)
    if signer is not None:
        obj["sig"] = signer.sign(SIGN_CONTEXT + canonical_json(body))
    return canonical_json(obj).decode("utf-8") + "\n"


def verify_line(line: AnchorLine, public_key_hex: str) -> bool:
    """True if ``line`` carries a valid signature by ``public_key_hex``."""
    return line.signature is not None and verify_signature(
        public_key_hex, SIGN_CONTEXT + canonical_json(line.body()), line.signature)


def _valid_time(value: object) -> bool:
    try:
        parse_time(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


def _valid_kind(value: object) -> bool:
    # Any short text: a kind is copied from the registry row, and a line that could not be read
    # back would make every later check write it again.
    return isinstance(value, str) and 0 < len(value) <= 200


def _valid_reason(value: object, required: bool) -> bool:
    if value is None:
        return not required
    return isinstance(value, str) and 0 < len(value) <= MAX_REASON and value == " ".join(value.split())


def _parse_previous(obj: object) -> Previous | None:
    if not isinstance(obj, dict) or set(obj) != _PREVIOUS_KEYS:
        return None
    acks, traces = obj["acks"], obj["released_traces"]
    if not (_is_hex(obj["log_id"], 32) and _is_seq(obj["bytes"]) and _is_hex(obj["sha256"], 64)
            and _is_seq(obj["seq"]) and _is_hex(obj["entry_hash"], 64) and isinstance(acks, list)
            and all(_is_seq(a) for a in acks) and acks == sorted(set(acks))
            and isinstance(traces, int) and not isinstance(traces, bool) and traces >= 0):
        return None
    return Previous(obj["log_id"], obj["bytes"], obj["sha256"], obj["seq"], obj["entry_hash"], tuple(acks), traces)


def parse_line(text: str, number: int) -> AnchorLine | None:
    """The line ``text`` (without its newline) as an :class:`AnchorLine`, or None if it is not a
    valid line of this format. Never raises."""
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != LINE_VERSION or isinstance(obj.get("v"), bool):
        return None
    kind_of_line = obj.get("type")
    if not isinstance(kind_of_line, str) or kind_of_line not in _LINE_KEYS:
        return None
    keys = set(obj) - {"sig"}
    optional = _START_OPTIONAL if kind_of_line == "start" else frozenset()
    if not _LINE_KEYS[kind_of_line] <= keys <= _LINE_KEYS[kind_of_line] | optional:
        return None
    sig = obj.get("sig")
    if "sig" in obj and not _is_hex(sig, 128):
        return None
    if not _is_hex(obj["log_id"], 32) or not _valid_time(obj["created_at"]):
        return None
    log_id = sys.intern(obj["log_id"])  # one string per log, not one per line, in a kept parse
    if kind_of_line == "start":
        if not isinstance(obj["restart"], bool) or not _valid_reason(obj["reason"], required=obj["restart"]):
            return None
        if "media" in obj and not _is_hex(obj["media"], 32):
            return None
        previous = _parse_previous(obj["previous"]) if "previous" in obj else None
        if "previous" in obj and (previous is None or obj["restart"]):
            return None
        return AnchorLine(number, "start", log_id, obj["created_at"], restart=obj["restart"],
                          reason=obj["reason"], signature=sig, media=obj.get("media"), previous=previous)
    if not (_is_seq(obj["seq"]) and _is_hex(obj["entry_hash"], 64) and _valid_kind(obj["kind"])):
        return None
    released: tuple[tuple[int, str], ...] = ()
    reason = None
    if kind_of_line == "ack":
        pairs = obj["released"]
        if not (isinstance(pairs, list) and pairs and all(
                isinstance(p, list) and len(p) == 2 and _is_seq(p[0]) and _is_hex(p[1], 64) for p in pairs)):
            return None
        released = tuple((p[0], p[1]) for p in pairs)
        if list(released) != sorted(set(released)) or not _valid_reason(obj["reason"], required=True):
            return None
        reason = obj["reason"]
    return AnchorLine(number, kind_of_line, log_id, obj["created_at"], seq=obj["seq"],
                      entry_hash=obj["entry_hash"], kind=sys.intern(obj["kind"]), released=released, reason=reason,
                      signature=sig)


# --- reading and writing the file ---------------------------------------------------------------


@dataclass
class AnchorFile:
    """What was read from the anchor log: valid lines, unreadable line numbers, a torn last line.

    ``memo``: results kept for the file's complete lines (see :func:`read_anchor_incremental`);
    None for a plain read.
    """

    path: Path
    lines: list[AnchorLine]
    unreadable: list[int] = field(default_factory=list)
    torn_tail: bool = False
    size: int = 0
    memo: _Memo | None = None


def parse_anchor_bytes(path: str | Path, data: bytes, first_number: int = 1) -> AnchorFile:
    """Parse the bytes of an anchor log. A last line without its newline is a torn write (a crash
    in the middle of an append) unless it parses as a complete line; it is never an error.
    ``first_number``: the number of the first line (when ``data`` is the tail of a log)."""
    parts = data.split(b"\n")
    lines: list[AnchorLine] = []
    unreadable: list[int] = []
    torn = False
    for number, raw in enumerate(parts, first_number):
        last = number == len(parts) + first_number - 1
        if last and raw == b"":
            break  # the file ends with a newline
        try:
            line = parse_line(raw.decode("utf-8"), number)
        except UnicodeDecodeError:
            line = None
        if line is not None:
            lines.append(line)
        elif last:
            torn = True
        else:
            unreadable.append(number)
    return AnchorFile(Path(path), lines, unreadable, torn, len(data))


def _lock(fd: int, mode: int, timeout: float = LOCK_TIMEOUT_S) -> None:
    """flock with a deadline, so a stuck process holding the lock cannot hang TAPAK forever."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() > deadline:
                raise AnchorUnavailable("log jangkar dikunci proses lain terlalu lama") from None
            time.sleep(0.02)


_ERRNO_TEXT = {
    errno.ENOENT: "berkas atau folder tidak ada", errno.EACCES: "tidak ada izin", errno.EPERM: "tidak diizinkan",
    errno.ENOSPC: "penyimpanan penuh", errno.EROFS: "penyimpanan hanya-baca", errno.EISDIR: "berupa folder",
    errno.ENOTDIR: "jalurnya bukan folder", errno.EIO: "galat masukan/keluaran penyimpanan",
    errno.ENXIO: "bukan berkas biasa", errno.ESTALE: "penyimpanan jaringan terputus",
}


def _why(exc: BaseException) -> str:
    """Short Indonesian reason for an OS error (TAPAK's own errors keep their message)."""
    if isinstance(exc, OSError) and exc.errno in _ERRNO_TEXT:
        return _ERRNO_TEXT[exc.errno]
    if isinstance(exc, OSError) and exc.errno is not None:
        return f"galat berkas {errno.errorcode.get(exc.errno, exc.errno)}"
    return str(exc)


def size_text(n: int) -> str:
    """'12,3 MiB' or, below 1 MiB, '45,6 KiB' (Indonesian decimal comma)."""
    value, unit = (n / 1048576, "MiB") if n >= 1048576 else (n / 1024, "KiB")
    return f"{value:.1f}".replace(".", ",") + " " + unit


def _too_large(path: Path, size: int, limit: int) -> AnchorUnavailable:
    return AnchorUnavailable(
        f"log jangkar di {path} terlalu besar ({size_text(size)}, batasnya {size_text(limit)}), jadi tidak dibaca. "
        "Teruskan ke segmen baru dengan tapak jangkar rotasi BERKAS_BARU (lihat docs/operasi.md)", too_large=True,
        size=size)


def read_log_bytes(path: str | Path, limit: int | None = None) -> bytes:
    """The bytes of the anchor log, read under a shared lock. AnchorUnavailable if it is missing
    (``missing=True``), not a regular file, larger than ``limit`` (default :data:`MAX_LOG_BYTES`;
    ``too_large=True``) or unreadable."""
    path = Path(path)
    limit = MAX_LOG_BYTES if limit is None else limit
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)  # a planted FIFO must not block the read
    except FileNotFoundError:
        raise AnchorUnavailable(f"log jangkar tidak ditemukan di {path}", missing=True) from None
    except OSError as exc:
        raise AnchorUnavailable(f"log jangkar di {path} tidak dapat dibuka ({_why(exc)})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AnchorUnavailable(f"log jangkar di {path} bukan berkas biasa")
        if info.st_size > limit:
            raise _too_large(path, info.st_size, limit)
        _lock(fd, fcntl.LOCK_SH)
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise _too_large(path, total, limit)
    except OSError as exc:
        raise AnchorUnavailable(f"log jangkar di {path} tidak dapat dibaca ({_why(exc)})") from None
    finally:
        os.close(fd)
    return b"".join(chunks)


def read_anchor_file(path: str | Path, limit: int | None = None) -> AnchorFile:
    """Read and parse the whole anchor log (see :func:`read_log_bytes` for the errors)."""
    return parse_anchor_bytes(path, read_log_bytes(path, limit))


# --- incremental checks within one process -------------------------------------------------------


@dataclass
class _Memo:
    """Results that depend only on bytes already seen, kept between checks of one log.

    ``size`` bytes of the log (its complete lines, up to and including the last newline) had
    SHA-256 ``digest`` and held ``count`` lines, of which ``lines`` were valid. ``signatures``
    maps a public key to ``(n, bad)``: the signatures of lines 1..n were checked with that key
    and ``bad`` are the numbers of the invalid ones. ``rows`` maps an entry number to the
    digest of a registry row whose payload and hash were found consistent: a pure function of
    the row, so it holds for any log.
    """

    size: int
    digest: bytes
    count: int
    lines: list[AnchorLine]
    unreadable: list[int]
    signatures: dict[str, tuple[int, frozenset[int]]] = field(default_factory=dict)
    rows: dict[int, bytes] = field(default_factory=dict)


_MEMO_SLOTS = 4
_MEMOS: OrderedDict[str, _Memo] = OrderedDict()
_MEMO_LOCK = threading.Lock()


def forget_memos() -> None:
    """Drop every kept result (the next check of every log is a full one)."""
    with _MEMO_LOCK:
        _MEMOS.clear()


def read_anchor_incremental(path: str | Path, limit: int | None = None) -> AnchorFile:
    """Like :func:`read_anchor_file`, but reuses the parse of an earlier read in this process.

    The whole file is still read under the shared lock and its complete lines hashed. The
    earlier parse is reused only when the file still begins with exactly the bytes it covered
    (same SHA-256), so only the lines appended since are parsed. A shorter file, any changed
    byte, or a log read for the first time is parsed in full: the result is always the same
    as :func:`read_anchor_file`. The returned file carries the memo for :func:`compare_anchor`.
    """
    path = Path(path)
    data = read_log_bytes(path, limit)
    key = os.path.abspath(path)
    with _MEMO_LOCK:
        old = _MEMOS.get(key)
    end = data.rfind(b"\n") + 1
    view = memoryview(data)
    hasher = hashlib.sha256()
    reuse = False
    if old is not None and old.size <= end:
        hasher.update(view[:old.size])
        reuse = hasher.digest() == old.digest
        if not reuse:
            hasher = hashlib.sha256()
    if reuse:
        assert old is not None
        tail = parse_anchor_bytes(path, data[old.size:], first_number=old.count + 1)
        lines, unreadable = old.lines + tail.lines, old.unreadable + tail.unreadable
        log = AnchorFile(path, lines, unreadable, tail.torn_tail, len(data))
        hasher.update(view[old.size:end])
        count = old.count + data.count(b"\n", old.size, end)
    else:
        log = parse_anchor_bytes(path, data)
        hasher.update(view[:end])
        count = data.count(b"\n", 0, end)
    complete = log.lines if not log.lines or log.lines[-1].number <= count else log.lines[:-1]
    memo = _Memo(end, hasher.digest(), count, complete, [n for n in log.unreadable if n <= count])
    if old is not None:
        memo.rows = old.rows  # keyed by the rows' own content
        if reuse:  # the same bytes, so the same lines 1..old.count: their signature results hold
            memo.signatures = dict(old.signatures)
    log.memo = memo
    with _MEMO_LOCK:
        _MEMOS[key] = memo
        _MEMOS.move_to_end(key)
        while len(_MEMOS) > _MEMO_SLOTS:
            _MEMOS.popitem(last=False)
    return log


def _ends_with_newline(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return True  # write-only storage: nothing to close
    try:
        size = os.fstat(fd).st_size
        return size == 0 or os.pread(fd, 1, size - 1) == b"\n"
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def append_lines(path: str | Path, lines: Sequence[str]) -> None:
    """Append complete lines to an existing anchor log under an exclusive lock, then fsync.

    The file is never created here: a missing log is an error, not something to recreate. A
    torn last line left by a crash is closed with a newline first, so the new lines stay whole.
    OSError or AnchorUnavailable on failure.
    """
    if not lines:
        return
    path = Path(path)
    data = "".join(lines).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise AnchorUnavailable(f"log jangkar di {path} bukan berkas biasa")
        _lock(fd, fcntl.LOCK_EX)
        if not _ends_with_newline(path):
            data = b"\n" + data
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def create_anchor_file(path: str | Path, first_line: str) -> None:
    """Create the anchor log with its first line; refuses (FileExistsError) an existing file.

    The parent folder is never created: when the separate storage is not mounted, the log must
    not silently land on the local disk instead.
    """
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        _write_all(fd, first_line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_folder(path.parent)


def _sync_folder(folder: Path) -> None:
    try:
        dfd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass  # some file systems cannot sync a directory; the file itself is synced
    finally:
        os.close(dfd)


def writable_problem(path: str | Path) -> str | None:
    """Why the anchor log cannot be appended to (Indonesian), or None. Opens it for appending
    and closes it again without writing: what every registry write needs before it records
    an entry."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NONBLOCK))
    except OSError as exc:
        return f"log jangkar di {path} tidak dapat ditulis ({_why(exc)})"
    return None


# --- the media marker -----------------------------------------------------------------------------


def read_media_id(folder: str | Path) -> str | None:
    """The id in the media marker (:data:`MEDIA_MARKER`) of ``folder``; None if there is none or
    it is not a marker."""
    try:
        fd = os.open(Path(folder) / MEDIA_MARKER, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        obj = json.loads(os.read(fd, 4096).decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    finally:
        os.close(fd)
    if not isinstance(obj, dict) or obj.get("type") != "media" or not _is_hex(obj.get("media_id"), 32):
        return None
    return obj["media_id"]


def create_media_marker(folder: str | Path) -> str:
    """Write a new media marker in ``folder`` (never over an existing file); return its id."""
    folder = Path(folder)
    media_id = secrets.token_hex(16)
    text = canonical_json({"v": 1, "type": "media", "media_id": media_id, "created_at": utc_now(),
                           "note": "penanda media log jangkar TAPAK; jangan dihapus atau dipindah tanpa log"})
    fd = os.open(folder / MEDIA_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        _write_all(fd, text + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_folder(folder)
    return media_id


def media_for_new_log(folder: str | Path, create: bool) -> str:
    """The media id for a log about to be created in ``folder``: the marker already there, or,
    with ``create``, a new one. AnchorError without a marker and without ``create``: the folder
    may be the empty mount point of a separate storage that is not mounted."""
    folder = Path(folder)
    found = read_media_id(folder)
    if found is not None:
        return found
    if (folder / MEDIA_MARKER).exists() or (folder / MEDIA_MARKER).is_symlink():
        raise AnchorError(f"penanda media {folder / MEDIA_MARKER} tidak dapat dibaca atau rusak. Periksa media itu; "
                          "pindahkan penandanya (simpan sebagai bukti) hanya bila media ini memang media log jangkar")
    if not create:
        raise AnchorError(
            f"folder {folder} tidak memuat penanda media log jangkar ({MEDIA_MARKER}). Penyimpanan terpisahnya "
            "mungkin belum dipasang, dan folder ini hanya titik kait kosong di disk lokal: pasang dulu penyimpanannya, "
            "lalu ulangi. Bila log memang dipindah ke media baru, atau media lama dipakai sebelum ada penanda, "
            "ulangi dengan --tandai-media")
    return create_media_marker(folder)


def mount_note(log_path: str | Path) -> str | None:
    """A note (Indonesian) when the log's folder is not a mount point, or None."""
    folder = Path(log_path).parent
    try:
        if os.path.ismount(folder):
            return None
    except OSError:
        return None
    return (f"folder {folder} bukan titik kait penyimpanan lain (perangkatnya sama dengan folder induknya). Itu wajar "
            "untuk berkas dengan chattr +a di disk yang sama. Bila log seharusnya berada di penyimpanan terpisah yang "
            "dipasang di folder ini, penyimpanan itu belum terpasang dan log ini tertulis di disk lokal: periksa dulu")


def _media_problem(path: Path, start: AnchorLine | None) -> str | None:
    """The media marker the log's start line names must sit next to the log."""
    if start is None or start.media is None or read_media_id(path.parent) == start.media:
        return None
    return (f"penanda media log jangkar ({MEDIA_MARKER}, id {start.media[:8]}) tidak ada di samping log di "
            f"{path.parent} atau berbeda. Penyimpanan terpisahnya mungkin belum dipasang dan berkas ini salinan di disk "
            "lokal, atau log dipindah tanpa penandanya. Pasang penyimpanannya, atau pindahkan penanda bersama log")


def read_registry_rows(registry_path: str | Path) -> list[tuple[Any, ...]]:
    """Every registry row as stored (see ``Registry.raw_rows``), read-only; [] if the file does not
    exist. sqlite3.Error for a file that is not a registry."""
    path = Path(registry_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("SELECT seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer "
                            "FROM entries ORDER BY seq").fetchall()
    finally:
        conn.close()


# --- comparing the log with the registry ----------------------------------------------------------


def _payload(text: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return None


def anchor_events(rows: Sequence[Sequence[Any]]) -> list[tuple[int, dict[str, Any]]]:
    """``(seq, payload)`` of every valid ``anchor_log`` entry among registry ``rows``, in order."""
    out = []
    for row in rows:
        if row[1] == KIND_ANCHOR and isinstance(row[0], int):
            payload = _payload(row[2])
            if not anchor_payload_problems(payload):
                out.append((row[0], payload))
    return out


def required_by(rows: Sequence[Sequence[Any]]) -> int | None:
    """Entry number of the first ``anchor_log`` event: from there on the registry requires an
    anchor log for every write. None for a registry that never used one."""
    events = anchor_events(rows)
    return events[0][0] if events else None


def _numbers(values: Sequence[int], limit: int = 6) -> str:
    """'3, 7 dan 9' style list of line numbers, shortened after ``limit``."""
    shown = [str(v) for v in values[:limit]]
    more = f" dan {len(values) - limit} lainnya" if len(values) > limit else ""
    return ", ".join(shown) + more


def seq_span(seqs: Sequence[int]) -> str:
    """'#5', '#5..#7' or '#5..#7, #9' for entry numbers (runs compressed)."""
    values = sorted(set(seqs))
    runs: list[list[int]] = []
    for v in values:
        if runs and v == runs[-1][1] + 1:
            runs[-1][1] = v
        else:
            runs.append([v, v])
    text = [f"#{a}" if a == b else f"#{a}..#{b}" for a, b in runs[:5]]
    if len(runs) > 5:
        text.append(f"dan {len(runs) - 5} rentang lain")
    return ", ".join(text)


def _kinds(lines: Sequence[AnchorLine]) -> str:
    counts = Counter(KIND_LABELS.get(line.kind, line.kind) for line in {line.seq: line for line in lines}.values())
    return ", ".join(f"{n} {label}" for label, n in sorted(counts.items()))


@dataclass
class AnchorStatus:
    """Outcome of comparing the anchor log with the registry.

    Attributes:
        configured: an anchor log location is set for this process.
        required_by: entry number of the first ``anchor_log`` event (from there on the
            registry requires an anchor log), or None.
        anchored_seq: highest entry number named by the log that the registry still has
            unchanged; ``lag`` registry entries after it are not in the log yet.
        completed: entries whose missing lines this check wrote (crash completion).
        recorded: entries appended after this check whose lines were written.
        acks: ``(seq, created_at)`` of the acknowledgement lines in force; ``released`` the
            pairs they released, ``released_traces`` how many of those the log names as
            ``trace`` entries (their trace numbers can be handed out again).
        restarted: ``(seq, created_at)`` of the registry entry that started this log again
            after an earlier one was lost or moved (``tapak jangkar mulai --ulang``), or None.
            Entries deleted before that point are invisible to this log, so every result says so.
            Also set for a later segment of such a log.
        rotated: ``(seq, created_at, previous log id)`` when this log is a segment that
            continues another one (``tapak jangkar rotasi``), or None. Named in every result:
            only the earlier segment proves the rotation was made at the true head
            (:func:`segment_chain`).
        releasable: anchored pairs the registry no longer has, or has differently (what an
            acknowledgement would release); ``blocking``: problems no acknowledgement can
            release (a broken chain, a forged or foreign line, a log not recorded).
        storage: problems with where the log is kept or which file is configured, not with
            what it says (it cannot be written, its media marker is missing, it was rotated
            away from); each one says what to do. ``unwritable``: the log can be read but not
            appended to.
        missing: configured, but the log is missing or cannot be read; ``unavailable`` says
            why: "not_started" (no log at that location and the registry does not use one
            yet), "missing" (the registry uses a log and it is not there), "too_large" (over
            :data:`MAX_LOG_BYTES`; rotate it) or "unreadable".
        size: length of the log file in bytes.
    """

    configured: bool = False
    path: str | None = None
    log_id: str | None = None
    required_by: int | None = None
    lines: int = 0
    signed_lines: int = 0
    anchored_seq: int = 0
    registry_head: int = 0
    lag: int = 0
    completed: list[int] = field(default_factory=list)
    recorded: list[int] = field(default_factory=list)
    acks: list[tuple[int, str]] = field(default_factory=list)
    released: list[tuple[int, str]] = field(default_factory=list)
    released_traces: int = 0
    restarted: tuple[int, str] | None = None
    rotated: tuple[int, str, str] | None = None
    releasable: list[tuple[int, str]] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    storage: list[str] = field(default_factory=list)
    unwritable: bool = False
    missing: bool = False
    unavailable: str | None = None
    size: int = 0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_storage_problem(self, text: str) -> None:
        """Record a problem with where the log is kept (it blocks writes like any other)."""
        self.storage.append(text)
        self.blocking.append(text)
        self.problems.append(text)
        self.lag = 0

    @property
    def ok(self) -> bool:
        """True if the log matches the registry (always True when no log is configured)."""
        return not self.problems

    def describe(self) -> str:
        """One Indonesian sentence on the state of the anchor log (for the trace result)."""
        if not self.configured:
            if self.required_by is not None:
                return (f"TIDAK DIATUR, padahal registri ini memakai log jangkar sejak entri #{self.required_by}; atur "
                        "TAPAK_ANCHOR_LOG atau --log-jangkar ke lokasi log itu")
            return ("tidak diatur; entri yang dihapus dari ujung registri hanya terdeteksi dengan log jangkar di "
                    "penyimpanan terpisah (tapak jangkar mulai) atau dengan jangkar yang tercetak di berita acara "
                    "(tapak verify --jangkar)")
        if self.problems:
            more = f"; dan {len(self.problems) - 3} masalah lain" if len(self.problems) > 3 else ""
            head = UNAVAILABLE_LABELS.get(self.unavailable or "", "TIDAK COCOK dengan registri")
            return f"{head}: " + "; ".join(self.problems[:3]) + more
        parts = [f"cocok dengan registri sampai entri #{self.anchored_seq}" if self.anchored_seq
                 else "cocok dengan registri (belum ada entri yang dijangkarkan)"]
        if self.lag:
            parts.append(f"{self.lag} entri terakhir ({seq_span(range(self.anchored_seq + 1, self.registry_head + 1))}) "
                         "belum tercatat di log dan dilengkapi pada penulisan berikutnya")
        if self.completed:
            parts.append(f"baris yang tertinggal untuk entri {seq_span(self.completed)} dilengkapi")
        if self.recorded:
            parts.append(f"entri baru {seq_span(self.recorded)} dicatat di log")
        if self.acks:
            parts.append(f"log memuat {len(self.acks)} pengakuan pemulihan, terakhir {self.acks[-1][1]} "
                         f"({len(self.released)} entri dilepas; lihat tapak verify)")
        if self.released_traces:
            parts.append(f"{self.released_traces} entri pelacakan di antaranya hilang dari registri, jadi nomor dan jatah "
                         "eps pelacakan itu dapat terpakai lagi dan batas tuduhan salah gabungan untuk dokumennya tidak "
                         "lagi terjamin")
        if self.restarted:
            parts.append(restart_note(*self.restarted))
        if self.rotated:
            # Like a restart, a forged rotation could hide a deletion made before it: name it.
            parts.append(f"log ini segmen lanjutan sejak entri #{self.rotated[0]} (tapak jangkar rotasi); rotasi itu "
                         "terbukti sah hanya dengan segmen lamanya (tapak verify --segmen-lama)")
        if self.warnings:
            parts.append("peringatan: " + "; ".join(self.warnings[:2]))
        return "; ".join(parts)

    def summary(self) -> str:
        """``describe`` with its label, as one line of the trace output."""
        return "Log jangkar: " + self.describe()

    def refusal(self) -> str:
        """Why a write or trace is refused (Indonesian), with how to recover deliberately."""
        if self.missing or not self.configured or (self.problems and self.problems == self.storage):
            return "; ".join(self.problems) or self.describe()
        return (f"log jangkar {self.path} tidak cocok dengan registri: " + "; ".join(self.problems[:4])
                + ". Entri yang pernah tercatat hilang atau berubah, misalnya entri pelacakan yang dihapus dari ujung "
                "registri, sehingga nomor pelacakan dan jatah eps tidak dapat dipastikan. Periksa dengan tapak verify. "
                + RECOVERY_HINT)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return {"configured": self.configured, "path": self.path, "log_id": self.log_id, "ok": self.ok,
                "required_by": self.required_by, "lines": self.lines, "signed_lines": self.signed_lines,
                "anchored_seq": self.anchored_seq, "registry_head": self.registry_head, "lag": self.lag,
                "completed": list(self.completed), "recorded": list(self.recorded),
                "acks": [list(a) for a in self.acks], "released": [list(p) for p in self.released],
                "released_traces": self.released_traces,
                "restarted": list(self.restarted) if self.restarted else None,
                "rotated": list(self.rotated) if self.rotated else None, "missing": self.missing,
                "unavailable": self.unavailable, "size": self.size,
                "storage": list(self.storage), "unwritable": self.unwritable, "problems": list(self.problems),
                "warnings": list(self.warnings)}


def restart_note(seq: int, created_at: str) -> str:
    """Indonesian clause for a log that was started again (``tapak jangkar mulai --ulang``)."""
    return (f"log ini dimulai ulang di entri #{seq} ({created_at}) setelah log sebelumnya hilang atau dipindah; "
            "entri yang dihapus dari ujung registri sebelum itu tidak terlihat oleh log ini (periksa dengan log lama "
            "atau jangkar berita acara, tapak verify --jangkar)")


def unconfigured_status(rows: Sequence[Sequence[Any]]) -> AnchorStatus:
    """Status for a process without an anchor log location (it may still be required)."""
    return AnchorStatus(configured=False, required_by=required_by(rows),
                        registry_head=rows[-1][0] if rows and isinstance(rows[-1][0], int) else 0)


def unavailable_status(path: str | Path, rows: Sequence[Sequence[Any]], exc: AnchorUnavailable) -> AnchorStatus:
    """Status for a configured log that is missing or cannot be read: always a problem, with how
    to recover (never by starting a new log automatically)."""
    st = AnchorStatus(configured=True, path=str(path), missing=True, required_by=required_by(rows),
                      registry_head=rows[-1][0] if rows and isinstance(rows[-1][0], int) else 0)
    if exc.missing and st.required_by is None:
        st.unavailable = "not_started"
        st.problems.append(f"log jangkar belum dimulai di {path}: jalankan tapak jangkar mulai (lokasi ini diatur "
                           "lewat TAPAK_ANCHOR_LOG atau --log-jangkar)")
    elif exc.missing:
        st.unavailable = "missing"
        st.problems.append(
            f"log jangkar tidak ditemukan di {path}, padahal registri memakai log jangkar sejak entri #{st.required_by}. "
            "Penyimpanannya mungkin belum dipasang, atau log itu dihapus (orang yang menghapus entri dari ujung "
            "registri juga ingin menghapus log ini), jadi pelacakan dan penulisan registri ditolak. Pasang kembali "
            "penyimpanannya. Bila log memang hilang, periksa dulu registri dengan tapak verify (dengan jangkar dari "
            "berita acara atau akar Merkle bila ada), lalu mulai log baru secara sadar dengan tapak jangkar mulai "
            "--ulang --alasan '...'; awal yang baru tercatat di registri")
    elif exc.too_large:
        st.unavailable, st.size = "too_large", exc.size
        st.problems.append(f"{exc}. Sampai saat itu pelacakan dan penulisan registri ditolak; jangan menghapus atau "
                           "memotong log ini")
    else:
        st.unavailable = "unreadable"
        st.problems.append(f"{exc}; pelacakan dan penulisan registri ditolak selama log jangkar tidak dapat dibaca. "
                           "Perbaiki izin atau penyimpanannya; jangan menghapus atau mengganti log ini")
    st.blocking = list(st.problems)
    return st


def _row_key(row: Sequence[Any]) -> bytes | None:
    """SHA-256 of the six hashed columns of a raw row, the variable ones length-prefixed so that
    no two different rows share a key; None for a row of another shape (always checked in full)."""
    seq, kind, payload, prev_hash, created_at, entry_hash = row[:6]
    if (type(seq) is not int or type(kind) is not str or type(payload) is not str or type(created_at) is not str
            or type(prev_hash) is not str or type(entry_hash) is not str or len(prev_hash) != 64
            or len(entry_hash) != 64):
        return None
    text = f"{seq}|{len(kind)}|{kind}{len(payload)}|{payload}{len(created_at)}|{created_at}{prev_hash}{entry_hash}"
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest()


def _content_problems(row: Sequence[Any], memo: _Memo | None, seen: dict[int, list[str]] | None = None) -> list[str]:
    """``entry_content_problems`` of a raw row. A row found consistent is remembered in ``memo``
    by its key, so the same row is not hashed again in a later check; ``seen`` holds the
    results of this check by row object."""
    if seen is not None and id(row) in seen:
        return seen[id(row)]
    key = _row_key(row) if memo is not None else None
    if memo is not None and key is not None and memo.rows.get(row[0]) == key:
        problems: list[str] = []
    else:
        problems = entry_content_problems(*row[:6])
        if memo is not None and key is not None and not problems:
            memo.rows[row[0]] = key
    if seen is not None:
        seen[id(row)] = problems
    return problems


def _chain_break(rows: Sequence[Sequence[Any]], upto: int, memo: _Memo | None = None,
                 seen: dict[int, list[str]] | None = None) -> tuple[int, str] | None:
    """First entry up to ``upto`` whose number, link or hash is wrong, with the reason."""
    prev, expected = ZERO_HASH, 1
    for row in rows:
        seq = row[0]
        if not isinstance(seq, int) or seq > upto:
            break
        if seq != expected:
            return seq, "nomor urut tidak berurutan"
        if row[3] != prev:
            return seq, "mata rantai terputus"
        if _content_problems(row, memo, seen):
            return seq, "isi atau hash entri diubah"
        prev, expected = row[5], expected + 1
    return None


def compare_anchor(log: AnchorFile, rows: Sequence[Sequence[Any]], public_key: str | None = None,
                   check_chain: bool = True, starting: bool = False) -> AnchorStatus:
    """Compare a parsed anchor log with registry ``rows`` (``Registry.raw_rows``). Never raises.

    Every ``(seq, entry_hash)`` the log names must be in the registry with that hash, a hash
    that still matches the entry's content, and the kind and time the line states, unless an
    acknowledgement line (backed by its ``ack`` entry in the registry) released it. The log
    must start with one ``start`` line whose log id the registry recorded (``starting``: the
    start command is recording it now) and that no later start or rotation replaced. Signed
    lines must verify with ``public_key`` when it is given. ``check_chain`` also checks the hash
    links of the anchored part of the registry (``tapak verify`` checks the whole chain itself).
    A log read with :func:`read_anchor_incremental` reuses the results kept in its memo.
    """
    st = AnchorStatus(configured=True, path=str(log.path), size=log.size)
    by_seq: dict[int, Sequence[Any]] = {}
    for row in rows:
        if isinstance(row[0], int):
            by_seq.setdefault(row[0], row)
    st.registry_head = rows[-1][0] if rows and isinstance(rows[-1][0], int) else 0
    events = anchor_events(rows)
    st.required_by = events[0][0] if events else None
    if log.torn_tail:
        st.warnings.append("baris terakhir log jangkar terpotong (penulisan terputus, misalnya mati listrik) dan "
                           "diabaikan; baris berikutnya ditulis di baris baru")
    if log.unreadable:
        st.warnings.append(f"baris ke-{_numbers(log.unreadable)} log jangkar tidak dapat dibaca dan diabaikan")
    if log.size >= ROTATE_WARN_BYTES:
        st.warnings.append(f"log jangkar sudah {size_text(log.size)}; di atas {size_text(MAX_LOG_BYTES)} log tidak dibaca "
                           "lagi dan semua pelacakan dan penerbitan ditolak. Teruskan sekarang ke segmen baru dengan "
                           "tapak jangkar rotasi BERKAS_BARU (lihat docs/operasi.md)")
    lines = log.lines
    st.lines = len(lines)
    if not lines:
        st.problems.append("log jangkar tidak memuat satu baris pun yang sah (kosong, atau isinya dihapus atau rusak)")
        st.blocking = list(st.problems)
        return st
    start = next((line for line in lines if line.type == "start"), None)
    st.log_id = (start or lines[0]).log_id
    if lines[0].type != "start":
        st.blocking.append(f"baris pertama log jangkar yang terbaca (baris ke-{lines[0].number}) bukan baris awal: log "
                           "dipotong dari depan atau disunting")
    extra = [line.number for line in lines if line.type == "start" and line is not start]
    if extra:
        st.blocking.append(f"log jangkar memuat lebih dari satu baris awal (baris ke-{_numbers(extra)})")
    foreign = [line.number for line in lines if line.log_id != st.log_id]
    if foreign:
        st.blocking.append(f"baris ke-{_numbers(foreign)} milik log jangkar lain (id berbeda dengan baris awal)")
    carried: set[tuple[int, str]] = set()
    if start is not None:
        carried = _check_registration(st, start, events, starting)
        head = start.previous
        if head is not None and not any(line.anchors and (line.seq, line.entry_hash) == (head.seq, head.entry_hash)
                                        for line in lines):
            st.blocking.append(f"segmen log jangkar ini tidak menjangkarkan ujung registri #{head.seq} yang diikat baris "
                               "awalnya, jadi entri sebelum rotasi tidak terlindungi (segmen disunting atau dipalsukan)")
    _check_signatures(st, lines, public_key, log.memo)
    excused = _acknowledged(st, lines, by_seq) | carried
    st.released = sorted(excused)
    _check_anchored(st, lines, by_seq, excused, check_chain, rows, log.memo)
    st.problems = st.blocking + st.problems
    if not st.problems and st.registry_head > st.anchored_seq:
        st.lag = st.registry_head - st.anchored_seq
    return st


_SEGMENT_EVENTS = ("start", "restart", "rotate")


def _check_registration(st: AnchorStatus, start: AnchorLine, events: list[tuple[int, dict[str, Any]]],
                        starting: bool) -> set[tuple[int, str]]:
    """The registry must record the start of this log, and no later start or rotation may have
    replaced it. A segment (``tapak jangkar rotasi``) must continue the log in use before it,
    and the acknowledgements it carries over must be in the registry; returns the pairs they
    released. A restart at the head of this chain of segments is named in ``st.restarted``."""
    starts = [(seq, p) for seq, p in events if p["event"] in _SEGMENT_EVENTS]
    mine = [i for i, (_, p) in enumerate(starts) if p["log_id"] == start.log_id]
    if not mine:
        if not starting:
            st.blocking.append(f"log jangkar ini (id {start.log_id[:8]}) belum tercatat di registri: log tidak dimulai "
                               "dengan tapak jangkar mulai, atau mulai terputus. Jalankan tapak jangkar mulai untuk "
                               "menyelesaikannya")
        return set()
    index = mine[0]
    seq, payload = starts[index]
    mismatch = ((payload["event"] == "restart") != start.restart
                or (payload["event"] == "rotate") != (start.previous is not None)
                or payload["reason_sha256"] != reason_digest(start.reason))
    if mismatch:
        st.blocking.append(f"baris awal log jangkar tidak cocok dengan entri registri #{seq} yang memulainya")
    first = index
    while first > 0 and starts[first][1]["event"] == "rotate":
        first -= 1
    if starts[first][1]["event"] == "restart":
        st.restarted = (starts[first][0], starts[first][1]["created_at"])
    carried: set[tuple[int, str]] = set()
    if start.previous is not None and not mismatch:
        prior = starts[index - 1][1]["log_id"] if index else None
        if seq != start.previous.seq + 1:
            # tapak jangkar rotasi records the rotation right after the head it commits to.
            st.blocking.append(f"baris awal segmen log jangkar ini mengikat ujung registri #{start.previous.seq}, padahal "
                               f"rotasinya tercatat di entri #{seq}; rotasi selalu tercatat tepat sesudah ujung yang "
                               "diikatnya (segmen atau registri disunting)")
        elif prior != start.previous.log_id:
            st.blocking.append(f"baris awal segmen log jangkar ini meneruskan log id {start.previous.log_id[:8]}, padahal "
                               f"registri mencatat log lain sebagai log yang dipakai sebelum entri #{seq}")
        else:
            st.rotated = (seq, payload["created_at"], start.previous.log_id)
            carried = _carried_acks(st, start.previous, events, {p["log_id"] for _, p in starts[first:index]})
    later = [(s, p) for s, p in starts[index + 1:] if p["log_id"] != start.log_id]
    if later and later[0][1]["event"] == "rotate":  # a setting to change, not a mismatch
        # Whoever can write the registry and create files on the log's medium can also forge a
        # rotation that hides a deletion: the switch is made only after the chain is checked.
        moved = (f"log jangkar ini sudah diteruskan ke segmen baru (tapak jangkar rotasi, log id "
                 f"{later[0][1]['log_id'][:8]}) di entri registri #{later[0][0]}. Periksa dulu rantai segmennya dengan "
                 f"tapak verify --log-jangkar BERKAS_SEGMEN_BARU --segmen-lama {st.path}; bila lulus, arahkan "
                 "TAPAK_ANCHOR_LOG atau --log-jangkar ke segmen baru itu dan simpan berkas ini sebagai segmen lama")
        st.blocking.append(moved)
        st.storage.append(moved)
    elif later:
        # Starting a new log is also how someone would hide a deletion from this one: never
        # tell the operator to switch without checking what this log still shows.
        st.blocking.append(f"log jangkar ini sudah diganti log lain yang dimulai ulang di entri registri #{later[0][0]}. "
                           "Arahkan TAPAK_ANCHOR_LOG atau --log-jangkar ke log baru itu hanya bila awal ulang itu "
                           "memang dilakukan operator dengan sengaja, dan periksa dulu masalah lain yang ditunjukkan "
                           "log ini dengan tapak verify")
    return carried


def _carried_acks(st: AnchorStatus, previous: Previous, events: list[tuple[int, dict[str, Any]]],
                  earlier_logs: set[str]) -> set[tuple[int, str]]:
    """Acknowledgements from the logs a segment continues. Every ``ack`` entry the registry holds
    for those logs is named (an omitted one cannot vanish from later results), and each one the
    segment's first line lists must be among them. Adds them to ``st.acks``; returns the pairs
    they released."""
    earlier = [(seq, p) for seq, p in events if p["event"] == "ack" and p["log_id"] in earlier_logs]
    released: set[tuple[int, str]] = set()
    for seq, payload in earlier:
        st.acks.append((seq, payload["created_at"]))
        released.update((pair[0], pair[1]) for pair in payload["released"])
    unknown = sorted(set(previous.acks) - {seq for seq, _ in earlier})
    if unknown:
        st.blocking.append(f"baris awal segmen log jangkar ini menyebut pengakuan di entri {seq_span(unknown)}, tetapi "
                           "registri tidak mencatat pengakuan itu untuk log sebelumnya")
    st.released_traces += previous.released_traces
    return released


def _check_signatures(st: AnchorStatus, lines: list[AnchorLine], public_key: str | None,
                      memo: _Memo | None = None) -> None:
    checked: int = 0
    known_bad: frozenset[int] = frozenset()
    if memo is not None and public_key is not None:
        checked, known_bad = memo.signatures.get(public_key, (0, frozenset()))
    bad = []
    for line in lines:
        if line.signature is None:
            continue
        st.signed_lines += 1
        if public_key is None:
            continue
        if line.number <= checked:
            if line.number in known_bad:
                bad.append(line.number)
        elif not verify_line(line, public_key):
            bad.append(line.number)
    if memo is not None and public_key is not None:
        memo.signatures[public_key] = (memo.count, frozenset(n for n in bad if n <= memo.count))
    if bad:
        st.blocking.append(f"tanda tangan baris ke-{_numbers(bad)} log jangkar tidak sah untuk kunci publik registri "
                           "(baris dipalsukan atau diubah)")
    if st.signed_lines and public_key is None:
        st.warnings.append("tanda tangan baris log jangkar tidak diperiksa karena kunci publik registri tidak tersedia")


def _acknowledged(st: AnchorStatus, lines: list[AnchorLine], by_seq: dict[int, Sequence[Any]]) -> set[tuple[int, str]]:
    """Pairs released by acknowledgement lines whose ``ack`` entry is in the registry, unchanged."""
    excused: set[tuple[int, str]] = set()
    for line in lines:
        if line.type != "ack" or line.log_id != st.log_id:
            continue
        row = by_seq.get(line.seq)
        if row is None or row[5] != line.entry_hash:
            continue  # its own anchor is reported as missing or different
        payload = _payload(row[2])
        if not (row[1] == KIND_ANCHOR and not anchor_payload_problems(payload) and payload["event"] == "ack"
                and payload["log_id"] == line.log_id and payload["released"] == [list(p) for p in line.released]
                and payload["reason_sha256"] == reason_digest(line.reason)):
            st.blocking.append(f"baris pengakuan ke-{line.number} log jangkar tidak cocok dengan entri registri "
                               f"#{line.seq}")
            continue
        excused.update(line.released)
        st.acks.append((line.seq, line.created_at))
    st.released_traces += len({(line.seq, line.entry_hash) for line in lines
                               if line.anchors and line.kind == KIND_TRACE and (line.seq, line.entry_hash) in excused})
    return excused


def _check_anchored(st: AnchorStatus, lines: list[AnchorLine], by_seq: dict[int, Sequence[Any]],
                    excused: set[tuple[int, str]], check_chain: bool, rows: Sequence[Sequence[Any]],
                    memo: _Memo | None = None) -> None:
    """Every anchored pair that was not released must be in the registry, unchanged."""
    head = st.registry_head
    seen: dict[int, list[str]] = {}  # rows are fixed during one check: hash each one once
    missing, replaced, edited, differ = [], [], [], []
    upto = 0
    for line in lines:
        if not line.anchors or (line.seq, line.entry_hash) in excused:
            continue
        row = by_seq.get(line.seq)
        if row is None:
            missing.append(line)
            continue
        upto = max(upto, line.seq)
        if row[5] != line.entry_hash:
            replaced.append(line)
        elif _content_problems(row, memo, seen):
            edited.append(line)
        elif row[1] != line.kind or row[4] != line.created_at:
            differ.append(line)
        else:
            st.anchored_seq = max(st.anchored_seq, line.seq)
    if missing:
        seqs = sorted({line.seq for line in missing})
        where = (f"registri kini berakhir di entri #{head}" if head else "registri kini kosong atau tidak ada")
        cause = ("entri dihapus dari ujung rantai, atau registri diganti salinan yang lebih lama"
                 if all(s > head for s in seqs) else "entri dihapus dari rantai")
        st.problems.append(f"log jangkar mencatat entri {seq_span(seqs)} ({_kinds(missing)}) yang tidak ada lagi di "
                           f"registri; {where}: {cause}")
    if replaced:
        st.problems.append(f"entri {seq_span([line.seq for line in replaced])} di registri berbeda dari log jangkar: "
                           "entri itu diganti entri lain (ujung rantai dihapus lalu ditambah entri baru sehingga "
                           "rantai bercabang, atau registri ditulis ulang)")
    st.releasable = sorted({(line.seq, line.entry_hash) for line in missing + replaced})
    if edited:
        st.blocking.append(f"isi entri {seq_span([line.seq for line in edited])} diubah: hash yang tersimpan masih sama "
                           "dengan log jangkar, tetapi tidak cocok lagi dengan isinya")
    if differ:
        st.blocking.append(f"baris log jangkar untuk entri {seq_span([line.seq for line in differ])} menyebut jenis atau "
                           "waktu yang berbeda dari registri (log atau registri disunting)")
    if check_chain and upto:
        broken = _chain_break(rows, upto, memo, seen)
        flagged = {line.seq for line in replaced + edited}
        if broken is not None and broken[0] not in flagged:
            st.blocking.append(f"rantai registri rusak di entri #{broken[0]} ({broken[1]}), di dalam bagian yang "
                               f"dijangkarkan log jangkar (sampai entri #{upto})")


# --- the configured log -------------------------------------------------------------------------


class AnchorLog:
    """The anchor log configured for this process: checks it and appends to it.

    Pass it to ``Registry.open(path, anchor=...)``: the registry calls :meth:`prepare` at the
    start of every write transaction and :meth:`record` after each commit. ``signer`` signs a
    line when the entry it names was signed by the same key; ``public_key`` verifies signed
    lines. ``starting`` is set only by :func:`start_log` and :func:`rotate_log` while they
    record a new log's start. ``protected`` lists folders (data, keys) the log should not live
    in: a log there gets a warning, since whoever edits the registry can most likely edit it
    too. ``limit``: the largest log it reads (default :data:`MAX_LOG_BYTES`). The latest check
    is kept in :attr:`status`.
    """

    def __init__(self, path: str | Path, signer: Signer | None = None, public_key: str | None = None,
                 starting: bool = False, protected: Sequence[str | Path] = (), limit: int | None = None) -> None:
        self.path = Path(path)
        self.signer = signer
        self.public_key = public_key
        self.starting = starting
        self.protected = list(protected)
        self.limit = limit
        self.status: AnchorStatus | None = None

    def read(self) -> AnchorFile:
        """The log as it is now (AnchorUnavailable if missing or unreadable). Incremental within
        this process (:func:`read_anchor_incremental`)."""
        return read_anchor_incremental(self.path, self.limit)

    def _finish(self, status: AnchorStatus, log: AnchorFile | None = None) -> AnchorStatus:
        if log is not None:
            problem = _media_problem(self.path, next((line for line in log.lines if line.type == "start"), None))
            if problem:
                status.add_storage_problem(problem)
        status.warnings += location_warnings(self.path, self.protected)
        return status

    def inspect(self, rows: Sequence[Sequence[Any]]) -> AnchorStatus:
        """Read the log now and compare it with ``rows``, which must have been read under the
        registry's write lock or before this call (see the module notes). Never raises."""
        try:
            log = self.read()
        except AnchorUnavailable as exc:
            return self._finish(unavailable_status(self.path, rows, exc))
        return self._finish(compare_anchor(log, rows, self.public_key, starting=self.starting), log)

    def inspect_registry_file(self, registry_path: str | Path) -> AnchorStatus:
        """Read-only check outside the write lock: the log first, then the registry. Never raises.

        Also probes, like :meth:`prepare`, that the log can be appended to (nothing is written):
        a log that cannot be written refuses every trace and issuance, so it is a problem here too.
        """
        error = None
        try:
            log: AnchorFile | None = self.read()
        except AnchorUnavailable as exc:
            log, error = None, exc
        try:
            rows = read_registry_rows(registry_path)
        except sqlite3.Error:
            st = AnchorStatus(configured=True, path=str(self.path))
            st.problems.append(f"registri {registry_path} tidak dapat dibaca untuk dibandingkan dengan log jangkar")
            st.blocking = list(st.problems)
            return st
        if log is None:
            assert error is not None
            return self._finish(unavailable_status(self.path, rows, error))
        status = self._finish(compare_anchor(log, rows, self.public_key, starting=self.starting), log)
        problem = writable_problem(self.path)
        if problem:
            status.unwritable = True
            status.add_storage_problem(f"{problem}; pelacakan dan penerbitan ditolak sebelum entri baru dicatat. "
                                       "Perbaiki izin atau penyimpanannya")
        return status

    def _sign_for(self, signed_by: str | None) -> Signer | None:
        if self.signer is not None and signed_by is not None and signed_by == self.signer.public_key_hex:
            return self.signer
        return None

    def prepare(self, registry: Registry, require_writable: bool = True) -> AnchorStatus:
        """Inside the registry's write transaction: refuse (AnchorRefused) when the log does not
        match the registry or cannot be read, and write the lines of committed entries the log
        is still missing (a crash between an earlier commit and its lines). Refuses a log that
        cannot be appended to unless ``require_writable`` is False (a rotation away from it)."""
        rows = registry.raw_rows()
        status = self.inspect(rows)
        if status.problems:
            raise AnchorRefused(status)
        problem = writable_problem(self.path) if require_writable else None
        if problem:  # before anything commits: a read-only log must not cost a trace its number
            raise AnchorUnavailable(f"{problem}; penulisan registri ditolak sebelum entri baru dicatat. Perbaiki izin "
                                    "atau penyimpanannya")
        if status.lag:
            todo = [row for row in rows if isinstance(row[0], int) and row[0] > status.anchored_seq]
            texts = [line_text(entry_body(str(status.log_id), row[0], row[1], row[4], row[5]), self._sign_for(row[7]))
                     for row in todo]
            try:
                append_lines(self.path, texts)
            except (OSError, AnchorUnavailable) as exc:
                raise AnchorUnavailable(f"baris log jangkar untuk entri {seq_span([r[0] for r in todo])} yang tertinggal "
                                        f"tidak dapat ditulis ke {self.path} ({_why(exc)}); penulisan registri ditolak "
                                        "sampai log jangkar dapat ditulis lagi") from exc
            status.completed = [row[0] for row in todo]
            status.anchored_seq, status.lag = status.registry_head, 0
            if len(todo) > 1 and not self.starting:
                status.warnings.append(f"{len(todo)} entri terakhir registri belum tercatat di log jangkar (ditulis proses "
                                       "tanpa log jangkar, misalnya tapak canary-dns --anchor, atau penulisan "
                                       "terputus); dilengkapi sekarang")
        self.status = status
        return status

    def record(self, entries: list[Entry]) -> None:
        """After a commit: one line per new entry. AnchorWriteError if they cannot be written
        (the entries stay committed; the next write completes their lines)."""
        status = self.status
        seqs = [e.seq for e in entries]
        if status is None or status.log_id is None:
            raise AnchorWriteError(f"entri {seq_span(seqs)} tercatat tanpa pemeriksaan log jangkar", entries)
        texts = [line_text(entry_body(status.log_id, e.seq, e.kind, e.created_at, e.entry_hash), self._sign_for(e.signer))
                 for e in entries]
        try:
            append_lines(self.path, texts)
        except (OSError, AnchorUnavailable) as exc:
            raise AnchorWriteError(f"entri {seq_span(seqs)} sudah tercatat di registri, tetapi baris log jangkarnya tidak "
                                   f"dapat ditulis ke {self.path} ({_why(exc)}); baris itu dilengkapi otomatis pada "
                                   "penulisan berikutnya setelah log jangkar dapat ditulis lagi", entries) from exc
        status.recorded.extend(seqs)
        status.anchored_seq = status.registry_head = max([status.anchored_seq, *seqs])


# --- operator commands ------------------------------------------------------------------------------


def _require_intact(rows: Sequence[Sequence[Any]], registry_path: str | Path, public_key: str | None) -> None:
    broken = _chain_break(rows, rows[-1][0] if rows and isinstance(rows[-1][0], int) else 0)
    if broken is not None:
        raise AnchorError(f"rantai registri rusak di entri #{broken[0]} ({broken[1]}); log jangkar tidak dimulai di atas "
                          "registri yang rusak. Periksa dengan tapak verify")
    if public_key and rows:
        from tapak.registry.verify import verify_registry

        report = verify_registry(registry_path, public_key, require_signed=False)
        if not report.ok:
            raise AnchorError("verifikasi registri gagal (" + "; ".join(text for _, text in report.problems[:3])
                              + "); log jangkar tidak dimulai di atas registri yang rusak. Periksa dengan tapak verify")


def _resume_header(path: Path, rows: Sequence[Sequence[Any]], restart: bool, reason: str | None) -> AnchorLine:
    """The start line of a log whose start was interrupted before the registry recorded it; the
    command must be repeated exactly (same ``--ulang`` and reason)."""
    exists = (f"log jangkar sudah ada di {path} dan tidak ditimpa. Bila log itu rusak atau milik registri lain, "
              "pindahkan dulu ke tempat lain (simpan sebagai bukti), lalu jalankan tapak jangkar mulai lagi")
    try:
        log = read_anchor_file(path)
    except AnchorUnavailable as exc:
        raise AnchorError(f"{exc}. {exists}") from None
    header = log.lines[0] if log.lines and log.lines[0].type == "start" else None
    if header is None:
        raise AnchorError(exists)
    events = anchor_events(rows)
    recorded = [seq for seq, p in events if p["log_id"] == header.log_id]
    if recorded:
        raise AnchorError(f"log jangkar di {path} sudah dimulai dan tercatat di registri (entri #{recorded[0]}); tidak "
                          "perlu dimulai lagi")
    if (header.restart != bool(events) or header.previous is not None
            or log.lines[1:] and any(line.type != "entry" for line in log.lines[1:])):
        raise AnchorError(exists)
    if restart != header.restart:
        raise AnchorError(f"log jangkar di {path} dimulai {'dengan' if header.restart else 'tanpa'} --ulang tetapi "
                          "belum tercatat di registri; ulangi perintah yang sama untuk menyelesaikannya")
    if reason != header.reason:
        raise AnchorError(f"alasan berbeda dengan yang tertulis di log jangkar {path}, yang mulainya belum tercatat di "
                          "registri; ulangi perintah yang sama untuk menyelesaikannya")
    return header


def _require_folder(path: Path) -> None:
    if not path.parent.is_dir():
        raise AnchorError(f"folder {path.parent} untuk log jangkar tidak ada. Pasang dulu penyimpanan terpisahnya; TAPAK "
                          "tidak membuat folder ini, agar log tidak diam-diam tertulis di disk lokal")


def start_log(registry_path: str | Path, path: str | Path, signer: Signer | None = None,
              public_key: str | None = None, reason: str | None = None, restart: bool = False,
              protected: Sequence[str | Path] = (), mark_media: bool = False) -> AnchorStatus:
    """``tapak jangkar mulai``: create the anchor log and record its start in the registry.

    The log file is written first (its ``start`` line), then the registry entry of kind
    ``anchor_log`` through an anchored registry, which also writes a line for every existing
    entry. A start interrupted between the two is finished by running the same command again.
    Refuses when the parent folder is missing, the registry chain is broken, or the registry
    already uses a log (``restart`` with a ``reason`` starts a new log after a loss, and the
    restart is recorded); never overwrites an existing log. A first start marks the folder
    with a media marker if it has none; a restart needs the marker already there (or
    ``mark_media``), see :func:`media_for_new_log`. ``protected``: see :class:`AnchorLog`.
    """
    path = Path(path)
    reason = clean_reason(reason, required=restart)
    _require_folder(path)
    rows = read_registry_rows(registry_path)
    events = anchor_events(rows)
    _require_intact(rows, registry_path, public_key)
    if path.exists() or path.is_symlink():
        log_id = _resume_header(path, rows, restart, reason).log_id
    else:
        if events and not restart:
            raise AnchorError(f"registri memakai log jangkar sejak entri #{events[0][0]} (log terakhir id "
                              f"{events[-1][1]['log_id'][:8]}), jadi log jangkar pernah ada. Log yang hilang tidak "
                              "dimulai ulang diam-diam: periksa dulu "
                              "registri dengan tapak verify (dengan jangkar dari berita acara atau akar Merkle bila ada), "
                              "lalu mulai log baru secara sadar dengan tapak jangkar mulai --ulang --alasan '...'")
        if restart and not events:
            raise AnchorError("registri belum memakai log jangkar; jalankan tapak jangkar mulai tanpa --ulang")
        media = media_for_new_log(path.parent, create=mark_media or not restart)
        log_id = secrets.token_hex(16)
        create_anchor_file(path, line_text(start_body(log_id, utc_now(), restart, reason, media), signer))
    log = AnchorLog(path, signer=signer, public_key=public_key, starting=True, protected=protected)
    with Registry.open(registry_path, anchor=log) as reg, reg.transaction():
        pending = bool(reg.pending())
        reg.record_anchor_event(event="restart" if restart else "start", log_id=log_id,
                                reason_sha256=reason_digest(reason), signer=None if pending else signer)
    assert log.status is not None
    return log.status


def rotate_log(registry_path: str | Path, old_path: str | Path, new_path: str | Path, signer: Signer | None = None,
               public_key: str | None = None, reason: str | None = None, mark_media: bool = False,
               protected: Sequence[str | Path] = ()) -> AnchorStatus:
    """``tapak jangkar rotasi``: continue the anchor log in a new segment file.

    All under the registry's write lock: the current log must match the registry (lines it is
    missing are written first; it need not be writable otherwise, so a full or finalised medium
    can still be rotated away from). The new file gets a ``start`` line that commits to the old
    log (:class:`Previous`: its id, the length and SHA-256 of all its bytes, the head it
    anchors, the acknowledgements in force) and an ``entry`` line that anchors that head again.
    Then the registry records the rotation (``anchor_log`` event ``rotate``), whose line goes to
    the new file after the commit. The old file is not written again; keep it. Refuses an
    existing new file, a folder without a media marker (unless ``mark_media``) and a log that
    does not match. Returns the new segment's status.
    """
    old_path, new_path = Path(old_path), Path(new_path)
    reason = clean_reason(reason, required=False)
    _require_folder(new_path)
    if new_path.exists() or new_path.is_symlink():
        raise AnchorError(f"berkas {new_path} sudah ada dan tidak ditimpa. Bila itu segmen dari rotasi yang terputus "
                          "(belum tercatat di registri), pindahkan dulu ke tempat lain (simpan sebagai bukti), lalu "
                          "jalankan perintah ini lagi")
    media = media_for_new_log(new_path.parent, create=mark_media)
    old = AnchorLog(old_path, signer=signer, public_key=public_key, protected=protected, limit=ROTATE_READ_LIMIT)
    new = AnchorLog(new_path, signer=signer, public_key=public_key, starting=True, protected=protected)
    with Registry.open(registry_path) as reg, reg.transaction():
        status = old.prepare(reg, require_writable=False)
        data = read_log_bytes(old_path, ROTATE_READ_LIMIT)
        head = reg.raw_rows()[-1]
        previous = Previous(str(status.log_id), len(data), hashlib.sha256(data).hexdigest(), head[0], head[5],
                            tuple(sorted({seq for seq, _ in status.acks})), status.released_traces)
        log_id = secrets.token_hex(16)
        create_anchor_file(new_path, line_text(start_body(log_id, utc_now(), False, reason, media, previous), signer)
                           + line_text(entry_body(log_id, head[0], head[1], head[4], head[5]), old._sign_for(head[7])))
        new.prepare(reg)
        entry = reg.record_anchor_event(event="rotate", log_id=log_id, reason_sha256=reason_digest(reason),
                                        signer=None if reg.pending() else signer)
    new.record([entry])
    return new.inspect_registry_file(registry_path)


def _first_line(data: bytes) -> AnchorLine | None:
    try:
        return parse_line(data.split(b"\n", 1)[0].decode("utf-8"), 1)
    except UnicodeDecodeError:
        return None


def _head_of(path: str | Path) -> AnchorLine | None:
    """The first line of a log file (read without loading the whole file), or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, 1 << 20)
    except OSError:
        return None
    finally:
        os.close(fd)
    return _first_line(data)


def segment_chain(older: Sequence[str | Path], current: AnchorFile, rows: Sequence[Sequence[Any]],
                  public_key: str | None = None) -> tuple[list[str], list[str]]:
    """Check the chain of log segments (``tapak verify --segmen-lama``); return (problems, warnings).

    ``older`` are the earlier segment files, oldest first. Each one must be followed (by the
    next one, the last by ``current``) by a segment whose ``start`` line commits to it: the
    same log id, the same bytes up to the recorded length (SHA-256), and those bytes anchor the
    recorded head and nothing after it. Every old segment's start must be recorded in the
    registry ``rows``. Those bytes must also have matched the registry at the rotation, as
    ``tapak jangkar rotasi`` requires: while the registry still holds the recorded head, its
    entries up to the head are the ones of that moment (the hash chain pins them), so the
    segment is compared with them like a configured log (``public_key`` checks its signed
    lines; the hash links are left to ``verify_registry``, the only caller, which walks the
    whole chain). This is what exposes a forged rotation made after a deletion. Bytes appended to an
    old segment after its rotation are a warning when they only name entries up to that head
    (a writer finishing its lines), a problem otherwise. One segment is read at a time.
    """
    problems: list[str] = []
    warnings: list[str] = []
    recorded = {p["log_id"] for _, p in anchor_events(rows) if p["event"] in _SEGMENT_EVENTS}
    for index, path in enumerate(Path(p) for p in older):
        if index + 1 < len(older):
            successor, head = Path(older[index + 1]), _head_of(older[index + 1])
        else:
            successor, head = current.path, next((line for line in current.lines if line.type == "start"), None)
        try:
            data = read_log_bytes(path, ROTATE_READ_LIMIT)
        except AnchorUnavailable as exc:
            problems.append(f"segmen lama: {exc}")
            continue
        own = _first_line(data)
        prev = head.previous if head is not None and head.type == "start" else None
        if own is None or own.type != "start" or own.log_id not in recorded:
            problems.append(f"segmen lama {path} tidak dimulai dengan baris awal yang tercatat di registri")
            continue
        if prev is None or prev.log_id != own.log_id:
            problems.append(f"{successor} tidak meneruskan segmen lama {path} (id {own.log_id[:8]}): baris awalnya "
                            "menyebut log sebelumnya yang lain, atau tidak menyebutnya; urutkan --segmen-lama dari "
                            "yang paling lama")
            continue
        if len(data) < prev.bytes or hashlib.sha256(data[:prev.bytes]).hexdigest() != prev.sha256:
            problems.append(f"segmen lama {path} tidak sama dengan isi yang dicatat saat rotasi ({prev.bytes} byte "
                            f"pertama, SHA-256 {prev.sha256[:16]}): segmen dipotong, disunting, atau diganti")
            continue
        sealed = parse_anchor_bytes(path, data[:prev.bytes])
        within = {(line.seq, line.entry_hash) for line in sealed.lines if line.anchors}
        if (prev.seq, prev.entry_hash) not in within or any(seq > prev.seq for seq, _ in within):
            problems.append(f"segmen lama {path} tidak berakhir di entri #{prev.seq} yang dicatat saat rotasi")
        pinned = [row for row in rows if isinstance(row[0], int) and row[0] <= prev.seq]
        if pinned and (pinned[-1][0], pinned[-1][5]) == (prev.seq, prev.entry_hash):
            sealed.size = 0  # an archived segment: its size is no longer a limit to warn about
            then = compare_anchor(sealed, pinned, public_key, check_chain=False)  # verify_registry walks the chain
            problems.extend(f"segmen lama {path} tidak cocok dengan registri saat rotasi: {p}" for p in then.problems)
            warnings.extend(f"segmen lama {path}: {w}" for w in then.warnings)
        else:  # the head itself is gone: the segment after it reports that (missing or acknowledged)
            warnings.append(f"segmen lama {path} tidak dapat dicocokkan dengan registri, karena entri #{prev.seq} yang "
                            "diikat saat rotasi tidak ada lagi di registri")
        if len(data) > prev.bytes:
            later = [line.seq for line in parse_anchor_bytes(path, data[prev.bytes:]).lines
                     if line.anchors and line.seq > prev.seq]
            if later:
                problems.append(f"segmen lama {path} memuat baris untuk entri {seq_span(later)} yang ditulis setelah "
                                "rotasi; entri itu seharusnya hanya di segmen berikutnya")
            else:
                warnings.append(f"segmen lama {path} memuat {len(data) - prev.bytes} byte yang ditulis setelah rotasi, "
                                "hanya untuk entri sebelum rotasi (proses yang sedang menulis saat itu)")
    return problems, warnings


def plan_acknowledgement(registry_path: str | Path, log: AnchorLog) -> AnchorStatus:
    """What ``tapak jangkar akui`` would release (``releasable``), read-only. AnchorError when
    the log cannot be read or shows problems no acknowledgement can release (``blocking``)."""
    try:
        log.read()
    except AnchorUnavailable as exc:
        raise AnchorError(f"{exc}. Pengakuan memerlukan log jangkar yang terbaca; bila log hilang, mulai log baru "
                          "dengan tapak jangkar mulai --ulang --alasan '...'") from None
    status = log.inspect_registry_file(registry_path)
    _ack_allowed(status)
    return status


def _ack_allowed(status: AnchorStatus) -> None:
    if status.blocking:
        raise AnchorError("pengakuan hanya dapat melepas entri yang hilang atau diganti; masalah ini harus diperbaiki "
                          "dulu: " + "; ".join(status.blocking[:3]))
    if not status.releasable:
        raise AnchorError("log jangkar cocok dengan registri; tidak ada entri yang perlu diakui")


def acknowledge(registry_path: str | Path, log: AnchorLog, reason: str | None) -> AnchorStatus:
    """``tapak jangkar akui``: release the anchored entries the registry no longer has.

    Only for an alarm that restoring the registry cannot resolve. The ``ack`` entry (released
    pairs, SHA-256 of the reason) is committed first; its line, with the reason, is appended
    afterwards. If that line cannot be written, the alarm stays and the command can simply be
    run again (the earlier ``ack`` entry then releases nothing). Returns the new status.
    """
    reason = clean_reason(reason, required=True)
    try:
        log.read()
    except AnchorUnavailable as exc:
        raise AnchorError(f"{exc}. Pengakuan memerlukan log jangkar yang terbaca; bila log hilang, mulai log baru "
                          "dengan tapak jangkar mulai --ulang --alasan '...'") from None
    # Without the anchor hook: its check would refuse the very alarm acknowledged here.
    with Registry.open(registry_path) as reg, reg.transaction():
        status = log.inspect(reg.raw_rows())
        _ack_allowed(status)
        entry = reg.record_anchor_event(event="ack", log_id=str(status.log_id), released=status.releasable,
                                        reason_sha256=reason_digest(reason),
                                        signer=None if reg.pending() else log.signer)
    body = entry_body(str(status.log_id), entry.seq, entry.kind, entry.created_at, entry.entry_hash)
    body.update(type="ack", released=[list(p) for p in status.releasable], reason=reason)
    try:
        append_lines(log.path, [line_text(body, log._sign_for(entry.signer))])
    except (OSError, AnchorUnavailable) as exc:
        raise AnchorWriteError(f"pengakuan tercatat di registri sebagai entri #{entry.seq}, tetapi barisnya tidak dapat "
                               f"ditulis ke log jangkar ({_why(exc)}); jalankan perintah ini lagi setelah log dapat "
                               "ditulis", [entry]) from exc
    return log.inspect_registry_file(registry_path)


def location_warnings(path: str | Path, protected: Sequence[str | Path]) -> list[str]:
    """Warnings (Indonesian) when the anchor log sits inside a folder of ``protected`` (the data or
    key folder): whoever can edit the registry can then most likely edit the log too."""
    try:
        target = Path(path).resolve()
    except OSError:
        return []
    out = []
    for folder in protected:
        try:
            root = Path(folder).resolve()
        except OSError:
            continue
        if target == root or root in target.parents:
            out.append(f"log jangkar berada di dalam {folder}, bersama registri atau kunci; siapa pun yang dapat "
                       "menyunting registri kemungkinan juga dapat menyunting log ini, jadi log ini tidak melindungi "
                       "dari penghapusan. Pindahkan ke akun lain, media tulis-sekali, atau mesin lain (lihat "
                       "docs/operasi.md)")
    return out
