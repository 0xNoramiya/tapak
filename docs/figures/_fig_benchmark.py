"""Benchmark figure: outcome per image of the synthetic photo sets, and its false-accusation bound.

Reads ``docs/results/bench_photos.json`` (written by ``make bench``). Left: one row per
group, one cell per trace, colored by outcome, in one section per medium, never counted
together (the media of ``tapak.benchmark``): photos of the page as on screen and screenshots,
photos of printed pages (simulated printer; single pages, and pages 1 and 2 traced together),
the screen-photo scenes processed by the simulated phone ISP, and photos of the copy on a
simulated monitor (with the phone ISP). Sections without rows are left out. Right: the
per-trace upper bound on the false-accusation probability (log scale) for the correct
answers, against the policy ``eps`` of ``TardosParams``.
"""

from __future__ import annotations

import json
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch
from matplotlib.transforms import blended_transform_factory

import style
from tapak.tardos.params import TardosParams

RESULTS = style.ROOT / "docs" / "results" / "bench_photos.json"
OUTCOMES = ("benar", "tidak cukup bukti", "salah")
SECTIONS = {"layar": "Foto layar dan tangkapan layar (halaman 1)",
            "cetak": "Foto kertas cetak, printer disimulasikan (halaman 1 dan 2)",
            "ponsel": "Foto dengan ISP ponsel, disimulasikan (halaman 1)",
            "fotolayar": "Foto monitor dengan ISP ponsel, disimulasikan (halaman 1)"}
# Three type sizes: title (same as the skor figure above it), primary labels, secondary text.
TITLE, PRIMARY, SECONDARY = 13, 12, 11
ROW_IN = 0.312  # height of one row in inches


def _pow10(e: int) -> str:
    # Mathtext keeps the exponent at 70% of the label size; Unicode superscripts are far smaller.
    return f"$10^{{{e}}}$"


def _group(row: dict) -> tuple:
    """(section, sort key, label) of a benchmark row."""
    angle = row.get("angle") or 0
    if row["kind"] == "photo":
        return "layar", (0, angle), f"Foto {angle:g}\u00b0"
    if row["kind"] == "cetak":
        if row.get("pages", 1) == 2:
            return "cetak", (1, 0), "Dua halaman"
        return "cetak", (0, angle), f"Cetak {angle:g}\u00b0"
    if row["kind"] == "ponsel":
        return "ponsel", (0, angle), f"Ponsel {angle:g}\u00b0"
    if row["kind"] == "fotolayar":
        return "fotolayar", (0, angle), f"Monitor {angle:g}\u00b0"
    if row["kind"] != "screenshot":
        raise ValueError(f"jenis baris benchmark tidak dikenal: {row['kind']}")
    return "layar", (1, 0), "Tangkapan layar"


def _outcome(row: dict) -> str:
    # benchmark.py writes "SALAH" or "benar + lain" when an innocent copy is accused.
    return row["outcome"] if row["outcome"] in OUTCOMES[:2] else "salah"


def load() -> list[tuple[str, list[tuple[str, list[dict]]]]]:
    """Rows of bench_photos.json as sections (in the order of ``SECTIONS``) of groups (kind and angle)."""
    groups: dict[tuple, tuple[str, list]] = {}
    for r in json.loads(RESULTS.read_text(encoding="utf-8"))["rows"]:
        section, key, label = _group(r)
        groups.setdefault((list(SECTIONS).index(section), key), (label, []))[1].append(r)
    out: list[tuple[str, list[tuple[str, list[dict]]]]] = []
    for (si, _), group in sorted(groups.items()):
        name = list(SECTIONS)[si]
        if not out or out[-1][0] != name:
            out.append((name, []))
        out[-1][1].append(group)
    return out


