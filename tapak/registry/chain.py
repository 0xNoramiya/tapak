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

Data minimization: payloads carry hashes, identifiers and parameters only. Recipient
names, document text and images never enter the registry; a copy is tied to its
recipient through ``recipient_id`` alone. The canary token is stored as a commitment
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
from typing import TYPE_CHECKING, Any

from tapak.registry.signing import Signer, verify_signature

if TYPE_CHECKING:
    from tapak.marker.issue import IssueManifest

ZERO_HASH = "0" * 64
SCHEMA_VERSION = 1
KIND_DOCUMENT = "document"
KIND_COPY = "copy"
KIND_LABELS = {KIND_DOCUMENT: "dokumen", KIND_COPY: "salinan"}
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
KIND_FIELDS: dict[str, frozenset[str]] = {KIND_DOCUMENT: DOCUMENT_FIELDS, KIND_COPY: COPY_FIELDS}
# Fields a row may carry in addition (added later; older rows stay valid without them).
KIND_OPTIONAL: dict[str, frozenset[str]] = {KIND_COPY: frozenset({"recipient_mac"})}

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


class Registry:
    """Handle on one registry file. Use :meth:`open`; close with :meth:`close` or ``with``."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self.path = path
        self._in_tx = False
        self.trigger_repairs: list[str] = []

    @classmethod
    def open(cls, path: str | Path, repair_triggers: bool = False) -> "Registry":
        """Open (and create if needed) the registry file with its schema and triggers.

        A file whose ``entries`` table exists but whose triggers are missing or altered was
        edited outside TAPAK: opening it raises RegistryError (run ``tapak-verify-registry``
        first). With ``repair_triggers=True`` the triggers are re-created instead and the
        repairs are listed in :attr:`trigger_repairs`.
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
        reg = cls(conn, path)
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
        """Group several appends atomically (all or nothing). Nested use joins the outer one."""
        if self._in_tx:
            yield
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._in_tx = False

    # ---- reading -------------------------------------------------------------------

    def head(self) -> Entry | None:
        """The last entry, or None for an empty registry."""
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM entries ORDER BY seq DESC LIMIT 1").fetchone()
        return _row_to_entry(row) if row else None

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
        return Entry(seq, kind, stored_payload, prev_hash, stamp, entry_hash, signature, public)

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
    ) -> Entry:
        """Record one issued document (parameters and hashes only, never its contents).

        A non-finite ``threshold_full`` is stored as null because JSON has no infinity.
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


def sign_pending(registry: Registry, signer: Signer, up_to: int | None = None) -> int:
    """Sign unsigned entries in order, up to and including entry ``up_to``; return how many.

    The whole chain is checked first, so the key holder never signs a tampered entry.
    ``up_to`` should be the last entry the key holder reviewed (``sign-pending --daftar``);
    entries appended after the review stay unsigned. None signs every pending entry.
    """
    with registry.transaction():
        return registry._sign_pending(signer, up_to)


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
            signer=signer)]
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
