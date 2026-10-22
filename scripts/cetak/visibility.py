"""Visibility of background patterns on paper and on screen (S-CIELAB and Mannos-Sakrison).

A pattern is judged by the colour difference a viewer would see after filtering by the
eye's spatial sensitivity, at 35 cm (TAPAK's visibility rule) and 25 cm:

* S-CIELAB (Zhang and Wandell, J. SID 5(1), 1997), luminance channel: three Gaussians with
  weights 0.921, 0.105, -0.108 and spreads 0.0283, 0.133, 4.336 degrees. For neutral grays
  the chromatic channels are zero, so Delta E is the Delta L* of the filtered luminance.
* Mannos-Sakrison CSF (IEEE Trans. Inf. Theory 20(4), 1974), set to 1 below its peak (the
  conservative choice for halftone visibility).

"texture" is the spread of the filtered marked sheet about its own mean (what one sheet
shows); "plain tint grain" is the same for an unmarked tint at the base level; "full
reference" compares with that tint sheet at identical print noise (overstates what one sheet
shows). Delta E of 1 is the nominal just-noticeable difference, 2.3 the often-quoted JND.
Central 120 mm of page 1 of copy 1. Writes visibility.json to $CETAK_OUT.

    PYTHONPATH=. python -m scripts.cetak.visibility
"""

from __future__ import annotations

import json
from dataclasses import replace

import cv2
import numpy as np

from scripts.cetak.common import OUT, SECRET, context
from tapak.marker.background import PRINT_BACKGROUND, SCREEN_BACKGROUND, BackgroundSettings, cell_levels, pattern_image
from tapak.photos import INKJET, PrintParams, print_page

REGION_MM = 120.0
R0 = 0.055  # print_page maps reflectance R0 to level 0


def px_per_degree(dpi: float, view_mm: float) -> float:
    """Pixels per degree of visual angle at a viewing distance."""
    return 2 * view_mm * np.tan(np.radians(0.5)) / 25.4 * dpi


def scielab_lum(y: np.ndarray, dpi: float, view_mm: float) -> np.ndarray:
    """S-CIELAB luminance-channel filter of a relative luminance image."""
    ppd = px_per_degree(dpi, view_mm)
    weights = np.array([0.921, 0.105, -0.108])
    weights = weights / weights.sum()
    out = np.zeros_like(y)
    for w, spread in zip(weights, (0.0283, 0.133, 4.336)):
        out += w * cv2.GaussianBlur(y, (0, 0), spread / np.sqrt(2.0) * ppd, borderType=cv2.BORDER_REFLECT)
    return out


def mannos_lowpass(y: np.ndarray, dpi: float, view_mm: float) -> np.ndarray:
    """Mannos-Sakrison CSF filter, flat below its peak."""
    h, w = y.shape
    ppd = px_per_degree(dpi, view_mm)
    f = np.sqrt((np.fft.rfftfreq(w)[None, :] * ppd) ** 2 + (np.fft.fftfreq(h)[:, None] * ppd) ** 2)
    a = 2.6 * (0.0192 + 0.114 * f) * np.exp(-((0.114 * f) ** 1.1))
    peak = np.argmax(a.ravel())
    a = np.where(f <= f.ravel()[peak], 1.0, a / a.ravel()[peak])
    mean = float(y.mean())
    return np.fft.irfft2(np.fft.rfft2(y - mean) * a, s=(h, w)) + mean


def lstar(y: np.ndarray) -> np.ndarray:
    """CIE L* of a relative luminance."""
    y = np.clip(y, 1e-6, None)
    f = np.where(y > (6 / 29) ** 3, np.cbrt(y), y / (3 * (6 / 29) ** 2) + 4 / 29)
    return 116 * f - 16


def srgb_to_y(v: np.ndarray) -> np.ndarray:
    """Relative luminance of an sRGB gray level."""
    c = v / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def stats(d: np.ndarray, margin: int) -> dict[str, float]:
    """Mean, 95th percentile and share above 2.3 of |Delta E| away from the region border."""
    d = np.abs(d[margin:-margin, margin:-margin])
    return {"mean": round(float(d.mean()), 2), "p95": round(float(np.percentile(d, 95)), 2),
            "frac_gt_2.3": round(float(np.mean(d > 2.3)), 3)}


