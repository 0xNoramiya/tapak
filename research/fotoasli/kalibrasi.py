"""Printer calibration sheet for the background pattern (docs/keamanan.md batasan 3 and 10).

Whether a real printer prints the pattern of the print profile is the one thing the replay
(``putar.py``) cannot say: its printer is simulated, and the model's highlight cutoff (levels
above about 250 print as plain paper) was never measured. One sheet answers it for a printer:
18 patches of the same kind of pattern (2 mm cells, a keyed sign per cell, level = base +/-
amplitude, linearly interpolated as ``marker.background.pattern_image`` draws it), at bases
from 253 (the default profile) down to 238 and amplitudes 2, 3 and 5. Printed once and
photographed, each patch gives how much of its pattern arrived: the correlation of the
photographed cells with the signs, and the wrong-bit share a code position of eight cells
would have. The sheet holds no document text, only labels.

    PYTHONPATH=. python research/fotoasli/kalibrasi.py buat LEMBAR.pdf
    PYTHONPATH=. python research/fotoasli/kalibrasi.py ukur LEMBAR.pdf FOTO [FOTO ...]

``ukur`` registers each photo against the sheet (``rectify.register``, so a sheet that does
not lie flat is followed) and prints one row per patch; ``--json`` also writes the rows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MM = 72.0 / 25.4
CELL_MM = 2.0
PX_PER_CELL = 4
PAGE_MM = (210.0, 297.0)
SEED = 61301
CELLS_PER_BIT = 8  # as BackgroundSettings.cells_per_bit
# (base, amplitude) per patch, row by row: amplitudes 2, 3, 5 across, lighter to darker down
PATCHES = [[(253, 2), (251, 3), (250, 5)], [(250, 2), (249, 3), (248, 5)], [(248, 2), (247, 3), (246, 5)],
           [(246, 2), (245, 3), (244, 5)], [(244, 2), (243, 3), (242, 5)], [(242, 2), (240, 3), (238, 5)]]
ORIGIN_MM = (16.0, 40.0)   # top-left of the first patch (a multiple of the cell)
PATCH_MM = (56.0, 32.0)
PITCH_MM = (62.0, 40.0)
TEXT = ("Lembar kalibrasi printer untuk pola latar TAPAK. Cetak pada skala 100 % (Actual size), kualitas normal, "
        "lalu potret lembar ini rata di meja dari atas, tajam, tanpa lampu kilat.",
        "Setiap petak memuat pola sel 2 mm dengan tingkat abu-abu dasar dan amplitudo yang tertulis di bawahnya. "
        "Tidak ada isi dokumen pada lembar ini; seluruhnya fiktif dan hanya untuk mengukur printer.")


def layout() -> list[dict]:
    """Every patch: its label, base, amplitude, cell box (x0, y0, nx, ny) and the signs of its cells."""
    rng = np.random.default_rng(SEED)
    nx, ny = int(PATCH_MM[0] / CELL_MM), int(PATCH_MM[1] / CELL_MM)
    out = []
    for r, row in enumerate(PATCHES):
        for c, (base, amp) in enumerate(row):
            x0 = int((ORIGIN_MM[0] + c * PITCH_MM[0]) / CELL_MM)
            y0 = int((ORIGIN_MM[1] + r * PITCH_MM[1]) / CELL_MM)
            signs = rng.choice(np.array([-1, 1], dtype=np.int8), size=(ny, nx))
            out.append({"label": f"{base} +/- {amp}", "base": base, "amplitude": amp, "box": (x0, y0, nx, ny), "signs": signs})
    return out


def sheet_image() -> np.ndarray:
    """The page background as the marker would draw it: 4 px per cell, levels interpolated."""
    import cv2

    cx, cy = int(PAGE_MM[0] / CELL_MM), int(math.ceil(PAGE_MM[1] / CELL_MM))
    level = np.full((cy, cx), 255.0, dtype=np.float32)
    for p in layout():
        x0, y0, nx, ny = p["box"]
        level[y0:y0 + ny, x0:x0 + nx] = p["base"] + p["amplitude"] * p["signs"].astype(np.float32)
    up = cv2.resize(level, (cx * PX_PER_CELL, cy * PX_PER_CELL), interpolation=cv2.INTER_LINEAR)
    return np.clip(np.rint(up), 0, 255).astype(np.uint8)


def make(path: Path) -> None:
    import cv2
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_MM[0] * MM, height=PAGE_MM[1] * MM)
    img = sheet_image()
    ok, png = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 4])
    assert ok
    rect = pymupdf.Rect(0, 0, img.shape[1] / PX_PER_CELL * CELL_MM * MM, img.shape[0] / PX_PER_CELL * CELL_MM * MM)
    page.insert_image(rect, stream=png.tobytes(), overlay=False)
    page.insert_text((16 * MM, 14 * MM), "TAPAK  -  LEMBAR KALIBRASI PRINTER  K", fontsize=13, fontname="hebo")
    page.insert_textbox(pymupdf.Rect(16 * MM, 17 * MM, 194 * MM, 38 * MM), "\n".join(TEXT), fontsize=8.5, fontname="helv")
    for p in layout():
        x0, y0, nx, ny = p["box"]
        left, top = x0 * CELL_MM * MM, y0 * CELL_MM * MM
        right, bottom = (x0 + nx) * CELL_MM * MM, (y0 + ny) * CELL_MM * MM
        for x, y, dx, dy in ((left, top, -1, -1), (right, top, 1, -1), (left, bottom, -1, 1), (right, bottom, 1, 1)):
            page.draw_line((x + dx * 1.5 * MM, y + dy * 0.6 * MM), (x + dx * 4.0 * MM, y + dy * 0.6 * MM), width=0.6)
            page.draw_line((x + dx * 0.6 * MM, y + dy * 1.5 * MM), (x + dx * 0.6 * MM, y + dy * 4.0 * MM), width=0.6)
        page.insert_text((left, bottom + 4.6 * MM), f"dasar {p['base']}  amplitudo {p['amplitude']}  ({p['label']})",
                         fontsize=8, fontname="helv")
    page.insert_text((16 * MM, 286 * MM), "CONTOH SINTETIS - BUKAN DOKUMEN ASLI   |   lembar K   |   sel 2 mm, 18 petak",
                     fontsize=8, fontname="helv")
    doc.save(path, deflate=True)
    print(f"{path}: {len(layout())} petak")


def _q(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def measure(pdf: Path, photo: Path) -> dict:
    """Per patch of one photo: how dark it printed and how much of its pattern arrived."""
    import cv2

    from tapak.decoder import rectify

    data = pdf.read_bytes()
    gray = rectify.load_gray(photo.read_bytes())
    size_pt = (PAGE_MM[0] * MM, PAGE_MM[1] * MM)
    reg = rectify.register(gray, data, [size_pt])
    if reg is None:
        return {"photo": photo.name, "registered": False}
    s = reg.dpi / 25.4  # pixels per mm
    img = reg.rectified.astype(np.float32)
    paper = float(np.percentile(img[reg.valid], 95))
    rows = []
    for p in layout():
        x0, y0, nx, ny = p["box"]
        means = np.full((ny, nx), np.nan)
        for j in range(ny):
            for i in range(nx):
                # the middle of the cell (60 % of its side): the level is interpolated towards the neighbours
                xa, xb = (x0 + i + 0.2) * CELL_MM * s, (x0 + i + 0.8) * CELL_MM * s
                ya, yb = (y0 + j + 0.2) * CELL_MM * s, (y0 + j + 0.8) * CELL_MM * s
                box = img[int(round(ya)):int(round(yb)), int(round(xa)):int(round(xb))]
                if box.size and reg.valid[int(round(ya)):int(round(yb)), int(round(xa)):int(round(xb))].all():
                    means[j, i] = float(box.mean())
        inner = np.zeros((ny, nx), dtype=bool)
        inner[1:-1, 1:-1] = True
        ok = inner & np.isfinite(means)
        if ok.sum() < 50:
            rows.append({"label": p["label"], "cells": int(ok.sum())})
            continue
        filled = np.where(np.isfinite(means), means, np.nanmean(means)).astype(np.float32)
        local = cv2.GaussianBlur(filled, (0, 0), 2.0, borderType=cv2.BORDER_REFLECT)  # light and paper, over about 4 mm
        mod = (filled / np.maximum(local, 1.0) - 1.0)[ok]
        sign = p["signs"][ok].astype(np.float64)
        amp = float(np.mean(mod * sign))
        noise = float(np.std(mod - amp * sign))
        r = float(np.corrcoef(mod, sign)[0, 1])
        snr = amp / noise if noise > 0 else float("inf")
        rows.append({"label": p["label"], "base": p["base"], "amplitude": p["amplitude"], "cells": int(ok.sum()),
                     "darkness": round(1.0 - float(np.nanmean(means[ok])) / paper, 4),
                     "issued_modulation": round(p["amplitude"] / p["base"], 4), "read_modulation": round(amp, 5),
                     "correlation": round(r, 3), "snr_cell": round(snr, 3),
                     "wrong_bit_share": round(_q(max(snr, 0.0) * math.sqrt(CELLS_PER_BIT)), 4)})
    return {"photo": photo.name, "registered": True, "method": reg.method, "correlation": round(reg.correlation, 3),
            "effective_dpi": round(reg.effective_dpi, 1), "patches": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("buat")
    b.add_argument("pdf", type=Path)
    u = sub.add_parser("ukur")
    u.add_argument("pdf", type=Path)
    u.add_argument("photos", nargs="+", type=Path)
    u.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.cmd == "buat":
        make(args.pdf)
        return
    out = []
    for photo in args.photos:
        res = measure(args.pdf, photo)
        out.append(res)
        if not res["registered"]:
            print(f"{photo.name}: lembar tidak ditemukan")
            continue
        print(f"{photo.name}: {res['method']}, korelasi {res['correlation']}, {res['effective_dpi']} dpi")
        print(f"  {'petak':>10s} {'gelap':>7s} {'terbit':>7s} {'terbaca':>8s} {'korelasi':>8s} {'SNR sel':>8s} {'bit salah':>9s}")
        for r in res["patches"]:
            if "base" not in r:
                print(f"  {r['label']:>10s} hanya {r['cells']} sel terbaca")
                continue
            print(f"  {r['label']:>10s} {r['darkness']:7.3f} {r['issued_modulation']:7.4f} {r['read_modulation']:8.5f} "
                  f"{r['correlation']:8.3f} {r['snr_cell']:8.2f} {r['wrong_bit_share']:9.3f}")
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
