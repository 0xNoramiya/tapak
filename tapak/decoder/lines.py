"""Tesseract-assisted line alignment (fallback registration).

When the page outline is not visible and feature matching fails (heavy blur, partial
crop), the decoder reads words with Tesseract, matches them to the master words of a page
by text, and fits a homography from matched word centres with RANSAC. The result is only
an initial estimate; ECC refinement in ``rectify.py`` does the precise alignment.
"""

from __future__ import annotations

import difflib
import shutil

import cv2
import numpy as np


def tesseract_available() -> bool:
    """True if the tesseract binary is installed."""
    return shutil.which("tesseract") is not None


def ocr_words(image: np.ndarray, lang: str = "ind+eng") -> list[tuple[str, float, float, float]]:
    """(text, centre x, centre y, height) for every word Tesseract recognizes confidently."""
    if not tesseract_available():
        return []
    import pytesseract

    img8 = np.clip(image, 0, 255).astype(np.uint8)
    try:
        data = pytesseract.image_to_data(img8, lang=lang, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(img8, output_type=pytesseract.Output.DICT)
    out = []
    for text, conf, x, y, w, h in zip(data["text"], data["conf"], data["left"], data["top"],
                                      data["width"], data["height"]):
        t = (text or "").strip()
        if len(t) >= 3 and float(conf) >= 60:
            out.append((t, x + w / 2.0, y + h / 2.0, float(h)))
    return out


def tesseract_homography(image: np.ndarray, pdf_bytes: bytes, page: int, dpi: float) -> np.ndarray | None:
    """Page-to-image homography from OCR word matches, or None."""
    from tapak.marker.layout import extract_layout

    words = ocr_words(image)
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
