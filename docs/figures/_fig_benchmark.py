"""Benchmark figure: outcome per image of the synthetic photo set, and its false-accusation bound.

Reads ``docs/results/bench_photos.json`` (written by ``make bench``). Left: one row per
group, one cell per image, colored by outcome. Right: the per-image upper bound on the
false-accusation probability (log scale) for the correct answers, against the policy
``eps`` of ``TardosParams``.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

import style
from tapak.tardos.params import TardosParams

RESULTS = style.ROOT / "docs" / "results" / "bench_photos.json"
OUTCOMES = ("benar", "tidak cukup bukti", "salah")
# Three type sizes: title (same as the skor figure above it), primary labels, secondary text.
TITLE, PRIMARY, SECONDARY = 13, 12, 11


def _pow10(e: int) -> str:
    # Mathtext keeps the exponent at 70% of the label size; Unicode superscripts are far smaller.
    return f"$10^{{{e}}}$"


def _group(row: dict) -> tuple:
    if row["kind"] == "photo":
        return (0, row["angle"]), f"Foto {row['angle']:g}\u00b0"
    return (1, 0), "Tangkapan layar"


def _outcome(row: dict) -> str:
    # benchmark.py writes "SALAH" or "benar + lain" when an innocent copy is accused.
    return row["outcome"] if row["outcome"] in OUTCOMES[:2] else "salah"


def load() -> tuple[list[str], list[list[dict]]]:
    """Rows of bench_photos.json grouped by kind and angle, photos first."""
    groups: dict[tuple, tuple[str, list]] = {}
    for r in json.loads(RESULTS.read_text(encoding="utf-8"))["rows"]:
        key, label = _group(r)
        groups.setdefault(key, (label, []))[1].append(r)
    ordered = [groups[k] for k in sorted(groups)]
    return [g[0] for g in ordered], [g[1] for g in ordered]


def _draw(t: style.Theme, labels: list[str], groups: list[list[dict]], eps: float) -> plt.Figure:
    rows = [r for g in groups for r in g]
    total = Counter(_outcome(r) for r in rows)
    n_rows, n_cells = len(groups), max(len(g) for g in groups)
    color = {"benar": t.accent, "tidak cukup bukti": t.warn, "salah": t.danger}
    fig = plt.figure(figsize=(8.8, 3.0))
    renderer = fig.canvas.get_renderer()
    top, bottom, x_right = 0.67, 0.15, 0.58
    left = fig.add_axes((0.17, bottom, 0.33, top - bottom))
    right = fig.add_axes((x_right, bottom, 0.985 - x_right, top - bottom), sharey=left)
    left.set_ylim(n_rows - 0.5, -0.5)

    fig.text(0.0, 0.93, f"Uji sintetis: {total['benar']} dari {len(rows)} benar, "
             f"{total['tidak cukup bukti']} tidak cukup bukti, "
             f"{total['salah']} salah", color=t.text, fontsize=TITLE, fontweight="semibold", va="baseline")
    pages = sorted({int(re.search(r"_p(\d+)", r["file"]).group(1)) for r in rows})
    fig.text(0.0, 0.775, f"Putusan per gambar ({len({r['expected'] for r in rows})} salinan, halaman "
             f"{', '.join(map(str, pages))})", color=t.muted, fontsize=SECONDARY, va="baseline")
    fig.text(x_right, 0.775, "Batas atas peluang tuduhan salah", color=t.muted, fontsize=SECONDARY,
             va="baseline")

    # Left: one rounded cell per image, sorted benar, tidak cukup bukti, salah.
    span = n_cells + 1.2
    left.set_xlim(0, span)
    left.axis("off")
    w, h, x_pad = 0.84, 0.54, 0.08
    box = left.get_window_extent()
    aspect = (n_rows / box.height) / (span / box.width)
    names = []
    for y, (label, g) in enumerate(zip(labels, groups)):
        names.append(left.text(-0.3, y, label, color=t.text, fontsize=PRIMARY, va="center", ha="right"))
        outs = sorted((_outcome(r) for r in g), key=OUTCOMES.index)
        for x, o in enumerate(outs):
            left.add_patch(FancyBboxPatch((x + x_pad, y - h / 2), w, h, mutation_aspect=aspect, linewidth=0,
                                          boxstyle="round,pad=0,rounding_size=0.12", facecolor=color[o]))
        ok = sum(o == "benar" for o in outs)
        left.text(n_cells + 0.35, y, f"{ok}/{len(g)}", color=t.text, fontsize=PRIMARY, va="center",
                  family=style.MONO)
    # Slide the panel left so the widest row label starts on the title's left edge.
    x_ink = min(n.get_window_extent(renderer).x0 for n in names) / fig.bbox.width
    pos = left.get_position()
    left.set_position((pos.x0 - x_ink, pos.y0, pos.width, pos.height))

    # Right: per-image bound for the correct answers, with the policy eps.
    rng = np.random.default_rng(2026)
    for y, g in enumerate(groups):
        fa = np.array([r["log10_fa"] for r in g if _outcome(r) == "benar"])
        right.scatter(fa, y + rng.uniform(-0.16, 0.16, fa.size), s=38, color=t.accent, alpha=0.7,
                      linewidths=0, zorder=3)
    log_eps = float(np.log10(eps))
    right.axvline(log_eps, color=t.danger, linewidth=1.2, zorder=2)
    right.text(log_eps, -0.6, f"\u03b5 = {_pow10(round(log_eps))}", color=t.danger, fontsize=PRIMARY,
               ha="right", va="bottom")
    right.set_xlim(-100, 2)
    ticks = [-90, -60, -30, 0]
    right.set_xticks(ticks, [_pow10(v) for v in ticks])
    style.style_axes(right, t, grid_axis="x")
    right.tick_params(axis="y", left=False, labelleft=False)
    right.tick_params(axis="x", labelsize=PRIMARY, pad=6)

    # Legend on the tick-label line, left edge flush with the first cell; "salah" shows its zero.
    tick = right.get_xticklabels()[0].get_window_extent(renderer)
    y_mid = (tick.y0 + tick.y1) / 2 / fig.bbox.height
    x0 = fig.transFigure.inverted().transform(left.transData.transform((x_pad, 0)))[0]
    sw, sh = 0.013, 0.045
    for o in OUTCOMES:
        fig.patches.append(FancyBboxPatch((x0, y_mid - sh / 2), sw, sh, boxstyle="round,pad=0,rounding_size=0.003",
                                          transform=fig.transFigure, facecolor=color[o], linewidth=0))
        text = fig.text(x0 + sw + 0.008, y_mid, f"{o} ({total[o]})" if o == "salah" else o,
                        color=t.muted, fontsize=SECONDARY, va="center")
        x0 = text.get_window_extent(renderer).x1 / fig.bbox.width + 0.03
    return fig


def benchmark() -> None:
    """Render docs/img/benchmark-{light,dark}.svg from the benchmark results."""
    labels, groups = load()
    eps = TardosParams().eps
    # Mathtext is laid out at save time, so the context covers drawing and saving.
    math = {"mathtext.fontset": "custom", "mathtext.default": "regular",
            "mathtext.rm": style.SANS, "mathtext.cal": style.SANS}
    for t in style.THEMES:
        with plt.rc_context(math):
            style.save(_draw(t, labels, groups, eps), "benchmark", t)


if __name__ == "__main__":
    style.setup_fonts()
    benchmark()
