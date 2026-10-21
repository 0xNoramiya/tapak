"""Flow figure for the README: master document, issued copies, leak, trace verdict.

Every picture and number comes from a real run of ``tapak demo`` into
``out/figures-work/alur/demo``: the sample nota dinas, the issued copies, the synthetic
phone photo of copy #13, the trace verdict and the berita acara PDF. The demo draws a fresh
code secret and random copy ids on each run; both are seeded here so the codewords, and so
every number in the figure, come out the same each time (only the dates printed inside the
berita acara thumbnail change).

    TAPAK_FIG_FONTS=... .venv/bin/python docs/figures/fig_alur.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import random
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pymupdf
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

ROOT = style.ROOT
sys.path.insert(0, str(ROOT))
WORK = ROOT / "out" / "figures-work" / "alur"
DEMO = WORK / "demo"
SECRET = hashlib.sha256(b"tapak-readme-alur").hexdigest()

W, H = 8.8, 3.2
PX = 200  # embedded raster resolution, px per figure inch (2x the 100 dpi README column)
TOP, BOTTOM = 2.78, 1.28  # the row of pictures
CAP = BOTTOM - 0.17  # first caption baseline
PAGE_H = TOP - BOTTOM
STACK_H, STACK_DX, STACK_DY = PAGE_H - 0.16, 0.2, 0.08
TILE_W, TILE_GAP = 0.86, 0.16
TILE_H = (PAGE_H - 0.27) / 2  # two rows of tiles filling the picture row; the lower labels sit on CAP
TILE_ROW = TILE_H + 0.27
BA_H = 0.86
A4 = 595.28 / 841.89
GAPS = (0.5, 0.5, 1.0)  # room for the arrows; only the last one is labelled
WIDTHS = [PAGE_H * A4, STACK_H * A4 + 2 * STACK_DX, 2 * TILE_W + TILE_GAP]
WIDTHS.append(W - sum(WIDTHS) - sum(GAPS))
LEFT = [sum(WIDTHS[:i]) + sum(GAPS[:i]) for i in range(4)]


# --- data -------------------------------------------------------------------------------


def run_scenario() -> dict:
    """Run ``tapak demo`` with a fixed secret and copy ids, then trace its photo again for the numbers."""
    import tapak.marker.issue
    from tapak.config import Settings
    from tapak.decoder.report import scientific_parts
    from tapak.demo import run_demo
    from tapak.marker.issue import read_recipients
    from tapak.service import list_workspaces, load_workspace, trace_evidence

    if DEMO.exists():
        shutil.rmtree(DEMO)
    (DEMO / "keys").mkdir(parents=True)
    (DEMO / ".tapak-demo").write_text("folder demo TAPAK; boleh dihapus\n", encoding="utf-8")
    (DEMO / "keys" / "code_secret.key").write_text(SECRET + "\n", encoding="ascii")
    rng = random.Random(13)
    ids = SimpleNamespace(token_hex=lambda n: rng.getrandbits(8 * n).to_bytes(n, "big").hex())
    with mock.patch.object(tapak.marker.issue, "secrets", ids), \
            contextlib.redirect_stdout(io.StringIO()) as log:
        status = run_demo(DEMO, keep=True)  # keep: the demo would otherwise wipe the key above
    (WORK / "demo.log").write_text(log.getvalue(), encoding="utf-8")
    if status != 0:
        raise SystemExit(f"tapak demo gagal; lihat {WORK / 'demo.log'}")

    settings = Settings(data_dir=DEMO / "data", key_dir=DEMO / "keys")
    doc_hash = list_workspaces(settings)[0].doc_hash
    manifest, _, folder = load_workspace(settings, doc_hash)
    photo = (DEMO / "foto_bocor.jpg").read_bytes()
    a = trace_evidence(settings, doc_hash, "foto_bocor.jpg", photo).attribution
    top = a.accused[0]
    return {
        "verdict": a.verdict,
        "seq": top.copy.seq,
        "recipient": top.copy.recipient_id,
        "score": top.score,
        "threshold": a.threshold.threshold,
        "log10_fap": top.log10_false_accusation,
        # Same rounding as the web UI and the berita acara: one decimal, rounded up.
        "fap": scientific_parts(0.0, log10_value=top.log10_false_accusation, round_up=True),
        "n_copies": len(manifest.copies),
        "n_recipients": len(read_recipients(ROOT / "samples" / "recipients.csv")),
        "channels": sorted(manifest.plan_summary),
        "copies": {c.seq: folder / "salinan" / c.file for c in manifest.copies},
        "photo": photo,
        "report": DEMO / "berita_acara_salinan13.pdf",
    }


# --- rasters ----------------------------------------------------------------------------


def posterize(img: np.ndarray, levels: int = 16) -> np.ndarray:
    """Fewer gray levels: invisible at thumbnail size, and the embedded PNG shrinks a lot."""
    return np.round(img * (levels - 1)) / (levels - 1)


def render_page(pdf: Path, height_in: float) -> np.ndarray:
    """Page 1 of a PDF as an RGB float array, ``height_in`` inches tall at PX."""
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        zoom = height_in * PX / page.rect.height
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return posterize(arr[..., :3] / 255.0)


def cover(img: Image.Image, w_in: float, h_in: float, anchor_y: float = 0.5) -> np.ndarray:
    """Crop to the aspect of a w x h inch box (anchor_y 0 keeps the top) and resize to PX."""
    w, h = img.size
    if w / h > w_in / h_in:
        cw, ch = round(h * w_in / h_in), h
    else:
        cw, ch = w, round(w * h_in / w_in)
    x0, y0 = (w - cw) // 2, round((h - ch) * anchor_y)
    img = img.convert("RGB").crop((x0, y0, x0 + cw, y0 + ch))
    img = img.resize((round(w_in * PX), round(h_in * PX)), Image.LANCZOS)
    return posterize(np.asarray(img) / 255.0, 32)


def screenshot_tile(copy_pdf: Path) -> np.ndarray:
    """Top-left corner of a synthetic PDF-viewer screenshot of the copy (tapak.photos)."""
    from tapak.marker.render import render_pages
    from tapak.photos import ScreenshotParams, screenshot

    page = render_pages(copy_pdf.read_bytes(), 200, [0])[0]
    img, _ = screenshot(page, np.random.default_rng(7), ScreenshotParams(screen_dpi=72.0, chrome=True))
    return cover(Image.fromarray(img), TILE_W, TILE_H, anchor_y=0.0)


def text_tile(copy_pdf: Path, color: tuple) -> np.ndarray:
    """Body text copied out of the issued PDF (homoglyphs included), drawn small in mono."""
    with pymupdf.open(copy_pdf) as doc:
        text = doc[0].get_text()
    text = " ".join(re.sub(r"[\u200b-\u200f\u2060-\u2064\ufeff]", "", text).split())
    words = text[text.find("Dengan hormat"):].split()
    lines = [""]
    for word in words:
        if len(lines[-1]) + len(word) >= 18:
            lines.append("")
        lines[-1] = f"{lines[-1]} {word}".strip()
    w, h = round(TILE_W * PX), round(TILE_H * PX)
    font = ImageFont.truetype(font_manager.findfont(style.MONO), size=round(0.06 * PX))
    tile = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(tile)
    pad, step = round(0.08 * PX), round(0.085 * PX)
    for i, line in enumerate(lines[:6]):
        draw.text((pad, pad + i * step), line, fill=255, font=font)
    rgba = np.zeros((h, w, 4))
    rgba[..., :3] = color[:3]
    rgba[..., 3] = posterize(np.asarray(tile) / 255.0)
    return rgba


def hide_behind(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Blank the part of a stacked page that the page in front of it covers (smaller SVG)."""
    out = img.copy()
    out[round(dy * PX):, :max(0, out.shape[1] - round(dx * PX))] = 1.0
    return out


