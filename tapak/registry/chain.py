"""Append-only registry: one SQLite file, one table of entries, a SHA-256 hash chain.

Every entry is a row ``(seq, kind, payload, prev_hash, created_at, entry_hash, signature,
signer)``:

* ``seq`` counts from 1 without gaps;
* ``payload`` is the canonical JSON text of a JSON object (see :func:`canonical_json`);
* ``prev_hash`` is the ``entry_hash`` of entry ``seq - 1`` (64 zeros for entry 1);
* ``entry_hash`` = SHA-256 of the canonical JSON of
  ``{"seq", "kind", "payload", "prev_hash", "created_at"}`` (payload as an object);
* ``signature`` is an Ed25519 signature over the 32 raw bytes of ``entry_hash`` and
  ``signer`` the hex public key that made it; both stay NULL until the entry is signed.

Changing any byte of any entry breaks its hash, or the next entry's link, or a signature;
``tapak.registry.verify`` checks all three with nothing but the public key.

SQLite triggers refuse DELETE, refuse UPDATE except filling a NULL signature (and signer)
once, and refuse an INSERT that does not extend the chain. They stop accidents and casual
edits; an attacker can drop them, which is why verification never relies on them.
:meth:`Registry.open` refuses a file whose triggers are missing or altered.

Signing rules (signed entries always form a prefix of the chain):

* ``append(..., signer=s)`` signs only the new entry and is refused while older entries
  are still unsigned. Pending entries are never signed as a side effect, because anyone
  with write access could have slipped a forged unsigned row in.
* :func:`sign_pending` is the only way to sign older entries. It checks the whole chain
  first and signs, in order, only up to the entry the key holder has reviewed
  (``python -m tapak.registry.signing sign-pending REGISTRY --daftar`` lists them).

An unsigned entry followed by a signed one is therefore evidence that a signature was
removed.

Entry kinds: ``document`` (one per issued document), ``copy`` (one per copy),
``trace`` (one per trace of a recorded document, appended before the evidence is decoded;
trace number k spends eps * 6 / (pi^2 k^2) of the document's false-accusation budget, see
``tapak.tardos.spending``; a trace that runs the staged accusation also records its stage
policy and the eps of every stage, ``stage_policy`` and ``stage_eps``) and ``anchor_log``
(the external anchor log of ``tapak.registry.anchor`` was started, started again after a
loss, continued in a new segment file, or an alarm was acknowledged: event, log id,
released ``[seq, entry_hash]`` pairs and the SHA-256 of the operator's reason). Other kinds, such as the canary log's
``canary_anchor``, are accepted as any JSON object.

A registry opened with an anchor log (``Registry.open(path, anchor=...)``) checks the log
against the chain at the start of every write transaction and appends one line per new
entry to it after the transaction has committed, never before (``tapak.registry.anchor``).

A ``document`` entry of a document that opted into the lexical channel (word choice) also
carries ``retype_positions``, ``lexical_digest``, ``lexicon_version``, ``lexicon_digest``,
``shift_excluded_rows`` and ``text_excluded_words``: the position rule, digests and the
positions of the point words, never the words. Its ``copy`` entries carry no lexical form
choice: those are code bits, recomputed from the code secret at trace time.

Data minimization: payloads carry hashes, identifiers and parameters only. Recipient
names, document text and images never enter the registry; a copy is tied to its
recipient through ``recipient_id`` alone. A trace entry holds the document hash, the
SHA-256 of each evidence file and numbers, never a name or a verdict. The canary token is stored as a commitment
(``"sha256:" + SHA-256 of the token``, see :func:`canary_token_digest`), not in clear:
the registry is handed to outside auditors, and a clear token would let any reader fake
a canary hit for any recipient.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from tapak.registry.signing import Signer, verify_signature

if TYPE_CHECKING:
    from tapak.marker.issue import IssueManifest

ZERO_HASH = "0" * 64
SCHEMA_VERSION = 1
KIND_DOCUMENT = "document"
KIND_COPY = "copy"
KIND_TRACE = "trace"
KIND_ANCHOR = "anchor_log"
KIND_LABELS = {KIND_DOCUMENT: "dokumen", KIND_COPY: "salinan", KIND_TRACE: "pelacakan", KIND_ANCHOR: "log jangkar"}
CANARY_DIGEST_PREFIX = "sha256:"
_HEX = frozenset("0123456789abcdef")

# Exact payload fields of the known kinds. Other kinds are accepted as any JSON object.
DOCUMENT_FIELDS = frozenset({
    "doc_hash", "doc_name", "params", "channels", "shift_mm", "excluded_rows", "plan_summary",
    "threshold_rule", "threshold_full", "issuer", "issued_at",
})
COPY_FIELDS = frozenset({
    "doc_hash", "recipient_id", "copy_id", "seq", "code_digest", "channels_used",
    "semantic_variant_ids", "issued_at", "issuer", "canary_token", "file_sha256",
})
TRACE_FIELDS = frozenset({"doc_hash", "trace_no", "evidence_sha256", "eps_share", "eps", "created_at"})
# Events of the external anchor log: started, started again after the log was lost, continued
# in a new segment file (rotation), and an alarm acknowledged by the operator (the released
# pairs are the anchored entries gone).
ANCHOR_FIELDS = frozenset({"event", "log_id", "released", "reason_sha256", "created_at"})
ANCHOR_EVENTS = ("start", "restart", "rotate", "ack")
KIND_FIELDS: dict[str, frozenset[str]] = {
    KIND_DOCUMENT: DOCUMENT_FIELDS, KIND_COPY: COPY_FIELDS, KIND_TRACE: TRACE_FIELDS,
    KIND_ANCHOR: ANCHOR_FIELDS,
}
# Fields a row may carry in addition (added later; older rows stay valid without them).
LEXICAL_DOCUMENT_FIELDS = frozenset({
    "retype_positions", "lexical_digest", "lexicon_version", "lexicon_digest", "shift_excluded_rows",
    "text_excluded_words",
})
# Scanned pages of a document (marker/raster.py): page numbers, resolution, OCR engine and the
# digest of the word boxes, never a box, word or image.
SCAN_DOCUMENT_FIELD = "scan"
SCAN_RECORD_KEYS = frozenset({"pages", "dpi", "ocr_layer_dropped", "ocr_engine", "boxes_sha256"})
# A trace logged for a staged accusation also records the stage policy and the eps of every
# stage, before decoding (both or neither; traces logged before staging have neither).
STAGE_TRACE_FIELDS = frozenset({"stage_policy", "stage_eps"})
KIND_OPTIONAL: dict[str, frozenset[str]] = {
    KIND_COPY: frozenset({"recipient_mac"}), KIND_DOCUMENT: LEXICAL_DOCUMENT_FIELDS | {SCAN_DOCUMENT_FIELD},
    KIND_TRACE: STAGE_TRACE_FIELDS,
}

_COLUMNS = "seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer"

TABLE_SQL = """CREATE TABLE IF NOT EXISTS entries (
    seq        INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    signature  TEXT,
    signer     TEXT
)"""

# Trigger name -> trigger text after the name. SQLite stores each one in sqlite_master as
# "CREATE TRIGGER <name> <text>", which is what verification compares against.
TRIGGERS: dict[str, str] = {
    "entries_no_delete": """BEFORE DELETE ON entries
