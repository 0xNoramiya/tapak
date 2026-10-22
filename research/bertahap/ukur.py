"""Staged accusation ("pelacakan bertahap") against single-stage accusation, code level.

The grid, the seeds and the stage policy were fixed before any of these simulations was run
(the policy ``bertahap-v1`` and the weights of ``tapak.tardos.staged`` were derived, not tuned
on results):

* ``koalisi``: coalitions larger than the design size. eps = 1e-6 with the whole budget as
  the trace's share (as ``tapak simulate`` and the tables in docs/cara-kerja.md), design
  c = 3, N in {20, 100}, coalition size 3 to 8, every strategy in
  ``tapak.tardos.attacks.STRATEGIES`` (including ``worst-case``), 1000 trials per cell,
  hard-decision reads without channel noise. Seed 50000 + 1000 * coalition + N.
* ``rancangan``: the existing grid for coalitions of at most c, to show what the staged
  policy costs stage 1 there: N in {20, 100}, coalition 1 and 2 (coalition 3 is in
  ``koalisi``), 1000 trials, no noise; and N = 100, coalition 3 with 5 % bit errors and 35 %
  erasures. Seed 60000 + 1000 * coalition + N (+ 1 with noise).
* ``batas``: proven stage-1 miss bounds (``tapak.tardos.detection``) for coalitions of at
  most c (design c = 2 to 5) at the stage-1 target of the staged policy, next to the
  single-stage target, for the whole budget and for logged traces 1, 10 and 100; and the
  median full-read stage-1 threshold over 20 bias draws (seed 7) for both.

Each cell compares, on the same codes and leaked words, the single-stage accusation (the
whole share at stage 1) with the staged one (stage 1 with 90 % of the share, then up to three
side-informed stages). Reported per strategy: members caught, trials with at least one and
with every member caught, innocents named per stage (must be 0), the largest innocent score
over its stage's threshold, and (per cell) how often an innocent's score at a stage >= 2
reached that stage's threshold recomputed for the loose targets 1e-2 and 1e-3.

Usage (from the repository root, at most 3 worker processes on a shared machine):

    python research/bertahap/ukur.py batas > research/bertahap/hasil/batas.jsonl
    python research/bertahap/ukur.py simulasi --workers 3 > research/bertahap/hasil/simulasi.jsonl
    python research/bertahap/ukur.py ringkas research/bertahap/hasil/simulasi.jsonl
"""

from __future__ import annotations

import argparse
import json
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

import numpy as np  # noqa: E402

from tapak.tardos.accuse import threshold  # noqa: E402
from tapak.tardos.code import random_code  # noqa: E402
from tapak.tardos.detection import miss_bound  # noqa: E402
from tapak.tardos.params import TardosParams  # noqa: E402
from tapak.tardos.simulate import run_staged_simulation  # noqa: E402
from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending  # noqa: E402

EPS = 1e-6
C = 3
NS = (20, 100)
COALITIONS = (3, 4, 5, 6, 7, 8)
SMALL = (1, 2)
TRIALS = 1000
NOISE = (0.05, 0.35)
POLICY = DEFAULT_STAGE_POLICY
MAX_WORKERS = 3


def cells() -> list[dict]:
    """Every simulation cell of the fixed grid, with its seed."""
    out = [{"bagian": "koalisi", "N": n, "koalisi": k, "ber": 0.0, "hapus": 0.0, "seed": 50000 + 1000 * k + n}
           for n in NS for k in COALITIONS]
    out += [{"bagian": "rancangan", "N": n, "koalisi": k, "ber": 0.0, "hapus": 0.0, "seed": 60000 + 1000 * k + n}
            for n in NS for k in SMALL]
    out.append({"bagian": "rancangan", "N": 100, "koalisi": 3, "ber": NOISE[0], "hapus": NOISE[1],
                "seed": 60000 + 1000 * 3 + 100 + 1})
    return out


def run_cell(cell: dict) -> dict:
    """One cell: staged against single-stage accusation, all strategies."""
    t0 = time.perf_counter()
    params = TardosParams(c=C, eps=EPS, n_max=cell["N"])
    rep = run_staged_simulation(params, cell["N"], cell["koalisi"], trials=TRIALS, seed=cell["seed"],
                                ber=cell["ber"], erasure=cell["hapus"], policy=POLICY)
    return {**cell, "m": params.length, "detik": round(time.perf_counter() - t0, 1), **rep.to_dict()}


