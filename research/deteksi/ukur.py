"""Proven miss bound (``tapak.tardos.detection``) next to simulated miss rates.

The evaluation grid was fixed before any simulation was run and is not tuned afterwards:

* eps = 1e-6, N in {20, 100}, design c in {2, 3, 4, 5}, coalition size = c, every strategy
  in ``tapak.tardos.attacks.STRATEGIES`` (including ``worst-case``), 1000 trials per cell,
  hard-decision code-level simulation (``run_simulation``, no channel noise);
* code lengths: the default (K = 2 pi^2), and the shorter codes whose proven bound for
  coalitions of at most c is 0.9, 0.5, 0.1 and 0.01 (``min_length``). Those lengths come
  from the bound alone, not from simulated rates; they are short enough that misses occur,
  so the comparison means something;
* seeds: 1000 c + N + level index (0 for the default length, 1 to 4 for the levels).

A miss is a trial in which no colluder reaches the threshold. A cell agrees with the proof
when the measured miss rate is at most the proven bound.

Usage (from the repository root, at most 3 worker processes on a shared machine):

    python research/deteksi/ukur.py batas > research/deteksi/hasil/batas.jsonl
    python research/deteksi/ukur.py simulasi --workers 3 > research/deteksi/hasil/simulasi.jsonl

Each line is one JSON object. ``batas`` also gives, for delta in {1e-3, 1e-6}, the shortest
code (and its K) with a proven miss bound <= delta. The committed ``simulasi.jsonl`` was run
before BLAS was limited to one thread per worker (below); the seeds fix every random draw, and
the thread count only changes the rounding of matrix products.
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

# One BLAS thread per process, so 3 workers use about 3 cores (set before numpy is imported).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tapak.tardos.detection import miss_bound, min_length, proven_miss_probability  # noqa: E402
from tapak.tardos.params import TardosParams  # noqa: E402
from tapak.tardos.spending import TraceSpending  # noqa: E402

EPS = 1e-6
NS = (20, 100)
CS = (2, 3, 4, 5)
TRIALS = 1000
LEVELS = (0.9, 0.5, 0.1, 0.01)
DELTAS = (1e-3, 1e-6)
MAX_WORKERS = 3


def bounds() -> list[dict]:
    """Proven bounds at the default length, per coalition size, and the lengths for DELTAS."""
    out = []
    for n in NS:
        for c in CS:
            params = TardosParams(c=c, eps=EPS, n_max=n)
            per = [miss_bound(params, k) for k in range(1, c + 1)]
            logged = TraceSpending.logged(EPS, 1).eps1(n)
            out.append({
                "bagian": "bawaan",
                "N": n, "c": c, "m": params.length, "K": params.k_constant,
                "log10_batas_per_koalisi": [round(b.log10_bound, 3) for b in per],
                "log10_batas": round(max(b.log10_bound for b in per), 3),
                "log10_batas_pelacakan_1": round(max(miss_bound(params, k, eps1=logged).log10_bound
                                                     for k in range(1, c + 1)), 3),
                "pilihan_chernoff": list(per[-1].chernoff_choice),
                "galat_kuadratur": max(b.quadrature_error for b in per),
            })
            for delta in DELTAS:
                req = min_length(c, EPS, n, delta)
                out.append({
                    "bagian": "panjang_minimum",
                    "N": n, "c": c, "delta": delta, "m": req.length, "K": round(req.k_constant, 3),
                    "batas": req.bound, "batas_m_kurang_1": req.bound_below,
                })
    return out


def _cells() -> list[tuple[int, int, int, int, float | None]]:
    cells = []
    for n in NS:
        for c in CS:
            params = TardosParams(c=c, eps=EPS, n_max=n)
            cells.append((n, c, params.length, 1000 * c + n, None))
            for i, q in enumerate(LEVELS, start=1):
                cells.append((n, c, min_length(c, EPS, n, q).length, 1000 * c + n + i, q))
    return cells


def _simulate(cell: tuple[int, int, int, int, float | None]) -> list[dict]:
    from tapak.tardos.simulate import run_simulation

    n, c, m, seed, level = cell
    params = TardosParams(c=c, eps=EPS, n_max=n)
    t0 = time.perf_counter()
    rep = run_simulation(params, n_users=n, coalition=c, trials=TRIALS, seed=seed, bound_levels=(), length=m)
    dt = time.perf_counter() - t0
    bound_c = miss_bound(params, c, length=m)
    proven = proven_miss_probability(params, length=m)
    rows = []
    for r in rep.results:
        miss = r.trials - r.detected_trials
        rows.append({
            "N": n, "c": c, "m": m, "K": round(m / (c * c * math.log(1.0 / params.eps1)), 3),
            "tingkat_batas": level, "seed": seed, "strategi": r.strategy, "percobaan": r.trials,
            "lolos": miss, "laju_lolos": miss / r.trials,
            "batas_koalisi_c": bound_c.bound, "batas_koalisi_maks_c": proven,
            "sesuai": miss / r.trials <= proven,
            "tuduhan_salah": r.false_accusation_trials,
            "z_rata2": round(r.mean_threshold, 2), "skor_koalisi_maks_rata2": round(r.mean_top_colluder_score, 2),
            "detik": round(dt, 1),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["batas", "simulasi"])
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = ap.parse_args(argv)
    if args.bagian == "batas":
        for row in bounds():
            print(json.dumps(row), flush=True)
        return 0
    workers = max(1, min(args.workers, MAX_WORKERS))
    cells = _cells()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(_simulate, cells):
            for row in rows:
                print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
