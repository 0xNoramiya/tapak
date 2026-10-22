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
  ``tapak jangkar akui`` acknowledges anchored entries that cannot be restored.
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
import time
from collections import Counter
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
MAX_LOG_BYTES = 256 * 1024 * 1024
LOCK_TIMEOUT_S = 10.0
_HEX = frozenset("0123456789abcdef")
_ANCHORED_KEYS = frozenset({"v", "type", "log_id", "seq", "entry_hash", "kind", "created_at"})
_LINE_KEYS = {
    "start": frozenset({"v", "type", "log_id", "created_at", "restart", "reason"}),
    "entry": _ANCHORED_KEYS,
    "ack": _ANCHORED_KEYS | {"released", "reason"},
}
LINE_TYPES = tuple(_LINE_KEYS)
RECOVERY_HINT = ("Pemulihan: kembalikan registri dari cadangan yang masih memuat entri itu, lalu ulangi. Bila entri itu "
                 "memang tidak dapat dikembalikan, catat pengakuan secara sadar dengan tapak jangkar akui --alasan '...' "
                 "(tercatat di registri dan di log jangkar; lihat docs/operasi.md)")


class AnchorError(RegistryError):
    """The anchor log refuses an operation or cannot be used (message in Indonesian)."""


class AnchorUnavailable(AnchorError):
    """The anchor log is missing (``missing``), or cannot be read or written."""

    def __init__(self, message: str, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


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


@dataclass(frozen=True)
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

    @property
    def anchors(self) -> bool:
        """True if the line names a registry entry (``entry`` and ``ack`` lines)."""
        return self.type != "start"

    def body(self) -> dict[str, Any]:
        """The line as an object without ``sig``: what the signature covers."""
        if self.type == "start":
            return start_body(self.log_id, self.created_at, self.restart, self.reason)
        body = entry_body(self.log_id, self.seq, self.kind, self.created_at, self.entry_hash)
        if self.type == "ack":
            body.update(type="ack", released=[list(p) for p in self.released], reason=self.reason)
        return body


def start_body(log_id: str, created_at: str, restart: bool, reason: str | None) -> dict[str, Any]:
    """The ``start`` line of a new log (without signature)."""
    return {"v": LINE_VERSION, "type": "start", "log_id": log_id, "created_at": created_at,
            "restart": bool(restart), "reason": reason}


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
    if set(obj) - {"sig"} != _LINE_KEYS[kind_of_line]:
        return None
    sig = obj.get("sig")
    if "sig" in obj and not _is_hex(sig, 128):
        return None
    if not _is_hex(obj["log_id"], 32) or not _valid_time(obj["created_at"]):
        return None
    if kind_of_line == "start":
        if not isinstance(obj["restart"], bool) or not _valid_reason(obj["reason"], required=obj["restart"]):
            return None
        return AnchorLine(number, "start", obj["log_id"], obj["created_at"], restart=obj["restart"],
                          reason=obj["reason"], signature=sig)
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
    return AnchorLine(number, kind_of_line, obj["log_id"], obj["created_at"], seq=obj["seq"],
                      entry_hash=obj["entry_hash"], kind=obj["kind"], released=released, reason=reason, signature=sig)


# --- reading and writing the file ---------------------------------------------------------------


@dataclass
class AnchorFile:
    """What was read from the anchor log: valid lines, unreadable line numbers, a torn last line."""

    path: Path
    lines: list[AnchorLine]
    unreadable: list[int] = field(default_factory=list)
    torn_tail: bool = False
    size: int = 0


def parse_anchor_bytes(path: str | Path, data: bytes) -> AnchorFile:
    """Parse the bytes of an anchor log. A last line without its newline is a torn write (a crash
    in the middle of an append) unless it parses as a complete line; it is never an error."""
    parts = data.split(b"\n")
    lines: list[AnchorLine] = []
    unreadable: list[int] = []
    torn = False
    for number, raw in enumerate(parts, 1):
        last = number == len(parts)
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


def read_anchor_file(path: str | Path) -> AnchorFile:
    """Read and parse the anchor log under a shared lock. AnchorUnavailable if it is missing
    (``missing=True``), not a regular file, too large or unreadable."""
    path = Path(path)
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
        if info.st_size > MAX_LOG_BYTES:
            raise AnchorUnavailable(f"log jangkar di {path} terlalu besar ({info.st_size} byte)")
        _lock(fd, fcntl.LOCK_SH)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > MAX_LOG_BYTES:
                raise AnchorUnavailable(f"log jangkar di {path} terlalu besar")
    except OSError as exc:
        raise AnchorUnavailable(f"log jangkar di {path} tidak dapat dibaca ({_why(exc)})") from None
    finally:
        os.close(fd)
    return parse_anchor_bytes(path, b"".join(chunks))


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
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass  # some file systems cannot sync a directory; the file itself is synced
    finally:
        os.close(dfd)


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
        releasable: anchored pairs the registry no longer has, or has differently (what an
            acknowledgement would release); ``blocking``: problems no acknowledgement can
            release (a broken chain, a forged or foreign line, a log not recorded).
        missing: configured, but the log is missing or cannot be read.
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
    releasable: list[tuple[int, str]] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    missing: bool = False
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

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
            return "TIDAK COCOK dengan registri: " + "; ".join(self.problems[:3]) + more
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
        if self.warnings:
            parts.append("peringatan: " + "; ".join(self.warnings[:2]))
        return "; ".join(parts)

    def summary(self) -> str:
        """``describe`` with its label, as one line of the trace output."""
        return "Log jangkar: " + self.describe()

    def refusal(self) -> str:
        """Why a write or trace is refused (Indonesian), with how to recover deliberately."""
        if self.missing or not self.configured:
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
                "released_traces": self.released_traces, "missing": self.missing, "problems": list(self.problems),
                "warnings": list(self.warnings)}


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
        st.problems.append(f"log jangkar belum dimulai di {path}: jalankan tapak jangkar mulai (lokasi ini diatur "
                           "lewat TAPAK_ANCHOR_LOG atau --log-jangkar)")
    elif exc.missing:
        st.problems.append(
            f"log jangkar tidak ditemukan di {path}, padahal registri memakai log jangkar sejak entri #{st.required_by}. "
            "Penyimpanannya mungkin belum dipasang, atau log itu dihapus (orang yang menghapus entri dari ujung "
            "registri juga ingin menghapus log ini), jadi pelacakan dan penulisan registri ditolak. Pasang kembali "
            "penyimpanannya. Bila log memang hilang, periksa dulu registri dengan tapak verify (dengan jangkar dari "
            "berita acara atau akar Merkle bila ada), lalu mulai log baru secara sadar dengan tapak jangkar mulai "
            "--ulang --alasan '...'; awal yang baru tercatat di registri")
    else:
        st.problems.append(f"{exc}; pelacakan dan penulisan registri ditolak selama log jangkar tidak dapat dibaca. "
                           "Perbaiki izin atau penyimpanannya; jangan menghapus atau mengganti log ini")
    st.blocking = list(st.problems)
    return st


