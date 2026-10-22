"""Scanned pages ("halaman pindaian"): marks in the pixel domain of the page image.

A scanned page has no text layer to redraw, so its marks are computed from the page image
itself, with the same plan, code positions, keys and channel code as a text page:

* detection (:func:`detect_scans`): a page is a scan when its only visible content is one
  image covering almost the whole page; text on it is absent or invisible (render mode 3, an
  OCR layer). Every other page stays on the text path, so mixed documents are handled page by
  page;
* word boxes (:func:`scan_boxes`): one deterministic Tesseract run (language ``ind``, LSTM
  engine, one thread) on the master page image gives word and line boxes. They become the
  rows, words and shift groups of that page in ``MasterDocument.shift_layout``, so the shift
  channel plans, embeds, measures and decodes exactly as on a text page. Only a SHA-256 of the
  box list (:func:`boxes_digest`) and the Tesseract version are recorded; boxes and words never
  leave the process;
* marks (:func:`mark_scan_image`): the ink of a data group moves by the channel's offset (0.05
  mm by default) with sub-pixel cubic resampling, blended in through a feathered mask around
  the ink only. The paper texture around a word is not resampled, so no seam or halo appears,
  and pixels the ink leaves take the neighbouring paper of the master. Data rows move
  vertically the same way. The keyed background pattern is added to paper pixels only
  (:func:`tapak.marker.background.paper_threshold`), at the page image resolution;
* copies (:func:`write_scan_pages`): the marked image replaces the master image object as
  lossless Flate, with the same size and placement. Any invisible OCR text of the master is
  removed with all other text, because it would carry the master's words unmarked;
* gates: an unmarked copy must decode to exactly the master page image (:func:`scan_gate`),
  and every marked page may differ from the master only around the moved ink and, on paper, by
  the pattern amplitude (:func:`check_scan_change`).

The minimum resolution is MIN_SCAN_DPI (200 dpi): see :func:`require_markable`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zlib
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pymupdf

from tapak.marker.background import BackgroundSettings, PageGrid, paper_threshold
from tapak.marker.layout import DocumentLayout, Glyph, GroupId, PageLayout, Row, RowId, Word, make_groups

if TYPE_CHECKING:
    from tapak.marker.master import MasterDocument

SCAN_MIN_COVER = 0.85      # the page image covers at least this share of the page
SCAN_MAX_OTHER = 0.05      # other images and vector drawings together cover at most this share
# Minimum scan resolution, a margin rather than a sharp limit: see require_markable.
MIN_SCAN_DPI = 200.0
OCR_LANG = "ind"
OCR_ARGS = ("--oem", "1", "--psm", "3")
OCR_MIN_CONF = 30.0        # weaker detections are mostly specks, rules and stamps
OCR_TIMEOUT_S = 300
PATCH_PAD_PX = 5           # margin around a word box that the moved patch may touch
INK_DILATE_PX = 2          # the blend mask reaches this far beyond the ink
FEATHER_SIGMA_PX = 1.0     # softness of the blend mask edge
FLATE_LEVEL = 6
PLACEHOLDER = "#"          # stands for a recognized character: the word text is never kept

# Page box list: page -> rows -> words (left, top, width, height, characters), image pixels.
WordBox = tuple[int, int, int, int, int]
ScanBoxes = dict[int, list[list[WordBox]]]


@dataclass(frozen=True)
class ScanPage:
    """A scanned page: its image object and where the image sits on the page.

    Attributes:
        page: page index.
        xref: PDF object number of the page image.
        width_px, height_px: image size in pixels.
        rect: image placement on the page (points, top-left origin).
        ocr_layer: the page carries invisible text (an OCR layer), which copies drop.
        problem: why this page cannot be marked (rotated or masked image, ...), or None.
    """

    page: int
    xref: int
    width_px: int
    height_px: int
    rect: tuple[float, float, float, float]
    ocr_layer: bool = False
    problem: str | None = None

    @property
    def scale(self) -> tuple[float, float]:
        """Image pixels per point along x and y."""
        x0, y0, x1, y1 = self.rect
        return self.width_px / (x1 - x0), self.height_px / (y1 - y0)

    @property
    def dpi(self) -> float:
        """Effective scan resolution (the lower of both axes)."""
        kx, ky = self.scale
        return 72.0 * min(kx, ky)


# --- detection ---------------------------------------------------------------------------


def _text_chars(page: pymupdf.Page) -> tuple[int, int]:
    """(visible, invisible) non-space characters drawn on the page."""
    visible = hidden = 0
    for span in page.get_texttrace():
        n = sum(1 for ch in span["chars"] if ch[0] > 32 and not chr(ch[0]).isspace())
        if span["type"] == 3 or span.get("opacity", 1.0) == 0:
            hidden += n
        else:
            visible += n
    return visible, hidden


def _cover(rect: Any, page: pymupdf.Page) -> float:
    """Share of the page covered by ``rect`` (clipped to the page). Image and drawing boxes are
    in unrotated page coordinates, so the page is taken unrotated too."""
    full = pymupdf.Rect(0, 0, page.cropbox.width, page.cropbox.height)
    r = pymupdf.Rect(rect) & full
    area = full.width * full.height
    return 0.0 if r.is_empty or area <= 0 else (r.width * r.height) / area


def _scan_page(page: pymupdf.Page) -> ScanPage | None:
    visible, hidden = _text_chars(page)
    if visible:
        return None
    infos = page.get_image_info(xrefs=True)
    big = [i for i in infos if _cover(i["bbox"], page) >= SCAN_MIN_COVER]
    if len(big) != 1:
        return None
    img = big[0]
    other = sum(_cover(i["bbox"], page) for i in infos if i is not img)
    other += sum(_cover(d["rect"], page) for d in page.get_drawings())
    if other > SCAN_MAX_OTHER:
        return None
    a, b, c, d, _, _ = img["transform"]
    problem = None
    if page.rotation or abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
        problem = "gambar halaman pindaian diputar atau dibalik; halaman seperti ini belum didukung"
    elif img.get("has-mask"):
        problem = "gambar halaman pindaian memiliki masker transparansi; halaman seperti ini belum didukung"
    elif int(img.get("xref") or 0) <= 0:
        problem = "gambar halaman pindaian tersisip langsung di isi halaman; halaman seperti ini belum didukung"
    x0, y0, x1, y1 = (float(v) for v in img["bbox"])
    return ScanPage(page.number, int(img.get("xref") or 0), int(img["width"]), int(img["height"]),
                    (x0, y0, x1, y1), hidden > 0, problem)


def detect_scans(doc: pymupdf.Document) -> dict[int, ScanPage]:
    """Scanned pages of a document by page index (pages on the text path are left out)."""
    scans: dict[int, ScanPage] = {}
    for page in doc:
        info = _scan_page(page)
        if info is not None:
            scans[page.number] = info
    shared = Counter(s.xref for s in scans.values())
    for k, s in scans.items():
        if s.problem is None and shared[s.xref] > 1:
            scans[k] = replace(s, problem="gambar yang sama dipakai di beberapa halaman; halaman seperti ini "
                                          "belum didukung")
    return scans


def page_modes(master: "MasterDocument") -> list[str]:
    """Mode of every page: "pindaian" for a scanned page, "teks" otherwise."""
    return ["pindaian" if i in master.scans else "teks" for i in range(len(master.layout.pages))]


def require_markable(master: "MasterDocument") -> None:
    """Refuse (ValueError, Indonesian) a scanned page that cannot carry the marks.

    The minimum is MIN_SCAN_DPI (200 dpi), a margin rather than a sharp limit. The word shift
    is 0.05 mm: 0.59 px at 300 dpi, 0.39 px at 200 dpi, 0.30 px at 150 dpi. Measured on the
    synthetic 11.5 pt sample (research/pindaian), 150 dpi still decodes, but the shift bit error
    on photos grows as the resolution drops (2.0 % at 300 dpi, 3.0 % at 200, 3.4 % at 150).
    Tesseract is made for about 300 dpi, and at 150 dpi the lowercase letters of 8 pt text are
    only about 9 px tall, so its word boxes depend more on noise and on the Tesseract version;
    boxes that change between issuance and trace cost the whole shift channel of the page.
    """
    for k, s in sorted(master.scans.items()):
        if s.problem:
            raise ValueError(f"halaman {k + 1}: {s.problem}")
        if s.dpi < MIN_SCAN_DPI - 0.5:
            raise ValueError(
                f"halaman {k + 1} hasil pindaian beresolusi {s.dpi:.0f} dpi; TAPAK memerlukan minimal "
                f"{MIN_SCAN_DPI:.0f} dpi agar geser kata 0,05 mm dan kotak kata Tesseract cukup andal untuk dibaca "
                "kembali. Pindai ulang dokumen pada 300 dpi.")


# --- page image --------------------------------------------------------------------------


def decode_scan_image(doc: pymupdf.Document, scan: ScanPage) -> np.ndarray:
    """Samples of the page image: uint8 (H, W) gray or (H, W, 3) RGB (other color spaces are
    converted to RGB; the scan gate then checks that nothing visible changed)."""
    pix = pymupdf.Pixmap(doc, scan.xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.colorspace is None:
        raise ValueError(f"halaman {scan.page + 1}: gambar halaman pindaian tidak memiliki ruang warna")
    if pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return (arr[:, :, 0] if pix.n == 1 else arr).copy()


def scan_image(master: "MasterDocument", page: int) -> np.ndarray:
    """The master page image of a scanned page (decoded once per process and kept)."""
    img = master.scan_images.get(page)
    if img is None:
        with pymupdf.open(stream=master.pdf_bytes, filetype="pdf") as doc:
            img = decode_scan_image(doc, master.scans[page])
        master.scan_images[page] = img
    return img


def to_gray(img: np.ndarray) -> np.ndarray:
    """Gray version of a page image (unchanged if already gray; float input stays float)."""
    if img.ndim == 2:
        return img
    return cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_RGB2GRAY)


# --- word boxes (Tesseract) --------------------------------------------------------------


class OcrUnavailable(RuntimeError):
    """Tesseract (with the Indonesian language data) is not installed."""


@lru_cache(maxsize=1)
def ocr_engine() -> str:
    """Tesseract version and a digest of its language data, as recorded at issuance."""
    exe = shutil.which("tesseract")
    if exe is None:
        raise OcrUnavailable("Tesseract tidak terpasang; halaman pindaian memerlukan tesseract-ocr dan "
                             "tesseract-ocr-ind")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    first = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    version = first[0].strip() if first else "tesseract"
    langs = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=60)
    text = (langs.stdout or "") + (langs.stderr or "")
    if OCR_LANG not in text.split():
        raise OcrUnavailable(f"data bahasa Tesseract '{OCR_LANG}' tidak terpasang (paket tesseract-ocr-ind)")
    found = re.search(r'"([^"]+)"', text)
    digest = ""
    if found:
        data = Path(found.group(1)) / f"{OCR_LANG}.traineddata"
        if data.is_file():
            digest = " sha256:" + hashlib.sha256(data.read_bytes()).hexdigest()[:16]
    return f"{version}; {OCR_LANG}.traineddata{digest}"


_OCR_CACHE: "OrderedDict[str, list[tuple[int, int, int, int, int, int, int, int]]]" = OrderedDict()
_OCR_CACHE_SIZE = 16


def ocr_words(gray: np.ndarray, dpi: float) -> list[tuple[int, int, int, int, int, int, int, int]]:
    """Words Tesseract finds on a page image: (block, paragraph, line, left, top, width, height,
    characters), pixel coordinates.

    One fixed call (language ``ind``, LSTM engine, automatic page segmentation, one thread,
    stated resolution) so the same image always gives the same boxes on the same Tesseract.
    Words weaker than OCR_MIN_CONF or without a letter or digit are dropped. The recognized
    text is used only for its length and is not kept. Results are cached in memory by image
    digest.
    """
    engine = ocr_engine()
    img8 = np.ascontiguousarray(gray, dtype=np.uint8)
    key = hashlib.sha256(img8.tobytes() + repr((img8.shape, int(round(dpi)), engine)).encode()).hexdigest()
    hit = _OCR_CACHE.get(key)
    if hit is not None:
        _OCR_CACHE.move_to_end(key)
        return list(hit)
    ok, png = cv2.imencode(".png", img8, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise RuntimeError("pengodean gambar untuk Tesseract gagal")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    cmd = [shutil.which("tesseract") or "tesseract", "stdin", "stdout", "-l", OCR_LANG, *OCR_ARGS,
           "--dpi", str(int(round(dpi))), "tsv"]
    run = subprocess.run(cmd, input=png.tobytes(), capture_output=True, env=env, timeout=OCR_TIMEOUT_S)
    if run.returncode != 0:
        raise RuntimeError("Tesseract gagal membaca halaman pindaian")
    words = parse_tsv(run.stdout.decode("utf-8", errors="replace"))
    _OCR_CACHE[key] = words
    while len(_OCR_CACHE) > _OCR_CACHE_SIZE:
        _OCR_CACHE.popitem(last=False)
    return list(words)


def parse_tsv(text: str) -> list[tuple[int, int, int, int, int, int, int, int]]:
    """Word rows (level 5) of Tesseract TSV output, filtered as in :func:`ocr_words`."""
    lines = text.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    col = {name: i for i, name in enumerate(header)}
    need = ("level", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text")
    if any(n not in col for n in need):
        return []
    out = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < len(header) or parts[col["level"]] != "5":
            continue
        word = parts[col["text"]].strip()
        try:
            conf = float(parts[col["conf"]])
            b, p, ln, left, top, w, h = (int(parts[col[n]]) for n in need[1:8])
        except ValueError:
            continue
        if conf < OCR_MIN_CONF or w < 2 or h < 4 or not any(ch.isalnum() for ch in word):
            continue
        out.append((b, p, ln, left, top, w, h, len(word)))
    return out


def group_rows(words: list[tuple[int, int, int, int, int, int, int, int]]) -> list[list[WordBox]]:
    """Rows of word boxes, top to bottom, each left to right.

    Words come grouped in Tesseract lines. Words much taller or shorter than the page's median
    word (logos, signatures, specks) are left out. Lines at the same height that do not overlap
    horizontally (a label and its value in different Tesseract blocks) are merged into one
    row, as the text layout does with glyphs on one baseline. Overlapping boxes keep the first.
    """
    if not words:
        return []
    med = float(np.median([w[6] for w in words]))
    kept = [w for w in words if 0.3 * med <= w[6] <= 3.0 * med]
    lines: dict[tuple[int, int, int], list[WordBox]] = {}
    for b, p, ln, left, top, w, h, n in kept:
        lines.setdefault((b, p, ln), []).append((left, top, w, h, max(1, n)))
    entries = []
    for boxes in lines.values():
        cy = float(np.median([t + h / 2.0 for _, t, _, h, _ in boxes]))
        entries.append((cy, min(b[0] for b in boxes), boxes))
    entries.sort(key=lambda e: (e[0], e[1]))
    rows: list[tuple[float, list[WordBox]]] = []
    for cy, _, boxes in entries:
        if rows and abs(cy - rows[-1][0]) < 0.5 * med and not _overlaps_x(rows[-1][1], boxes):
            rows[-1][1].extend(boxes)
        else:
            rows.append((cy, list(boxes)))
    out = []
    for _, boxes in rows:
        boxes.sort(key=lambda b: (b[0], b[1]))
        clean: list[WordBox] = []
        for box in boxes:
            if clean and box[0] < clean[-1][0] + clean[-1][2] - 0.5 * min(box[2], clean[-1][2]):
                continue  # overlaps its left neighbour by more than half: a duplicate detection
            clean.append(box)
        out.append(clean)
    return out


def _overlaps_x(a: list[WordBox], b: list[WordBox]) -> bool:
    a0, a1 = min(w[0] for w in a), max(w[0] + w[2] for w in a)
    b0, b1 = min(w[0] for w in b), max(w[0] + w[2] for w in b)
    return a0 < b1 and b0 < a1


def scan_boxes(master: "MasterDocument") -> ScanBoxes:
    """Word boxes of every scanned page (Tesseract on the master page image)."""
    out: ScanBoxes = {}
    for k, s in sorted(master.scans.items()):
        out[k] = group_rows(ocr_words(to_gray(scan_image(master, k)), s.dpi))
    return out


def boxes_digest(master: "MasterDocument", boxes: ScanBoxes) -> str:
    """SHA-256 of the box list and the image sizes (what the plan depends on)."""
    payload = {"v": 1, "pages": [[k, master.scans[k].width_px, master.scans[k].height_px,
                                  [[list(w) for w in row] for row in boxes[k]]] for k in sorted(boxes)]}
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def scan_page_layout(text_page: PageLayout, scan: ScanPage, rows_px: list[list[WordBox]]) -> PageLayout:
    """The shift layout of a scanned page: rows, words and groups from the word boxes, in
    page points. Each word gets one placeholder glyph per recognized character (the count only
    decides which rows are long enough), its box split evenly; the word text is not kept."""
    kx, ky = scan.scale
    rx0, ry0 = scan.rect[0], scan.rect[1]
    rows = []
    for r_idx, row_px in enumerate(rows_px):
        words = []
        for w_idx, (left, top, w, h, n) in enumerate(row_px):
            x0, x1 = rx0 + left / kx, rx0 + (left + w) / kx
            y0, y1 = ry0 + top / ky, ry0 + (top + h) / ky
            adv = (x1 - x0) / n
            glyphs = [Glyph(PLACEHOLDER, x0 + k * adv, y1, adv, y1 - y0, "", 0, (x0 + k * adv, y0, x0 + (k + 1) * adv, y1))
                      for k in range(n)]
            words.append(Word((scan.page, r_idx, w_idx), glyphs))
        row = Row(scan.page, r_idx, float(np.median([w.glyphs[0].y for w in words])), words)
        row.groups = make_groups(row)
        rows.append(row)
    return PageLayout(text_page.index, text_page.width, text_page.height, rows)


def attach_scan_layout(master: "MasterDocument", boxes: ScanBoxes) -> None:
    """Give the scanned pages in ``boxes`` their rows in ``master.shift_layout``."""
    pages = [scan_page_layout(p, master.scans[p.index], boxes[p.index]) if p.index in boxes else p
             for p in master.layout.pages]
    master.scan_layout = DocumentLayout(master.layout.doc_hash, pages, master.layout.fonts)


def scan_record(master: "MasterDocument", boxes: ScanBoxes) -> dict[str, object]:
    """What the manifest and the registry keep about the scanned pages: page numbers,
    resolution, which pages had an OCR layer, the OCR engine and the digest of the word boxes.
    No box, word or image."""
    pages = sorted(master.scans)
    return {"pages": pages, "dpi": [int(round(master.scans[k].dpi)) for k in pages],
            "ocr_layer_dropped": [k for k in pages if master.scans[k].ocr_layer],
            "ocr_engine": ocr_engine(), "boxes_sha256": boxes_digest(master, boxes)}


def prepare_scans(master: "MasterDocument") -> tuple[dict[str, object] | None, ScanBoxes | None]:
    """Check, read and attach the scanned pages of a master before issuance.

    Refuses (ValueError, Indonesian) a page that cannot be marked, finds the word boxes with
    Tesseract (OcrUnavailable without it) and attaches them. Returns (:func:`scan_record`, the
    boxes for the worker processes); (None, None) for a document without scanned pages, for
    which nothing changes.
    """
    if not master.scans:
        return None, None
    require_markable(master)
    boxes = scan_boxes(master)
    attach_scan_layout(master, boxes)
    return scan_record(master, boxes), boxes


# --- marks -------------------------------------------------------------------------------


def pattern_field(grid: PageGrid, level: np.ndarray, scan: ScanPage, shape: tuple[int, int]) -> np.ndarray:
    """The background pattern at the page image resolution, in units of the amplitude.

    Cell values are interpolated linearly between cell centres, replicated up to the grid
    edge (as ``background.pattern_image`` and the text page do) and zero outside the grid.
    """
    h, w = shape
    kx, ky = scan.scale
    ox, oy = grid.offset_pt
    cell = grid.cell_pt
    xs = scan.rect[0] + (np.arange(w) + 0.5) / kx
    ys = scan.rect[1] + (np.arange(h) + 0.5) / ky
    lv = np.asarray(level, dtype=np.float32)

    def axis(coord: np.ndarray, origin: float, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        c = np.clip((coord - origin) / cell - 0.5, 0.0, n - 1.0)
        i0 = np.minimum(np.floor(c).astype(np.int64), max(n - 2, 0))
        i1 = np.minimum(i0 + 1, n - 1)
        f = (c - i0).astype(np.float32)
        inside = (coord >= origin) & (coord < origin + n * cell)
        return i0, i1, f, inside

    x0, x1, fx, in_x = axis(xs, ox, grid.nx)
    y0, y1, fy, in_y = axis(ys, oy, grid.ny)
    lx = lv[:, x0] * (1.0 - fx) + lv[:, x1] * fx
    field = lx[y0] * (1.0 - fy)[:, None] + lx[y1] * fy[:, None]
    field[~in_y] = 0.0
    field[:, ~in_x] = 0.0
    return field


def _box_px(bbox: tuple[float, float, float, float], scan: ScanPage, shape: tuple[int, int],
            pad: int) -> tuple[int, int, int, int]:
    kx, ky = scan.scale
    h, w = shape
    x0 = int(np.floor((bbox[0] - scan.rect[0]) * kx)) - pad
    y0 = int(np.floor((bbox[1] - scan.rect[1]) * ky)) - pad
    x1 = int(np.ceil((bbox[2] - scan.rect[0]) * kx)) + pad
    y1 = int(np.ceil((bbox[3] - scan.rect[1]) * ky)) + pad
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


_DILATE = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * INK_DILATE_PX + 1, 2 * INK_DILATE_PX + 1))


def _move_patch(src: np.ndarray, gray: np.ndarray, out: np.ndarray, moved: np.ndarray,
                box: tuple[int, int, int, int], dx: float, dy: float, threshold: float) -> None:
    """Move the ink inside ``box`` by (dx, dy) pixels into ``out``; mark the blended pixels."""
    x0, y0, x1, y1 = box
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    m = PATCH_PAD_PX
    h, w = gray.shape
    sx0, sy0, sx1, sy1 = max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m)
    region = src[sy0:sy1, sx0:sx1]
    warp = np.float32([[1, 0, dx], [0, 1, dy]])
    size = (sx1 - sx0, sy1 - sy0)
    shifted = cv2.warpAffine(region, warp, size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    sl = (slice(y0 - sy0, y1 - sy0), slice(x0 - sx0, x1 - sx0))
    patch = shifted[sl]
    ink = (gray[y0:y1, x0:x1] < threshold) | (to_gray(patch) < threshold)
    if not ink.any():
        return
    mask = cv2.dilate(ink.astype(np.uint8), _DILATE).astype(np.float32)
    mask = cv2.GaussianBlur(mask, (0, 0), FEATHER_SIGMA_PX)
    mask[0, :] = mask[-1, :] = 0.0
    mask[:, 0] = mask[:, -1] = 0.0
    np.clip(mask, 0.0, 1.0, out=mask)
    weight = mask if out.ndim == 2 else mask[:, :, None]
    target = out[y0:y1, x0:x1]
    target += weight * (patch - target)
    moved[y0:y1, x0:x1] |= mask > 0


def mark_scan_image(img: np.ndarray, scan: ScanPage, rows: list[Row], group_dx: dict[GroupId, float],
                    row_dy: dict[RowId, float], pattern: tuple[PageGrid, np.ndarray] | None,
                    settings: BackgroundSettings | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(marked image, mask of pixels moved with the ink) of one scanned page.

    ``rows`` are the page's rows in the shift layout; ``group_dx`` and ``row_dy`` the copy's
    offsets in points, as for text pages; ``pattern`` the page grid and its cell levels (from
    ``background.cell_levels``) or None. Without offsets and pattern the image is returned
    unchanged, pixel for pixel. Paper pixels (at or above ``paper_threshold``) with the pattern
    become min(v, base) + amplitude * level, so the pattern never clips at white. The pattern
    settings are the grid's own (those of the issuance) unless ``settings`` is given.
    """
    settings = settings or (pattern[0].settings if pattern is not None else BackgroundSettings())
    gray = to_gray(img)
    threshold = paper_threshold(gray)
    src = img.astype(np.float32)
    out = src.copy()
    moved = np.zeros(gray.shape, dtype=bool)
    kx, ky = scan.scale
    for row in rows:
        dy = row_dy.get(row.id, 0.0) * ky
        for g in row.groups:
            dx = group_dx.get(g.id, 0.0) * kx
            if dx == 0.0 and dy == 0.0:
                continue
            _move_patch(src, gray, out, moved, _box_px(g.bbox, scan, gray.shape, PATCH_PAD_PX), dx, dy, threshold)
    if pattern is not None:
        grid, level = pattern
        field = settings.amplitude * pattern_field(grid, level, scan, gray.shape)
        paper = to_gray(out) >= threshold
        if out.ndim == 3:
            paper, field = paper[:, :, None], field[:, :, None]
        out = np.where(paper, np.minimum(out, settings.base) + field, out)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8), moved