def _draw(t: style.Theme, sections: list, eps: float) -> plt.Figure:
    # Layout rows: a header row per section (only when there is more than one), then its groups;
    # a little extra space separates the sections.
    slots: list[tuple[str, object, float]] = []
    y = 0.0
    for k, (name, groups) in enumerate(sections):
        if len(sections) > 1:
            y += 0.35 if k else 0.0
            slots.append(("header", name, y))
            y += 1.0
        for g in groups:
            slots.append(("group", g, y))
            y += 1.0
    groups = [g for kind, g, _ in slots if kind == "group"]
    rows = [r for _, g in groups for r in g]
    screen = [r for name, gs in sections if name == "layar" for _, g in gs for r in g]
    total = Counter(_outcome(r) for r in rows)
    n_rows, n_cells = y, max(len(g) for _, g in groups)
    color = {"benar": t.accent, "tidak cukup bukti": t.warn, "salah": t.danger}
    # Fixed heights in inches: title block, rows, legend and axis below.
    head_in, foot_in = 0.99, 0.45
    fig_h = head_in + n_rows * ROW_IN + foot_in
    fig = plt.figure(figsize=(8.8, fig_h))
    renderer = fig.canvas.get_renderer()
    top, bottom, x_right = 1 - head_in / fig_h, foot_in / fig_h, 0.58
    left = fig.add_axes((0.17, bottom, 0.33, top - bottom))
    right = fig.add_axes((x_right, bottom, 0.985 - x_right, top - bottom), sharey=left)
    left.set_ylim(n_rows - 0.5, -0.5)

    wrong = total["salah"]
    title = "tidak ada tuduhan salah" if wrong == 0 else f"{wrong} tuduhan salah"
    if screen:
        ok = sum(_outcome(r) == "benar" for r in screen)
        title += f"; foto layar {ok} dari {len(screen)} benar"
    fig.text(0.0, 1 - 0.21 / fig_h, f"Uji sintetis: {title}", color=t.text, fontsize=TITLE,
             fontweight="semibold", va="baseline")
    fig.text(0.0, 1 - 0.675 / fig_h, f"Putusan per pelacakan ({len({r['expected'] for r in rows})} salinan)",
             color=t.muted, fontsize=SECONDARY, va="baseline")
    fig.text(x_right, 1 - 0.675 / fig_h, "Batas atas peluang tuduhan salah", color=t.muted, fontsize=SECONDARY,
             va="baseline")

    # Left: one rounded cell per trace, sorted benar, tidak cukup bukti, salah.
    span = n_cells + 1.2
    left.set_xlim(0, span)
    left.axis("off")
    w, h, x_pad = 0.84, 0.54, 0.08
    box = left.get_window_extent()
    aspect = (n_rows / box.height) / (span / box.width)
    names = []
    fig_x = blended_transform_factory(fig.transFigure, left.transData)
    for kind, item, y in slots:
        if kind == "header":
            fig.text(0.0, y + 0.22, SECTIONS[item], color=t.muted, fontsize=SECONDARY, va="baseline",
                     transform=fig_x)
            continue
        label, g = item
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

    # Right: per-trace bound for the correct answers, with the policy eps.
    rng = np.random.default_rng(2026)
    for kind, item, y in slots:
        if kind != "group":
            continue
        fa = np.array([r["log10_fa"] for r in item[1] if _outcome(r) == "benar"])
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
    sw, sh = 0.013, 0.135 / fig_h
    for o in OUTCOMES:
        fig.patches.append(FancyBboxPatch((x0, y_mid - sh / 2), sw, sh, boxstyle="round,pad=0,rounding_size=0.003",
                                          transform=fig.transFigure, facecolor=color[o], linewidth=0))
        text = fig.text(x0 + sw + 0.008, y_mid, f"{o} ({total[o]})" if o == "salah" else o,
                        color=t.muted, fontsize=SECONDARY, va="center")
        x0 = text.get_window_extent(renderer).x1 / fig.bbox.width + 0.03
    return fig


def benchmark() -> None:
    """Render docs/img/benchmark-{light,dark}.svg from the benchmark results."""
    sections = load()
    eps = TardosParams().eps
    # Mathtext is laid out at save time, so the context covers drawing and saving.
    math = {"mathtext.fontset": "custom", "mathtext.default": "regular",
            "mathtext.rm": style.SANS, "mathtext.cal": style.SANS}
    for t in style.THEMES:
        with plt.rc_context(math):
            style.save(_draw(t, sections, eps), "benchmark", t)


if __name__ == "__main__":
    style.setup_fonts()
    benchmark()
