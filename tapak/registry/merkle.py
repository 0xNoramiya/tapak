"""Daily Merkle roots over the registry's entry hashes.

Tree (binary, SHA-256, exactly as specified):

* the leaves are the ``entry_hash`` values (as 32 raw bytes) of the entries created on one
  UTC date, in ``seq`` order;
* an inner node is ``SHA-256(left || right)``;
* a level with an odd number of nodes pairs its last node with itself (the odd node is
  duplicated); a single leaf is its own root, so a day with one entry has that entry's
  hash as its root.

Two known properties of this plain construction, and how they are pinned down:

* duplicating the odd node means ``[a, b, c]`` and ``[a, b, c, c]`` share a root, so every
  root file also records the number of entries and the ``seq`` range;
* leaves and inner nodes are not domain-separated, so a proof alone could present an inner
  node as a "leaf". :func:`verify_proof` therefore accepts the leaf's ``index`` and the
  day's ``count`` and then requires a proof of exactly the right length and shape; and a
  leaf only means something when it is the recomputed ``entry_hash`` of a real entry.
  :func:`check_daily_roots` never relies on proofs: it rebuilds each root from the
  registry rows.

One text file per completed UTC day, ``merkle-YYYY-MM-DD.txt``, with ``key: value`` lines::

    date: 2026-11-03
    entries: 12
    first_seq: 1
    last_seq: 12
    root: <64 hex>
    previous_root_file_sha256: <SHA-256 of the previous day's file; 64 zeros for the first>

The files chain to each other. Copy them off the machine (print them, send them to a
higher echelon): a root kept elsewhere reveals any later change to that day, including
entries deleted from the end of the chain, which the hash chain alone cannot show.

A day's file is written once, after the UTC day has ended, and is never rewritten, so a
copy taken off the machine stays valid. The running day can be exported on request as
``merkle-YYYY-MM-DD.partial.txt``: same lines, rewritten on each export, outside the
``previous_root_file_sha256`` chain, and deleted when the day's final file is written.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timezone
from pathlib import Path

from tapak.registry.chain import ZERO_HASH, RegistryError, parse_time

FILE_PREFIX = "merkle-"
FILE_SUFFIX = ".txt"
PARTIAL_SUFFIX = ".partial.txt"
_FIELDS = ("date", "entries", "first_seq", "last_seq", "root", "previous_root_file_sha256")
_FINAL_NAME = re.compile(r"merkle-([0-9]{4}-[0-9]{2}-[0-9]{2})\.txt")
_PARTIAL_NAME = re.compile(r"merkle-([0-9]{4}-[0-9]{2}-[0-9]{2})\.partial\.txt")

Proof = list[tuple[str, str]]  # (sibling hash hex, "L" or "R": side of the sibling)


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def _levels(entry_hashes: Sequence[str]) -> list[list[bytes]]:
    """All tree levels from the leaves up to the root (levels are stored unpadded)."""
    if not entry_hashes:
        raise ValueError("pohon Merkle membutuhkan minimal satu entri")
    level = [bytes.fromhex(h) for h in entry_hashes]
    if any(len(leaf) != 32 for leaf in level):
        raise ValueError("daun pohon Merkle harus hash SHA-256 (64 karakter heksadesimal)")
    levels = [level]
    while len(level) > 1:
        padded = level + [level[-1]] if len(level) % 2 else level
        level = [_node(padded[i], padded[i + 1]) for i in range(0, len(padded), 2)]
        levels.append(level)
    return levels


def merkle_root(entry_hashes: Sequence[str]) -> str:
    """Root (hex) of the tree over ``entry_hashes`` in the given order."""
    return _levels(entry_hashes)[-1][0].hex()


def tree_depth(count: int) -> int:
    """Number of levels above the leaves for ``count`` leaves (the length of every proof)."""
    if count < 1:
        raise ValueError("pohon Merkle membutuhkan minimal satu entri")
    depth = 0
    while count > 1:
        count, depth = (count + 1) // 2, depth + 1
    return depth


def merkle_proof(entry_hashes: Sequence[str], index: int) -> Proof:
    """Inclusion proof for ``entry_hashes[index]``: sibling hashes from leaf to root."""
    if not 0 <= index < len(entry_hashes):
        raise IndexError("indeks di luar daftar entri")
    proof: Proof = []
    idx = index
    for level in _levels(entry_hashes)[:-1]:
        sib = idx ^ 1
        sibling = level[sib] if sib < len(level) else level[idx]  # odd node: paired with itself
        proof.append((sibling.hex(), "L" if sib < idx else "R"))
        idx //= 2
    return proof


def verify_proof(leaf: str, proof: Sequence[tuple[str, str]], root: str,
                 index: int | None = None, count: int | None = None) -> bool:
    """True if ``proof`` links entry hash ``leaf`` to ``root``.

    With ``index`` (position of the leaf) and ``count`` (entries that day, from the root
    file) the proof must also have exactly :func:`tree_depth` steps, each on the side the
    index dictates, which rules out passing an inner node off as a leaf.
    """
    try:
        if index is not None and count is not None:
            if not 0 <= index < count or len(proof) != tree_depth(count):
                return False
            idx = index
            for _, side in proof:
                if side != ("L" if idx % 2 else "R"):
                    return False
                idx //= 2
        h = bytes.fromhex(leaf)
        if len(h) != 32:
            return False
        for sibling_hex, side in proof:
            sibling = bytes.fromhex(sibling_hex)
            if len(sibling) != 32:
                return False
            if side == "L":
                h = _node(sibling, h)
            elif side == "R":
                h = _node(h, sibling)
            else:
                return False
    except (ValueError, TypeError):
        return False
    return h.hex() == root.strip().lower()


def utc_date(created_at: str) -> str:
    """UTC calendar date (YYYY-MM-DD) of an entry timestamp."""
    return parse_time(created_at).astimezone(timezone.utc).date().isoformat()


def read_hash_rows(db_path: str | Path) -> list[tuple[int, str, str]]:
    """(seq, created_at, entry_hash) of every entry, read-only, in ``seq`` order."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"berkas registri tidak ditemukan: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return [(int(s), str(c), str(h)) for s, c, h in
                conn.execute("SELECT seq, created_at, entry_hash FROM entries ORDER BY seq")]
    finally:
        conn.close()


