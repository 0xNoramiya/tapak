"""Append-only log of canary DNS hits (SQLite table ``canary_events``).

The table lives in a database file given by path. The file is shared with the registry,
so this module only touches its own objects (table ``canary_events``, index
``canary_events_token`` and the two triggers named after the table) and creates them with
``IF NOT EXISTS``.

Write path and read path are separate on purpose:

* :func:`connect_writer`, :func:`record_event` and :func:`init_store` create the schema,
  but only when the table does not exist yet. They never re-create a trigger that has
  gone missing, because a missing trigger is a sign that someone edited the file by hand
  and a verifier must be able to see it.
* :func:`events`, :func:`chain_head` and the verification functions open the file
  read-only (``mode=ro``) and never create or repair anything. Verifying a file that does
  not exist, or whose table or triggers are gone, fails.

Hash chain: every row stores the hash of the previous row (``prev_hash``) and its own hash

    hash = SHA-256(prev_hash || compact JSON of [seq, received_at, qname, token, qtype,
                                                  src_ip, src_port])

starting from 64 zeros. What this proves, honestly:

* On its own the chain is unkeyed. It catches accidental damage and naive edits (a row
  changed or deleted in the middle without recomputing the later hashes). Anyone who can
  write the file can drop the triggers, edit or delete rows and recompute every later
  hash in a few lines; the plain chain check then passes. It also cannot see rows cut off
  at the end.
* Anchoring closes that gap. :func:`anchor_head` writes the current ``(seq, hash)`` head
  into the TAPAK registry as an entry of kind ``canary_anchor``; the registry signs its
  entries with Ed25519 (immediately with a signer, or later when the key holder signs
  pending entries). :func:`verify_events_anchored` then checks every signed anchor: row
  ``seq`` must still exist with exactly that hash. A recomputed chain or a cut-off tail
  that reaches back to an anchored row fails. Rows written after the newest signed
  anchor are protected only by the plain chain until the next anchor.

Two triggers reject UPDATE and DELETE through SQLite, so honest code cannot rewrite
history by mistake.

What an event means: a row shows that some host sent this DNS query to the listener. It
does not show who opened a file. Queries are unauthenticated: anyone who holds a copy can
read its token and send queries for it, UDP source addresses can be spoofed, and the
listener logs any well-formed token, issued or not. Reports should show only tokens that
match an issued copy and treat events as weak supporting evidence.

Data minimization: a row holds only the query name, the token, the query type, the source
address and port, and the time. No document text, no recipient data.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tapak.registry.signing import Signer

GENESIS_HASH = "0" * 64
TABLE = "canary_events"
ANCHOR_KIND = "canary_anchor"
MAX_LISTED_PROBLEMS = 20
_LOCK = threading.Lock()

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS canary_events (
    seq INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    qname TEXT NOT NULL,
    token TEXT NOT NULL,
    qtype TEXT NOT NULL,
    src_ip TEXT NOT NULL,
    src_port INTEGER NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
)"""
_INDEX_SQL = "CREATE INDEX IF NOT EXISTS canary_events_token ON canary_events (token)"
TRIGGERS: dict[str, str] = {
    "canary_events_no_update": "BEFORE UPDATE ON canary_events BEGIN "
    "SELECT RAISE(ABORT, 'canary_events hanya boleh ditambah, tidak boleh diubah'); END",
    "canary_events_no_delete": "BEFORE DELETE ON canary_events BEGIN "
    "SELECT RAISE(ABORT, 'canary_events hanya boleh ditambah, tidak boleh dihapus'); END",
}

_COLUMNS = "seq, received_at, qname, token, qtype, src_ip, src_port, prev_hash, hash"


@dataclass(frozen=True)
class CanaryEvent:
    """One logged DNS query for a canary name."""

    seq: int
    received_at: str
    qname: str
    token: str
    qtype: str
    src_ip: str
    src_port: int
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class NewEvent:
    """A query waiting to be appended: every column except seq and the two hashes."""

    received_at: datetime | str
    qname: str
    token: str
    qtype: str
    src_ip: str
    src_port: int