def _chain_break(rows: Sequence[Sequence[Any]], upto: int) -> tuple[int, str] | None:
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
        if entry_content_problems(*row[:6]):
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
    start command is recording it now) and that no later start replaced. Signed lines must
    verify with ``public_key`` when it is given. ``check_chain`` also checks the hash links of
    the anchored part of the registry (``tapak verify`` checks the whole chain itself).
    """
    st = AnchorStatus(configured=True, path=str(log.path))
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
    if start is not None:
        _check_registration(st, start, events, starting)
    _check_signatures(st, lines, public_key)
    excused = _acknowledged(st, lines, by_seq)
    _check_anchored(st, lines, by_seq, excused, check_chain, rows)
    st.problems = st.blocking + st.problems
    if not st.problems and st.registry_head > st.anchored_seq:
        st.lag = st.registry_head - st.anchored_seq
    return st


def _check_registration(st: AnchorStatus, start: AnchorLine, events: list[tuple[int, dict[str, Any]]],
                        starting: bool) -> None:
    """The registry must record the start of this log, and no later start may have replaced it."""
    starts = [(seq, p) for seq, p in events if p["event"] in ("start", "restart")]
    mine = [(seq, p) for seq, p in starts if p["log_id"] == start.log_id]
    if not mine:
        if not starting:
            st.blocking.append(f"log jangkar ini (id {start.log_id[:8]}) belum tercatat di registri: log tidak dimulai "
                               "dengan tapak jangkar mulai, atau mulai terputus. Jalankan tapak jangkar mulai untuk "
                               "menyelesaikannya")
        return
    seq, payload = mine[0]
    if (payload["event"] == "restart") != start.restart or payload["reason_sha256"] != reason_digest(start.reason):
        st.blocking.append(f"baris awal log jangkar tidak cocok dengan entri registri #{seq} yang memulainya")
    later = [s for s, p in starts if s > seq and p["log_id"] != start.log_id]
    if later:
        st.blocking.append(f"log jangkar ini sudah diganti log lain yang dimulai di entri registri #{later[-1]}; "
                           "arahkan TAPAK_ANCHOR_LOG atau --log-jangkar ke log yang baru")


def _check_signatures(st: AnchorStatus, lines: list[AnchorLine], public_key: str | None) -> None:
    bad = []
    for line in lines:
        if line.signature is None:
            continue
        st.signed_lines += 1
        if public_key is not None and not verify_line(line, public_key):
            bad.append(line.number)
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
    st.released = sorted(excused)
    st.released_traces = len({(line.seq, line.entry_hash) for line in lines
                              if line.anchors and line.kind == KIND_TRACE and (line.seq, line.entry_hash) in excused})
    return excused


def _check_anchored(st: AnchorStatus, lines: list[AnchorLine], by_seq: dict[int, Sequence[Any]],
                    excused: set[tuple[int, str]], check_chain: bool, rows: Sequence[Sequence[Any]]) -> None:
    """Every anchored pair that was not released must be in the registry, unchanged."""
    head = st.registry_head
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
        elif entry_content_problems(*row[:6]):
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
        broken = _chain_break(rows, upto)
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
    lines. ``starting`` is set only by :func:`start_log` while it records a new log's start.
    ``protected`` lists folders (data, keys) the log should not live in: a log there gets a
    warning, since whoever edits the registry can most likely edit it too. The latest check
    is kept in :attr:`status`.
    """

    def __init__(self, path: str | Path, signer: Signer | None = None, public_key: str | None = None,
                 starting: bool = False, protected: Sequence[str | Path] = ()) -> None:
        self.path = Path(path)
        self.signer = signer
        self.public_key = public_key
        self.starting = starting
        self.protected = list(protected)
        self.status: AnchorStatus | None = None

    def read(self) -> AnchorFile:
        """The log as it is now (AnchorUnavailable if missing or unreadable)."""
        return read_anchor_file(self.path)

    def _finish(self, status: AnchorStatus) -> AnchorStatus:
        status.warnings += location_warnings(self.path, self.protected)
        return status

    def inspect(self, rows: Sequence[Sequence[Any]]) -> AnchorStatus:
        """Read the log now and compare it with ``rows``, which must have been read under the
        registry's write lock or before this call (see the module notes). Never raises."""
        try:
            log = self.read()
        except AnchorUnavailable as exc:
            return self._finish(unavailable_status(self.path, rows, exc))
        return self._finish(compare_anchor(log, rows, self.public_key, starting=self.starting))

    def inspect_registry_file(self, registry_path: str | Path) -> AnchorStatus:
        """Read-only check outside the write lock: the log first, then the registry. Never raises."""
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
        return self._finish(compare_anchor(log, rows, self.public_key, starting=self.starting))

    def _sign_for(self, signed_by: str | None) -> Signer | None:
        if self.signer is not None and signed_by is not None and signed_by == self.signer.public_key_hex:
            return self.signer
        return None

    def prepare(self, registry: Registry) -> AnchorStatus:
        """Inside the registry's write transaction: refuse (AnchorRefused) when the log does not
        match the registry or cannot be read, and write the lines of committed entries the log
        is still missing (a crash between an earlier commit and its lines)."""
        rows = registry.raw_rows()
        status = self.inspect(rows)
        if status.problems:
            raise AnchorRefused(status)
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
    if header.restart != bool(events) or log.lines[1:] and any(line.type != "entry" for line in log.lines[1:]):
        raise AnchorError(exists)
    if restart != header.restart:
        raise AnchorError(f"log jangkar di {path} dimulai {'dengan' if header.restart else 'tanpa'} --ulang tetapi "
                          "belum tercatat di registri; ulangi perintah yang sama untuk menyelesaikannya")
    if reason != header.reason:
        raise AnchorError(f"alasan berbeda dengan yang tertulis di log jangkar {path}, yang mulainya belum tercatat di "
                          "registri; ulangi perintah yang sama untuk menyelesaikannya")
    return header