def change_bounds(settings: BackgroundSettings | None = None) -> tuple[int, int]:
    """(lowest, highest) change of a paper pixel away from moved ink: the pattern amplitude
    around min(v, base)."""
    s = settings or BackgroundSettings()
    return -int(np.ceil(255.0 - s.base + s.amplitude)), int(np.ceil(s.amplitude))


def check_scan_change(master_img: np.ndarray, marked: np.ndarray, moved: np.ndarray,
                      settings: BackgroundSettings | None = None) -> int:
    """Largest absolute change outside the moved ink; RuntimeError if a pixel there changed
    beyond the pattern bounds (:func:`change_bounds`) or an ink pixel changed at all."""
    if master_img.shape != marked.shape:
        raise RuntimeError("ukuran gambar halaman pindaian berubah")
    diff = marked.astype(np.int16) - master_img.astype(np.int16)
    gray = to_gray(master_img)
    outside = ~moved
    # One gray level of margin: the marker decides on exact (float) luminance, this on uint8.
    ink = outside & (gray < paper_threshold(gray) - 1.0)
    if diff.ndim == 3:
        outside, ink = outside[:, :, None], ink[:, :, None]
        outside = np.broadcast_to(outside, diff.shape)
        ink = np.broadcast_to(ink, diff.shape)
    lo, hi = change_bounds(settings)
    d_out = diff[outside]
    if d_out.size and (int(d_out.min()) < lo or int(d_out.max()) > hi):
        raise RuntimeError("salinan halaman pindaian berubah di luar batas kanal (pola latar terlalu kuat)")
    if np.any(diff[ink] != 0):
        raise RuntimeError("salinan halaman pindaian mengubah tinta di luar kata yang digeser")
    return int(np.abs(d_out).max(initial=0))


