"""Figure: three embedding channels on a real issued copy, compared with its master.

Issues samples/nota_dinas.pdf with the tapak CLI into out/figures-work/kanal/ (fixed code
secret and copy ids, so every run produces the same copies), then draws:

(a) word shift: one word gap of master and copy 001 rendered at 1200 dpi and overlaid;
(b) background pattern: a crop of copy 001 as seen, next to master minus copy, amplified
    and drawn as an olive tint;
(c) invisible characters: one line of copy 001's text layer with its zero-width symbols
    and Cyrillic look-alike letters made visible.

Every value drawn (shift size, gray levels, symbol counts) is measured from those PDFs
or read from the issuance manifest.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
import shutil
import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pymupdf
from matplotlib.patches import FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import style  # noqa: E402
from style import plt  # noqa: E402

from tapak import cli  # noqa: E402
from tapak.marker import issue as issue_mod  # noqa: E402
from tapak.marker.master import REVERSE_HOMOGLYPHS, load_master  # noqa: E402
from tapak.marker.pdf_zerowidth import ZW_CHARS  # noqa: E402

WORK = style.ROOT / "out" / "figures-work" / "kanal"
DOC = style.ROOT / "samples" / "nota_dinas.pdf"
RECIPIENTS = style.ROOT / "samples" / "recipients.csv"
SEQ = 1                      # which copy to show
SHIFT_DPI = 1200
PATTERN_DPI = 300
PATTERN_GAIN = 40            # contrast amplification of the difference image
PATTERN_CROP_MM = (90.0, 246.5, 30.0)   # page 2: x, y, width; blank paper above the footer
SHIFT_PAIR = ("tahun", "anggaran")      # page 1: a still word, then one shifted right
SHIFT_CROP_MM = 5.0          # width of the word-shift crop
SHIFT_BELOW_MM = 0.75        # paper kept under the baseline, room for the scale bar
TEXT_LINE = "Satu berkas jadwal latihan sintetis"
MM = 25.4 / 72.0             # millimetres per point

# Ink colors on paper are fixed: the paper stays light in both themes. Only the copy's
# own edge is dark and saturated; the master's edge stays a light neutral.
INK = np.array(style.LIGHT.text[:3])
GHOST = 0.13                 # ink strength of glyph parts the two renders share
MASTER_INK = np.array(style.oklch(0.74, 0.01, 115)[:3])
COPY_INK = np.array(style.LIGHT.accent[:3])


def mm(v: float) -> str:
    """Millimetres with a decimal comma."""
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def issue_copies() -> tuple[Path, dict]:
    """Issue the sample with the tapak CLI; return the workspace folder and its manifest."""
    shutil.rmtree(WORK / "ws", ignore_errors=True)
    keys = WORK / "ws" / "keys"
    keys.mkdir(parents=True)
    (keys / "code_secret.key").write_text(bytes(range(32)).hex() + "\n", encoding="ascii")
    rng = random.Random(2026)
    fake = types.SimpleNamespace(token_hex=lambda n: rng.getrandbits(8 * n).to_bytes(n, "big").hex())
    umask = os.umask(0o022)
    try:
        with mock.patch.object(issue_mod, "secrets", fake), contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["--data", str(WORK / "ws" / "data"), "--keys", str(keys), "issue",
                           str(DOC), str(RECIPIENTS), "--workers", "1", "--no-registry"])
    finally:
        os.umask(umask)
    if rc != 0:
        raise SystemExit(f"tapak issue failed ({rc})")
    folder = next((WORK / "ws" / "data" / "dokumen").glob("*/manifest.json")).parent
    return folder, json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def gray(page: pymupdf.Page, clip: pymupdf.Rect, dpi: int) -> np.ndarray:
    """Grayscale render of a page region as float 0..255."""
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).astype(float)


def copy_origins(page: pymupdf.Page) -> np.ndarray:
    """Baseline origins (x, y) of every visible glyph of a copy page."""
    pts = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                pts += [ch["origin"] for ch in span["chars"] if ch["c"] not in ZW_CHARS]
    return np.array(pts)


def find_shifted_pair(master_pdf: Path, copy: pymupdf.Document, shift_mm: float):
    """SHIFT_PAIR on page 1, checked to show the word shift alone.

    Displacements are measured: each master glyph origin is matched to the nearest glyph
    origin in the copy. The right word must have moved by the manifest's shift, and the
    left word and the row must not have moved. Returns both words and both x shifts in mm.
    """
    layout = load_master(master_pdf.read_bytes()).layout
    pts = copy_origins(copy[0])

    def disp(word) -> tuple[float, float]:
        g = word.glyphs[0]
        k = np.hypot(pts[:, 0] - g.x, pts[:, 1] - g.y).argmin()
        return (pts[k, 0] - g.x) * MM, (pts[k, 1] - g.y) * MM

    for row in layout.pages[0].rows:
        for left, right in zip(row.words, row.words[1:]):
            if (left.text, right.text) != SHIFT_PAIR:
                continue
            (lx, ly), (rx, ry) = disp(left), disp(right)
            if max(abs(lx), abs(ly), abs(ry)) < 0.005 and abs(rx - shift_mm) < 0.005:
                return left, right, rx, lx
    raise SystemExit(f"{SHIFT_PAIR} does not show a lone +{shift_mm} mm word shift on page 1")


def overlay(master: np.ndarray, copy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Difference overlay on white: shared ink faint, master-only gray, copy-only olive.

    Returns the RGB image and the copy-only coverage.
    """
    am = np.clip(1 - master / 255.0, 0, 1)
    paper = np.median(copy[copy > 240])            # the copy sits on its 251..255 pattern
    ac = np.clip((1 - copy / paper - 0.02) / 0.98, 0, 1)   # drop the +/-2 level pattern
    both = np.minimum(am, ac)
    layers = ((both, GHOST * (1 - INK)), (am - both, 1 - MASTER_INK), (ac - both, 1 - COPY_INK))
    return 1 - sum(cov[..., None] * dark for cov, dark in layers), ac - both