# --- drawing ----------------------------------------------------------------------------


def box(x, y, w, h, radius, **kw) -> FancyBboxPatch:
    return FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}", **kw)


def place(ax, img, x, y, w, h, t, edge=None, lw=0.7, radius=0.035, z=2.0, tint=True) -> None:
    """An image in a rounded box with a hairline border; pages take the theme's paper tint."""
    if tint:
        img = img * np.asarray(t.paper[:3])
    im = ax.imshow(img, extent=(x, x + w, y, y + h), interpolation="none", zorder=z)
    im.set_clip_path(box(x, y, w, h, radius, transform=ax.transData))
    ax.add_patch(box(x, y, w, h, radius, facecolor="none", edgecolor=edge or t.line, linewidth=lw,
                     zorder=z + 0.1))


def label(ax, x, y, text, t, size=9.0, color=None, weight="normal", **kw):
    return ax.text(x, y, text, fontsize=size, color=color or t.muted, fontweight=weight,
                   va="baseline", **kw)


def header(ax, i: int, title: str, t: style.Theme) -> None:
    label(ax, LEFT[i], 3.0, title, t, size=11, color=t.text, weight="semibold")


def arrow(ax, i: int, t: style.Theme, command: str | None = None) -> None:
    x0, x1 = LEFT[i] + WIDTHS[i] + 0.1, LEFT[i + 1] - 0.1
    y = TOP - TILE_H / 2  # level with the first row of leak tiles, clear of their labels
    ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle="-|>", mutation_scale=7, linewidth=0.8,
                                 color=t.faint, shrinkA=0, shrinkB=0, zorder=1))
    if command:
        label(ax, (x0 + x1) / 2, y + 0.1, command, t, ha="center", family=style.MONO)


