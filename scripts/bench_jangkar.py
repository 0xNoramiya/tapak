"""Time anchored registry writes against a large anchor log (docs/operasi.md, log jangkar).

Builds once, in FOLDER, a registry of N signed entries and its anchor log (one signed line per
entry; the entries are synthetic ``canary_anchor`` rows, no document data), then times writes
on a copy: each write appends one signed entry through ``Registry.open(anchor=...)``, so it
checks the whole log against the registry under the write lock and appends one line, as a
trace does. The first write in a process is a full check; later ones reuse the kept results
(``tapak.registry.anchor.read_anchor_incremental``). ``--full`` forgets them before every
write, which is what every write cost before the check was incremental.

Usage: python scripts/bench_jangkar.py [--n 100000] [--writes 5] [--full] FOLDER
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

from tapak.registry.anchor import AnchorLog, entry_body, forget_memos, line_text, start_body
from tapak.registry.chain import TABLE_SQL, TRIGGERS, ZERO_HASH, Registry, canonical_json, compute_entry_hash
from tapak.registry.signing import Signer

SIGNER = Signer(bytes([7]) * 32)  # a fixed test key, never a real one
STAMP = "2026-10-01T00:00:00.000+00:00"


def build(folder: Path, n: int) -> tuple[Path, Path]:
    """The registry and anchor log of ``n`` entries in ``folder`` (reused when present)."""
    reg_path, log_path = folder / f"registry-{n}.db", folder / f"jangkar-{n}.log"
    if reg_path.exists() and log_path.exists():
        return reg_path, log_path
    log_id = "ab" * 16
    con = sqlite3.connect(reg_path)
    con.execute(TABLE_SQL)
    for name, body in TRIGGERS.items():
        con.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {body}")
    prev, rows = ZERO_HASH, []
    lines = [line_text(start_body(log_id, STAMP, False, None), SIGNER)]
    for seq in range(1, n + 1):
        if seq == 1:
            kind = "anchor_log"
            payload: dict = {"event": "start", "log_id": log_id, "released": [], "reason_sha256": None,
                             "created_at": STAMP}
        else:
            kind, payload = "canary_anchor", {"events_seq": seq, "events_hash": f"{seq:064x}"}
        entry_hash = compute_entry_hash(seq, kind, payload, prev, STAMP)
        rows.append((seq, kind, canonical_json(payload).decode(), prev, STAMP, entry_hash,
                     SIGNER.sign(bytes.fromhex(entry_hash)), SIGNER.public_key_hex))
        lines.append(line_text(entry_body(log_id, seq, kind, STAMP, entry_hash), SIGNER))
        prev = entry_hash
    con.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    log_path.write_text("".join(lines), encoding="utf-8")
    return reg_path, log_path


def one_write(reg_path: Path, log_path: Path) -> float:
    """Seconds for one anchored write (check, append, line)."""
    log = AnchorLog(log_path, signer=SIGNER, public_key=SIGNER.public_key_hex)
    start = time.perf_counter()
    with Registry.open(reg_path, anchor=log) as reg:
        reg.append("canary_anchor", {"events_seq": 0, "events_hash": "0" * 64}, signer=SIGNER)
    assert log.status is not None and log.status.ok
    return time.perf_counter() - start


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--n", type=int, default=100_000)
    ap.add_argument("--writes", type=int, default=5)
    ap.add_argument("--full", action="store_true", help="forget kept results before every write")
    args = ap.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    reg_path, log_path = build(args.folder, args.n)
    work = args.folder / "salinan"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    reg_copy, log_copy = Path(shutil.copy(reg_path, work)), Path(shutil.copy(log_path, work))
    print(f"log {log_path.stat().st_size / 1048576:.1f} MiB, {args.n + 1} baris")
    times = []
    for _ in range(args.writes):
        if args.full:
            forget_memos()
        times.append(one_write(reg_copy, log_copy))
    print("detik per penulisan:", " ".join(f"{t:.2f}" for t in times))


if __name__ == "__main__":
    main()