CARD_W, CARD_H, PAD = 2.74, 2.2, 0.12      # card size and inner padding, inches
LABEL_H = 0.3                               # label row at the top of every card
LABEL_Y = CARD_H - PAD - 0.08
BODY_H = CARD_H - 2 * PAD - LABEL_H         # height left for the crop or text
SHIFT_PAPER = (CARD_W - 2 * PAD, BODY_H)    # word-shift crop as drawn, inches
PATTERN_GAP = 0.1
PATTERN_PAPER = ((CARD_W - 2 * PAD - PATTERN_GAP) / 2, BODY_H)


def rounded(ax, x, y, w, h, r, **kw) -> FancyBboxPatch:
    """A rounded rectangle in data (inch) coordinates."""
    p = FancyBboxPatch((x + r, y + r), w - 2 * r, h - 2 * r, boxstyle=f"round,pad={r}",
                       linewidth=kw.pop("lw", 0.8), **kw)
    ax.add_patch(p)
    return p


def paper(ax, img, x, y, w, h, t, **kw) -> None:
    """A pixel crop on a rounded hairline card."""
    im = ax.imshow(img, extent=(x, x + w, y, y + h), interpolation="antialiased", zorder=2, **kw)
    im.set_clip_path(rounded(ax, x, y, w, h, 0.05, facecolor="none", edgecolor="none"))
    rounded(ax, x, y, w, h, 0.05, facecolor="none", edgecolor=t.line, zorder=3)


def pill(ax, x, y, w, h, color) -> None:
    """A small filled rounded bar (legend swatch or zero-width marker)."""
    rounded(ax, x, y, w, h, min(w, h) / 2.2, facecolor=color, edgecolor="none", lw=0, zorder=2)


