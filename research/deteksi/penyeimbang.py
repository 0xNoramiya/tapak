"""Review check: a cross-position, score-balancing coalition against the proven miss bound.

None of the strategies in ``tapak.tardos.attacks`` uses other positions: each leaks a bit from
the colluders' bits at that position alone. The proof in ``tapak.tardos.detection`` also covers
strategies that do. This script plays one: the coalition estimates each choice's contribution
to every member's score by E[U(y, b, p) | z] (Monte Carlo over the bias density, seed 0), visits
its detectable positions in a random order and leaks the bit that keeps the highest running
estimate lowest. A miss needs every member below Z, so levelling the scores is what an evading
coalition wants.

Grid, fixed before running: eps = 1e-6, N = 20, c in {2, 3, 4}, coalition size = c, the code
lengths whose proven bound (coalitions of at most c) is 0.9, 0.5 and 0.1 (``min_length``),
2000 trials per cell, every strategy in ``attacks.STRATEGIES`` plus ``balance`` on the same
codes, seed 777000 + 10 c + 10 level. Only the c colluders' codewords are drawn (innocent
recipients do not change a miss).

Usage (from the repository root, at most 3 worker processes on a shared machine):

    python research/deteksi/penyeimbang.py > research/deteksi/hasil/penyeimbang.jsonl
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from tapak.tardos import attacks  # noqa: E402
from tapak.tardos.accuse import scores, threshold  # noqa: E402
from tapak.tardos.code import random_code  # noqa: E402
from tapak.tardos.detection import min_length, proven_miss_probability  # noqa: E402
from tapak.tardos.params import TardosParams  # noqa: E402

EPS = 1e-6
N = 20
CS = (2, 3, 4)
LEVELS = (0.9, 0.5, 0.1)
TRIALS = 2000
MAX_WORKERS = 3


def posterior_u(c: int, t: float, n: int = 400_000, seed: int = 0) -> np.ndarray:
    """E[U(y, b, p) | z] for leaked bit y, colluder bit b and z = 0..c, by Monte Carlo."""
    rng = np.random.default_rng(seed)
    tp = math.asin(math.sqrt(t))
    p = np.sin(tp + rng.random(n) * (math.pi / 2 - 2 * tp)) ** 2
    z = rng.binomial(c, p)
    g, h = np.sqrt((1 - p) / p), np.sqrt(p / (1 - p))
    out = np.zeros((c + 1, 2, 2))
    for k in range(c + 1):
        sel = z == k
        if sel.any():
            eg, eh = g[sel].mean(), h[sel].mean()
            out[k, 1, 1], out[k, 1, 0], out[k, 0, 0], out[k, 0, 1] = eg, -eh, eh, -eg
    return out


def make_balancer(c: int, t: float):
    eu = posterior_u(c, t)

    def balance(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        xc = np.asarray(xc, dtype=np.int64)
        ones = xc.sum(axis=0)
        y = (ones == c).astype(np.uint8)
        run = np.zeros(c)
        for i in rng.permutation(np.flatnonzero((ones > 0) & (ones < c))):
            c1, c0 = run + eu[ones[i], 1, xc[:, i]], run + eu[ones[i], 0, xc[:, i]]
            if c1.max() < c0.max() or (c1.max() == c0.max() and rng.random() < 0.5):
                y[i], run = 1, c1
            else:
                y[i], run = 0, c0
        return y, np.ones(xc.shape[1])

    return balance


def cell(args: tuple[int, int, float, int]) -> dict:
    c, m, level, seed = args
    params = TardosParams(c=c, eps=EPS, n_max=N)
    strategies = dict(attacks.STRATEGIES)
    strategies["balance"] = make_balancer(c, params.cutoff)
    rng = np.random.default_rng(seed)
    miss = {k: 0 for k in strategies}
    for _ in range(TRIALS):
        p, x = random_code(params, c, rng, m)
        z_full = threshold(p, params.eps1)
        for name, strat in strategies.items():
            y, w = strat(x, rng)
            z = z_full if np.all(w == 1) else threshold(p, params.eps1, w)
            miss[name] += int(not np.any(scores(x.astype(float), y, p, w) >= z))
    bound = proven_miss_probability(params, length=m)
    rates = {k: v / TRIALS for k, v in miss.items()}
    return {"N": N, "c": c, "m": m, "tingkat_batas": level, "seed": seed, "percobaan": TRIALS,
            "batas": bound, "laju_lolos": rates, "sesuai": max(rates.values()) <= bound}


def main() -> int:
    cells = [(c, min_length(c, EPS, N, lvl).length, lvl, 777_000 + 10 * c + int(lvl * 10))
             for c in CS for lvl in LEVELS]
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for row in pool.map(cell, cells):
            print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
