"""Lens distortion on simulated screen photos (docs/keamanan.md batasan 10).

The photo simulator (``tapak.photos``) has a blurring lens but a geometrically perfect one: a
straight line stays straight. A phone lens bends it, also after the phone's own correction (a
few tenths of a per cent to about one per cent at the corners of the frame), so on a real photo
one homography cannot fit a page that fills the frame, however flat the screen or the sheet.
The real photos of ``ukur.py`` hold that distortion together with the shape of the paper. This
script isolates it: photos of a copy on a screen (the default background profile, as in the
README benchmark) get a radial distortion x' = x (1 + k1 r^2), r = 1 at the corner of the
frame, and are traced as they are. It asks whether the registration's bend stage carries a
phone photo of a flat page, and what the distortion costs each channel.

Nothing is chosen; the protocol was fixed before the run. Copies come from the issuance of
``putar.py`` (variant "v2"). Process pool capped at 2. Usage, from the repository root:

    PYTHONPATH=. python research/fotoasli/lensa.py jalan
    PYTHONPATH=. python research/fotoasli/lensa.py ringkas
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import putar  # noqa: E402

HASIL = HERE / "hasil"
WORKERS = 2
PROTOCOL: dict = {
    "issuance": "putar.py variant v2 (geser-v2, default background), copies 3 and 11",
    "pages": [["surat_telegram", 1], ["nota_dinas", 1]], "seqs": [3, 11],
    "evidence": "photo of the copy on a screen (tapak.photos.photo_jpeg on the page rendered at 150 dpi)",
    "evidence_seed": 61221,
    "res": [1600, 4000],  # long side (px)
    "k1": [0.0, 0.003, 0.01, -0.01],  # radial distortion at the corner of the frame: none, 0.3 %, 1 % pincushion, 1 % barrel
}


def distort(image: np.ndarray, k1: float) -> np.ndarray:
    """The image through a lens with radial distortion k1 (relative displacement at the corner)."""
    import cv2

    if k1 == 0.0:
        return image
    h, w = image.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xs - cx, ys - cy
    r2 = (dx * dx + dy * dy) / (cx * cx + cy * cy)
    # the distorted image at q shows the scene point q / (1 + k1 r^2) (first order in k1)
    scale = 1.0 / (1.0 + k1 * r2)
    return cv2.remap(image, cx + dx * scale, cy + dy * scale, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def run_job(job: dict) -> dict:
    import cv2

    cv2.setNumThreads(1)
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.trace import run_trace
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, decode_jpeg, encode_jpeg, photo_jpeg

    t0 = time.time()
    try:
        ctx, manifest, folder = putar.context("v2", job["doc"])
        pdf = (folder / manifest.copies[job["seq"] - 1].file).read_bytes()
        rng = np.random.default_rng([PROTOCOL["evidence_seed"], putar.DOCS.index(job["doc"]), job["page"], job["seq"], job["res"]])
        page = render_pages(pdf, 150, [job["page"] - 1])[0]
        data, meta = photo_jpeg(page, rng, PhotoParams(sensor_long_side=max(2400, job["res"]), long_side=job["res"]))
        photo = distort(decode_jpeg(data).astype(np.float32), job["k1"])
        # through the camera's JPEG once more, as the distorted frame would be saved
        gray = decode_jpeg(encode_jpeg(np.clip(photo, 0, 255).astype(np.uint8), 92)).astype(np.float32)
        obs = collect_from_gray(gray, ctx, read_text=False)
        a = run_trace(obs, ctx)
        accused = sorted(c.copy.seq for c in a.accused)
        z = a.threshold.threshold
        scores = {c.copy.seq: c.score for c in a.candidates}
        ok = bool(np.isfinite(z) and z > 0)
        reg = next((sb.meta for sb in obs if "method" in sb.meta), {})
        return {**job, "view_angle": round(meta["view_angle_deg"], 1),
                "verdict": "tidak cukup bukti" if not accused else ("benar" if accused == [job["seq"]] else "salah"),
                "accused": accused, "score_z": round(scores.get(job["seq"], 0.0) / z, 3) if ok else None,
                "max_innocent_z": round(max(s for k, s in scores.items() if k != job["seq"]) / z, 3) if ok else None,
                "channels": putar._stats(obs, ctx, ctx.codewords[job["seq"] - 1]),
                "registered": bool(reg), "method": reg.get("method"), "correlation": reg.get("correlation"),
                "eff_dpi": reg.get("effective_dpi"), "seconds": round(time.time() - t0, 1)}
    except Exception:  # noqa: BLE001 - a failed job is a row, not a lost run
        return {**job, "error": traceback.format_exc()}


def jobs() -> list[dict]:
    return [{"doc": doc, "page": page, "seq": seq, "res": res, "k1": k1}
            for doc, page in PROTOCOL["pages"] for seq in PROTOCOL["seqs"] for res in PROTOCOL["res"] for k1 in PROTOCOL["k1"]]


def run() -> None:
    for doc in {d for d, _ in PROTOCOL["pages"]}:
        putar.ensure_issued("v2", doc)
    path = HASIL / "lensa.jsonl"
    key = lambda r: json.dumps([r[k] for k in ("doc", "page", "seq", "res", "k1")])  # noqa: E731
    done = {key(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    todo = [j for j in jobs() if key(j) not in done]
    (HASIL / "protokol_lensa.json").write_text(json.dumps(PROTOCOL, indent=1) + "\n", encoding="utf-8")
    print(f"{len(todo)} pekerjaan ({len(done)} sudah ada)", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool, path.open("a", encoding="utf-8") as out:
        for n, fut in enumerate(as_completed([pool.submit(run_job, j) for j in todo]), 1):
            row = fut.result()
            out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")
            out.flush()
            note = row["error"].splitlines()[-1] if "error" in row else f"{row['verdict']} {row['method']} {row['channels']}"
            print(f"[{n}/{len(todo)}] {row['doc']} s{row['seq']} {row['res']} k1={row['k1']}: {note}", flush=True)


def summarize() -> None:
    rows = [json.loads(line) for line in (HASIL / "lensa.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if "error" not in r]
    out: dict = {"jobs": len(rows), "cells": {}}
    for res in PROTOCOL["res"]:
        for k1 in PROTOCOL["k1"]:
            cell = [r for r in rows if r["res"] == res and r["k1"] == k1]
            if not cell:
                continue
            ch = {k: [sum(r["channels"][k]["read"] for r in cell), sum(r["channels"][k]["errors"] for r in cell)]
                  for k in ("kata", "baris", "latar")}
            scores = sorted(r["score_z"] for r in cell if r["score_z"] is not None)
            out["cells"][f"{res} px, k1 {k1}"] = {
                "n": len(cell), "registered": sum(r["registered"] for r in cell),
                "bent": sum(bool(r["method"]) and r["method"].endswith("+lengkung") for r in cell),
                "benar": sum(r["verdict"] == "benar" for r in cell), "salah": sum(r["verdict"] == "salah" for r in cell),
                "score_z": [scores[0], scores[-1]] if scores else None,
                "wrong_bit_share": {k: (round(e / n, 3) if n else None) for k, (n, e) in ch.items()},
                "bits_read_per_photo": {k: round(n / len(cell)) for k, (n, _) in ch.items()}}
    (HASIL / "ringkas_lensa.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, c in out["cells"].items():
        print(f"{name:22s} terdaftar {c['registered']}/{c['n']} (lengkung {c['bent']}) benar {c['benar']} salah {c['salah']} "
              f"skor {c['score_z']} bit salah {c['wrong_bit_share']} per foto {c['bits_read_per_photo']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cmd", choices=("jalan", "ringkas"))
    args = parser.parse_args()
    run() if args.cmd == "jalan" else summarize()


if __name__ == "__main__":
    main()