BEGIN
    SELECT RAISE(ABORT, 'registri hanya boleh ditambah: penghapusan entri ditolak');
END""",
    "entries_no_update": """BEFORE UPDATE ON entries
WHEN NOT (
    OLD.signature IS NULL AND OLD.signer IS NULL
    AND NEW.signature IS NOT NULL AND NEW.signer IS NOT NULL
    AND NEW.seq IS OLD.seq AND NEW.kind IS OLD.kind AND NEW.payload IS OLD.payload
    AND NEW.prev_hash IS OLD.prev_hash AND NEW.created_at IS OLD.created_at
    AND NEW.entry_hash IS OLD.entry_hash
)
BEGIN
    SELECT RAISE(ABORT, 'registri hanya boleh ditambah: perubahan entri ditolak');
END""",
    "entries_extend_chain": f"""BEFORE INSERT ON entries
WHEN NEW.seq IS NOT (SELECT COALESCE(MAX(seq), 0) + 1 FROM entries)
  OR NEW.prev_hash IS NOT COALESCE(
        (SELECT entry_hash FROM entries ORDER BY seq DESC LIMIT 1), '{ZERO_HASH}')
  OR (NEW.signature IS NULL) <> (NEW.signer IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'registri hanya boleh ditambah: entri baru harus menyambung ujung rantai');
END""",
}


class RegistryError(RuntimeError):
    """Raised when an append or signing would break the registry's guarantees."""


