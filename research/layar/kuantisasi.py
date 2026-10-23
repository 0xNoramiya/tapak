"""Where do the renderers put a glyph? Grid of glyph positions per renderer (research/layar).

A one-page PDF with ten glyphs "o" (Times, ``--pt`` points) is drawn again and again, moved by a
fraction of a pixel (0 to 1 pixel in steps of 1/20) horizontally or vertically, by every renderer
of ``ukur.py`` at ``--dpi``. The ink centroid of the page follows the glyphs; the number of
jumps of the centroid over one pixel of movement is the renderer's positioning grid (4: a quarter
pixel, 1: a whole pixel, 20: no rounding at this step). Writes ``hasil/kuantisasi.json``.

    python research/layar/kuantisasi.py --dpi 28,32,40,48,56,72,96,150,180,225
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ukur import HASIL, RENDERERS, render  # noqa: E402

STEPS = 20


def page_with(dx_pt: float, dy_pt: float, size: float) -> bytes:
    """Ten glyphs on a small page, all moved by (dx_pt, dy_pt)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    for i in range(10):
        page.insert_text((20 + i * 16 + dx_pt, 50 + dy_pt), "o", fontname="tiro", fontsize=size)
    return doc.tobytes()


def centroid_steps(renderer: str, dpi: float, axis: str, size: float) -> list[float]:
    """Ink centroid (pixels, relative to the unmoved page) for moves of k/STEPS pixel, k = 0..STEPS."""
    out = []
    for k in range(STEPS + 1):
        off = k * (72.0 / dpi) / STEPS
        img = 255.0 - render(page_with(off if axis == "x" else 0.0, off if axis == "y" else 0.0, size), 0, dpi,
                             renderer).astype(np.float64)
        yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
        out.append(float((img * (xx if axis == "x" else yy)).sum() / img.sum()))
    return [round(v - out[0], 4) for v in out]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dpi", default="28,32,40,48,56,72,96,150,180,225")
    ap.add_argument("--pt", type=float, default=11.0)
    args = ap.parse_args(argv)
    res = []
    for dpi in [float(v) for v in args.dpi.split(",")]:
        for renderer in RENDERERS:
            row = {"renderer": renderer, "dpi": dpi, "pt": args.pt}
            for axis in ("x", "y"):
                c = centroid_steps(renderer, dpi, axis, args.pt)
                jumps = int(sum(abs(b - a) > 0.02 for a, b in zip(c, c[1:])))  # over one pixel of movement
                row[axis] = {"centroid_px": c, "jumps_per_pixel": jumps}
            res.append(row)
            print(json.dumps({k: (v["jumps_per_pixel"] if isinstance(v, dict) else v) for k, v in row.items()}),
                  flush=True)
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / "kuantisasi.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
