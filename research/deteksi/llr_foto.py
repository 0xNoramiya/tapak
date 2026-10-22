"""Decoder weights and bit errors on the synthetic photo set: the weight law of ``kanal.py``.

Reads every image of the benchmark photo set (``make photos``: 32 screen photos at 0 to 30
degrees and 8 screenshots of copies 13, 7, 1 and 20, research seed 2026), runs the channel
decoders and the fusion exactly as a trace does (``collect_from_image``, ``fuse``), and compares
the fused decision with the copy's real codeword. No accusation is run.

For every position the decoder observed (at least one LLR) it records the weight
w = tanh(|L| / 2) (0 below the erasure rule |L| < 0.25) and whether the decided bit is wrong.
Output, one JSON object:

* ``bins``: weight bins (w = 0, then 20 bins of width 0.05), per bin the number of positions,
  the mean weight, the number of wrong bits, the measured error rate and the rate a calibrated
  LLR predicts, (1 - w) / 2, averaged over the bin;
* ``law``: the per-position weight law used by ``kanal.py`` and ``tapak deteksi --sebaran``
  (``tapak.tardos.detection.ChannelLaw``): bin mean weights, bin frequencies and the measured
  error rate per bin;
* ``photos``: per image the positions observed, the wrong bits among those with weight > 0
  and the number a calibrated LLR predicts there (sum of (1 - w) / 2).

Usage (from the repository root, after an issuance and photo set in out/foto made like
``make photos`` with ``PHOTO_DATA=out/foto``):

    python research/deteksi/llr_foto.py --data out/foto/data --keys out/foto/keys \
        --photos out/foto/layar > research/deteksi/hasil/llr_foto.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

EDGES = np.linspace(0.0, 1.0, 21)


def bin_index(w: np.ndarray) -> np.ndarray:
    """0 for an erased position (w = 0), k = 1..20 for w in ((k-1)/20, k/20]."""
    k = np.ceil(np.asarray(w) * 20.0).astype(int)
    return np.clip(k, 0, 20)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--photos", required=True)
    args = ap.parse_args(argv)
    os.environ["TAPAK_DATA"] = args.data
    os.environ["TAPAK_KEY_DIR"] = args.keys

    from tapak.config import load_settings
    from tapak.decoder.fuse import fuse
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import load_context
    from tapak.service import ensure_keys, list_workspaces, load_workspace

    settings = load_settings()
    keys = ensure_keys(settings, create_signing_key=False, create_secret=False)
    doc = list_workspaces(settings)[0]
    manifest, master, folder = load_workspace(settings, doc.doc_hash)
    ctx = load_context(master, manifest, keys.code_secret, folder=folder)
    row_of = {r.copy_id: i for i, r in enumerate(ctx.refs)}
    truth = json.loads((Path(args.photos) / "truth.json").read_text(encoding="utf-8"))
    items = truth["items"] if isinstance(truth, dict) else truth

    count = np.zeros(21, dtype=np.int64)
    wrong = np.zeros(21, dtype=np.int64)
    wsum = np.zeros(21)
    predicted = np.zeros(21)
    photos = []
    for e in items:
        data = (Path(args.photos) / e["file"]).read_bytes()
        est = fuse(collect_from_image(data, ctx), ctx.params.length)
        seen = est.observations > 0
        w = est.weights[seen]
        err = est.y[seen] != ctx.codewords[row_of[e["copy_id"]]][seen]
        k = bin_index(w)
        np.add.at(count, k, 1)
        np.add.at(wrong, k, err.astype(np.int64))
        np.add.at(wsum, k, w)
        np.add.at(predicted, k, (1.0 - w) / 2.0)
        photos.append({"file": e["file"], "kind": e["kind"], "angle": e.get("angle"),
                       "observed": int(seen.sum()), "weight_positive": int((w > 0).sum()),
                       "wrong_weight_positive": int(err[w > 0].sum()),
                       "calibrated_wrong": round(float(np.sum((1.0 - w[w > 0]) / 2.0)), 1),
                       "sum_w2": round(float(np.sum(w**2)), 1)})
        print(f"{e['file']}: {int(seen.sum())} posisi, {int(err[w > 0].sum())} salah", file=sys.stderr, flush=True)

    bins = []
    for k in range(21):
        lo, hi = (0.0, 0.0) if k == 0 else (float(EDGES[k - 1]), float(EDGES[k]))
        n = int(count[k])
        bins.append({"bin": k, "w_lo": lo, "w_hi": hi, "n": n,
                     "w_mean": round(wsum[k] / n, 6) if n else None, "wrong": int(wrong[k]),
                     "error_rate": round(wrong[k] / n, 6) if n else None,
                     "calibrated_rate": round(predicted[k] / n, 6) if n else None})
    used = [b for b in bins if b["n"]]
    total = sum(b["n"] for b in used)
    law = {
        "weights": [0.0 if b["bin"] == 0 else b["w_mean"] for b in used],
        "error_rates": [0.0 if b["bin"] == 0 else b["error_rate"] for b in used],
        "probabilities": [b["n"] / total for b in used],
    }
    out = {"photo_set": str(args.photos), "doc_hash": doc.doc_hash, "m": ctx.params.length,
           "images": len(items), "positions": total, "bins": bins, "law": law, "photos": photos}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
