"""Shared look for the README figures: palette, type and light/dark export.

Every figure is drawn twice, once per GitHub theme, and saved as SVG with text converted
to paths (no font needed by the viewer). Colors mirror the web UI tokens in
``tapak/web/static/tapak.css`` (olive accent, warm neutrals). Backgrounds are transparent;
cards use translucent fills so they sit on both GitHub's white and its dark canvas.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
IMG_DIR = ROOT / "docs" / "img"
# Optional raster previews (for reviewing SVGs by eye); not committed.
PREVIEW_DIR = Path(os.environ.get("TAPAK_FIG_PREVIEW", ROOT / "out" / "figures"))


def oklch(lightness: float, chroma: float, hue: float, alpha: float = 1.0) -> tuple:
    """Convert an OKLCH color to an sRGB(A) tuple in 0..1 for matplotlib."""
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    rgb = (
        4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
        -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
        -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc,
    )

    def gamma(x: float) -> float:
        x = min(1.0, max(0.0, x))
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055

    return (*(gamma(v) for v in rgb), alpha)


@dataclass(frozen=True)
class Theme:
    """Color tokens for one GitHub theme."""

    name: str
    text: tuple
    muted: tuple
    faint: tuple
    line: tuple          # hairlines, axes, card borders
    card: tuple          # translucent card fill
    card_strong: tuple   # emphasized card fill
    accent: tuple        # olive, the "identified" color
    accent_soft: tuple
    danger: tuple        # wrong / false accusation
    warn: tuple          # undecided ("tidak cukup bukti")
    info: tuple          # neutral data series (innocent scores)
    paper: tuple         # document thumbnails background


LIGHT = Theme(
    name="light",
    text=oklch(0.23, 0.012, 115),
    muted=oklch(0.47, 0.012, 115),
    faint=oklch(0.62, 0.01, 115),
    line=oklch(0.2, 0.02, 115, 0.16),
    card=oklch(0.2, 0.02, 115, 0.035),
    card_strong=oklch(0.43, 0.075, 128, 0.10),
    accent=oklch(0.48, 0.09, 128),
    accent_soft=oklch(0.93, 0.035, 128),
    danger=oklch(0.55, 0.17, 27),
    warn=oklch(0.62, 0.12, 70),
    info=oklch(0.6, 0.02, 250),
    paper=oklch(0.995, 0.002, 110),
)

DARK = Theme(
    name="dark",
    text=oklch(0.93, 0.008, 110),
    muted=oklch(0.74, 0.01, 110),
    faint=oklch(0.6, 0.01, 110),
    line=oklch(1, 0, 0, 0.16),
    card=oklch(1, 0, 0, 0.045),
    card_strong=oklch(0.62, 0.07, 128, 0.16),
    accent=oklch(0.72, 0.1, 128),
    accent_soft=oklch(0.32, 0.04, 128),
    danger=oklch(0.68, 0.15, 27),
    warn=oklch(0.78, 0.11, 75),
    info=oklch(0.68, 0.03, 250),
    paper=oklch(0.96, 0.004, 110),
)

THEMES = (LIGHT, DARK)

_FONT_DIRS = [
    Path(os.environ["TAPAK_FIG_FONTS"]) if os.environ.get("TAPAK_FIG_FONTS") else None,
    ROOT / "tapak" / "assets" / "fonts",
]
SANS = "DejaVu Sans"
MONO = "DejaVu Sans Mono"


def setup_fonts() -> None:
    """Register Inter and JetBrains Mono when TAPAK_FIG_FONTS points at them, else DejaVu."""
    global SANS, MONO
    found = set()
    for d in _FONT_DIRS:
        if d and d.is_dir():
            for f in d.rglob("*.ttf"):
                font_manager.fontManager.addfont(str(f))
                found.add(f.stem.split("-")[0])
    if "Inter" in found:
        SANS = "Inter"
    if "JetBrainsMono" in found:
        MONO = "JetBrains Mono"
    plt.rcParams.update({
        "font.family": SANS,
        "font.size": 10,
        "svg.fonttype": "path",
        "svg.hashsalt": "tapak",
        "axes.unicode_minus": False,
        "figure.dpi": 100,
        "savefig.transparent": True,
    })


def style_axes(ax, t: Theme, grid_axis: str | None = "y") -> None:
    """Quiet axes: no box, hairline baseline, faint grid, muted tick labels."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t.line)
    ax.tick_params(colors=t.muted, labelcolor=t.muted, length=0, labelsize=9)
    if grid_axis:
        ax.grid(axis=grid_axis, color=t.line, linewidth=0.6)
        ax.set_axisbelow(True)
    ax.set_facecolor((0, 0, 0, 0))


def save(fig, name: str, t: Theme, png: bool = False) -> Path:
    """Write docs/img/<name>-<theme>.svg (or .png at 2x) plus a raster preview."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "png" if png else "svg"
    out = IMG_DIR / f"{name}-{t.name}.{suffix}"
    kw = {"bbox_inches": "tight", "pad_inches": 0.08, "transparent": True}
    if png:
        fig.savefig(out, dpi=200, **kw)
    else:
        fig.savefig(out, metadata={"Date": None, "Creator": None}, **kw)
    # Preview on the theme's GitHub canvas so it can be checked by eye.
    bg = "#ffffff" if t.name == "light" else "#0d1117"
    fig.savefig(PREVIEW_DIR / f"{name}-{t.name}.png", dpi=150, bbox_inches="tight",
                pad_inches=0.15, facecolor=bg, transparent=False)
    plt.close(fig)
    return out
