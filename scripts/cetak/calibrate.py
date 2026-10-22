"""Calibration of the print model (tapak.photos.print_page) for the laser and inkjet presets.

* Tone reproduction: uniform patches at nominal gray levels; printed reflectance R relative
  to paper and the effective coverage a_eff = (1 - R) / (1 - R_solid) (Murray-Davies),
  against the nominal coverage a = 1 - level / 255. a_eff - a is the dot gain.
* Text: a vertical bar of 0.30 mm (a 10 to 12 pt stem) and an isolated one-pixel line;
  printed width at half depth and edge raggedness (sd of the edge position along the bar).

Six seeds per setting (the printer parameters are drawn per page). Writes calibration.json
to $CETAK_OUT.

    PYTHONPATH=. python -m scripts.cetak.calibrate
"""

from __future__ import annotations

import json

import numpy as np

from scripts.cetak.common import OUT
from tapak.photos import INKJET, PrintParams, print_page

LEVELS = [255, 252, 251, 250, 249, 248, 246, 245, 242, 240, 238, 235, 230, 220, 200, 160, 128, 64, 0]
SEEDS = range(6)
R0 = 0.055  # print_page maps reflectance R0 to level 0


def tone_curve(params: PrintParams) -> list[dict]:
    """Printed level, effective coverage and dot gain per nominal gray level."""
    n = 240  # patch of 240 x 240 device px (10 mm at 600 dpi)
    vals: dict[int, list[float]] = {lv: [] for lv in LEVELS}
    for seed in SEEDS:
        bg = np.pad(np.concatenate([np.full((n, n), lv, np.uint8) for lv in LEVELS], axis=1), 60,
                    constant_values=255)
        sheet, _ = print_page(np.zeros(bg.shape, np.float32), bg, np.random.default_rng(seed), params)
        refl = sheet / 255.0 * (1 - R0) + R0  # reflectance relative to mean paper
        k = params.out_dpi / params.device_dpi
        for j, lv in enumerate(LEVELS):
            x0, x1 = int((60 + j * n + 40) * k), int((60 + (j + 1) * n - 40) * k)
            y0, y1 = int(100 * k), int((60 + n - 40) * k)
            vals[lv].append(float(refl[y0:y1, x0:x1].mean()))
    rs = float(np.mean(vals[0]))
    rows = []
    for lv in LEVELS:
        r = float(np.mean(vals[lv]))
        a_nom, a_eff = 1 - lv / 255, (1 - r) / (1 - rs)
        rows.append({"level": lv, "printed_level": round(255 * r, 1), "nominal_coverage_pct": round(100 * a_nom, 2),
                     "effective_coverage_pct": round(100 * a_eff, 2),
                     "dot_gain_pct_points": round(100 * (a_eff - a_nom), 2),
                     "dL_vs_paper": round(float(116 * (np.cbrt(r) - 1)), 2)})
    return rows


def strokes(params: PrintParams) -> dict:
    """Printed width and edge raggedness of a 0.30 mm stem and a one-pixel line."""
    dev = params.device_dpi
    out = {}
    for name, width_px in (("stem_0.30mm", round(0.30 / 25.4 * dev)), ("line_1px", 1)):
        widths, rag = [], []
        for seed in SEEDS:
            text = np.zeros((400, 400), np.float32)
            x0 = 200 - width_px // 2
            text[50:350, x0:x0 + width_px] = 1.0
            sheet, _ = print_page(text, np.full((400, 400), 255, np.uint8), np.random.default_rng(seed), params)
            k = params.out_dpi / dev
            prof = sheet[int(100 * k):int(300 * k)]
            half = 0.5 * (float(np.median(prof.min(axis=1))) + 255.0)
            lefts, rights = [], []
            for row in prof:
                dark = np.nonzero(row < half)[0]
                if len(dark) == 0:
                    continue
                i, j = dark[0], dark[-1]
                lefts.append(i - ((row[i - 1] - half) / (row[i - 1] - row[i]) if row[i - 1] != row[i] else 0))
                rights.append(j + ((row[j + 1] - half) / (row[j + 1] - row[j]) if row[j + 1] != row[j] else 0))
            lefts_a, rights_a = np.array(lefts), np.array(rights)
            widths.append(float(np.mean(rights_a - lefts_a)) / params.out_dpi * 25.4)
            t = np.arange(len(lefts_a))
            rag.append(float((lefts_a - np.polyval(np.polyfit(t, lefts_a, 1), t)).std()) / params.out_dpi * 25400)
        out[name] = {"nominal_mm": round(width_px / dev * 25.4, 4), "printed_width_mm": round(float(np.mean(widths)), 4),
                     "growth_um_per_edge": round(float((np.mean(widths) - width_px / dev * 25.4) / 2 * 1000), 1),
                     "edge_raggedness_um_sd": round(float(np.mean(rag)), 1)}
    return out


def main() -> None:
    """Print the calibration of both presets and write calibration.json."""
    res = {}
    for name, prm in (("laser", PrintParams()), ("inkjet", INKJET)):
        res[name] = {"tone": tone_curve(prm), "strokes": strokes(prm)}
        print(f"== {name}")
        for r in res[name]["tone"]:
            print("  ", r)
        print("  ", json.dumps(res[name]["strokes"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibration.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
