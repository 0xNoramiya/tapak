"""Find the page in a photo or screenshot and map it onto the master page.

1. Detect the page outline (OpenCV contours) and compute an initial perspective transform.
   If no outline is found (screenshot, cropped photo), fall back to SIFT feature matching
   against the master render, then to Tesseract word matching (``lines.py``).
2. Refine with ECC (enhanced correlation coefficient) image alignment, coarse to fine,
   against the master page rendered at the analysis resolution. Text strokes give ECC
   sub-pixel accuracy, which the shift and background decoders need.
3. Pick the master page with the highest correlation and resample the evidence image into
   that page's coordinate frame ("rectified" image).

Homographies here map *page pixel coordinates* at the analysis dpi to *image coordinates*.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import pymupdf

DPI_MIN = 100
DPI_MAX = 300


MAX_PIXELS = 60_000_000  # a 60 megapixel photo is far beyond any phone camera output


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG or JPEG header without decoding; None for other formats."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + length
    return None


def load_gray(data: bytes) -> np.ndarray:
    """Decode an image file (JPEG, PNG, ...) to a float32 grayscale array.

    Images whose header declares more than MAX_PIXELS are refused before decoding, so a small
    file cannot make the decoder allocate gigabytes: PNG and JPEG here, every other format by
    OpenCV's own pixel limit (OPENCV_IO_MAX_IMAGE_PIXELS, set in tapak/__init__.py).
    """
    size = image_size(data)
    if size is not None and size[0] * size[1] > MAX_PIXELS:
        raise ValueError(f"gambar terlalu besar ({size[0]}x{size[1]} piksel); maksimum 60 megapiksel")
    arr = np.frombuffer(data, dtype=np.uint8)
    try:
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    except cv2.error as exc:  # OPENCV_IO_MAX_IMAGE_PIXELS (set in tapak/__init__.py) refused it
        raise ValueError("gambar terlalu besar (maksimum 60 megapiksel) atau rusak") from exc
    if img is None:
        raise ValueError("berkas gambar tidak dapat dibaca")
    if img.shape[0] * img.shape[1] > MAX_PIXELS:
        raise ValueError("gambar terlalu besar; maksimum 60 megapiksel")
    return img.astype(np.float32)


def render_page(pdf_bytes: bytes, page: int, dpi: float, supersample: int = 4, cache: bool = True) -> np.ndarray:
    """Render a page at ``dpi`` by supersampling and area-averaging.

    Plain low-resolution rendering snaps glyphs to the pixel grid (up to half a pixel),
    which is larger than the marks being measured; supersampling removes that bias.
    Masters are cached (rendered again for every trace); pass ``cache=False`` for evidence, so
    renders of uploaded files never stay in memory after the request.
    """
    if not cache:
        return _render(pdf_bytes, page, float(dpi), supersample)
    return _render_cached(pdf_bytes, page, float(dpi), supersample).copy()


def _render(pdf_bytes: bytes, page: int, dpi: float, supersample: int) -> np.ndarray:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        p = doc[page]
        w = int(round(p.rect.width * dpi / 72.0))
        h = int(round(p.rect.height * dpi / 72.0))
        mat = pymupdf.Matrix(dpi * supersample / 72.0, dpi * supersample / 72.0)
        pix = p.get_pixmap(matrix=mat, colorspace=pymupdf.csGRAY, alpha=False)
        hi = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    return cv2.resize(hi, (w, h), interpolation=cv2.INTER_AREA)


_render_cached = lru_cache(maxsize=16)(_render)


# MuPDF caches small glyphs as bitmaps and draws a cached glyph at a whole device pixel
# vertically (a quarter pixel horizontally). Even with 4x supersampling (400 to 1200 dpi for
# the analysis resolutions) every text row of ``render_page`` lands up to half a supersampled
# pixel (10 to 30 um) off its true position, differently per row and word, and the same for
# every copy and photo. Glyphs larger than about 256 px per em are drawn as outlines without
# snapping; at 3200 dpi a 7 pt glyph is 311 px per em.
EXACT_MIN_DPI = 3200.0
EXACT_BAND_PT = 40.0  # band height: about 50 MB per band at 3300 dpi


def render_page_exact(pdf_bytes: bytes, page: int, dpi: float, min_dpi: float = EXACT_MIN_DPI,
                      cache: bool = True) -> np.ndarray:
    """Render a page at ``dpi`` without glyph snapping: draw it at an integer multiple of ``dpi``
    of at least ``min_dpi``, in horizontal bands, and average each block of k x k pixels.

    Output pixel (row, col) covers exactly the page points [col, col + 1) x [row, row + 1)
    times 72 / dpi, the frame in which the decoders read positions. Cached per page and dpi
    like ``render_page`` (the analysis dpi varies per photo); ``cache=False`` renders afresh.
    """
    if not cache:
        return _render_exact(pdf_bytes, page, float(dpi), float(min_dpi))
    return _render_exact_cached(pdf_bytes, page, float(dpi), float(min_dpi)).copy()


def _render_exact(pdf_bytes: bytes, page: int, dpi: float, min_dpi: float) -> np.ndarray:
    k = max(1, int(np.ceil(min_dpi / dpi - 1e-9)))
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        p = doc[page]
        w = int(round(p.rect.width * dpi / 72.0))
        h = int(round(p.rect.height * dpi / 72.0))
        mat = pymupdf.Matrix(dpi * k / 72.0, dpi * k / 72.0)
        out = np.empty((h, w), dtype=np.float32)
        band = max(1, int(EXACT_BAND_PT * dpi / 72.0))
        content = p.get_displaylist()  # interpreted once, rasterized per band
        for y0 in range(0, h, band):
            y1 = min(h, y0 + band)
            # Device rows y0*k .. y1*k (and columns 0 .. w*k) of the full-page raster; the clip
            # is widened by a quarter row so rounding never drops a row, and the pixmap origin
            # says where its first row and column lie.
            clip = pymupdf.Rect(p.rect.x0, p.rect.y0 + (y0 - 0.25) * 72.0 / dpi, p.rect.x1,
                                p.rect.y0 + (y1 + 0.25) * 72.0 / dpi)
            pix = content.get_pixmap(matrix=mat, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
            hi = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            buf = np.full(((y1 - y0) * k, w * k), 255, dtype=np.uint8)  # paper beyond the raster
            ox = int(round(p.rect.x0 * dpi * k / 72.0))
            oy = int(round(p.rect.y0 * dpi * k / 72.0))
            r0, c0 = y0 * k - (pix.y - oy), -(pix.x - ox)
            rs, re_ = max(r0, 0), min(r0 + buf.shape[0], hi.shape[0])
            cs, ce = max(c0, 0), min(c0 + buf.shape[1], hi.shape[1])
            if re_ > rs and ce > cs:
                buf[rs - r0:re_ - r0, cs - c0:ce - c0] = hi[rs:re_, cs:ce]
            sums = buf.reshape(y1 - y0, k, w, k).sum(axis=(1, 3), dtype=np.uint32)
            out[y0:y1] = sums.astype(np.float32) / np.float32(k * k)
    return out


# An exact master page at 300 dpi is 35 MB; the analysis dpi takes at most 21 values.
_render_exact_cached = lru_cache(maxsize=8)(_render_exact)


def flatten_illumination(gray: np.ndarray, sigma: float) -> np.ndarray:
    """Divide out slow illumination changes (shadows, vignetting); paper becomes about 1.0."""
    k = int(max(3, round(sigma / 4)) | 1)
    paper = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    paper = cv2.GaussianBlur(paper, (0, 0), sigma)
    return gray / np.maximum(paper, 1.0)


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def detect_page_quad(gray: np.ndarray) -> np.ndarray | None:
    """Corners (TL, TR, BR, BL) of the brightest large quadrilateral, or None."""
    h, w = gray.shape
    scale = 1000.0 / max(h, w)
    small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA).astype(np.uint8)
    small = cv2.GaussianBlur(small, (5, 5), 0)
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = max(contours, key=cv2.contourArea)
    area_frac = cv2.contourArea(best) / float(small.shape[0] * small.shape[1])
    if area_frac < 0.15 or area_frac > 0.985:
        return None  # nothing page-like, or the page fills the frame (no outline visible)
    peri = cv2.arcLength(best, True)
    quad = None
    for eps in (0.01, 0.02, 0.03, 0.05):
        approx = cv2.approxPolyDP(best, eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            quad = approx.reshape(4, 2)
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(best))
    return order_corners(quad / scale)


def page_corners(width_px: float, height_px: float) -> np.ndarray:
    """Page corners in page pixel coordinates (TL, TR, BR, BL)."""
    return np.array([[0, 0], [width_px - 1, 0], [width_px - 1, height_px - 1], [0, height_px - 1]], dtype=np.float64)


def effective_dpi(h_page_to_img: np.ndarray, page_w_px: float, page_h_px: float, dpi: float) -> float:
    """Image resolution at the page centre, in dots per inch of the page."""
    cx, cy = page_w_px / 2.0, page_h_px / 2.0
    pts = np.array([[[cx, cy]], [[cx + 1, cy]], [[cx, cy + 1]]], dtype=np.float64)
    q = cv2.perspectiveTransform(pts, h_page_to_img).reshape(3, 2)
    jac = np.array([q[1] - q[0], q[2] - q[0]])
    return float(dpi * np.sqrt(abs(np.linalg.det(jac))))


def _scale_h(h: np.ndarray, s_page: float, s_img: float) -> np.ndarray:
    """Homography for page coordinates scaled by s_page and image coordinates by s_img."""
    return np.diag([s_img, s_img, 1.0]) @ h @ np.diag([1 / s_page, 1 / s_page, 1.0])


def _prep(img: np.ndarray) -> np.ndarray:
    """ECC input: illumination-flattened, inverted (ink positive), lightly blurred."""
    flat = flatten_illumination(img, sigma=max(img.shape) / 30.0)
    ink = np.clip(1.0 - flat, 0.0, 1.0).astype(np.float32)
    return cv2.GaussianBlur(ink, (0, 0), 1.0)


def ecc_refine(template: np.ndarray, image: np.ndarray, h_init: np.ndarray,
               levels: tuple[tuple[float, int], ...] = ((0.25, 60), (0.5, 40), (1.0, 15))) -> tuple[np.ndarray, float]:
    """Refine a page-to-image homography with ECC, coarse to fine. Returns (H, correlation).

    ``levels`` lists (scale, maximum iterations); the finest level starts close to the
    answer, so few iterations suffice there.
    """
    h = h_init.astype(np.float64)
    cc = -1.0
    t_full, i_full = _prep(template), _prep(image)
    for lv, iters in levels:
        # The analysis dpi is chosen close to the image resolution, so both are scaled alike.
        t = cv2.resize(t_full, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else t_full
        i = cv2.resize(i_full, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else i_full
        warp = _scale_h(h, lv, lv).astype(np.float32)
        warp /= warp[2, 2]
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-6)
        try:
            cc, warp = cv2.findTransformECC(t, i, warp, cv2.MOTION_HOMOGRAPHY, criteria, None, 3)
        except cv2.error:
            return h, -1.0
        h = _scale_h(warp.astype(np.float64), 1 / lv, 1 / lv)
        h /= h[2, 2]
    return h, float(cc)


def quick_score(image_ink: np.ndarray, h_page_to_img: np.ndarray, template_ink: np.ndarray,
                dpi_template: float, dpi_h: float) -> float:
    """Correlation of the evidence warped by H with a low-resolution master render (ink images)."""
    s = dpi_template / dpi_h
    h = h_page_to_img @ np.diag([1 / s, 1 / s, 1.0])
    size = (template_ink.shape[1], template_ink.shape[0])
    warped = cv2.warpPerspective(image_ink, h, size, flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP)
    a = warped - warped.mean()
    b = template_ink - template_ink.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 0 else -1.0


def feature_homography(template: np.ndarray, image: np.ndarray) -> np.ndarray | None:
    """Page-to-image homography from SIFT features + RANSAC, or None."""
    det = cv2.SIFT_create(nfeatures=4000)
    t8 = np.clip(template, 0, 255).astype(np.uint8)
    scale = min(1.0, 1600.0 / max(image.shape))
    i8 = cv2.resize(np.clip(image, 0, 255).astype(np.uint8), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    k1, d1 = det.detectAndCompute(t8, None)
    k2, d2 = det.detectAndCompute(i8, None)
    if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
        return None
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.8 * n.distance]
    if len(good) < 25:
        return None
    src = np.float32([k1[m.queryIdx].pt for m in good])
    dst = np.float32([k2[m.trainIdx].pt for m in good]) / scale
    h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if h is None or inliers is None or inliers.sum() < 20:
        return None
    return h


@dataclass
class Registration:
    """Result of mapping the evidence image onto one master page."""

    page: int
    dpi: float
    h_page_to_img: np.ndarray
    correlation: float
    method: str
    rectified: np.ndarray
    valid: np.ndarray
    effective_dpi: float


def warp_to_page(image: np.ndarray, h_page_to_img: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Resample the image into page coordinates; also return the mask of valid pixels."""
    flags = cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP
    rect = cv2.warpPerspective(image, h_page_to_img, size, flags=flags, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones_like(image, dtype=np.uint8), h_page_to_img, size,
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
    return rect, valid.astype(bool)


def register(image: np.ndarray, pdf_bytes: bytes, page_sizes: list[tuple[float, float]],
             min_correlation: float = 0.75) -> Registration | None:
    """Find the best-matching master page and the precise page-to-image transform.

    Candidate (page, initial transform) pairs are scored cheaply at 30 dpi; only the best is
    refined with full ECC. Initial transforms come from the page outline, then SIFT
    features, then Tesseract word matching, each tried only if the previous gave nothing
    convincing.
    """
    probe_dpi, score_dpi = 100.0, 30.0
    img_ink = _prep(image)
    lo = [(_prep(render_page(pdf_bytes, p, score_dpi))) for p in range(len(page_sizes))]

    def corners_h(page: int, quad: np.ndarray) -> np.ndarray:
        w_pt, h_pt = page_sizes[page]
        src = page_corners(w_pt * probe_dpi / 72.0, h_pt * probe_dpi / 72.0).astype(np.float32)
        return cv2.getPerspectiveTransform(src, quad.astype(np.float32)).astype(np.float64)

    cands: list[tuple[float, int, np.ndarray, str]] = []

    def add(page: int, h0: np.ndarray, method: str) -> None:
        cands.append((quick_score(img_ink, h0, lo[page], score_dpi, probe_dpi), page, h0, method))

    quad = detect_page_quad(image)
    if quad is not None:
        for page in range(len(page_sizes)):
            add(page, corners_h(page, quad), "kontur")
    if not cands or max(c[0] for c in cands) < 0.6:
        for page in range(len(page_sizes)):
            fh = feature_homography(render_page(pdf_bytes, page, probe_dpi), image)
            if fh is not None:
                add(page, fh, "fitur")
    if not cands or max(c[0] for c in cands) < 0.4:
        from tapak.decoder.lines import tesseract_homography

        for page in range(len(page_sizes)):
            th = tesseract_homography(image, pdf_bytes, page, probe_dpi)
            if th is not None:
                add(page, th, "tesseract")
    if not cands:
        return None
    cands.sort(key=lambda c: c[0], reverse=True)
    best: tuple[float, int, np.ndarray, str, float] | None = None
    for _, page, h0, method in cands[:2]:
        w_pt, h_pt = page_sizes[page]
        wp, hp = w_pt * probe_dpi / 72.0, h_pt * probe_dpi / 72.0
        dpi = float(np.clip(round(effective_dpi(h0, wp, hp, probe_dpi) / 10) * 10, DPI_MIN, DPI_MAX))
        s = dpi / probe_dpi
        h, cc = ecc_refine(render_page(pdf_bytes, page, dpi), image, h0 @ np.diag([1 / s, 1 / s, 1.0]))
        if best is None or cc > best[0]:
            best = (cc, page, h, method, dpi)
        if cc > 0.85:
            break
    assert best is not None
    cc, page, h, method, dpi = best
    if cc < min_correlation:
        return None
    w_pt, h_pt = page_sizes[page]
    size = (int(round(w_pt * dpi / 72.0)), int(round(h_pt * dpi / 72.0)))
    rect, valid = warp_to_page(image, h, size)
    return Registration(page=page, dpi=dpi, h_page_to_img=h, correlation=cc, method=method,
                        rectified=rect, valid=valid,
                        effective_dpi=effective_dpi(h, size[0], size[1], dpi))
