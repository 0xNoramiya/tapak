"""Synthetic Indonesian military letters for testing (fictional units, people, numbers).

Templates live in ``samples/templates/*.json``. The generator is a small layout engine on
top of PyMuPDF: it typesets every word individually with the bundled DejaVu fonts, so the
output is a normal text PDF (selectable, searchable) that TAPAK can mark.

Every page carries the footer "CONTOH SINTETIS - BUKAN DOKUMEN ASLI" so a generated file
can never be mistaken for a real document. ``scanned_sample`` turns a generated sample into a
fictional scan (image-only pages, optionally with an invisible OCR layer, or mixed with text
pages); the footer stays in every page image.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from tapak.fonts import font_path

A4 = (595.28, 841.89)
MARGIN_LEFT = 72.0
MARGIN_RIGHT = 64.0
MARGIN_TOP = 56.0
MARGIN_BOTTOM = 72.0
BODY_SIZE = 11.5
LEADING = 1.38
FOOTER_TEXT = "CONTOH SINTETIS - BUKAN DOKUMEN ASLI"


@dataclass
class _Pen:
    doc: pymupdf.Document
    page: pymupdf.Page
    writer: pymupdf.TextWriter
    y: float
    classification: str


class _Typesetter:
    """Very small flowing layout engine: words, justified paragraphs, page breaks."""

    def __init__(self, classification: str) -> None:
        self.doc = pymupdf.open()
        self.regular = pymupdf.Font(fontfile=str(font_path("DejaVuSans")))
        self.bold = pymupdf.Font(fontfile=str(font_path("DejaVuSans-Bold")))
        self.classification = classification
        self.pen: _Pen | None = None
        self._new_page()

    # page handling -----------------------------------------------------------------
    def _new_page(self) -> None:
        if self.pen is not None:
            self._finish_page()
        page = self.doc.new_page(width=A4[0], height=A4[1])
        writer = pymupdf.TextWriter(page.rect)
        self.pen = _Pen(self.doc, page, writer, MARGIN_TOP, self.classification)
        self._centered(self.classification, self.bold, 11.0, 34.0, writer)

    def _finish_page(self) -> None:
        assert self.pen is not None
        w = self.pen.writer
        self._centered(self.classification, self.bold, 11.0, A4[1] - 30.0, w)
        self._centered(FOOTER_TEXT, self.regular, 7.0, A4[1] - 16.0, w)
        w.write_text(self.pen.page)

    def _centered(self, text: str, font: pymupdf.Font, size: float, y: float, w: pymupdf.TextWriter) -> None:
        width = font.text_length(text, size)
        self._words_at(text.split(), font, size, (A4[0] - width) / 2.0, y, w)

    def _words_at(
        self, words: list[str], font: pymupdf.Font, size: float, x: float, y: float,
        w: pymupdf.TextWriter, gap: float | None = None,
    ) -> float:
        space = font.text_length(" ", size) if gap is None else gap
        for word in words:
            w.append((x, y), word, font=font, fontsize=size)
            x += font.text_length(word, size) + space
        return x

    def ensure(self, height: float) -> None:
        assert self.pen is not None
        if self.pen.y + height > A4[1] - MARGIN_BOTTOM:
            self._new_page()

    @property
    def right(self) -> float:
        return A4[0] - MARGIN_RIGHT

    # elements ----------------------------------------------------------------------
    def line(self, text: str, *, bold: bool = False, size: float = BODY_SIZE, x: float = MARGIN_LEFT,
             align: str = "left", width: float | None = None, advance: bool = True) -> None:
        font = self.bold if bold else self.regular
        self.ensure(size * LEADING)
        assert self.pen is not None
        baseline = self.pen.y + size
        words = text.split()
        tw = font.text_length(" ".join(words), size)
        avail = (self.right - x) if width is None else width
        if align == "center":
            x = x + (avail - tw) / 2.0
        elif align == "right":
            x = x + avail - tw
        self._words_at(words, font, size, x, baseline, self.pen.writer)
        if advance:
            self.pen.y += size * LEADING

    def rule(self, x0: float, x1: float, width: float = 0.8) -> None:
        assert self.pen is not None
        y = self.pen.y + 2.0
        self.pen.page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=width)
        self.pen.y += 6.0

    def gap(self, h: float) -> None:
        assert self.pen is not None
        self.pen.y += h

    def paragraph(self, text: str, *, x: float = MARGIN_LEFT, first_x: float | None = None,
                  label: str | None = None, label_x: float | None = None, size: float = BODY_SIZE,
                  bold: bool = False) -> None:
        """Justified paragraph; optional hanging label (e.g. "1.") at ``label_x``."""
        font = self.bold if bold else self.regular
        words = text.split()
        space = font.text_length(" ", size)
        lines: list[list[str]] = []
        cur: list[str] = []
        start_x = first_x if first_x is not None else x
        line_start = start_x
        for word in words:
            trial = cur + [word]
            if cur and font.text_length(" ".join(trial), size) > self.right - line_start:
                lines.append(cur)
                cur = [word]
                line_start = x
            else:
                cur = trial
        if cur:
            lines.append(cur)
        for i, ws in enumerate(lines):
            self.ensure(size * LEADING)
            assert self.pen is not None
            baseline = self.pen.y + size
            lx = start_x if i == 0 else x
            if i == 0 and label is not None:
                self._words_at([label], font, size, MARGIN_LEFT if label_x is None else label_x,
                               baseline, self.pen.writer)
            last = i == len(lines) - 1
            if last or len(ws) == 1:
                self._words_at(ws, font, size, lx, baseline, self.pen.writer, gap=space)
            else:
                text_w = sum(font.text_length(wd, size) for wd in ws)
                g = (self.right - lx - text_w) / (len(ws) - 1)
                self._words_at(ws, font, size, lx, baseline, self.pen.writer, gap=g)
            self.pen.y += size * LEADING

    def field(self, label: str, value: str, *, label_x: float = MARGIN_LEFT, colon_x: float = 150.0,
              size: float = BODY_SIZE) -> None:
        self.ensure(size * LEADING)
        assert self.pen is not None
        baseline = self.pen.y + size
        self._words_at(label.split(), self.regular, size, label_x, baseline, self.pen.writer)
        self._words_at([":"], self.regular, size, colon_x, baseline, self.pen.writer)
        self.pen.y -= 0  # value may wrap like a paragraph
        self.paragraph_at_baseline(value, colon_x + 10.0, size)

    def paragraph_at_baseline(self, text: str, x: float, size: float) -> None:
        """Left-aligned wrapped text starting on the current line (used for field values)."""
        font = self.regular
        words = text.split()
        cur: list[str] = []
        rows: list[list[str]] = []
        for word in words:
            if cur and font.text_length(" ".join(cur + [word]), size) > self.right - x:
                rows.append(cur)
                cur = [word]
            else:
                cur.append(word)
        if cur:
            rows.append(cur)
        for ws in rows:
            self.ensure(size * LEADING)
            assert self.pen is not None
            self._words_at(ws, font, size, x, self.pen.y + size, self.pen.writer)
            self.pen.y += size * LEADING

    def finish(self) -> bytes:
        self._finish_page()
        self.doc.set_metadata({"producer": "TAPAK samplegen", "creator": "TAPAK samplegen",
                               "title": "Contoh sintetis"})
        self.doc.subset_fonts()
        return self.doc.tobytes(garbage=3, deflate=True)


def render_template(template: dict) -> bytes:
    """Typeset a template dictionary (see samples/templates) into PDF bytes."""
    ts = _Typesetter(template.get("klasifikasi", "RAHASIA"))
    for line in template["kop"]:
        ts.line(line, bold=True, size=10.5)
    ts.rule(MARGIN_LEFT, MARGIN_LEFT + 230.0)
    ts.gap(14)
    ts.line(template["judul"], bold=True, size=12.5, align="center")
    ts.line(template["nomor"], align="center")
    ts.gap(12)
    for label, value in template["kepala"]:
        ts.field(label, value)
    ts.gap(6)
    ts.rule(MARGIN_LEFT, ts.right, width=0.5)
    ts.gap(6)
    if template.get("pembuka"):
        ts.paragraph(template["pembuka"])
        ts.gap(4)
    for i, item in enumerate(template["isi"], start=1):
        if isinstance(item, str):
            ts.paragraph(item, x=MARGIN_LEFT + 22.0, label=f"{i}.")
        else:
            ts.paragraph(item["teks"], x=MARGIN_LEFT + 22.0, label=f"{i}.")
            for j, sub in enumerate(item.get("sub", [])):
                ts.paragraph(sub, x=MARGIN_LEFT + 44.0, label=f"{chr(97 + j)}.", label_x=MARGIN_LEFT + 22.0)
        ts.gap(3)
    if template.get("penutup"):
        ts.paragraph(template["penutup"])
    ts.gap(18)
    sig_x = 330.0
    for line in template["ttd"]:
        ts.line(line, x=sig_x)
        if line == template["ttd"][len(template["ttd"]) // 2 - 1]:
            ts.gap(28)
    if template.get("tembusan"):
        ts.gap(10)
        ts.line("Tembusan:")
        for i, t in enumerate(template["tembusan"], start=1):
            ts.line(f"{i}. {t}", x=MARGIN_LEFT + 6.0)
    return ts.finish()


def load_template(path: Path) -> dict:
    """Read a JSON template."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_recipients(path: Path, n: int = 20) -> None:
    """Write a CSV of ``n`` fictional recipients."""
    ranks = ["Letkol Inf", "Mayor Inf", "Mayor Arh", "Kapten Inf", "Kapten Kav", "Lettu Czi", "Kapten Chk"]
    first = ["Arga", "Bayu", "Candra", "Dimas", "Eka", "Fajar", "Galih", "Hendra", "Indra", "Joko",
             "Kurnia", "Lukas", "Made", "Nanda", "Oki", "Pandu", "Rangga", "Satria", "Taufan", "Umar",
             "Wira", "Yoga", "Zaki", "Bagas", "Damar"]
    units = ["Yonif 9901/Contoh", "Yonkav 9902/Fiktif", "Kodim 9903/Sintetis", "Denzipur 9904/Uji",
             "Brigif 9905/Latihan", "Yonarhanud 9906/Simulasi"]
    jabatan = ["Danyon", "Wadanyon", "Pasi Ops", "Pasi Intel", "Dandim", "Kasdim", "Danki"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["recipient_id", "nama", "jabatan", "satuan"])
        for i in range(n):
            rid = f"R{i + 1:03d}"
            nama = f"{ranks[i % len(ranks)]} {first[i % len(first)]} Fiktif{i + 1:02d}"
            wr.writerow([rid, nama, jabatan[i % len(jabatan)], units[i % len(units)]])