def start_log(registry_path: str | Path, path: str | Path, signer: Signer | None = None,
              public_key: str | None = None, reason: str | None = None, restart: bool = False,
              protected: Sequence[str | Path] = ()) -> AnchorStatus:
    """``tapak jangkar mulai``: create the anchor log and record its start in the registry.

    The log file is written first (its ``start`` line), then the registry entry of kind
    ``anchor_log`` through an anchored registry, which also writes a line for every existing
    entry. A start interrupted between the two is finished by running the same command again.
    Refuses when the parent folder is missing, the registry chain is broken, or the registry
    already uses a log (``restart`` with a ``reason`` starts a new log after a loss, and the
    restart is recorded); never overwrites an existing log. ``protected``: see
    :class:`AnchorLog`.
    """
    path = Path(path)
    reason = clean_reason(reason, required=restart)
    if not path.parent.is_dir():
        raise AnchorError(f"folder {path.parent} untuk log jangkar tidak ada. Pasang dulu penyimpanan terpisahnya; TAPAK "
                          "tidak membuat folder ini, agar log tidak diam-diam tertulis di disk lokal")
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
        log_id = secrets.token_hex(16)
        create_anchor_file(path, line_text(start_body(log_id, utc_now(), restart, reason), signer))
    log = AnchorLog(path, signer=signer, public_key=public_key, starting=True, protected=protected)
    with Registry.open(registry_path, anchor=log) as reg, reg.transaction():
        pending = bool(reg.pending())
        reg.record_anchor_event(event="restart" if restart else "start", log_id=log_id,
                                reason_sha256=reason_digest(reason), signer=None if pending else signer)
    assert log.status is not None
    return log.status


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