@dataclass
class ChainReport:
    """Result of a chain check. ``problems`` and ``warnings`` are Indonesian sentences."""

    rows: int = 0
    head: tuple[int, str] = (0, GENESIS_HASH)
    anchors_checked: int = 0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no problem was found."""
        return not self.problems

    def lines(self) -> list[str]:
        """Human-readable summary (Indonesian), one line per item."""
        out = [
            f"Rantai catatan kanari: {'UTUH' if self.ok else 'RUSAK'}",
            f"  Jumlah catatan     : {self.rows}",
            f"  Ujung rantai       : #{self.head[0]} {self.head[1][:16]}...",
            f"  Jangkar diperiksa  : {self.anchors_checked}",
        ]
        out += [f"  MASALAH: {p}" for p in self.problems]
        out += [f"  Catatan: {w}" for w in self.warnings]
        return out


def utc_now() -> str:
    """Current UTC time in the ISO format used for ``received_at``."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalize_time(value: datetime | str) -> str:
    """Canonical ``received_at`` form: UTC, microseconds, ``+00:00``.

    Accepts a datetime or an ISO 8601 string (``Z`` or any offset; naive means UTC), so
    stored values and ``since`` filters always compare correctly as strings.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError(f"waktu bukan format ISO 8601 yang sah: {value!r}") from None
    if not isinstance(value, datetime):
        raise ValueError(f"waktu harus berupa datetime atau teks ISO 8601: {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def event_hash(prev_hash: str, seq: int, received_at: str, qname: str, token: str,
               qtype: str, src_ip: str, src_port: int) -> str:
    """Chain hash of one row (see module docstring)."""
    body = json.dumps([seq, received_at, qname, token, qtype, src_ip, src_port],
                      separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256((prev_hash + body).encode("ascii")).hexdigest()


# --- write path --------------------------------------------------------------------------


def _has_table(con: sqlite3.Connection, name: str = TABLE) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


def _trigger_problems(con: sqlite3.Connection) -> list[str]:
    """Missing or altered append-only triggers (Indonesian messages)."""
    problems = []
    for name, body in TRIGGERS.items():
        row = con.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                          (name,)).fetchone()
        if row is None:
            problems.append(f"pemicu {name} hilang (berkas pernah disunting di luar TAPAK)")
        elif " ".join(str(row[0]).split()) != " ".join(f"CREATE TRIGGER {name} {body}".split()):
            problems.append(f"pemicu {name} telah diubah (berkas pernah disunting di luar TAPAK)")
    return problems


def connect_writer(db_path: str | Path) -> sqlite3.Connection:
    """Open a write connection. Creates table, index and triggers only for a new table.

    A trigger missing from an existing table is not re-created (see module docstring).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    try:
        if not _has_table(con):
            con.execute("BEGIN IMMEDIATE")
            try:
                if not _has_table(con):  # another process may have created it meanwhile
                    con.execute(_TABLE_SQL)
                    con.execute(_INDEX_SQL)
                    for name, body in TRIGGERS.items():
                        con.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {body}")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
    except BaseException:
        con.close()
        raise
    return con


def init_store(db_path: str | Path) -> list[str]:
    """Create the store if needed; return warnings (Indonesian) about missing triggers."""
    con = connect_writer(db_path)
    try:
        return _trigger_problems(con)
    finally:
        con.close()


