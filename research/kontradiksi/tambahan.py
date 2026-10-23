"""Diagnostic added AFTER the held-out run of ``ukur.py`` (not part of the fixed protocol).

Part ``lawan`` compares a reversed forgery with the honest first member through the same
degradation, but the honest copy keeps TAPAK's text channel (zero-width symbols and homoglyphs),
which every forgery of ``tapak.collusion`` strips. On the ``latar`` ladder that channel alone
names the honest copy, so the comparison says little about the background and shift channels.
This diagnostic redraws the first member of every ``lawan`` coalition without its text marks
(the attack on the copy given twice, nothing neutralized: the copy's own shifts and background,
as ``forge_copy`` draws every forgery) and traces it at the noise levels where the warning
stopped for the reversed forgery and around them, with the seeds of part ``lawan``. One JSON
line per evidence, as ``ukur.analyse`` records it.

    python research/kontradiksi/tambahan.py --out research/kontradiksi/hasil/tambahan.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import ukur  # noqa: E402

LEVELS = (0.0, 2.0, 3.0, 4.0, 6.0, "buang")


def job(item: tuple) -> list[dict]:
    """The first member of one coalition, text marks stripped, through the noise levels."""
    from tapak.collusion import attack
    from tapak.decoder.trace import collect_file

    name, iss, k, ci, members = item
    ctx, _ = ukur.context(name)
    first = ukur.copy_pdf(name, members[0])
    stripped, _, _ = attack(ctx.master, [first, first], "salin", 0.0, rng=np.random.default_rng(0))
    rows = []
    for level in LEVELS:
        li = ukur.NOISE_LEVELS.index(level)
        data = ukur.degrade_latar(stripped, level, np.random.default_rng([ukur.SEEDS["lawan_latar"], iss, k, ci, li]))
        obs = collect_file("bukti.pdf", data, ctx)[0]
        rows.append({**ukur._base("tambahan", name), "k": k, "koalisi_ke": ci, "koalisi": members,
                     "serangan": "jujur-tanpa-teks", "tangga": "latar", "tingkat": str(level), "urut": li,
                     **ukur.analyse(obs, ctx, {members[0]})})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    ukur._init()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for item in ukur.lawan_jobs():
            for r in job(item):
                fh.write(json.dumps({"job": json.dumps(item), **r}) + "\n")
            fh.flush()
            print(item, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