def panel_axes(fig, col: int, t, title: str, caption: str):
    """Card axes for one column, with its title above and caption below (units: inches)."""
    W, H = fig.get_size_inches()
    x0 = col * (CARD_W + (W - 3 * CARD_W) / 2)
    card_y = 0.36
    ax = fig.add_axes((x0 / W, card_y / H, CARD_W / W, CARD_H / H))
    ax.set_xlim(0, CARD_W)
    ax.set_ylim(0, CARD_H)
    ax.axis("off")
    rounded(ax, 0, 0, CARD_W, CARD_H, 0.09, facecolor=t.card, edgecolor=t.line, zorder=0)
    fig.text(x0 / W, (card_y + CARD_H + 0.14) / H, title, color=t.text, fontsize=11.5,
             fontweight="semibold", va="baseline")
    fig.text(x0 / W, (card_y - 0.24) / H, caption, color=t.muted, fontsize=9.5, va="baseline")
    return ax


def draw_shift(fig, t, data) -> None:
    """Panel (a): master and copy overlaid around one shifted word."""
    ax = panel_axes(fig, 0, t, "Geser kata",
                    f"Kata bergeser {mm(data['shift_mm'])} mm, tetangganya diam")
    pw, ph = SHIFT_PAPER
    paper(ax, data["overlay"], PAD, PAD, pw, ph, t)
    # 1 mm scale bar in the strip under the baseline, in paper ink.
    bar = pw / SHIFT_CROP_MM
    bx, by = PAD + 0.14, PAD + SHIFT_BELOW_MM / SHIFT_CROP_MM * pw / 2
    ax.plot([bx, bx + bar], [by, by], color=INK, lw=1.4, solid_capstyle="butt", zorder=4)
    ax.text(bx + bar + 0.07, by, "1 mm", color=INK, fontsize=9, va="center", zorder=4)
    # Label the olive edge with the shift it measures, from the same strip.
    ex, ey = PAD + data["edge"][0] * pw, PAD + (1 - data["edge"][1]) * ph
    lx = ex + 0.07
    ax.plot([ex + 0.012, lx, lx], [ey, ey, by], color=COPY_INK, lw=0.8, zorder=4)
    ax.text(lx - 0.06, by, f"{mm(data['shift_mm'])} mm", color=COPY_INK, fontsize=9,
            ha="right", va="center", zorder=4)
    # Legend: what each ink means (shared ink stays faint). The copy swatch takes the
    # theme's olive, which equals COPY_INK in the light theme and stays visible on dark.
    x = PAD + 0.02
    for color, label in ((MASTER_INK, "hanya induk"), (t.accent, f"hanya salinan {SEQ:03d}")):
        pill(ax, x, LABEL_Y - 0.05, 0.1, 0.1, color)
        ax.text(x + 0.16, LABEL_Y, label, color=t.muted, fontsize=9.5, va="center")
        x += 1.0


def draw_pattern(fig, t, data) -> None:
    """Panel (b): the copy as seen, and master minus copy amplified."""
    ax = panel_axes(fig, 1, t, "Pola latar",
                    f"Pola \u00b1{data['amp']:g} tingkat abu-abu, diperkuat {PATTERN_GAIN}\u00d7")
    gray_kw = {"cmap": "gray", "vmin": 0, "vmax": 255}
    for i, (img, label, kw) in enumerate(((data["seen"], "terlihat", gray_kw),
                                          (data["diff"], f"selisih \u00d7{PATTERN_GAIN}", {}))):
        x = PAD + i * (PATTERN_PAPER[0] + PATTERN_GAP)
        paper(ax, img, x, PAD, *PATTERN_PAPER, t, **kw)
        ax.text(x + 0.02, LABEL_Y, label, color=t.muted, fontsize=9.5, va="center")