def append_events(con: sqlite3.Connection, items: Sequence[NewEvent]) -> list[CanaryEvent]:
    """Append several events in one transaction on a connection from :func:`connect_writer`.

    The last row is read and the new rows written inside one ``BEGIN IMMEDIATE``
    transaction, so concurrent writers (threads or processes) cannot fork the chain.
    ``qname`` and ``token`` are stored in lowercase and ``received_at`` in canonical form.
    """
    rows = [(normalize_time(i.received_at), i.qname.lower(), i.token.lower(), i.qtype, i.src_ip,
             int(i.src_port)) for i in items]
    out: list[CanaryEvent] = []
    with _LOCK:
        con.execute("BEGIN IMMEDIATE")
        try:
            last = con.execute("SELECT seq, hash FROM canary_events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last[0], last[1]) if last else (0, GENESIS_HASH)
            for when, qname, token, qtype, ip, port in rows:
                seq += 1
                h = event_hash(prev, seq, when, qname, token, qtype, ip, port)
                con.execute(f"INSERT INTO canary_events ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (seq, when, qname, token, qtype, ip, port, prev, h))
                out.append(CanaryEvent(seq, when, qname, token, qtype, ip, port, prev, h))
                prev = h
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
    return out


def record_event(db_path: str | Path, qname: str, token: str, qtype: str, src_ip: str,
                 src_port: int, received_at: datetime | str | None = None) -> CanaryEvent:
    """Append one event to the chain and return it (opens and closes its own connection)."""
    item = NewEvent(utc_now() if received_at is None else received_at, qname, token, qtype,
                    src_ip, int(src_port))
    con = connect_writer(db_path)
    try:
        return append_events(con, [item])[0]
    finally:
        con.close()


# --- read path (read-only, never creates anything) ---------------------------------------


def _connect_ro(db_path: str | Path) -> sqlite3.Connection | None:
    """Read-only connection, or None when the file does not exist."""
    path = Path(db_path)
    if not path.is_file():
        return None
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10.0)


def _read_rows(db_path: str | Path, where: str = "", args: Sequence[object] = ()) -> list[tuple]:
    con = _connect_ro(db_path)
    if con is None:
        return []
    try:
        if not _has_table(con):
            return []
        return con.execute(f"SELECT {_COLUMNS} FROM canary_events {where} ORDER BY seq", args).fetchall()
    finally:
        con.close()


def events(db_path: str | Path, token: str | None = None,
           since: datetime | str | None = None) -> list[CanaryEvent]:
    """Logged events in chain order, optionally for one token and/or from a time on.

    ``since`` is a datetime or an ISO 8601 string (normalized like ``received_at``).
    Returns an empty list when the file or the table does not exist; use
    :func:`check_events_chain` to tell a missing log from an empty one.
    """
    clauses, args = [], []
    if token is not None:
        clauses.append("token = ?")
        args.append(token.lower())
    if since is not None:
        clauses.append("received_at >= ?")
        args.append(normalize_time(since))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return [CanaryEvent(*row) for row in _read_rows(db_path, where, args)]


def chain_head(db_path: str | Path) -> tuple[int, str]:
    """(last seq, last hash) of the chain, or (0, GENESIS_HASH) when it is empty or absent."""
    con = _connect_ro(db_path)
    if con is None:
        return 0, GENESIS_HASH
    try:
        if not _has_table(con):
            return 0, GENESIS_HASH
        last = con.execute("SELECT seq, hash FROM canary_events ORDER BY seq DESC LIMIT 1").fetchone()
    finally:
        con.close()
    return (int(last[0]), str(last[1])) if last else (0, GENESIS_HASH)


def _walk_chain(rows: list[tuple], report: ChainReport) -> dict[int, str]:
    """Check seq order and every link and hash; return {seq: stored hash}."""
    prev, expected_seq, by_seq = GENESIS_HASH, 1, {}
    for row in rows:
        ev = CanaryEvent(*row)
        if ev.seq != expected_seq:
            report.problems.append(f"nomor urut melompat: diharapkan #{expected_seq}, ditemukan #{ev.seq} "
                                   "(catatan dihapus atau disisipkan)")
        if ev.prev_hash != prev:
            report.problems.append(f"catatan #{ev.seq}: prev_hash tidak sama dengan hash catatan sebelumnya")
        if event_hash(ev.prev_hash, ev.seq, ev.received_at, ev.qname, ev.token, ev.qtype,
                      ev.src_ip, ev.src_port) != ev.hash:
            report.problems.append(f"catatan #{ev.seq}: hash tidak cocok dengan isinya (isi diubah)")
        by_seq[ev.seq] = ev.hash
        prev, expected_seq = ev.hash, ev.seq + 1
    report.rows = len(rows)
    if rows:
        report.head = (int(rows[-1][0]), str(rows[-1][8]))
    return by_seq


def check_events_chain(db_path: str | Path,
                       expected_heads: Iterable[tuple[int, str]] = ()) -> ChainReport:
    """Full read-only check of the event log, with Indonesian messages.

    Problems: file or table missing, append-only triggers missing or altered, a gap in
    ``seq``, a broken ``prev_hash`` link, a hash that does not recompute, and for every
    ``(seq, hash)`` in ``expected_heads`` (trusted anchors) a row ``seq`` that is missing
    or holds a different hash.
    """
    report = ChainReport()
    path = Path(db_path)
    try:
        con = _connect_ro(path)
        if con is None:
            report.problems.append(f"berkas catatan kanari tidak ditemukan: {path}")
            return report
        try:
            if not _has_table(con):
                report.problems.append("tabel canary_events tidak ada (terhapus atau belum pernah dibuat)")
                return report
            report.problems += _trigger_problems(con)
            rows = con.execute(f"SELECT {_COLUMNS} FROM canary_events ORDER BY seq").fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        report.problems.append(f"berkas tidak dapat dibaca sebagai basis data SQLite ({exc})")
        return report
    by_seq = _walk_chain(rows, report)
    for seq, h in expected_heads:
        report.anchors_checked += 1
        if seq == 0:
            continue
        if seq not in by_seq:
            report.problems.append(f"catatan #{seq} yang dijangkarkan tidak ada lagi (ujung rantai dipotong "
                                   "atau catatan dihapus)")
        elif by_seq[seq] != h:
            report.problems.append(f"hash catatan #{seq} berbeda dari jangkar (rantai ditulis ulang)")
    if len(report.problems) > MAX_LISTED_PROBLEMS:
        more = len(report.problems) - MAX_LISTED_PROBLEMS
        report.problems = report.problems[:MAX_LISTED_PROBLEMS] + [f"... dan {more} masalah lain"]
    if not rows:
        report.warnings.append("catatan kanari masih kosong")
    return report


def verify_events_chain(db_path: str | Path, expected_head: tuple[int, str] | None = None) -> bool:
    """True if the log exists with its triggers, seq runs 1, 2, 3, ... and every hash
    recomputes; with ``expected_head`` (a trusted anchor) row ``seq`` must also hold that
    hash. Never creates or repairs anything."""
    heads = [expected_head] if expected_head is not None else []
    return check_events_chain(db_path, heads).ok


# --- anchoring in the signed registry ----------------------------------------------------


def anchor_head(db_path: str | Path, signer: Signer | None = None,
                registry_path: str | Path | None = None) -> tuple[int, str]:
    """Record the current chain head in the TAPAK registry; return the anchored head.

    Appends a registry entry of kind ``canary_anchor`` with payload
    ``{"events_seq": seq, "events_hash": hash}`` to ``registry_path`` (default: the same
    file as the events). With ``signer`` the entry is signed now (the registry refuses
    this while older entries are unsigned); without it the entry stays pending until the
    key holder signs pending entries, so the internet-facing listener never needs the
    private key. Refuses (ValueError) to anchor a log that fails :func:`check_events_chain`.
    Nothing is written while the log is empty.
    """
    from tapak.registry.chain import Registry

    report = check_events_chain(db_path)
    if not report.ok:
        raise ValueError("rantai catatan kanari tidak utuh, jangkar tidak dibuat: " + "; ".join(report.problems))
    if report.head[0] == 0:
        return report.head
    with Registry.open(registry_path or db_path) as reg:
        reg.append(ANCHOR_KIND, {"events_seq": report.head[0], "events_hash": report.head[1]}, signer=signer)
    return report.head


def read_anchors(registry_path: str | Path, public_key_hex: str) -> tuple[list[tuple[int, str]], int]:
    """Signed canary anchors in the registry, read-only: ``(valid heads, invalid count)``.

    An anchor counts only if its entry hash recomputes and its Ed25519 signature verifies
    under ``public_key_hex``. Unsigned (pending) anchors are ignored, not counted as
    invalid. The registry's own chain is checked by ``tapak-verify-registry``.
    """
    from tapak.registry.chain import compute_entry_hash
    from tapak.registry.signing import normalize_public_key, verify_signature

    pub = normalize_public_key(public_key_hex)
    con = _connect_ro(registry_path)
    if con is None:
        return [], 0
    try:
        if not _has_table(con, "entries"):
            return [], 0
        rows = con.execute("SELECT seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer "
                           "FROM entries WHERE kind = ? ORDER BY seq", (ANCHOR_KIND,)).fetchall()
    finally:
        con.close()
    heads, invalid = [], 0
    for seq, kind, payload_text, prev_hash, created_at, entry_hash, signature, signer in rows:
        if signature is None:
            continue
        try:
            payload = json.loads(payload_text)
            ok = (compute_entry_hash(seq, kind, payload, prev_hash, created_at) == entry_hash
                  and signer == pub and verify_signature(pub, bytes.fromhex(entry_hash), signature))
            head = (int(payload["events_seq"]), str(payload["events_hash"]))
        except (TypeError, ValueError, KeyError):
            ok = False
        if ok:
            heads.append(head)
        else:
            invalid += 1
    return heads, invalid


def verify_events_anchored(db_path: str | Path, public_key_hex: str,
                           registry_path: str | Path | None = None) -> ChainReport:
    """:func:`check_events_chain` against every signed anchor in the registry."""
    heads, invalid = read_anchors(registry_path or db_path, public_key_hex)
    report = check_events_chain(db_path, heads)
    if invalid:
        report.problems.append(f"{invalid} jangkar kanari di registri tidak sah (hash atau tanda tangan salah)")
    if not heads:
        report.warnings.append("belum ada jangkar bertanda tangan di registri: penulisan ulang rantai atau "
                               "pemotongan ujungnya tidak dapat dideteksi")
    elif report.head[0] > max(seq for seq, _ in heads):
        report.warnings.append(f"catatan #{max(seq for seq, _ in heads) + 1} sampai #{report.head[0]} belum "
                               "dijangkarkan")
    return report