# --- copies ------------------------------------------------------------------------------


def write_scan_image(doc: pymupdf.Document, scan: ScanPage, img: np.ndarray) -> None:
    """Replace the page image object with ``img`` as lossless Flate (8-bit gray or RGB); its
    size and placement on the page stay the same."""
    h, w = img.shape[:2]
    cs = "/DeviceGray" if img.ndim == 2 else "/DeviceRGB"
    data = zlib.compress(np.ascontiguousarray(img).tobytes(), FLATE_LEVEL)
    doc.update_object(scan.xref, f"<</Type/XObject/Subtype/Image/Width {w}/Height {h}/ColorSpace {cs}"
                                 "/BitsPerComponent 8>>")
    doc.update_stream(scan.xref, data, compress=False)
    doc.xref_set_key(scan.xref, "Filter", "/FlateDecode")


def write_scan_pages(doc: pymupdf.Document, master: "MasterDocument", group_dx: dict[GroupId, float],
                     row_dy: dict[RowId, float], patterns: dict[int, tuple[PageGrid, np.ndarray]]) -> dict[int, int]:
    """Write the marked image of every scanned page into the copy ``doc``.

    Returns, per page, the largest change outside the moved ink (checked against the channel
    bounds by :func:`check_scan_change`; a violation raises and no copy is written).
    """
    layout = master.shift_layout
    out = {}
    for k, scan in sorted(master.scans.items()):
        img = scan_image(master, k)
        pattern = patterns.get(k)
        settings = pattern[0].settings if pattern is not None else None
        marked, moved = mark_scan_image(img, scan, layout.pages[k].rows, group_dx, row_dy, pattern, settings)
        out[k] = check_scan_change(img, marked, moved, settings)
        write_scan_image(doc, scan, marked)
    return out


