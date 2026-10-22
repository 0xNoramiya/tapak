"""Proven miss bound for noisy and soft-weighted reads next to simulated miss rates.

Part ``derau`` checks ``tapak.tardos.detection.channel_miss_bound``; part ``sasaran`` measures
erasures aimed at the positions where the colluders' copies agree, which the bound does not
cover. Both grids were fixed before any simulation was run and are not tuned afterwards.

Part ``derau`` (one JSON line per cell):

* eps = 1e-6, N = 20 (eps1 = eps / N), design c in {2, 3, 4, 5}, coalition size = c, every
  strategy in ``tapak.tardos.attacks.STRATEGIES`` (including ``worst-case``), 1000 trials per
  cell. Only the c colluders' codewords are drawn (innocent recipients do not change a miss).
* reads, each a per-position law of (weight, flip rate), positions independent:
  - ``keras``: weight 1, flip rate e in {0, 0.02, 0.05, 0.10, 0.20} (binary symmetric channel);
  - ``lunak``: weights drawn from the decoder's weight law on the synthetic photo set
    (``hasil/llr_foto.json``, ``law``: 18 bin-mean weights plus weight 0 for erased positions),
    flips with rate e in {0, 0.02, 0.05, 0.10, 0.20}, independent of the weight;
  - ``lunak-kalibrasi``: the same weights, flip rate (1 - w) / 2 (a calibrated LLR);
  - ``lunak-foto``: the same weights, the flip rate measured on the photos for that bin.
* code lengths: the shortest codes whose proven bound through that read, for coalitions of at
  most c, is 0.5 and 0.1 (``channel_min_length``). They come from the bound alone.
* the channel acts after the strategy: y is the coalition's word, each position gets a weight
  from the law and its bit flips with the flip rate; positions the strategy erases keep weight
  0. Z(p, w) is computed from the read's weights, as the decoder does. The channel draw of a
  trial is shared by the 8 strategies.
* seed: 50000 + 1000 c + 10 * read index + level index (reads in the order above, 0 to 11).

A miss is a trial in which no colluder reaches Z(p, w). A cell agrees with the proof when the
measured miss rate of every strategy is at most the proven bound for c' = c.

Part ``sasaran`` (one JSON line per cell):

* eps = 1e-6, N = 20, c in {2, 3, 4, 5}, coalition size = c, default code length
  (K = 2 pi^2), hard read without flips, the 8 strategies, 1000 trials per cell;
* on top of each strategy the coalition erases every position where all c copies agree with
  probability r in {0, 0.5, 0.8, 0.9, 0.95, 0.98, 1}, independently per position;
* ``batas_naif``: the proven bound for a code-independent erasure that leaves the same mean
  number of positions (``proven_miss_probability`` at that length). It does not apply here;
  it is shown to see how far the real miss rate is from it.
* seed: 60000 + 1000 c + index of r.

Part ``batas`` (bounds only, no simulation): for N in {20, 100} and c in {2, 3, 4, 5}, the
proven bound for coalitions of at most c at the default length (K = 2 pi^2, whole eps) for the
reads ``keras`` (every e above), ``lunak-kalibrasi`` and ``lunak-foto``; and for N = 20 the
shortest code (and its K) with a proven bound of at most 1e-6 for ``keras`` with e in
{0.02, 0.05, 0.10, 0.20} and for ``lunak-foto``.

Usage (from the repository root, at most 2 worker processes on a shared machine):

    python research/deteksi/kanal.py derau --workers 2 > research/deteksi/hasil/kanal.jsonl
    python research/deteksi/kanal.py sasaran --workers 2 > research/deteksi/hasil/sasaran.jsonl
    python research/deteksi/kanal.py batas --workers 2 > research/deteksi/hasil/batas_kanal.jsonl
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

# One BLAS thread per process (set before numpy is imported).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from tapak.tardos import attacks  # noqa: E402
from tapak.tardos.accuse import scores, threshold  # noqa: E402
from tapak.tardos.code import random_code  # noqa: E402
from tapak.tardos.detection import (  # noqa: E402
    ChannelLaw,
    channel_miss_bound,
    channel_min_length,
    proven_channel_miss_probability,
    proven_miss_probability,
)
from tapak.tardos.params import TardosParams  # noqa: E402

EPS = 1e-6
N = 20
CS = (2, 3, 4, 5)
ERRORS = (0.0, 0.02, 0.05, 0.10, 0.20)
LEVELS = (0.5, 0.1)
TRIALS = 1000
ERASE_FRACTIONS = (0.0, 0.5, 0.8, 0.9, 0.95, 0.98, 1.0)
MAX_WORKERS = 2
PHOTO_LAW = Path(__file__).resolve().parent / "hasil" / "llr_foto.json"


def reads() -> list[tuple[str, float | None, ChannelLaw]]:
    """The 12 reads of part ``derau``, in seed order: (name, flip rate or None, law)."""
    foto = ChannelLaw.from_dict(json.loads(PHOTO_LAW.read_text(encoding="utf-8"))["law"])
    out: list[tuple[str, float | None, ChannelLaw]] = []
    out += [("keras", e, ChannelLaw.binary_symmetric(e)) for e in ERRORS]
    out += [("lunak", e, foto.with_error_rate(e)) for e in ERRORS]
    out.append(("lunak-kalibrasi", None, ChannelLaw.calibrated(foto.weights, foto.probabilities)))
    out.append(("lunak-foto", None, foto))
    return out


def _miss(x: np.ndarray, y: np.ndarray, p: np.ndarray, w: np.ndarray, z: float) -> bool:
    return not (math.isfinite(z) and np.any(scores(x, y, p, w) >= z))


def _noise_cell(args: tuple[int, int, int]) -> dict:
    c, ri, li = args
    name, e, law = reads()[ri]
    level = LEVELS[li]
    params = TardosParams(c=c, eps=EPS, n_max=N)
    t0 = time.perf_counter()
    req = channel_min_length(c, EPS, N, level, law)
    m = req.length
    bound_c = channel_miss_bound(params, law, c, m)
    seed = 50_000 + 1000 * c + 10 * ri + li
    rng = np.random.default_rng(seed)
    wk, ek, qk = (np.asarray(v) for v in (law.weights, law.error_rates, law.probabilities))
    misses = {k: 0 for k in attacks.STRATEGIES}
    for _ in range(TRIALS):
        p, xb = random_code(params, c, rng, m)
        x = xb.astype(np.float64)
        k = rng.choice(wk.size, size=m, p=qk)
        w_chan = wk[k]
        flip = (rng.random(m) < ek[k]).astype(np.uint8)
        z_full = threshold(p, params.eps1, w_chan)
        for sname, strat in attacks.STRATEGIES.items():
            y, w_s = strat(xb, rng)
            w = w_chan * w_s
            z = z_full if np.all(w_s == 1.0) else threshold(p, params.eps1, w)
            misses[sname] += int(_miss(x, y ^ flip, p, w, z))
    rates = {s: v / TRIALS for s, v in misses.items()}
    return {
        "bagian": "derau", "N": N, "c": c, "baca": name, "laju_salah": e, "tingkat_batas": level, "m": m,
        "K": round(req.k_constant, 3), "fraksi_efektif": round(law.effective_fraction, 4), "seed": seed,
        "percobaan": TRIALS, "batas_koalisi_c": bound_c.bound, "batas_koalisi_maks_c": req.bound,
        "lolos": misses, "laju_lolos": rates, "laju_lolos_maks": max(rates.values()),
        "sesuai": max(rates.values()) <= bound_c.bound, "detik": round(time.perf_counter() - t0, 1),
    }


def _erasure_cell(args: tuple[int, int]) -> dict:
    c, ri = args
    r = ERASE_FRACTIONS[ri]
    params = TardosParams(c=c, eps=EPS, n_max=N)
    m = params.length
    seed = 60_000 + 1000 * c + ri
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    misses = {k: 0 for k in attacks.STRATEGIES}
    observed = 0
    for _ in range(TRIALS):
        p, xb = random_code(params, c, rng, m)
        x = xb.astype(np.float64)
        ones = xb.sum(axis=0)
        agree = (ones == 0) | (ones == c)
        keep = np.where(agree & (rng.random(m) < r), 0.0, 1.0)
        observed += int(keep.sum())
        z_keep = threshold(p, params.eps1, keep)
        for sname, strat in attacks.STRATEGIES.items():
            y, w_s = strat(xb, rng)
            w = keep * w_s
            z = z_keep if np.all(w_s == 1.0) else threshold(p, params.eps1, w)
            misses[sname] += int(_miss(x, y, p, w, z))
    mean_obs = observed / TRIALS
    rates = {s: v / TRIALS for s, v in misses.items()}
    naive = proven_miss_probability(params, length=max(1, round(mean_obs)))
    return {
        "bagian": "sasaran", "N": N, "c": c, "m": m, "fraksi_hapus_sama": r, "seed": seed, "percobaan": TRIALS,
        "posisi_terbaca_rata2": round(mean_obs, 1), "batas_naif": naive,
        "batas_pembacaan_penuh": proven_channel_miss_probability(params, ChannelLaw.binary_symmetric(0.0)),
        "lolos": misses, "laju_lolos": rates, "laju_lolos_maks": max(rates.values()),
        "detik": round(time.perf_counter() - t0, 1),
    }


def _bound_cell(args: tuple[str, int, int, int]) -> dict:
    kind, n, c, ri = args
    name, e, law = reads()[ri]
    params = TardosParams(c=c, eps=EPS, n_max=n)
    t0 = time.perf_counter()
    row: dict = {"bagian": "batas", "N": n, "c": c, "baca": name, "laju_salah": e}
    if kind == "bawaan":
        per = [channel_miss_bound(params, law, k) for k in range(1, c + 1)]
        row.update(jenis="bawaan", m=params.length, K=round(params.k_constant, 3),
                   log10_batas=round(max(b.log10_bound for b in per), 3),
                   galat_kuadratur=max(b.quadrature_error for b in per))
    else:
        req = channel_min_length(c, EPS, n, 1e-6, law)
        row.update(jenis="panjang_minimum", delta=1e-6, m=req.length, K=round(req.k_constant, 3),
                   batas=req.bound, batas_m_kurang_1=req.bound_below)
    row["detik"] = round(time.perf_counter() - t0, 1)
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["derau", "sasaran", "batas"])
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = ap.parse_args(argv)
    workers = max(1, min(args.workers, MAX_WORKERS))
    if args.bagian == "derau":
        cells = [(c, ri, li) for c in CS for ri in range(12) for li in range(len(LEVELS))]
        fn = _noise_cell
    elif args.bagian == "sasaran":
        cells = [(c, ri) for c in CS for ri in range(len(ERASE_FRACTIONS))]
        fn = _erasure_cell
    else:
        hard_and_photo = [*range(5), 10, 11]
        cells = [("bawaan", n, c, ri) for n in (20, 100) for c in CS for ri in hard_and_photo]
        cells += [("panjang", 20, c, ri) for c in CS for ri in (1, 2, 3, 4, 11)]
        fn = _bound_cell
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(fn, cells):
            print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