def draw(t: style.Theme, d: dict, imgs: dict) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    # 1 master document
    header(ax, 0, "Dokumen induk", t)
    place(ax, imgs["induk"], LEFT[0], BOTTOM, WIDTHS[0], PAGE_H, t)
    label(ax, LEFT[0], CAP, "PDF berlapis teks", t, size=9.5, color=t.text)
    label(ax, LEFT[0], CAP - 0.19, f"+ daftar {d['n_recipients']} penerima", t)

    # 2 issued copies, front copy first
    header(ax, 1, "Terbitkan", t)
    for i in (2, 1, 0):
        place(ax, imgs["copies"][i], LEFT[1] + i * STACK_DX, BOTTOM + i * STACK_DY, STACK_H * A4, STACK_H,
              t, z=5.0 - i)
    label(ax, LEFT[1], CAP, f"{d['n_copies']} salinan unik", t, size=9.5, color=t.text)
    # The README counts zero-width symbols and homoglyphs as one channel; the canary carries no code.
    n_code = len({"zw" if c == "homoglyph" else c for c in d["channels"]})
    label(ax, LEFT[1], CAP - 0.19, f"kode Tardos di {n_code} kanal + kanari", t)

    # 3 leak forms; the photo is the one traced here
    header(ax, 2, "Bocor", t)
    for i, name in enumerate(("foto sintetis", "tangkapan layar", "PDF diteruskan", "teks disalin")):
        x = LEFT[2] + (i % 2) * (TILE_W + TILE_GAP)
        y = TOP - TILE_H - (i // 2) * TILE_ROW
        if name == "foto sintetis":
            place(ax, imgs["foto"], x, y, TILE_W, TILE_H, t, edge=t.accent, lw=1.4, tint=False)
        elif name == "tangkapan layar":
            place(ax, imgs["layar"], x, y, TILE_W, TILE_H, t)
        else:
            ax.add_patch(box(x, y, TILE_W, TILE_H, 0.035, facecolor=t.card, edgecolor=t.line, linewidth=0.7))
        if name == "PDF diteruskan":
            ph = TILE_H - 0.14
            place(ax, imgs["pdf"], x + (TILE_W - ph * A4) / 2, y + 0.07, ph * A4, ph, t, radius=0.012, z=3)
        if name == "teks disalin":
            ax.imshow(imgs["teks"][t.name], extent=(x, x + TILE_W, y, y + TILE_H), interpolation="none", zorder=3)
        hot = name == "foto sintetis"
        label(ax, x, y - 0.17, name, t, color=t.accent if hot else t.muted, weight="semibold" if hot else "normal")

    # 4 verdict card, as the web UI shows it
    header(ax, 3, "Lacak", t)
    x, w = LEFT[3], WIDTHS[3]
    ax.add_patch(box(x, BOTTOM, w, PAGE_H, 0.07, facecolor=t.card_strong, edgecolor="none"))
    px = x + 0.18
    label(ax, px, TOP - 0.27, d["verdict"].upper(), t, color=t.accent, weight="bold")
    label(ax, px, TOP - 0.59, f"Salinan #{d['seq']}", t, size=16, color=t.text, weight="semibold")
    label(ax, px, TOP - 0.8, f"penerima {d['recipient']}", t)
    label(ax, px, BOTTOM + 0.4, "peluang tuduhan salah", t)
    mant, exp = d["fap"]
    sup = str(exp).translate(str.maketrans("-0123456789", "\u207b\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076"
                                                          "\u2077\u2078\u2079"))
    label(ax, px, BOTTOM + 0.16, f"\u2264 {mant} \u00d7 10{sup}", t, size=13, color=t.text, weight="semibold")
    bx = x + w - 0.18 - BA_H * A4
    place(ax, imgs["ba"], bx, BOTTOM + (PAGE_H - BA_H) / 2, BA_H * A4, BA_H, t, radius=0.015, z=3)
    label(ax, x + w, CAP, "+ berita acara PDF", t, ha="right")

    arrow(ax, 0, t)
    arrow(ax, 1, t)
    arrow(ax, 2, t, command="tapak trace")

    # registry band: issuance writes to it, a trace checks against it before naming anyone
    bx0, by, bh = LEFT[1], 0.06, 0.34
    ax.add_patch(box(bx0, by, W - bx0, bh, 0.06, facecolor=t.card, edgecolor=t.line, linewidth=0.7))
    for x, word in ((LEFT[1] + 0.3, "dicatat"), (LEFT[3] + 0.3, "dicocokkan")):
        ax.plot([x, x], [by + bh, 0.68], color=t.faint, linewidth=0.8, solid_capstyle="butt", zorder=1)
        ax.plot([x], [by + bh], marker="o", markersize=3, color=t.faint, zorder=2)
        label(ax, x + 0.08, 0.5, word, t)
    strong = label(ax, bx0 + 0.18, by + bh / 2, "Registri tambah-saja, ditandatangani Ed25519:", t,
                   size=9.5, color=t.text, weight="semibold")
    strong.set_va("center_baseline")
    width = strong.get_window_extent(fig.canvas.get_renderer()).width / fig.dpi
    rest = label(ax, bx0 + 0.18 + width + 0.06, by + bh / 2, "hash dan komitmen, tanpa isi dokumen", t,
                 size=9.5)
    rest.set_va("center_baseline")

    style.save(fig, "alur", t)


def main() -> None:
    style.setup_fonts()
    d = run_scenario()
    copy = d["copies"][d["seq"]]
    stack = [render_page(d["copies"][s], STACK_H) for s in (d["seq"], 1, 2)]
    imgs = {
        "induk": render_page(ROOT / "samples" / "nota_dinas.pdf", PAGE_H),
        "copies": [stack[0]] + [hide_behind(img, i * STACK_DX, i * STACK_DY) for i, img in enumerate(stack) if i],
        "foto": cover(Image.open(io.BytesIO(d["photo"])), TILE_W, TILE_H, anchor_y=0.15),
        "layar": screenshot_tile(copy),
        "pdf": render_page(copy, TILE_H - 0.14),
        "ba": render_page(d["report"], BA_H),
        "teks": {t.name: text_tile(copy, t.muted) for t in style.THEMES},
    }
    for t in style.THEMES:
        draw(t, d, imgs)
    mant, exp = d["fap"]
    print(f"{d['verdict']}: salinan #{d['seq']} ({d['recipient']}), skor {d['score']:.1f} >= ambang "
          f"{d['threshold']:.1f}, peluang tuduhan salah <= {mant} x 10^{exp} (log10 {d['log10_fap']:.4f}); "
          f"{d['n_copies']} salinan, {d['n_recipients']} penerima, kanal kode: {', '.join(d['channels'])}")


if __name__ == "__main__":
    main()