def scan_gate(master: "MasterDocument", copy_pdf: bytes) -> bool:
    """True when every scanned page of an unmarked copy holds exactly the master page image
    (same samples, same size, same placement)."""
    with pymupdf.open(stream=copy_pdf, filetype="pdf") as doc:
        if len(doc) != len(master.layout.pages):
            return False
        for k, scan in master.scans.items():
            found = _scan_page(doc[k])  # saving renumbers objects: find the image again
            if (found is None or found.problem or found.ocr_layer
                    or (found.width_px, found.height_px) != (scan.width_px, scan.height_px)
                    or any(abs(a - b) > 1e-3 for a, b in zip(found.rect, scan.rect))):
                return False
            if not np.array_equal(decode_scan_image(doc, found), scan_image(master, k)):
                return False
    return True


def ocr_text_in(pdf_bytes: bytes, pages: list[int]) -> int:
    """Number of text characters (visible or not) on the given pages of a PDF."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return sum(sum(_text_chars(doc[k])) for k in pages if k < len(doc))


def plan_lines(record: dict[str, object] | None, n_pages: int) -> list[str]:
    """Indonesian lines for the issuance plan: page modes and what scanned pages carry."""
    if not record:
        return [f"Mode halaman: {n_pages} halaman teks"]
    pages = [int(p) for p in record["pages"]]  # type: ignore[union-attr]
    dpi = sorted({int(d) for d in record["dpi"]})  # type: ignore[union-attr]
    dpi_text = " dan ".join(str(d) for d in dpi)
    nums = ", ".join(str(p + 1) for p in pages)
    lines = [f"Mode halaman: {n_pages - len(pages)} halaman teks, {len(pages)} halaman pindaian "
             f"(halaman {nums}; {dpi_text} dpi)",
             "Halaman pindaian membawa kanal geser (kotak kata dari Tesseract, ditanam pada piksel gambar) dan pola "
             "latar; karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di sana",
             f"Kotak kata: {record['ocr_engine']}; hanya hash daftar kotaknya yang dicatat "
             f"({str(record['boxes_sha256'])[:16]}...)"]
    dropped = [int(p) for p in record.get("ocr_layer_dropped") or []]  # type: ignore[union-attr]
    if dropped:
        lines.append("Lapisan teks OCR tak terlihat di halaman " + ", ".join(str(p + 1) for p in dropped)
                     + " tidak disalin ke salinan, karena berisi kata dokumen induk tanpa tanda")
    return lines