def pattern_region(settings: BackgroundSettings, dpi: int) -> tuple[np.ndarray, np.ndarray]:
    """(pattern gray levels, uniform base) of the central REGION_MM square of page 1 at ``dpi``."""
    from tapak.marker.issue import build_document_plan, document_grids

    ctx = context("layar")
    plan = build_document_plan(ctx.master, ctx.params, SECRET, ("background",), set(), settings)
    grid = document_grids(ctx.master, SECRET, settings)[0]
    img = pattern_image(grid, cell_levels(grid, plan.channel("background"), ctx.codewords[0]))
    s = dpi / 72.0
    gw, gh = int(round(grid.nx * grid.cell_pt * s)), int(round(grid.ny * grid.cell_pt * s))
    full = cv2.resize(img.astype(np.float32), (gw, gh), interpolation=cv2.INTER_LINEAR)
    n = int(round(REGION_MM / 25.4 * dpi))
    y0, x0 = (gh - n) // 2, (gw - n) // 2
    pat = np.rint(full[y0:y0 + n, x0:x0 + n]).astype(np.uint8)
    return pat, np.full_like(pat, int(round(settings.base)))


def _filters(y: np.ndarray, dpi: float, view_mm: float) -> dict[str, np.ndarray]:
    return {"scielab": lstar(scielab_lum(y, dpi, view_mm)), "mannos": lstar(mannos_lowpass(y, dpi, view_mm))}


def printed(settings: BackgroundSettings, params: PrintParams, view_mm: float = 350.0, seed: int = 11) -> dict:
    """Gray cast and texture of the pattern printed with ``params``."""
    pat, uni = pattern_region(settings, params.device_dpi)
    zero = np.zeros(pat.shape, dtype=np.float32)
    sheets = {k: print_page(zero, img, np.random.default_rng(seed), params)[0]
              for k, img in (("pattern", pat), ("uniform", uni), ("paper", np.full_like(uni, 255)))}
    dpi = params.out_dpi
    y = {k: (v / 255.0 * (1 - R0) + R0).astype(np.float64) for k, v in sheets.items()}
    m = int(10 / 25.4 * dpi)
    out: dict = {}
    for name in ("scielab", "mannos"):
        lp, lu, lw = (_filters(y[k], dpi, view_mm)[name] for k in ("pattern", "uniform", "paper"))
        out[name] = {"full_reference": stats(lp - lu, m), "tint_vs_paper_dL": round(float((lu - lw)[m:-m, m:-m].mean()), 2),
                     "texture": stats(lp - float(lp[m:-m, m:-m].mean()), m),
                     "plain_tint_grain": stats(lu - float(lu[m:-m, m:-m].mean()), m)}
    return out


def screen(settings: BackgroundSettings, view_mm: float = 350.0, dpi: int = 300) -> dict:
    """The pattern on an sRGB display at physical size (no printer)."""
    pat, uni = pattern_region(settings, dpi)
    m = int(10 / 25.4 * dpi)
    out: dict = {"tint_vs_white_dL": round(float(lstar(srgb_to_y(np.array(float(settings.base)))) - 100.0), 2)}
    for name in ("scielab", "mannos"):
        lp = _filters(srgb_to_y(pat.astype(np.float64)), dpi, view_mm)[name]
        lu = _filters(srgb_to_y(uni.astype(np.float64)), dpi, view_mm)[name]
        out[name] = {"full_reference": stats(lp - lu, m), "texture": stats(lp - float(lp[m:-m, m:-m].mean()), m)}
    return out


def main() -> None:
    """Both profiles on screen, laser, inkjet and an 85 lpi laser; write visibility.json."""
    res: dict[str, dict] = {}
    laser = PrintParams()
    for name, st in (("layar", SCREEN_BACKGROUND), ("cetak", PRINT_BACKGROUND)):
        res[name] = {"screen_35cm": screen(st), "laser_35cm": printed(st, laser), "laser_25cm": printed(st, laser, 250.0),
                     "inkjet_35cm": printed(st, INKJET), "laser_85lpi_35cm": printed(st, replace(laser, screen_lpi=85.0))}
        print(name, json.dumps(res[name]), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "visibility.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
