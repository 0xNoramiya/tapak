"""How many readable code positions does one trace need? A code-level Monte Carlo with the
production threshold (Chernoff, eps1 = 1e-8 for N = 100) on the sample's real bias vector.

A trace reads n random code positions; every read bit is wrong with probability e and gets
the weight 1 - 2e. Lone leaker: y = x. c = 3 cut-and-paste: each position comes from one of
three members (thirds). Nothing here looks at results of the image measurements.

    PYTHONPATH=. python -m scripts.cetak.needbits
"""

from __future__ import annotations

import numpy as np

from scripts.cetak.common import context
from tapak.tardos.accuse import scores, threshold

NS = [50, 75, 100, 150, 200, 300, 400, 500, 600, 800, 1000, 1200, 1500, 2000, 2500, 3273]
ES = [0.0, 0.02, 0.05, 0.10, 0.20]
TRIALS = 300


def main() -> None:
    """Print P(named) per (error rate, positions) and the smallest n with P >= 0.95."""
    ctx = context("layar")
    p_all, eps1, m = ctx.p, ctx.params.eps1, ctx.params.length
    rng = np.random.default_rng(99)
    print(f"m={m}, eps1={eps1:g}")
    print("e      n  | lone: P(named)  | c=3: P(>=1 named) P(all 3)")
    table = {}
    for e in ES:
        for n in NS:
            lone = one = all3 = 0
            for _ in range(TRIALS):
                idx = rng.choice(m, n, replace=False)
                p = p_all[idx]
                w = np.full(n, 1 - 2 * e)
                z = threshold(p, eps1, w)
                x = (rng.random((3, n)) < p).astype(np.uint8)
                flips = rng.random(n) < e
                lone += scores(x[0], x[0] ^ flips, p, w) >= z
                owner = rng.permutation(np.arange(n) % 3)
                s3 = scores(x, x[owner, np.arange(n)] ^ flips, p, w)
                one += np.any(s3 >= z)
                all3 += np.all(s3 >= z)
            table[(e, n)] = (lone / TRIALS, one / TRIALS, all3 / TRIALS)
            print(f"{e:4.2f} {n:5d}  | {lone / TRIALS:6.2f}          | {one / TRIALS:6.2f}           "
                  f"{all3 / TRIALS:6.2f}", flush=True)
    print("\nsmallest n with P >= 0.95:")
    for e in ES:
        first = [next((n for n in NS if table[(e, n)][k] >= 0.95), None) for k in range(3)]
        print(f"  e={e:.2f}: lone {first[0]}, c=3 >=1 colluder {first[1]}, c=3 all {first[2]}")


if __name__ == "__main__":
    main()