# Fictional scanned sample: the text sample rendered like a flatbed scan of a printout.
SCAN_DPI = 300
SCAN_SEED = 2026
SCAN_PAPER = 243.0        # paper tone (gray level) of the scan
SCAN_INK = 35.0           # toner as the scanner sees it
SCAN_NOISE = 1.2          # sensor noise (gray levels, before JPEG)
SCAN_SKEW_DEG = (0.35, -0.25)
SCAN_JPEG_QUALITY = 85


def scan_page_image(page: pymupdf.Page, dpi: int, rng: np.random.Generator, skew_deg: float) -> np.ndarray:
    """A synthetic scan of one page: gray render at ``dpi``, slight skew, optics blur, paper
    tone with slow variation, sensor noise. Returns a uint8 array."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    h, w = img.shape
    rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), skew_deg, 1.0)
    img = cv2.warpAffine(img, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    tone = cv2.resize(rng.standard_normal((6, 4)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    paper = SCAN_PAPER + 1.5 * tone
    img = SCAN_INK + (paper - SCAN_INK) * (img / 255.0)
    img += rng.normal(0.0, SCAN_NOISE, img.shape).astype(np.float32)
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


def scanned_sample(src_pdf: bytes, *, dpi: int = SCAN_DPI, seed: int = SCAN_SEED, scan_pages: set[int] | None = None,
                   ocr_layer: bool = False) -> bytes:
    """A fictional scanned version of a sample PDF (deterministic for the same inputs).

    Pages in ``scan_pages`` (all if None) become one gray JPEG image filling the page, like a
    300 dpi office scan; the others are copied as text pages (a mixed document). With
    ``ocr_layer`` every scanned page also gets the source words as invisible text (render
    mode 3), as OCR software writes it. The source footer "CONTOH SINTETIS - BUKAN DOKUMEN
    ASLI" is part of every page image.
    """
    from tapak.marker.layout import extract_layout

    src = pymupdf.open(stream=src_pdf, filetype="pdf")
    layout = extract_layout(src_pdf) if ocr_layer else None
    out = pymupdf.open()
    for i, page in enumerate(src):
        if scan_pages is not None and i not in scan_pages:
            out.insert_pdf(src, from_page=i, to_page=i)
            continue
        rng = np.random.default_rng([seed, i, dpi])
        img = scan_page_image(page, dpi, rng, SCAN_SKEW_DEG[i % len(SCAN_SKEW_DEG)])
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, SCAN_JPEG_QUALITY])
        if not ok:
            raise RuntimeError("pengodean JPEG gagal")
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=jpg.tobytes(), keep_proportion=False)
        if layout is not None:
            for row in layout.pages[i].rows:
                for word in row.words:
                    g = word.glyphs[0]
                    new.insert_text((g.x, g.y), word.text, fontsize=g.size, fontname="helv", render_mode=3)
    out.set_metadata({"producer": "TAPAK samplegen", "creator": "TAPAK samplegen",
                      "title": "Contoh sintetis hasil pindai"})
    data = out.tobytes(garbage=3, deflate=True, no_new_id=True)
    out.close()
    src.close()
    return data


SCANNED_VARIANTS = {  # file name -> (scanned pages or None for all, OCR layer)
    "nota_dinas_pindaian.pdf": (None, False),
    "nota_dinas_pindaian_ocr.pdf": (None, True),
    "nota_dinas_campuran.pdf": ({1}, False),
}


def write_scanned_samples(src: Path, out_dir: Path) -> list[Path]:
    """Write the scanned variants of ``src`` (see SCANNED_VARIANTS) into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = Path(src).read_bytes()
    written = []
    for name, (pages, ocr) in SCANNED_VARIANTS.items():
        path = out_dir / name
        path.write_bytes(scanned_sample(data, scan_pages=pages, ocr_layer=ocr))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    """Generate every template in samples/templates into samples/ (PDF) plus recipients.csv;
    with ``--pindaian``, the fictional scanned variants of nota_dinas.pdf instead."""
    import argparse

    ap = argparse.ArgumentParser(description="Buat dokumen contoh sintetis")
    ap.add_argument("--templates", default="samples/templates")
    ap.add_argument("--out", default="samples")
    ap.add_argument("--recipients", type=int, default=20)
    ap.add_argument("--pindaian", action="store_true",
                    help="buat versi hasil pindai (300 dpi) dari nota_dinas.pdf di <out>/generated/")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.pindaian:
        for path in write_scanned_samples(out / "nota_dinas.pdf", out / "generated"):
            print(f"ditulis: {path} ({path.stat().st_size / 1e6:.1f} MB)")
        return 0
    for tpl in sorted(Path(args.templates).glob("*.json")):
        pdf = render_template(load_template(tpl))
        (out / f"{tpl.stem}.pdf").write_bytes(pdf)
        print(f"ditulis: {out / (tpl.stem + '.pdf')}")
    write_recipients(out / "recipients.csv", args.recipients)
    print(f"ditulis: {out / 'recipients.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