def draw_text(fig, t, data) -> None:
    """Panel (c): copied text with zero-width symbols and homoglyphs made visible."""
    ax = panel_axes(fig, 2, t, "Karakter tak terlihat", "Ikut terbawa saat teks disalin")
    size = 13.0
    adv = 0.6 * size / 72            # JetBrains Mono advance, inches
    zw = 0.42 * adv                  # room given to one zero-width marker
    bar_h = 0.1
    w = CARD_W - 2 * PAD
    rounded(ax, PAD, PAD, w, BODY_H, 0.05, facecolor=t.card, edgecolor=t.line, zorder=1)
    step = 0.42
    y = PAD + BODY_H / 2 + step * (len(data["lines"]) - 1) / 2 - 0.05
    for line in data["lines"]:
        x = PAD + 0.16
        for ch in line:
            if ch in ZW_CHARS:
                pill(ax, x + 0.3 * zw, y - 0.01, 0.4 * zw, bar_h, t.accent)
                x += zw
                continue
            cyr = ch in REVERSE_HOMOGLYPHS
            if cyr:
                rounded(ax, x - 0.004, y - 0.06, adv + 0.008, 0.25, 0.03,
                        facecolor=t.accent_soft, edgecolor="none", lw=0, zorder=1)
            ax.text(x + adv / 2, y, ch, family=style.MONO, fontsize=size, ha="center",
                    va="baseline", color=t.accent if cyr else t.text,
                    fontweight="bold" if cyr else "normal", zorder=2)
            x += adv
        y -= step
    # Legend with the real counts.
    x = PAD + 0.02
    pill(ax, x + 0.03, LABEL_Y - 0.06, 0.4 * zw, 0.12, t.accent)
    ax.text(x + 0.12, LABEL_Y, f"{data['n_zw']} simbol lebar-nol", color=t.muted, fontsize=9.5,
            va="center")
    x += 1.42
    rounded(ax, x, LABEL_Y - 0.1, 0.13, 0.2, 0.03, facecolor=t.accent_soft, edgecolor="none", lw=0)
    ax.text(x + 0.065, LABEL_Y - 0.005, "\u0430", family=style.MONO, fontsize=10, ha="center",
            va="center", color=t.accent, fontweight="bold")
    ax.text(x + 0.2, LABEL_Y, f"{data['n_hg']} huruf Kiril", color=t.muted, fontsize=9.5,
            va="center")


