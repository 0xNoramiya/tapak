"""Tesseract-assisted line alignment (fallback registration).

When the page outline is not visible and feature matching fails (heavy blur, partial
crop), the decoder reads words with Tesseract, matches them to the master words of a page
by text, and fits a homography from matched word centres with RANSAC. The result is only
an initial estimate; ECC refinement in ``rectify.py`` does the precise alignment.

Tesseract reads the image from stdin and writes its TSV to stdout, so neither the image nor
the recognized words are written to disk (the call is the one pytesseract makes, without its
temporary files). The words live in memory for the matching only.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess

import cv2
import numpy as np

OCR_TIMEOUT_S = 120


def tesseract_available() -> bool:
    """True if the tesseract binary is installed."""
    return shutil.which("tesseract") is not None


def tesseract_tsv(img8: np.ndarray, lang: str | None) -> str | None:
    """Tesseract's TSV for an 8-bit grayscale image, or None when Tesseract fails.

    Same engine settings as ``pytesseract.image_to_data`` (default engine and page
    segmentation, ``tessedit_create_tsv``, no stated resolution), so the same image gives the
    same words; one thread. The image goes in through stdin and the TSV comes back through
    stdout: no temporary files.
    """
    ok, png = cv2.imencode(".png", np.ascontiguousarray(img8, dtype=np.uint8))
    if not ok:
        return None
    cmd = [shutil.which("tesseract") or "tesseract", "stdin", "stdout"]
    if lang:
        cmd += ["-l", lang]
    cmd += ["-c", "tessedit_create_tsv=1"]
    try:
        run = subprocess.run(cmd, input=png.tobytes(), capture_output=True, timeout=OCR_TIMEOUT_S,
                             env=dict(os.environ, OMP_THREAD_LIMIT="1"))
    except (OSError, subprocess.SubprocessError):
        return None
    if run.returncode != 0:
        return None
    return run.stdout.decode("utf-8", errors="replace")


def parse_words(tsv: str) -> list[tuple[str, float, float, float]]:
    """(text, centre x, centre y, height) of the TSV words with at least 3 characters and a
    confidence of at least 60 (truncated to an integer, as pytesseract reports it)."""
    out = []
    for row in tsv.strip().split("\n")[1:]:
        cells = row.split("\t")
        if len(cells) == 11:  # the last word of the page may come without its (empty) text cell
            cells.append("")
        if len(cells) < 12:
            continue
        try:
            x, y, w, h, conf = (int(float(c)) for c in cells[6:11])
        except ValueError:
            continue
        t = cells[11].strip()
        if len(t) >= 3 and conf >= 60:
            out.append((t, x + w / 2.0, y + h / 2.0, float(h)))
    return out


def ocr_words(image: np.ndarray, lang: str = "ind+eng") -> list[tuple[str, float, float, float]]:
    """(text, centre x, centre y, height) for every word Tesseract recognizes confidently.

    Without the language data ``lang`` Tesseract's default language is used; without
    Tesseract, or when it fails, no words.
    """
    if not tesseract_available():
        return []
    img8 = np.clip(image, 0, 255).astype(np.uint8)
    tsv = tesseract_tsv(img8, lang)
    if tsv is None:
        tsv = tesseract_tsv(img8, None)
    return parse_words(tsv) if tsv is not None else []


def tesseract_homography(image: np.ndarray, pdf_bytes: bytes, page: int, dpi: float,
                         words: list[tuple[str, float, float, float]] | None = None) -> np.ndarray | None:
    """Page-to-image homography from OCR word matches, or None. ``words``, when given, is
    ``ocr_words(image)`` read beforehand (once for every page of a registration)."""
    from tapak.marker.layout import extract_layout

    words = ocr_words(image) if words is None else words
    if len(words) < 8:
        return None
    layout = extract_layout(pdf_bytes)
    master = [w for r in layout.pages[page].rows for w in r.words]
    s = dpi / 72.0
    sm = difflib.SequenceMatcher(None, [w.text.lower() for w in master], [t.lower() for t, *_ in words],
                                 autojunk=False)
    src, dst = [], []
    for b in sm.get_matching_blocks():
        for k in range(b.size):
            mw = master[b.a + k]
            x0, y0, x1, y1 = mw.bbox
            src.append(((x0 + x1) / 2.0 * s, (y0 + y1) / 2.0 * s))
            dst.append(words[b.b + k][1:3])
    if len(src) < 8:
        return None
    h, inliers = cv2.findHomography(np.float32(src), np.float32(dst), cv2.RANSAC, 6.0)
    if h is None or inliers is None or inliers.sum() < 6:
        return None
    return h


def identify_page_by_text(image: np.ndarray, page_texts: list[str]) -> int | None:
    """Index of the master page whose text best matches the OCR text, or None."""
    words = ocr_words(image)
    if not words:
        return None
    ocr = " ".join(t for t, *_ in words).lower()
    scores = [difflib.SequenceMatcher(None, ocr, t.lower(), autojunk=False).ratio() for t in page_texts]
    best = int(np.argmax(scores))
    return best if scores[best] > 0.3 else None