def bounds() -> list[dict]:
    """Proven stage-1 miss bounds and stage-1 thresholds, single-stage against staged.

    For design c = 2 to 5 (coalitions of at most c), so the detection numbers quoted in the
    docs for logged traces can be restated at the staged policy's stage-1 target.
    """
    out = []
    for n in NS:
        for design in (2, 3, 4, 5):
            params = TardosParams(c=design, eps=EPS, n_max=n)
            rng = np.random.default_rng(7)
            ps = [random_code(params, 1, rng)[0] for _ in range(20)]
            for k in (None, 1, 10, 100):
                single = TraceSpending.unlogged(EPS) if k is None else TraceSpending.logged(EPS, k)
                staged = TraceSpending(single.eps, single.eps_share, single.trace_no, POLICY)
                e_single, e_staged = single.stage_eps1(1, n), staged.stage_eps1(1, n)
                out.append({
                    "bagian": "batas", "N": n, "c": design, "m": params.length, "pelacakan": k,
                    "log10_batas_satu_tahap": round(max(miss_bound(params, c, eps1=e_single).log10_bound
                                                        for c in range(1, design + 1)), 3),
                    "log10_batas_tahap_1": round(max(miss_bound(params, c, eps1=e_staged).log10_bound
                                                     for c in range(1, design + 1)), 3),
                    "z_satu_tahap": round(float(np.median([threshold(p, e_single) for p in ps])), 2),
                    "z_tahap_1": round(float(np.median([threshold(p, e_staged) for p in ps])), 2),
                })
    return out


def summarize(path: Path) -> None:
    """Print the tables used in the docs from a ``simulasi.jsonl``."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        k = r["koalisi"]
        res = r["results"]
        trials = r["trials"]
        noise = f", BER {r['ber']}, hapus {r['hapus']}" if r["ber"] or r["hapus"] else ""
        print(f"\n[{r['bagian']}] N={r['N']} koalisi={k}{noise} (m={r['m']}, {r['detik']} s)")
        print(f"{'strategi':<11} {'anggota 1 thp':>13} {'bertahap':>9} {'>=1: 1thp/bthp':>15} "
              f"{'semua: 1thp/bthp':>17} {'salah 1thp/bthp':>16} {'tahap baru':>14} {'maks inosen/Z per tahap':>30}")
        for s in res:
            ratios = "/".join("-" if v is None else f"{v:.2f}" for v in s["stage_max_innocent_over_threshold"])
            print(f"{s['strategy']:<11} {s['single_member_fraction']:>13.3f} {s['staged_member_fraction']:>9.3f} "
                  f"{s['single_detected_trials'] / trials:>7.3f}/{s['staged_detected_trials'] / trials:<7.3f} "
                  f"{s['single_all_caught_trials'] / trials:>8.3f}/{s['staged_all_caught_trials'] / trials:<8.3f} "
                  f"{s['single_false_accusation_trials']:>8}/{s['staged_false_accusation_trials']:<7} "
                  f"{str(s['stage_members'][1:]):>14} {ratios:>30}")
        for b in r["bound_check"].values():
            emp = "-" if b["empirical"] is None else f"{b['empirical']:.2e}"
            print(f"  tahap >= 2, target {b['target']:g}: {int(b['exceed'])} dari {int(b['evaluations'])} skor "
                  f"inosen ({emp})")
        single_fa = sum(s["single_false_accusation_trials"] for s in res)
        staged_fa = sum(s["staged_false_accusation_trials"] for s in res)
        print(f"  tuduhan salah: satu tahap {single_fa}, bertahap {staged_fa}; "
              f"rata-rata anggota tertangkap {np.mean([s['single_member_fraction'] for s in res]):.3f} -> "
              f"{np.mean([s['staged_member_fraction'] for s in res]):.3f}; "
              f"terendah {min(s['single_member_fraction'] for s in res):.3f} -> "
              f"{min(s['staged_member_fraction'] for s in res):.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["batas", "simulasi", "ringkas"])
    ap.add_argument("berkas", nargs="?", default=None, help="simulasi.jsonl untuk ringkas")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    if args.bagian == "ringkas":
        summarize(Path(args.berkas or ROOT / "research/bertahap/hasil/simulasi.jsonl"))
        return
    if args.bagian == "batas":
        for row in bounds():
            print(json.dumps(row), flush=True)
        return
    workers = max(1, min(args.workers, MAX_WORKERS))
    todo = cells()
    if workers == 1:
        for cell in todo:
            print(json.dumps(run_cell(cell)), flush=True)
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(run_cell, todo):
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