def measure() -> dict:
    """Issue the copies and compute everything the panels show."""
    folder, manifest = issue_copies()
    entry = next(c for c in manifest["copies"] if c["seq"] == SEQ)
    master_pdf = folder / "induk.pdf"
    master = pymupdf.open(master_pdf)
    copy = pymupdf.open(folder / "salinan" / entry["file"])
    shift_mm = manifest["shift_mm"]["word_mm"]
    bg = manifest["background"]

    # (a) the gap between a still word and a shifted word: the end of the left word and the
    # first letter of the right one, x-height band plus a strip under the baseline.
    # The pair is checked to move right, so the outer copy-only edge is the rightmost one.
    left, right, dx, left_dx = find_shifted_pair(master_pdf, copy, shift_mm)
    size, base = right.glyphs[0].size, right.glyphs[0].y
    crop_w = SHIFT_CROP_MM / MM
    crop_h = crop_w * SHIFT_PAPER[1] / SHIFT_PAPER[0]
    x1, y1 = right.glyphs[1].x - 0.05 / MM, base + SHIFT_BELOW_MM / MM  # stop before letter 2
    clip = pymupdf.Rect(x1 - crop_w, y1 - crop_h, x1, y1)
    ov, copy_only = overlay(gray(master[0], clip, SHIFT_DPI), gray(copy[0], clip, SHIFT_DPI))
    # Point the label at the outer copy-only edge, at mid x-height.
    r = int((base - 0.27 * size - clip.y0) / crop_h * ov.shape[0])
    cols = np.nonzero(copy_only[r] > 0.5)[0]
    edge = ((cols.max() + 1) / ov.shape[1], r / ov.shape[0])

    # (b) master minus copy over a page-2 region (the master paper is white), drawn as an
    # olive tint on paper: the darker the tint, the darker the copy is than the master.
    x, y, cw = (v / MM for v in PATTERN_CROP_MM)
    ch = cw * PATTERN_PAPER[1] / PATTERN_PAPER[0]
    clip_b = pymupdf.Rect(x, y, x + cw, y + ch)
    seen = gray(copy[1], clip_b, PATTERN_DPI)
    delta = gray(master[1], clip_b, PATTERN_DPI) - seen
    tint = np.clip(PATTERN_GAIN * delta, 0, 255) / 255
    diff = 1 - tint[..., None] * (1 - COPY_INK)
    diff = np.minimum(diff, (seen / 255.0)[..., None])  # the page's own ink on top, as in "terlihat"
    words = copy[1].get_text("words", clip=clip_b)
    if any(w[0] < clip_b.x0 or w[2] > clip_b.x1 or w[3] > clip_b.y1 for w in words):
        raise SystemExit("a word is cut by the pattern crop")
    top = min(w[1] for w in words)                    # paper above the first line is blank
    blank = int((top - clip_b.y0) * MM / 25.4 * PATTERN_DPI) - 2
    levels = sorted({int(v) for v in seen[:blank].ravel()})
    if (levels[0], levels[-1]) != (bg["base"] - bg["amplitude"], bg["base"] + bg["amplitude"]):
        raise SystemExit(f"copy paper levels {levels} do not match the manifest {bg}")

    # (c) the copy's text layer for one line, split into three display rows.
    text = copy[0].get_text("text", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    line = next(ln for ln in text.splitlines()
                if TEXT_LINE in "".join(REVERSE_HOMOGLYPHS.get(c, c) for c in ln if c not in ZW_CHARS))
    tokens = [tk for tk in line.split(" ")
              if "".join(c for c in tk if c not in ZW_CHARS).strip(":")]
    rows = [" ".join(tokens[:2]), " ".join(tokens[2:4]), " ".join(tokens[4:])]
    shown = "".join(rows)
    return {
        "copy": entry["file"], "recipient": entry["recipient"]["recipient_id"],
        "shift_mm": shift_mm, "dx_mm": dx, "left_dx_mm": left_dx,
        "word": right.text, "neighbour": left.text,
        "overlay": ov, "edge": edge, "fringe_px": int((copy_only[r] > 0.5).sum()),
        "amp": bg["amplitude"], "base": bg["base"],
        "seen": seen, "diff": diff, "words": " ".join(w[4] for w in words),
        "copy_levels": levels,
        "master_levels": sorted({int(v) for v in (seen + delta)[:blank].ravel()}),
        "lines": rows, "n_zw": sum(c in ZW_CHARS for c in shown),
        "n_hg": sum(c in REVERSE_HOMOGLYPHS for c in shown),
    }


def main() -> None:
    style.setup_fonts()
    data = measure()
    for t in style.THEMES:
        fig = plt.figure(figsize=(8.8, 3.0))
        draw_shift(fig, t, data)
        draw_pattern(fig, t, data)
        draw_text(fig, t, data)
        style.save(fig, "kanal", t, png=True)
    print(f"copy {data['copy']} ({data['recipient']}): word '{data['word']}' moved {data['dx_mm']:+.4f} mm "
          f"(manifest {data['shift_mm']} mm), neighbour '{data['neighbour']}' moved "
          f"{data['left_dx_mm']:+.4f} mm; copy-only pixels at mid x-height: {data['fringe_px']}")
    print(f"background base {data['base']:g} +/- {data['amp']:g}; blank paper levels: copy "
          f"{data['copy_levels']}, master {data['master_levels']}; gain {PATTERN_GAIN}; "
          f"words in crop: {data['words']!r}")
    print(f"text rows {[r.encode('unicode_escape').decode() for r in data['lines']]}")
    print(f"zero-width {data['n_zw']}, homoglyphs {data['n_hg']}")


if __name__ == "__main__":
    main()