@dataclass(frozen=True)
class DailyRoot:
    """Merkle root of the entries created on one UTC date."""

    date: str
    entries: int
    first_seq: int
    last_seq: int
    root: str

    def to_text(self, previous_root_file_sha256: str) -> str:
        """Content of the day's root file."""
        values = (self.date, self.entries, self.first_seq, self.last_seq, self.root, previous_root_file_sha256)
        return "".join(f"{k}: {v}\n" for k, v in zip(_FIELDS, values))


def _group_by_date(rows: Sequence[tuple[int, str, str]]) -> dict[str, list[tuple[int, str]]]:
    days: dict[str, list[tuple[int, str]]] = {}
    for seq, created_at, entry_hash in rows:
        days.setdefault(utc_date(created_at), []).append((seq, entry_hash))
    return dict(sorted(days.items()))


def _roots_from_rows(rows: Sequence[tuple[int, str, str]]) -> list[DailyRoot]:
    return [DailyRoot(day, len(items), items[0][0], items[-1][0], merkle_root([h for _, h in items]))
            for day, items in _group_by_date(rows).items()]


def daily_roots(db_path: str | Path) -> list[DailyRoot]:
    """One :class:`DailyRoot` per UTC date that has entries, oldest first."""
    return _roots_from_rows(read_hash_rows(db_path))


def root_file_name(day: str) -> str:
    """File name of a completed day's root file."""
    return f"{FILE_PREFIX}{day}{FILE_SUFFIX}"


def partial_file_name(day: str) -> str:
    """File name of a running day's provisional root file."""
    return f"{FILE_PREFIX}{day}{PARTIAL_SUFFIX}"


def parse_root_file(text: str) -> dict[str, str]:
    """``key: value`` lines of a root file as a dict."""
    out = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _today(today: Date | str | None) -> str:
    if today is None:
        return datetime.now(timezone.utc).date().isoformat()
    return today if isinstance(today, str) else today.isoformat()


def export_daily_roots(
    db_path: str | Path,
    out_dir: str | Path,
    today: Date | str | None = None,
    include_partial: bool = False,
) -> list[Path]:
    """Write the root file of every completed UTC day into ``out_dir``; return their paths.

    A day is completed when its date is before ``today`` (default: the current UTC date).
    Existing files are never rewritten: an identical file is left alone and a different
    one raises RegistryError, because that means the registry or the file was changed.
    With ``include_partial`` the running day(s) are also written as ``.partial.txt``
    files, which are provisional and outside the chain.
    """
    rows = read_hash_rows(db_path)
    day_limit = _today(today)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    previous = ZERO_HASH
    paths = []
    roots = _roots_from_rows(rows)
    for r in (r for r in roots if r.date < day_limit):
        text = r.to_text(previous)
        path = out_dir / root_file_name(r.date)
        if path.exists():
            if path.read_bytes() != text.encode("utf-8"):
                raise RegistryError(f"{path.name} sudah ada dan berbeda dari registri; berkas akar tidak pernah "
                                    "ditulis ulang (registri atau berkas akar telah diubah)")
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            (out_dir / partial_file_name(r.date)).unlink(missing_ok=True)
        previous = _sha256_text(text)
        paths.append(path)
    if include_partial:
        for r in (r for r in roots if r.date >= day_limit):
            path = out_dir / partial_file_name(r.date)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(r.to_text(previous), encoding="utf-8")
            tmp.replace(path)
            paths.append(path)
    return paths


