"""A coalition that knows the erasure check: escape against detection (abstract, code level).

Grid and seed fixed and committed before running. eps = 1e-6, N = 20, design c = 3 (default
length m = 2987), coalitions of k = 2 and 3, full read of every position, 500 trials per cell,
seed [7401, k, cell index]. The coalition erases each position where its k codewords agree
with probability e_A and each position where they differ with probability e_D, independently;
it leaks the bit of a random member at every other position (interleaving). Grid:
e_A in {0.5, 0.8, 0.9, 1.0} and e_D in {0, 0.25, 0.5, 0.75, 0.9, 1.0}.

Per trial: escape (no member reaches Z(p, w), w = 1 read, 0 erased, Z from the bias vector and
the weights as in the decoder) and the erasure statistic of ``tapak.decoder.erasure`` with
strengths 1 + N(0, 0.2^2) at read positions and N(0, 0.2^2) in absolute value at erased
ones (a clean read; an erased unit still measures noise). Detection: Z <= -3.0902 (the
nominal threshold; the calibrated one is reported in the docs). When e_A = e_D the erasure
does not depend on agreement: the proven miss bound for the positions left then applies.

    python research/sepakat/sadar.py --out research/sepakat/hasil/sadar.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

EPS, N, C = 1e-6, 20, 3
TRIALS = 500
E_AGREE = (0.5, 0.8, 0.9, 1.0)
E_DIFFER = (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)
Z_ALARM = 3.0902


def cell(args: tuple[int, int, float, float]) -> dict:
    """One (k, e_A, e_D) cell."""
    from tapak.decoder.erasure import agreement_score, erasure_z
    from tapak.tardos.accuse import scores, threshold
    from tapak.tardos.code import random_code
    from tapak.tardos.params import TardosParams

    k, idx, ea, ed = args
    params = TardosParams(c=C, eps=EPS, n_max=N)
    m = params.length
    rng = np.random.default_rng([7401, k, idx])
    escapes = detections = 0
    read = 0
    t0 = time.perf_counter()
    for _ in range(TRIALS):
        p, x = random_code(params, k, rng, m)
        agree = np.all(x == x[:1], axis=0)
        erase = np.where(agree, rng.random(m) < ea, rng.random(m) < ed)
        y = x[rng.integers(0, k, m), np.arange(m)].astype(np.uint8)
        w = np.where(erase, 0.0, 1.0)
        read += int(w.sum())
        z = threshold(p, params.eps1, w) if w.any() else math.inf
        s = scores(x.astype(np.float64), y, p, w) if w.any() else np.zeros(k)
        escapes += int(not (math.isfinite(z) and np.any(s >= z)))
        strength = np.where(erase, np.abs(rng.normal(0, 0.2, m)), 1.0 + rng.normal(0, 0.2, m))
        detections += int(erasure_z(strength, agreement_score(p)) <= -Z_ALARM)
    return {"k": k, "e_sama": ea, "e_beda": ed, "m": m, "percobaan": TRIALS, "terbaca_rata2": round(read / TRIALS, 1),
            "lolos": round(escapes / TRIALS, 4), "terdeteksi": round(detections / TRIALS, 4),
            "detik": round(time.perf_counter() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)
    cells = [(k, i, ea, ed) for k in (2, 3) for i, (ea, ed) in enumerate((a, d) for a in E_AGREE for d in E_DIFFER)]
    with ProcessPoolExecutor(max_workers=min(3, args.workers)) as pool, args.out.open("a", encoding="utf-8") as fh:
        for row in pool.map(cell, cells):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