def canonical_json(obj: object) -> bytes:
    """Canonical JSON as UTF-8: sorted keys, no whitespace, no ASCII escaping, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def compute_entry_hash(seq: int, kind: str, payload: object, prev_hash: str, created_at: str) -> str:
    """SHA-256 (hex) of the canonical JSON of the five hashed fields of an entry."""
    body = {"seq": seq, "kind": kind, "payload": payload, "prev_hash": prev_hash, "created_at": created_at}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def recipient_commitment(secret: bytes, doc_hash: str, copy_id: str, recipient_id: str, nama: str,
                         jabatan: str = "", satuan: str = "") -> str:
    """Keyed commitment to who received a copy: ``"hmac-sha256:"`` + hex.

    It binds the recipient's name, position and unit to the signed copy row without putting
    them in the registry. A plain hash could be reversed by hashing a personnel list; the key
    (the code secret) prevents that. Whoever traces holds the secret and recomputes it from
    the local manifest, so an edited name no longer matches the signed row.
    """
    import hmac

    record = json.dumps({"doc_hash": doc_hash, "copy_id": copy_id, "recipient_id": recipient_id,
                         "nama": nama, "jabatan": jabatan, "satuan": satuan},
                        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "hmac-sha256:" + hmac.new(secret, record.encode("utf-8"), hashlib.sha256).hexdigest()


def canary_token_digest(token: str) -> str:
    """Commitment stored instead of a clear canary token: ``"sha256:"`` + SHA-256 hex.

    The token is lowercased first (DNS names are case-insensitive). The operator, who can
    recompute every token from the code secret, or the DNS listener, which sees the token
    in a query, finds the copy with :meth:`Registry.find_copy_by_canary`.
    """
    return CANARY_DIGEST_PREFIX + hashlib.sha256(token.strip().lower().encode("utf-8")).hexdigest()


def _is_canary_digest(value: str) -> bool:
    rest = value[len(CANARY_DIGEST_PREFIX):]
    return value.startswith(CANARY_DIGEST_PREFIX) and len(rest) == 64 and set(rest) <= _HEX


def _is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _is_number(value: object) -> bool:
    try:  # math.isfinite raises OverflowError for an integer beyond the float range
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def trace_payload_problems(payload: object) -> list[str]:
    """Problems (Indonesian) with the values of a ``trace`` payload; empty when it is valid.

    Checks the field set, the hashes (64 lowercase hex), the trace number (whole number from
    1), that ``eps_share`` follows the fixed schedule eps * 6 / (pi^2 k^2) for that number,
    and the timestamp. A trace logged for a staged accusation also carries ``stage_policy``
    (a known policy name) and ``stage_eps`` (the eps of every stage: the policy's split of
    ``eps_share``, adding up to it); a trace without them has a single stage. Never raises,
    whatever the payload holds.
    """
    from tapak.tardos.spending import eps_for_trace

    if not isinstance(payload, dict):
        return ["isi entri pelacakan bukan objek JSON"]
    problems = []
    allowed = TRACE_FIELDS | STAGE_TRACE_FIELDS
    if not TRACE_FIELDS <= set(payload) <= allowed:
        problems.append(f"kolom entri pelacakan tidak sesuai skema: kurang {sorted(TRACE_FIELDS - set(payload))}, "
                        f"berlebih {sorted(set(payload) - allowed)}")
    if not _is_sha256_hex(payload.get("doc_hash")):
        problems.append("doc_hash entri pelacakan bukan SHA-256 heksadesimal")
    evidence = payload.get("evidence_sha256")
    if not isinstance(evidence, list) or not evidence or not all(_is_sha256_hex(d) for d in evidence):
        problems.append("evidence_sha256 harus daftar SHA-256 heksadesimal yang tidak kosong")
    k, eps, share = payload.get("trace_no"), payload.get("eps"), payload.get("eps_share")
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 10**9:
        problems.append("trace_no harus bilangan bulat mulai dari 1")
    elif not (_is_number(eps) and 0.0 < eps < 1.0):
        problems.append("eps entri pelacakan harus di antara 0 dan 1")
    elif not (_is_number(share) and math.isclose(share, eps_for_trace(eps, k), rel_tol=1e-9)):
        problems.append(f"eps_share tidak sesuai jadwal eps x 6 / (pi^2 k^2) untuk pelacakan ke-{k}")
    else:
        problems += _stage_problems(payload, share)
    try:
        parse_time(payload.get("created_at"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        problems.append("created_at entri pelacakan bukan waktu ISO 8601 dengan zona waktu")
    return problems


def _stage_problems(payload: dict[str, Any], share: float) -> list[str]:
    """Problems with the optional stage fields of a ``trace`` payload whose share is valid."""
    from tapak.tardos.spending import split_stage_eps

    present = set(payload) & STAGE_TRACE_FIELDS
    if not present:
        return []
    if present != STAGE_TRACE_FIELDS:
        return ["stage_policy dan stage_eps entri pelacakan harus hadir bersama"]
    if not isinstance(payload["stage_policy"], str):  # None would mean a single stage: not a staged entry
        return ["stage_policy entri pelacakan bukan kebijakan tahap yang dikenal"]
    try:
        expected = split_stage_eps(share, payload["stage_policy"])
    except ValueError:
        return ["stage_policy entri pelacakan bukan kebijakan tahap yang dikenal"]
    stages = payload["stage_eps"]
    if not (isinstance(stages, list) and len(stages) == len(expected) and all(_is_number(v) for v in stages)
            and all(math.isclose(v, e, rel_tol=1e-9) for v, e in zip(stages, expected))
            and math.isclose(math.fsum(stages), share, rel_tol=1e-9)):
        return [f"stage_eps tidak sesuai kebijakan {payload['stage_policy']} untuk eps_share pelacakan ini"]
    return []


def anchor_payload_problems(payload: object) -> list[str]:
    """Problems (Indonesian) with an ``anchor_log`` payload; empty when it is valid.

    ``event`` is one of :data:`ANCHOR_EVENTS`, ``log_id`` 32 lowercase hex, ``released`` a
    sorted list of distinct ``[seq, entry_hash]`` pairs that is non-empty exactly for an
    acknowledgement (``ack``), ``reason_sha256`` the SHA-256 of the operator's reason
    (required for ``restart`` and ``ack``, optional for ``start`` and ``rotate``) and
    ``created_at`` a timestamp. Never raises, whatever the payload holds.
    """
    if not isinstance(payload, dict):
        return ["isi entri log jangkar bukan objek JSON"]
    if set(payload) != ANCHOR_FIELDS:
        return [f"kolom entri log jangkar tidak sesuai skema: kurang {sorted(ANCHOR_FIELDS - set(payload))}, "
                f"berlebih {sorted(set(payload) - ANCHOR_FIELDS)}"]
    problems = []
    event = payload["event"]
    if not isinstance(event, str) or event not in ANCHOR_EVENTS:
        problems.append("peristiwa log jangkar tidak dikenal")
    log_id = payload["log_id"]
    if not (isinstance(log_id, str) and len(log_id) == 32 and set(log_id) <= _HEX):
        problems.append("log_id entri log jangkar bukan 32 karakter heksadesimal")
    released = payload["released"]
    if not (isinstance(released, list) and all(
            isinstance(r, list) and len(r) == 2 and isinstance(r[0], int) and not isinstance(r[0], bool)
            and r[0] >= 1 and _is_sha256_hex(r[1]) for r in released)):
        problems.append("released entri log jangkar harus daftar [nomor entri, hash]")
    elif released != [list(pair) for pair in sorted({(r[0], r[1]) for r in released})]:
        problems.append("released entri log jangkar harus terurut dan tanpa pasangan ganda")
    elif (event == "ack") != bool(released):
        problems.append("released hanya diisi, dan wajib diisi, pada pengakuan (ack)")
    reason = payload["reason_sha256"]
    if reason is not None and not _is_sha256_hex(reason):
        problems.append("reason_sha256 entri log jangkar bukan SHA-256 heksadesimal")
    elif reason is None and event in ("restart", "ack"):
        problems.append("alasan wajib dicatat untuk memulai ulang log jangkar dan untuk pengakuan")
    try:
        parse_time(payload["created_at"])
    except (TypeError, ValueError):
        problems.append("created_at entri log jangkar bukan waktu ISO 8601 dengan zona waktu")
    return problems


def utc_now() -> str:
    """Current UTC time, ISO 8601 with milliseconds."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_time(value: str) -> datetime:
    """Parse an ISO 8601 timestamp that carries a timezone."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"waktu tanpa zona waktu: {value}")
    return dt


def _normalize_time(value: datetime | str) -> str:
    dt = parse_time(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError("created_at harus memiliki zona waktu")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _span(seqs: Sequence[int]) -> str:
    """'#a' or '#a..#b' for a run of entry numbers."""
    return f"#{seqs[0]}" if seqs[0] == seqs[-1] else f"#{seqs[0]}..#{seqs[-1]}"


def entry_content_problems(seq: Any, kind: Any, payload_text: Any, prev_hash: Any, created_at: Any,
                           entry_hash: Any) -> list[str]:
    """Problems (Indonesian) with the stored payload and ``entry_hash`` of one raw row.

    Empty when the payload is a canonical JSON object and ``entry_hash`` recomputes. Never
    raises, whatever an attacker put in the row (wrong types, deeply nested JSON).
    """
    if not isinstance(payload_text, str):
        return ["isi entri bukan teks JSON"]
    try:
        payload = json.loads(payload_text)
    except (ValueError, RecursionError):
        return ["isi entri bukan JSON yang sah"]
    problems = []
    if not isinstance(payload, dict):
        problems.append("isi entri bukan objek JSON")
    try:
        canonical = canonical_json(payload).decode("utf-8")
        recomputed = compute_entry_hash(seq, kind, payload, prev_hash, created_at)
    except (TypeError, ValueError, RecursionError):
        canonical, recomputed = None, None
    if canonical != payload_text:
        problems.append("isi entri tidak dalam bentuk JSON kanonik (diubah di luar TAPAK?)")
    if recomputed != entry_hash:
        problems.append("hash entri tidak cocok dengan isinya (isi atau hash diubah)")
    return problems


def _normalize_sql(text: str | None) -> str:
    return " ".join((text or "").split())


def trigger_problems(conn: sqlite3.Connection) -> list[str]:
    """Missing, altered or unexpected triggers on ``entries`` (Indonesian descriptions).

    Compares the SQL text stored in ``sqlite_master`` with :data:`TRIGGERS`, so a trigger
    that keeps its name but was disarmed (for example with ``WHEN 0``) is reported too.
    """
    found = {name: sql for name, sql in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'entries'")}
    problems = []
    for name, body in TRIGGERS.items():
        if name not in found:
            problems.append(f"pemicu {name} hilang")
        elif _normalize_sql(found[name]) != _normalize_sql(f"CREATE TRIGGER {name} {body}"):
            problems.append(f"pemicu {name} diubah")
    problems += [f"pemicu tak dikenal {name} pada tabel entri" for name in sorted(set(found) - set(TRIGGERS))]
    return problems


@dataclass(frozen=True)
class Entry:
    """One registry row as read back from the file."""

    seq: int
    kind: str
    payload: dict[str, Any]
    prev_hash: str
    created_at: str
    entry_hash: str
    signature: str | None
    signer: str | None

    @property
    def signed(self) -> bool:
        """True once a signature has been stored."""
        return self.signature is not None

    def recomputed_hash(self) -> str:
        """Hash of the stored fields, to compare with :attr:`entry_hash`."""
        return compute_entry_hash(self.seq, self.kind, self.payload, self.prev_hash, self.created_at)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return {"seq": self.seq, "kind": self.kind, "payload": self.payload, "prev_hash": self.prev_hash,
                "created_at": self.created_at, "entry_hash": self.entry_hash,
                "signature": self.signature, "signer": self.signer}


class AnchorHook(Protocol):
    """What :class:`Registry` needs from an anchor log (``tapak.registry.anchor.AnchorLog``)."""

    def prepare(self, registry: Registry) -> object:
        """Check the log against the chain inside the write transaction; raise to refuse the write."""

    def record(self, entries: list[Entry]) -> None:
        """Write one line per committed entry; raise if they cannot be written."""


def describe_entry(entry: Entry) -> str:
    """One Indonesian line identifying an entry, for the key holder's review before signing.

    Shows identifiers only (doc_hash, doc_name, recipient_id, copy_id), never payload text.
    """
    parts = [f"#{entry.seq}", KIND_LABELS.get(entry.kind, entry.kind), f"dibuat {entry.created_at}"]
    p = entry.payload
    if "doc_hash" in p:
        parts.append(f"doc_hash {str(p['doc_hash'])[:16]}")
    for key in ("doc_name", "recipient_id", "copy_id"):
        if key in p:
            parts.append(f"{key} {p[key]}")
    if entry.kind == KIND_TRACE:
        parts.append(f"pelacakan ke-{p.get('trace_no')}, {len(p.get('evidence_sha256') or [])} berkas bukti")
    if entry.kind == KIND_ANCHOR:
        parts.append(f"peristiwa {p.get('event')}, log {str(p.get('log_id'))[:8]}, "
                     f"{len(p.get('released') or [])} entri dilepas")
    if entry.kind not in KIND_FIELDS:
        parts.append("kolom: " + ", ".join(sorted(map(str, p))))
    return "  ".join(parts)


def _row_to_entry(row: Sequence[Any]) -> Entry:
    seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer = row
    try:
        obj = json.loads(payload)
    except (TypeError, ValueError, RecursionError):
        raise RegistryError(f"isi entri #{seq} bukan JSON yang sah (berkas diubah di luar TAPAK?)") from None
    return Entry(seq, kind, obj, prev_hash, created_at, entry_hash, signature, signer)


def _check_payload(kind: str, payload: object) -> None:
    if not isinstance(kind, str) or not kind or not all(ch.isalnum() or ch in "_-" for ch in kind):
        raise ValueError(f"jenis entri tidak sah: {kind!r}")
    if not isinstance(payload, dict):
        raise ValueError("isi entri harus berupa objek JSON (dict)")
    expected = KIND_FIELDS.get(kind)
    present = set(payload) - KIND_OPTIONAL.get(kind, frozenset())
    if expected is not None and present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        raise ValueError(f"isi entri '{kind}' tidak sesuai skema: kurang {missing}, berlebih {extra}")
    problems = trace_payload_problems(payload) if kind == KIND_TRACE else []
    if problems:
        raise ValueError("isi entri 'trace' tidak sah: " + "; ".join(problems))
    problems = anchor_payload_problems(payload) if kind == KIND_ANCHOR else []
    if problems:
        raise ValueError(f"isi entri '{KIND_ANCHOR}' tidak sah: " + "; ".join(problems))
    if kind == KIND_DOCUMENT and set(payload) & LEXICAL_DOCUMENT_FIELDS:
        lexical = lexical_document_problems(payload)
        if lexical:
            raise ValueError("isi entri 'document' tidak sah: " + "; ".join(lexical))
    if kind == KIND_DOCUMENT and SCAN_DOCUMENT_FIELD in payload:
        scan = scan_document_problems(payload[SCAN_DOCUMENT_FIELD])
        if scan:
            raise ValueError("isi entri 'document' tidak sah: " + "; ".join(scan))


def scan_document_problems(record: object) -> list[str]:
    """Problems (Indonesian) with the ``scan`` field of a ``document`` payload; empty when valid.

    Exactly the keys of SCAN_RECORD_KEYS: page numbers, one resolution per page, the pages
    whose OCR layer was dropped (a subset), a short engine description and a SHA-256 digest.
    Nothing there can hold a word box, a word or an image.
    """
    if not isinstance(record, dict) or set(record) != SCAN_RECORD_KEYS:
        return ["kolom halaman pindaian tidak sesuai skema"]

    def numbers(value: object) -> bool:
        return isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                                               for v in value)

    problems = []
    pages = record["pages"]
    if not numbers(pages) or not pages or len(set(pages)) != len(pages):
        problems.append("daftar halaman pindaian tidak sah")
    elif not numbers(record["dpi"]) or len(record["dpi"]) != len(pages):
        problems.append("resolusi halaman pindaian tidak sah")
    if not numbers(record["ocr_layer_dropped"]) or not set(record["ocr_layer_dropped"]) <= set(
            pages if isinstance(pages, list) else []):
        problems.append("daftar halaman berlapis OCR tidak sah")
    engine = record["ocr_engine"]
    if not isinstance(engine, str) or not engine or len(engine) > 200 or not engine.isascii():
        problems.append("keterangan mesin OCR tidak sah")
    if not _is_sha256_hex(record["boxes_sha256"]):
        problems.append("boxes_sha256 bukan SHA-256 heksadesimal")
    return problems


def lexical_document_problems(payload: dict[str, Any]) -> list[str]:
    """Problems (Indonesian) with the lexical fields of a ``document`` payload; empty when valid.

    All six fields come together; digests are 64 lowercase hex, the position rule is a known
    one, the exclusions are lists of [page, row] and [page, row, word] numbers. No field may
    hold document words.
    """
    from tapak.marker.plan import RETYPE_RULES

    present = set(payload) & LEXICAL_DOCUMENT_FIELDS
    if present != LEXICAL_DOCUMENT_FIELDS:
        return [f"kolom pilihan kata tidak lengkap: kurang {sorted(LEXICAL_DOCUMENT_FIELDS - present)}"]
    problems = []
    if payload["retype_positions"] not in RETYPE_RULES:
        problems.append("aturan posisi ketik ulang tidak dikenal")
    for key in ("lexical_digest", "lexicon_digest"):
        if not _is_sha256_hex(payload[key]):
            problems.append(f"{key} bukan SHA-256 heksadesimal")
    if not isinstance(payload["lexicon_version"], str) or not payload["lexicon_version"].replace("_", "").isalnum():
        problems.append("lexicon_version tidak sah")
    for key, size in (("shift_excluded_rows", 2), ("text_excluded_words", 3)):
        value = payload[key]
        if not isinstance(value, list) or not all(
                isinstance(v, list) and len(v) == size and all(isinstance(x, int) and not isinstance(x, bool)
                                                               and x >= 0 for x in v) for v in value):
            problems.append(f"{key} harus berupa daftar nomor posisi")
    return problems


class Registry:
    """Handle on one registry file. Use :meth:`open`; close with :meth:`close` or ``with``."""

    def __init__(self, conn: sqlite3.Connection, path: Path, anchor: AnchorHook | None = None) -> None:
        self._conn = conn
        self.path = path
        self._in_tx = False
        self.trigger_repairs: list[str] = []
        self._anchor = anchor
        self._appended: list[Entry] = []

    @property
    def anchor(self) -> AnchorHook | None:
        """The external anchor log this handle writes to (None: no anchor log)."""
        return self._anchor

    @classmethod
    def open(cls, path: str | Path, repair_triggers: bool = False, anchor: AnchorHook | None = None) -> "Registry":
        """Open (and create if needed) the registry file with its schema and triggers.

        A file whose ``entries`` table exists but whose triggers are missing or altered was
        edited outside TAPAK: opening it raises RegistryError (run ``tapak-verify-registry``
        first). With ``repair_triggers=True`` the triggers are re-created instead and the
        repairs are listed in :attr:`trigger_repairs`.

        With an ``anchor`` (``tapak.registry.anchor.AnchorLog``), every write transaction
        first checks the anchor log against the chain (and refuses on a mismatch), and the
        entries it appended are written to the anchor log after the commit.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, timeout=10.0)
        repairs: list[str] = []
        try:
            conn.execute("BEGIN IMMEDIATE")  # schema check and creation are atomic
            try:
                has_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entries'").fetchone()
                if has_table:
                    repairs = trigger_problems(conn)
                    if repairs and not repair_triggers:
                        raise RegistryError(
                            f"pemicu hanya-tambah registri {path} tidak utuh ({'; '.join(repairs)}): berkas "
                            "pernah disunting di luar TAPAK. Jalankan tapak-verify-registry, lalu buka dengan "
                            "repair_triggers=True untuk memasang ulang pemicu")
                    if repairs:  # drop every trigger on entries; the correct ones are re-created below
                        for (name,) in conn.execute("SELECT name FROM sqlite_master "
                                                    "WHERE type = 'trigger' AND tbl_name = 'entries'").fetchall():
                            conn.execute('DROP TRIGGER "{}"'.format(name.replace('"', '""')))
                else:
                    conn.execute(TABLE_SQL)
                for name, body in TRIGGERS.items():
                    conn.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {body}")
                if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        except BaseException:
            conn.close()
            raise
        reg = cls(conn, path, anchor)
        reg.trigger_repairs = repairs
        return reg

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "Registry":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group several appends atomically (all or nothing). Nested use joins the outer one.

        With an anchor log, the outermost transaction checks the log first, under the write
        lock (``anchor.prepare``, which raises on a mismatch), and hands the entries it
        appended to ``anchor.record`` only once COMMIT has succeeded. A rolled-back or failed
        commit never reaches the anchor log, so the log cannot get ahead of the registry.
        """
        if self._in_tx:
            yield
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        self._appended = []
        try:
            if self._anchor is not None:
                self._anchor.prepare(self)
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            self._in_tx, self._appended = False, []
            raise
        try:
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            self._appended = []
            raise
        finally:
            self._in_tx = False
        appended, self._appended = self._appended, []
        if self._anchor is not None and appended:
            self._anchor.record(appended)  # after the commit: may raise, the entries stay committed

    # ---- reading -------------------------------------------------------------------

    def head(self) -> Entry | None:
        """The last entry, or None for an empty registry."""
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM entries ORDER BY seq DESC LIMIT 1").fetchone()
        return _row_to_entry(row) if row else None

    def raw_rows(self) -> list[tuple[Any, ...]]:
        """Every row exactly as stored, in ``seq`` order: ``(seq, kind, payload, prev_hash,
        created_at, entry_hash, signature, signer)`` with the payload as text. Never parses a
        payload, so a row edited outside TAPAK cannot make this raise."""
        return self._conn.execute(f"SELECT {_COLUMNS} FROM entries ORDER BY seq").fetchall()

    def entries(self, kind: str | None = None) -> list[Entry]:
        """All entries in order, optionally only those of one kind."""
        if kind is None:
            rows = self._conn.execute(f"SELECT {_COLUMNS} FROM entries ORDER BY seq")
        else:
            rows = self._conn.execute(f"SELECT {_COLUMNS} FROM entries WHERE kind = ? ORDER BY seq", (kind,))
        return [_row_to_entry(r) for r in rows]

    def pending(self) -> list[Entry]:
        """Unsigned entries in order (what ``sign-pending --daftar`` shows)."""
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM entries WHERE signature IS NULL ORDER BY seq")
        return [_row_to_entry(r) for r in rows]

    def last_signed_seq(self) -> int | None:
        """Number of the last signed entry, or None if nothing is signed yet."""
        return self._conn.execute("SELECT MAX(seq) FROM entries WHERE signature IS NOT NULL").fetchone()[0]

    def get(self, seq: int) -> Entry | None:
        """Entry number ``seq``, or None."""
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM entries WHERE seq = ?", (seq,)).fetchone()
        return _row_to_entry(row) if row else None

    def find_document(self, doc_hash: str) -> dict[str, Any] | None:
        """Payload of the latest ``document`` entry for ``doc_hash``, or None."""
        row = self._conn.execute(
            "SELECT payload FROM entries WHERE kind = ? AND json_extract(payload, '$.doc_hash') = ? "
            "ORDER BY seq DESC LIMIT 1", (KIND_DOCUMENT, doc_hash)).fetchone()
        return json.loads(row[0]) if row else None

    def copies(self, doc_hash: str) -> list[dict[str, Any]]:
        """Payloads of all ``copy`` entries of ``doc_hash``, in registry order."""
        rows = self._conn.execute(
            "SELECT payload FROM entries WHERE kind = ? AND json_extract(payload, '$.doc_hash') = ? "
            "ORDER BY seq", (KIND_COPY, doc_hash))
        return [json.loads(r[0]) for r in rows]

    def traces(self, doc_hash: str) -> list[dict[str, Any]]:
        """Payloads of all ``trace`` entries of ``doc_hash``, in registry order."""
        rows = self._conn.execute(
            "SELECT payload FROM entries WHERE kind = ? AND json_extract(payload, '$.doc_hash') = ? "
            "ORDER BY seq", (KIND_TRACE, doc_hash))
        return [json.loads(r[0]) for r in rows]

    def find_copy_by_canary(self, token: str) -> dict[str, Any] | None:
        """Payload of the ``copy`` entry whose canary token is ``token`` (clear text), or None."""
        row = self._conn.execute(
            "SELECT payload FROM entries WHERE kind = ? AND json_extract(payload, '$.canary_token') = ? "
            "ORDER BY seq DESC LIMIT 1", (KIND_COPY, canary_token_digest(token))).fetchone()
        return json.loads(row[0]) if row else None

    # ---- writing -------------------------------------------------------------------

    def append(
        self,
        kind: str,
        payload: dict[str, Any],
        signer: Signer | None = None,
        created_at: datetime | str | None = None,
    ) -> Entry:
        """Add one entry at the end of the chain and return it.

        With a ``signer`` the new entry is signed immediately; this is refused
        (RegistryError) while older entries are unsigned, since signing them is the job
        of :func:`sign_pending` after a review. Without a signer, signature and signer
        stay NULL. ``created_at`` defaults to now (UTC) and may not go back in time
        relative to the previous entry.
        """
        _check_payload(kind, payload)
        text = canonical_json(payload)
        stored_payload = json.loads(text)  # exactly what a verifier will parse back
        with self.transaction():
            if signer is not None:
                pending = [r[0] for r in self._conn.execute(
                    "SELECT seq FROM entries WHERE signature IS NULL ORDER BY seq")]
                if pending:
                    raise RegistryError(
                        f"ada {len(pending)} entri belum bertanda tangan ({_span(pending)}); entri baru tidak "
                        "ditandatangani agar entri lama tidak ikut tertanda tangan tanpa diperiksa. Periksa "
                        "dengan 'sign-pending --daftar', lalu tanda tangani dengan 'sign-pending --sampai'")
            head = self.head()
            seq = head.seq + 1 if head else 1
            prev_hash = head.entry_hash if head else ZERO_HASH
            if created_at is None:
                stamp = utc_now()
                if head and parse_time(stamp) < parse_time(head.created_at):
                    stamp = head.created_at  # clock stepped back: keep timestamps monotonic
            else:
                stamp = _normalize_time(created_at)
                if head and parse_time(stamp) < parse_time(head.created_at):
                    raise RegistryError(
                        f"waktu entri baru ({stamp}) lebih awal dari entri #{head.seq} ({head.created_at})")
            entry_hash = compute_entry_hash(seq, kind, stored_payload, prev_hash, stamp)
            signature = signer.sign(bytes.fromhex(entry_hash)) if signer else None
            public = signer.public_key_hex if signer else None
            self._conn.execute(
                f"INSERT INTO entries ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (seq, kind, text.decode("utf-8"), prev_hash, stamp, entry_hash, signature, public))
            entry = Entry(seq, kind, stored_payload, prev_hash, stamp, entry_hash, signature, public)
            self._appended.append(entry)  # anchored after the outermost transaction commits
        return entry

    def _sign_pending(self, signer: Signer, up_to: int | None) -> int:
        """Check the whole chain, then sign unsigned entries up to ``up_to`` (call inside a transaction).

        Refuses (RegistryError) a broken hash or link, a sequence gap, an invalid existing
        signature, and an unsigned entry before a signed one (a removed signature).
        """
        todo: list[tuple[int, str]] = []
        prev, expected_seq, first_unsigned = ZERO_HASH, 1, None
        for row in self._conn.execute(f"SELECT {_COLUMNS} FROM entries ORDER BY seq").fetchall():
            seq, kind, payload_text, prev_hash, created_at, entry_hash, signature, signer_hex = row
            if (seq != expected_seq or prev_hash != prev
                    or entry_content_problems(seq, kind, payload_text, prev_hash, created_at, entry_hash)):
                raise RegistryError(f"entri #{seq} rusak (nomor urut, hash atau rantai tidak cocok); "
                                    "penandatanganan dibatalkan, jalankan tapak-verify-registry")
            if signature is None and signer_hex is None:
                first_unsigned = first_unsigned or seq
                if up_to is None or seq <= up_to:
                    todo.append((seq, entry_hash))
            elif first_unsigned is not None:
                raise RegistryError(f"entri #{first_unsigned} belum bertanda tangan padahal entri #{seq} sesudahnya "
                                    "sudah (tanda tangan dihapus?); penandatanganan dibatalkan")
            elif (signature is None or signer_hex is None
                  or not verify_signature(str(signer_hex), bytes.fromhex(entry_hash), str(signature))):
                raise RegistryError(f"tanda tangan entri #{seq} tidak sah; penandatanganan dibatalkan")
            prev, expected_seq = entry_hash, expected_seq + 1
        for seq, entry_hash in todo:
            self._conn.execute(
                "UPDATE entries SET signature = ?, signer = ? WHERE seq = ? AND signature IS NULL",
                (signer.sign(bytes.fromhex(entry_hash)), signer.public_key_hex, seq))
        return len(todo)

    def record_document(
        self,
        *,
        doc_hash: str,
        doc_name: str,
        params: dict[str, Any],
        channels: list[str],
        shift_mm: dict[str, float],
        excluded_rows: list[list[int]],
        plan_summary: dict[str, dict[str, int]],
        threshold_rule: str,
        threshold_full: float | None,
        issuer: str,
        issued_at: str,
        signer: Signer | None = None,
        created_at: datetime | str | None = None,
        lexical: dict[str, Any] | None = None,
        scan: dict[str, Any] | None = None,
    ) -> Entry:
        """Record one issued document (parameters and hashes only, never its contents).

        A non-finite ``threshold_full`` is stored as null because JSON has no infinity.
        ``lexical`` holds the six lexical fields of a document that uses the word-choice
        channel (:data:`LEXICAL_DOCUMENT_FIELDS`); None for any other document, whose entry is
        then exactly as before. ``scan`` is the scanned-page record (:data:`SCAN_RECORD_KEYS`,
        field ``scan``), likewise only for a document with scanned pages.
        """
        if threshold_full is not None:
            threshold_full = float(threshold_full)
            if not math.isfinite(threshold_full):
                threshold_full = None
        payload = {
            "doc_hash": doc_hash, "doc_name": doc_name, "params": dict(params),
            "channels": list(channels), "shift_mm": dict(shift_mm),
            "excluded_rows": [list(r) for r in excluded_rows], "plan_summary": dict(plan_summary),
            "threshold_rule": threshold_rule, "threshold_full": threshold_full,
            "issuer": issuer, "issued_at": issued_at,
        }
        if lexical is not None:
            payload.update(json.loads(json.dumps(lexical)))
        if scan is not None:
            payload[SCAN_DOCUMENT_FIELD] = json.loads(json.dumps(scan))
        return self.append(KIND_DOCUMENT, payload, signer=signer, created_at=created_at)

    def record_copy(
        self,
        *,
        doc_hash: str,
        recipient_id: str,
        copy_id: str,
        seq: int,
        code_digest: str,
        channels_used: list[str],
        file_sha256: str,
        issued_at: str,
        issuer: str,
        semantic_variant_ids: list[str] | tuple[str, ...] = (),
        canary_token: str | None = None,
        signer: Signer | None = None,
        created_at: datetime | str | None = None,
        recipient_mac: str | None = None,
    ) -> Entry:
        """Record one issued copy. Only ``recipient_id`` identifies the recipient in clear.

        ``canary_token`` is the clear token; the payload field ``canary_token`` stores its
        commitment :func:`canary_token_digest` (a value already in that form is kept).
        ``recipient_mac`` is :func:`recipient_commitment` of the full recipient record.
        """
        if not recipient_id:
            raise ValueError("recipient_id wajib diisi")
        if canary_token is not None:
            if not isinstance(canary_token, str) or not canary_token.strip():
                raise ValueError("canary_token harus berupa teks atau None")
            if not _is_canary_digest(canary_token):
                canary_token = canary_token_digest(canary_token)
        payload = {
            "doc_hash": doc_hash, "recipient_id": recipient_id, "copy_id": copy_id, "seq": int(seq),
            "code_digest": code_digest, "channels_used": list(channels_used),
            "semantic_variant_ids": list(semantic_variant_ids), "issued_at": issued_at,
            "issuer": issuer, "canary_token": canary_token, "file_sha256": file_sha256,
        }
        if recipient_mac is not None:
            payload["recipient_mac"] = recipient_mac
        return self.append(KIND_COPY, payload, signer=signer, created_at=created_at)

    def record_trace(
        self,
        *,
        doc_hash: str,
        evidence_sha256: list[str],
        eps: float,
        signer: Signer | None = None,
        stage_policy: str | None = None,
    ) -> Entry:
        """Log one trace of a recorded document before its evidence is decoded; return the entry.

        The trace number is 1 + the number of earlier ``trace`` entries of ``doc_hash``. It is
        counted and appended in one write transaction, so two concurrent traces never get the
        same number. The payload holds the document hash, the SHA-256 of every evidence file,
        the trace number, the document's budget ``eps`` and the part this trace spends
        (``eps_share`` = eps * 6 / (pi^2 k^2)), and the time: no name, verdict or content.
        With ``stage_policy`` (a staged accusation, ``tapak.tardos.staged``) it also holds the
        policy name and the eps of every stage (``stage_eps``), fixed here, before decoding.
        Refuses (ValueError) a document without a ``document`` entry.
        """
        from tapak.tardos.spending import eps_for_trace, split_stage_eps

        evidence = [str(d).lower() for d in evidence_sha256]
        with self.transaction():
            if self.find_document(doc_hash) is None:
                raise ValueError("dokumen ini tidak tercatat di registri; pelacakan tidak dapat dicatat")
            trace_no = 1 + int(self._conn.execute(
                "SELECT COUNT(*) FROM entries WHERE kind = ? AND json_extract(payload, '$.doc_hash') = ?",
                (KIND_TRACE, doc_hash)).fetchone()[0])
            head = self.head()
            stamp = utc_now()
            if head and parse_time(stamp) < parse_time(head.created_at):
                stamp = head.created_at  # clock stepped back: keep timestamps monotonic
            share = eps_for_trace(float(eps), trace_no)
            payload = {"doc_hash": doc_hash, "trace_no": trace_no, "evidence_sha256": evidence,
                       "eps_share": share, "eps": float(eps), "created_at": stamp}
            if stage_policy is not None:
                payload.update(stage_policy=stage_policy, stage_eps=list(split_stage_eps(share, stage_policy)))
            return self.append(KIND_TRACE, payload, signer=signer, created_at=stamp)  # validates the values

    def record_anchor_event(
        self,
        *,
        event: str,
        log_id: str,
        released: Sequence[tuple[int, str]] = (),
        reason_sha256: str | None = None,
        signer: Signer | None = None,
    ) -> Entry:
        """Log an event of the external anchor log (``tapak.registry.anchor``); return the entry.

        ``event`` is ``start`` (a log was started), ``restart`` (a new log replaces a lost
        one), ``rotate`` (the log continues in a new segment file) or ``ack`` (the operator
        acknowledged anchored entries that the registry no longer has; ``released`` lists them
        as ``(seq, entry_hash)``). ``reason_sha256`` is
        the SHA-256 of the operator's reason: the reason itself stays in the anchor log.
        """
        pairs = [[int(seq), str(h)] for seq, h in sorted({(int(s), str(h)) for s, h in released})]
        with self.transaction():
            head = self.head()
            stamp = utc_now()
            if head and parse_time(stamp) < parse_time(head.created_at):
                stamp = head.created_at  # clock stepped back: keep timestamps monotonic
            payload = {"event": event, "log_id": log_id, "released": pairs, "reason_sha256": reason_sha256,
                       "created_at": stamp}
            return self.append(KIND_ANCHOR, payload, signer=signer, created_at=stamp)  # validates the values


def sign_pending(registry: Registry, signer: Signer, up_to: int | None = None) -> int:
    """Sign unsigned entries in order, up to and including entry ``up_to``; return how many.

    The whole chain is checked first, so the key holder never signs a tampered entry.
    ``up_to`` should be the last entry the key holder reviewed (``sign-pending --daftar``);
    entries appended after the review stay unsigned. None signs every pending entry.
    """
    with registry.transaction():
        return registry._sign_pending(signer, up_to)


def manifest_lexical_fields(manifest: IssueManifest) -> dict[str, Any] | None:
    """The lexical fields of a manifest for its ``document`` entry (None without the channel)."""
    values = {key: getattr(manifest, key, None) for key in sorted(LEXICAL_DOCUMENT_FIELDS)}
    if all(v is None for v in values.values()):
        return None
    return values


def registry_from_manifest(
    manifest: IssueManifest,
    registry: Registry,
    signer: Signer | None = None,
    threshold_rule: str | None = None,
    code_secret: bytes | None = None,
) -> list[Entry]:
    """Record the document and every copy of an issuance, atomically.

    Only ``recipient_id`` is taken from each recipient in clear; names, ranks and units stay
    in the manifest and, given ``code_secret``, are bound to the row by a keyed commitment
    (:func:`recipient_commitment`). Refuses a manifest whose copies are already in the registry; the check runs
    inside the write transaction, so two processes cannot record the same copies twice.
    """
    if threshold_rule is None:
        from tapak.decoder.accuse import THRESHOLD_RULE

        threshold_rule = THRESHOLD_RULE
    with registry.transaction():
        known = {c["copy_id"] for c in registry.copies(manifest.doc_hash)}
        again = [c.seq for c in manifest.copies if c.copy_id in known]
        if again:
            raise RegistryError(f"salinan {again} dokumen ini sudah tercatat di registri")
        entries = [registry.record_document(
            doc_hash=manifest.doc_hash,
            # The file name of a classified document often states its subject: store only its hash.
            doc_name="sha256:" + hashlib.sha256(manifest.doc_name.encode("utf-8")).hexdigest(),
            params=manifest.params,
            channels=manifest.channels, shift_mm=manifest.shift_mm, excluded_rows=manifest.excluded_rows,
            plan_summary=manifest.plan_summary, threshold_rule=threshold_rule,
            threshold_full=manifest.threshold_full, issuer=manifest.issuer, issued_at=manifest.issued_at,
            signer=signer, lexical=manifest_lexical_fields(manifest), scan=getattr(manifest, "scan", None))]
        for c in manifest.copies:
            entries.append(registry.record_copy(
                doc_hash=manifest.doc_hash, recipient_id=c.recipient.recipient_id, copy_id=c.copy_id,
                seq=c.seq, code_digest=c.code_digest, channels_used=c.channels_used,
                semantic_variant_ids=c.semantic_variant_ids, issued_at=manifest.issued_at,
                issuer=manifest.issuer, canary_token=getattr(c, "canary_token", None),
                file_sha256=c.file_sha256, signer=signer,
                recipient_mac=None if code_secret is None else recipient_commitment(
                    code_secret, manifest.doc_hash, c.copy_id, c.recipient.recipient_id, c.recipient.nama,
                    c.recipient.jabatan, c.recipient.satuan)))
    return entries