def _day_of(by_seq: dict[int, tuple[str, str]], seq: int) -> str | None:
    try:
        return utc_date(by_seq[seq][0]) if seq in by_seq else None
    except ValueError:
        return None


def _check_root_fields(fields: dict[str, str], by_seq: dict[int, tuple[str, str]], name: str,
                       final: bool) -> list[tuple[int, str]]:
    """Compare one parsed root file with the registry rows; return problems.

    Every final file must cover its whole day: no entry of that date just before
    ``first_seq`` or just after ``last_seq``. A partial file must cover the start only.
    """
    missing = [k for k in _FIELDS if k not in fields]
    if missing:
        return [(0, f"{name}: kolom {missing} tidak ada")]
    try:
        day = Date.fromisoformat(fields["date"]).isoformat()
        n, first, last = int(fields["entries"]), int(fields["first_seq"]), int(fields["last_seq"])
    except ValueError:
        return [(0, f"{name}: isi berkas tidak sah")]
    expected_name = root_file_name(day) if final else partial_file_name(day)
    problems = []
    if name != expected_name:
        problems.append((0, f"{name}: nama berkas tidak sesuai tanggal di dalamnya ({day})"))
    if n != last - first + 1 or n < 1:
        return problems + [(first, f"{name}: jumlah entri {n} tidak sesuai rentang #{first}..#{last}")]
    absent = [s for s in range(first, last + 1) if s not in by_seq]
    if absent:
        span = f"#{absent[0]}" if len(absent) == 1 else f"#{absent[0]}..#{absent[-1]}"
        return problems + [(absent[0], f"{name}: entri {span} tercatat di akar harian "
                                       "tetapi tidak ada di registri (entri dihapus?)")]
    wrong_day = [s for s in range(first, last + 1) if _day_of(by_seq, s) != day]
    if wrong_day:
        problems.append((wrong_day[0], f"{name}: entri #{wrong_day[0]} tidak bertanggal {day} di registri"))
    if _day_of(by_seq, first - 1) == day:
        problems.append((first - 1, f"{name}: entri #{first - 1} bertanggal {day} tetapi tidak tercakup "
                                    "di berkas akar hari itu"))
    if final and _day_of(by_seq, last + 1) == day:
        problems.append((last + 1, f"{name}: entri #{last + 1} bertanggal {day} tetapi tidak tercakup di berkas "
                                   "akar hari itu (ditambahkan setelah hari ditutup?)"))
    try:
        root = merkle_root([by_seq[s][1] for s in range(first, last + 1)])
    except ValueError:
        root = ""
    if root != fields["root"].lower():
        problems.append((first, f"{name}: akar Merkle tidak cocok dengan entri #{first}..#{last} di registri"))
    return problems


def check_daily_roots(db_path: str | Path, merkle_dir: str | Path) -> tuple[int, list[tuple[int, str]]]:
    """Check every root file in ``merkle_dir`` against the registry.

    Returns (number of files checked, problems). Final day files must be named after their
    date, cover their whole day and chain through ``previous_root_file_sha256``; the file
    of the registry's first day must point to 64 zeros. Partial files are checked as a
    prefix of their day and are not part of the chain.
    """
    rows = read_hash_rows(db_path)
    by_seq = {s: (c, h) for s, c, h in rows}
    first_day = _day_of(by_seq, rows[0][0]) if rows else None
    finals, partials, problems = [], [], []
    for path in sorted(p for p in Path(merkle_dir).glob(f"{FILE_PREFIX}*{FILE_SUFFIX}") if p.is_file()):
        if _FINAL_NAME.fullmatch(path.name):
            finals.append(path)
        elif _PARTIAL_NAME.fullmatch(path.name):
            partials.append(path)
        else:
            problems.append((0, f"{path.name}: nama berkas tidak sesuai pola merkle-YYYY-MM-DD.txt"))
    if not finals and not partials:
        return 0, problems + [(0, f"tidak ada berkas akar Merkle di {merkle_dir}")]
    previous_sha: str | None = None
    for path in finals:
        raw = path.read_bytes()
        fields = parse_root_file(raw.decode("utf-8", errors="replace"))
        problems += _check_root_fields(fields, by_seq, path.name, final=True)
        link = fields.get("previous_root_file_sha256", "")
        if previous_sha is not None and link != previous_sha:
            problems.append((0, f"{path.name}: tidak menyambung ke berkas akar hari sebelumnya"))
        if previous_sha is None and fields.get("date") == first_day and link != ZERO_HASH:
            problems.append((0, f"{path.name}: berkas hari pertama harus menunjuk 64 angka nol"))
        previous_sha = hashlib.sha256(raw).hexdigest()
    for path in partials:
        fields = parse_root_file(path.read_bytes().decode("utf-8", errors="replace"))
        problems += _check_root_fields(fields, by_seq, path.name, final=False)
    return len(finals) + len(partials), problems
