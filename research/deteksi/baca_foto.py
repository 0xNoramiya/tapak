"""Proven miss bound of single photo reads, from each read's own weights.

``channel_miss_bound`` with the weight law of ``llr_foto.py`` assumes that every one of the m
positions is read and draws its weight independently of the others. A real photo covers one
page and its weights move together (a photo is good or bad as a whole), so the pooled law does
not bound it. This script decodes every image of the benchmark photo set exactly as a trace
does (``collect_from_image``, ``fuse``) and computes ``read_miss_bound`` from the read's own
weights for coalitions of 1 to c (the issuance's c). No accusation is run and no codeword is
used.

Flip rates: the measured error rate of the weight's bin in ``hasil/llr_foto.json`` (pooled over
the 40 images; per image the error count is 0.5 to 4.3 times its calibrated prediction, so the
numbers illustrate the size of a single-read bound and are not proven for any one photo).
Threshold: whole eps (eps1 = eps / N), as in the default-length tables.

One JSON line per image: file, kind, positions with weight > 0, sum of w^2, and log10 of the
bound for c' = 1..c and for coalitions of at most c. The first line is the pooled law at the
full length for comparison.

Usage (from the repository root, after ``llr_foto.py``, at most 2 worker processes):

    python research/deteksi/baca_foto.py --data out/foto/data --keys out/foto/keys \
        --photos out/foto/layar --workers 2 > research/deteksi/hasil/baca_foto.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

LAW = Path(__file__).resolve().parent / "hasil" / "llr_foto.json"
MAX_WORKERS = 2
_CTX = None


def _context():
    global _CTX
    if _CTX is None:
        from tapak.config import load_settings
        from tapak.decoder.trace import load_context
        from tapak.service import ensure_keys, list_workspaces, load_workspace

        settings = load_settings()
        keys = ensure_keys(settings, create_signing_key=False, create_secret=False)
        doc = list_workspaces(settings)[0]
        manifest, master, folder = load_workspace(settings, doc.doc_hash)
        _CTX = load_context(master, manifest, keys.code_secret, folder=folder)
    return _CTX


def bin_rates() -> np.ndarray:
    """Measured error rate per weight bin (index as ``llr_foto.bin_index``), 0 for bin 0."""
    rate = np.zeros(21)
    for b in json.loads(LAW.read_text(encoding="utf-8"))["bins"]:
        if b["n"] and b["bin"] > 0:
            rate[b["bin"]] = min(0.5, b["error_rate"])
    return rate


def _photo(args: tuple[str, str, str]) -> dict:
    path, name, kind = args
    from tapak.decoder.fuse import fuse
    from tapak.decoder.image import collect_from_image
    from tapak.tardos.detection import read_miss_bound

    ctx = _context()
    est = fuse(collect_from_image(Path(path).read_bytes(), ctx), ctx.params.length)
    w = est.weights
    k = np.clip(np.ceil(w * 20.0).astype(int), 0, 20)
    e = np.where(w > 0, bin_rates()[k], 0.0)
    logs = [read_miss_bound(ctx.params, w, e, c).log10_bound for c in range(1, ctx.params.c + 1)]
    return {"file": name, "kind": kind, "weight_positive": int((w > 0).sum()),
            "sum_w2": round(float(np.sum(w**2)), 1), "log10_bound_per_c": [round(v, 3) for v in logs],
            "log10_bound": round(max(logs), 3)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--photos", required=True)
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = ap.parse_args(argv)
    os.environ["TAPAK_DATA"] = args.data
    os.environ["TAPAK_KEY_DIR"] = args.keys

    from tapak.tardos.detection import ChannelLaw, channel_miss_bound

    ctx = _context()
    law = ChannelLaw.from_dict(json.loads(LAW.read_text(encoding="utf-8"))["law"])
    pooled = [channel_miss_bound(ctx.params, law, c).log10_bound for c in range(1, ctx.params.c + 1)]
    print(json.dumps({"file": "sebaran gabungan, semua posisi", "kind": "law", "m": ctx.params.length,
                      "c": ctx.params.c, "N": ctx.params.n_max, "log10_bound_per_c": [round(v, 3) for v in pooled],
                      "log10_bound": round(max(pooled), 3)}), flush=True)
    truth = json.loads((Path(args.photos) / "truth.json").read_text(encoding="utf-8"))
    items = truth["items"] if isinstance(truth, dict) else truth
    cells = [(str(Path(args.photos) / e["file"]), e["file"], e["kind"]) for e in items]
    with ProcessPoolExecutor(max_workers=max(1, min(args.workers, MAX_WORKERS))) as pool:
        for row in pool.map(_photo, cells):
            print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
