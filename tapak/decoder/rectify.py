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

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
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
# Byte budget of the exact-template cache. Entries keep only the rendered band parts (the text
# rows the shift decoder reads: 45 to 70 % of a sample page), so about 14 text pages at 300 dpi
# or 30 at 200 dpi stay cached; an 8-entry LRU missed every page of a 9-page scan traced again.
EXACT_CACHE_BYTES = 320_000_000

Box = tuple[int, int, int, int]


def render_page_exact(pdf_bytes: bytes, page: int, dpi: float, min_dpi: float = EXACT_MIN_DPI,
                      cache: bool = True, boxes: tuple[Box, ...] | None = None) -> np.ndarray:
    """Render a page at ``dpi`` without glyph snapping: draw it at an integer multiple of ``dpi``
    of at least ``min_dpi``, in horizontal bands, and average each block of k x k pixels.

    Output pixel (row, col) covers exactly the page points [col, col + 1) x [row, row + 1)
    times 72 / dpi, the frame in which the decoders read positions. ``boxes`` (output pixel
    rectangles (x0, y0, x1, y1), end exclusive) limits the work to the bands that meet a box,
    each clipped to the columns of its boxes: every pixel inside a box is exactly that of the
    whole-page render, and pixels that were not rendered are paper (255). The rendering is
    cached per document, page, dpi and boxes within ``EXACT_CACHE_BYTES`` (the analysis dpi
    varies per photo); ``cache=False`` renders afresh.
    """
    key = (pdf_bytes, page, float(dpi), float(min_dpi), boxes)
    entry = _EXACT_CACHE.get(key) if cache else None
    if entry is None:
        entry = _exact_blocks(pdf_bytes, page, float(dpi), float(min_dpi), boxes)
        if cache:
            _EXACT_CACHE.put(key, entry)
    (h, w), blocks = entry
    out = np.empty((h, w), dtype=np.float32) if boxes is None else np.full((h, w), 255.0, dtype=np.float32)
    for y0, x0, block in blocks:
        out[y0:y0 + block.shape[0], x0:x0 + block.shape[1]] = block
    return out


_Entry = tuple[tuple[int, int], list[tuple[int, int, np.ndarray]]]


def _band_columns(boxes: tuple[Box, ...] | None, y0: int, y1: int, w: int) -> list[tuple[int, int]]:
    """Merged column ranges of the boxes that meet output rows [y0, y1) (all columns without boxes)."""
    if boxes is None:
        return [(0, w)]
    spans = sorted((max(b[0], 0), min(b[2], w)) for b in boxes if b[1] < y1 and b[3] > y0 and b[2] > b[0])
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        elif b > a:
            merged.append((a, b))
    return merged


def _exact_blocks(pdf_bytes: bytes, page: int, dpi: float, min_dpi: float, boxes: tuple[Box, ...] | None) -> _Entry:
    """The page size at ``dpi`` and the exact render of each band (or band part), as
    (row, column, block).

    The bands always follow the whole-page grid (every ``EXACT_BAND_PT`` from the top) with the
    same vertical clip: MuPDF draws the rows near a vertical clip edge slightly differently (up
    to about one gray level after averaging), so only the grid used for every measurement
    reproduces it. Clipping columns changed no pixel away from the clip edge in our checks
    (tests/test_exact_template.py compares them), and the quarter-pixel widening keeps the
    edge itself out of the output.
    """
    k = max(1, int(np.ceil(min_dpi / dpi - 1e-9)))
    blocks: list[tuple[int, int, np.ndarray]] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        p = doc[page]
        w = int(round(p.rect.width * dpi / 72.0))
        h = int(round(p.rect.height * dpi / 72.0))
        mat = pymupdf.Matrix(dpi * k / 72.0, dpi * k / 72.0)
        band = max(1, int(EXACT_BAND_PT * dpi / 72.0))
        ox = int(round(p.rect.x0 * dpi * k / 72.0))
        oy = int(round(p.rect.y0 * dpi * k / 72.0))
        content = p.get_displaylist()  # interpreted once, rasterized per band
        for y0 in range(0, h, band):
            y1 = min(h, y0 + band)
            for x0, x1 in _band_columns(boxes, y0, y1, w):
                # Device rows y0*k .. y1*k and columns x0*k .. x1*k of the full-page raster;
                # the clip is widened by a quarter pixel so rounding never drops a row or
                # column, and the pixmap origin says where its first row and column lie.
                full_width = x0 == 0 and x1 == w
                clip = pymupdf.Rect(p.rect.x0 if full_width else p.rect.x0 + (x0 - 0.25) * 72.0 / dpi,
                                    p.rect.y0 + (y0 - 0.25) * 72.0 / dpi,
                                    p.rect.x1 if full_width else p.rect.x0 + (x1 + 0.25) * 72.0 / dpi,
                                    p.rect.y0 + (y1 + 0.25) * 72.0 / dpi)
                pix = content.get_pixmap(matrix=mat, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
                hi = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                rows, cols = (y1 - y0) * k, (x1 - x0) * k
                r0, c0 = y0 * k - (pix.y - oy), x0 * k - (pix.x - ox)
                if r0 >= 0 and c0 >= 0 and r0 + rows <= hi.shape[0] and c0 + cols <= hi.shape[1]:
                    buf = hi[r0:r0 + rows, c0:c0 + cols]  # a view: no copy of the raster
                else:  # the page raster ends inside the band: paper beyond it
                    buf = np.full((rows, cols), 255, dtype=np.uint8)
                    rs, re_ = max(r0, 0), min(r0 + rows, hi.shape[0])
                    cs, ce = max(c0, 0), min(c0 + cols, hi.shape[1])
                    if re_ > rs and ce > cs:
                        buf[rs - r0:re_ - r0, cs - c0:ce - c0] = hi[rs:re_, cs:ce]
                # Exact integer block sums (rows first: about three times faster than one
                # reduction over both axes, with the same result).
                sums = buf.reshape(y1 - y0, k, cols).sum(axis=1, dtype=np.uint32)
                sums = sums.reshape(y1 - y0, x1 - x0, k).sum(axis=2, dtype=np.uint32)
                blocks.append((y0, x0, sums.astype(np.float32) / np.float32(k * k)))
                del pix, hi, buf
    return (h, w), blocks


class _ByteBudgetCache:
    """Least recently used cache bounded by the total bytes of its entries (thread safe)."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.hits = self.misses = self.bytes = 0
        self._items: OrderedDict[tuple, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _size(entry: _Entry) -> int:
        return sum(b.nbytes for _, _, b in entry[1])

    def get(self, key: tuple) -> _Entry | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return entry

    def put(self, key: tuple, entry: _Entry) -> None:
        size = self._size(entry)
        if size > self.max_bytes:
            return
        with self._lock:
            if key in self._items:
                return
            self._items[key] = entry
            self.bytes += size
            while self.bytes > self.max_bytes:
                _, old = self._items.popitem(last=False)
                self.bytes -= self._size(old)

    def __len__(self) -> int:
        return len(self._items)


_EXACT_CACHE = _ByteBudgetCache(EXACT_CACHE_BYTES)


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


class _ArrayCache(_ByteBudgetCache):
    """``_ByteBudgetCache`` of plain arrays (or tuples of arrays), sized by their bytes."""

    @staticmethod
    def _size(entry) -> int:
        parts = entry if isinstance(entry, tuple) else (entry,)
        return sum(a.nbytes for a in parts if isinstance(a, np.ndarray))


# Master ink and master SIFT features are the same for every trace of a document; the
# illumination blur behind ``_prep`` (a Gaussian of a thirtieth of the page) is most of the
# cost of a registration that has to try every page, so each master page is prepared once.
MASTER_CACHE_BYTES = 200_000_000
_MASTER_CACHE = _ArrayCache(MASTER_CACHE_BYTES)


def master_ink(pdf_bytes: bytes, page: int, dpi: float) -> np.ndarray:
    """``_prep(render_page(pdf_bytes, page, dpi))``, cached and read only (the same values)."""
    key = ("ink", pdf_bytes, page, float(dpi))
    ink = _MASTER_CACHE.get(key)
    if ink is None:
        ink = _prep(_render_cached(pdf_bytes, page, float(dpi), 4))
        ink.setflags(write=False)
        _MASTER_CACHE.put(key, ink)
    return ink


def ecc_refine(template: np.ndarray, image: np.ndarray, h_init: np.ndarray,
               levels: tuple[tuple[float, int], ...] = ((0.25, 60), (0.5, 40), (1.0, 15)),
               mask: np.ndarray | None = None, affine: bool = False,
               template_ink: np.ndarray | None = None, image_ink: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """Refine a page-to-image homography with ECC, coarse to fine. Returns (H, correlation).

    ``levels`` lists (scale, maximum iterations); the finest level starts close to the
    answer, so few iterations suffice there. ``mask`` (the rescue stage, ``paper_mask``)
    restricts the correlation to image pixels that show the page, so viewer chrome cannot pull
    the pose; the correlation is then measured over those pixels only. ``affine`` (the rescue
    stage, for screen captures, which have no perspective) refines an affine map instead of a
    homography, so a page part with little text cannot tilt the pose. Without them (the
    default) nothing changes. ``template_ink`` and ``image_ink``, when given, are ``_prep`` of
    ``template`` and ``image`` computed beforehand (``master_ink``): the same result, without
    preparing the same images again for every page and pose.
    """
    h = h_init.astype(np.float64)
    cc = -1.0
    t_full = _prep(template) if template_ink is None else template_ink
    i_full = _prep(image) if image_ink is None else image_ink
    for lv, iters in levels:
        # The analysis dpi is chosen close to the image resolution, so both are scaled alike.
        t = cv2.resize(t_full, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else t_full
        i = cv2.resize(i_full, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else i_full
        m = None
        if mask is not None:
            m = mask if lv == 1.0 else cv2.resize(mask, (i.shape[1], i.shape[0]), interpolation=cv2.INTER_NEAREST)
        warp = _scale_h(h, lv, lv).astype(np.float32)
        warp /= warp[2, 2]
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-6)
        try:
            if affine:
                cc, w23 = cv2.findTransformECC(t, i, np.ascontiguousarray(warp[:2]), cv2.MOTION_AFFINE, criteria, m, 3)
                warp = np.vstack([w23, np.array([[0.0, 0.0, 1.0]], dtype=np.float32)])
            else:
                cc, warp = cv2.findTransformECC(t, i, warp, cv2.MOTION_HOMOGRAPHY, criteria, m, 3)
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


Features = tuple[np.ndarray, np.ndarray | None]  # SIFT keypoint positions (n, 2) and descriptors


def sift_features(img8: np.ndarray) -> Features:
    """SIFT keypoint positions (n, 2) and descriptors (at most 4000 features) of a uint8 image."""
    k, d = cv2.SIFT_create(nfeatures=4000).detectAndCompute(img8, None)
    return np.float32([p.pt for p in k]).reshape(-1, 2), d


def evidence_features(image: np.ndarray) -> tuple[Features, float]:
    """SIFT features of an evidence image as ``feature_homography`` reads it (long side at most
    1600 px), and that scale."""
    scale = min(1.0, 1600.0 / max(image.shape))
    i8 = cv2.resize(np.clip(image, 0, 255).astype(np.uint8), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return sift_features(i8), scale


def master_features(pdf_bytes: bytes, page: int, dpi: float) -> Features:
    """SIFT features of ``render_page(pdf_bytes, page, dpi)``, cached (read only)."""
    key = ("sift", pdf_bytes, page, float(dpi))
    feats = _MASTER_CACHE.get(key)
    if feats is None:
        feats = sift_features(np.clip(_render_cached(pdf_bytes, page, float(dpi), 4), 0, 255).astype(np.uint8))
        for a in feats:
            if a is not None:
                a.setflags(write=False)
        _MASTER_CACHE.put(key, feats)
    return feats


def feature_homography(template: np.ndarray, image: np.ndarray, template_features: Features | None = None,
                       image_features: tuple[Features, float] | None = None) -> np.ndarray | None:
    """Page-to-image homography from SIFT features + RANSAC, or None.

    ``template_features`` (``master_features``) and ``image_features`` (``evidence_features``),
    when given, are the features of ``template`` and ``image`` computed beforehand: the same
    result, without detecting the evidence's features again for every page."""
    p1, d1 = sift_features(np.clip(template, 0, 255).astype(np.uint8)) if template_features is None \
        else template_features
    (p2, d2), scale = evidence_features(image) if image_features is None else image_features
    if d1 is None or d2 is None or len(p1) < 20 or len(p2) < 20:
        return None
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.8 * n.distance]
    if len(good) < 25:
        return None
    src = np.float32([p1[m.queryIdx] for m in good])
    dst = np.float32([p2[m.trainIdx] for m in good]) / scale
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
    bend: Bend | None = None  # set when the page did not lie in the plane of ``h_page_to_img``


@dataclass(frozen=True)
class Bend:
    """Where the content of a page that does not lie in a plane sits, relative to the plane of
    its homography: page point p is found in the image at H(p + displacement(p)).

    Attributes:
        field: (rows, cols, 2) displacements (dx, dy) in page points on a lattice over the
            page; cell (i, j) is centred at ((j + 0.5) / cols, (i + 0.5) / rows) of the page.
        page_size: page width and height in points.
    """

    field: np.ndarray
    page_size: tuple[float, float]

    def __post_init__(self) -> None:
        f = np.asarray(self.field)
        if f.ndim != 3 or f.shape[2] != 2 or min(f.shape[:2]) < 2 or min(self.page_size) <= 0:
            raise ValueError("medan lengkung memerlukan kisi (baris, kolom, 2) dan ukuran halaman positif")

    def pixels(self, size: tuple[int, int]) -> np.ndarray:
        """(height, width, 2) displacements in pixels of a page frame of ``size`` (width, height)."""
        f = np.asarray(self.field, dtype=np.float32) * (size[0] / self.page_size[0])
        return np.dstack([cv2.resize(np.ascontiguousarray(f[..., k]), size, interpolation=cv2.INTER_CUBIC)
                          for k in range(2)])

    def largest_mm(self) -> float:
        """Largest displacement on the lattice, in millimetres."""
        return float(np.hypot(self.field[..., 0], self.field[..., 1]).max()) * 25.4 / 72.0


def _bend_maps(h_page_to_img: np.ndarray, size: tuple[int, int], shift_px: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Image coordinates of every pixel of a page frame of ``size`` whose content is displaced
    by ``shift_px`` (height, width, 2) from the plane of ``h_page_to_img``."""
    ys, xs = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
    px, py = xs + shift_px[..., 0], ys + shift_px[..., 1]
    h = np.asarray(h_page_to_img, dtype=np.float64)
    den = h[2, 0] * px + h[2, 1] * py + h[2, 2]
    return (((h[0, 0] * px + h[0, 1] * py + h[0, 2]) / den).astype(np.float32),
            ((h[1, 0] * px + h[1, 1] * py + h[1, 2]) / den).astype(np.float32))


def warp_to_page(image: np.ndarray, h_page_to_img: np.ndarray, size: tuple[int, int],
                 bend: Bend | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Resample the image into page coordinates; also return the mask of valid pixels. With
    ``bend`` (a page that does not lie in a plane) every page pixel is read where the bent page
    shows it."""
    if bend is not None:
        mx, my = _bend_maps(h_page_to_img, size, bend.pixels(size))
        rect = cv2.remap(image, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rect, (mx >= 0) & (my >= 0) & (mx <= image.shape[1] - 1) & (my <= image.shape[0] - 1)
    flags = cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP
    rect = cv2.warpPerspective(image, h_page_to_img, size, flags=flags, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones_like(image, dtype=np.uint8), h_page_to_img, size,
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
    return rect, valid.astype(bool)


# --- Pages that do not lie in a plane (real paper) ------------------------------------------------
# A printed sheet photographed on a table is curled, cockled or creased, and a phone lens bends
# straight lines, so one homography leaves parts of a real page a millimetre and more off the
# master. ECC then stays below ``min_correlation`` although the page was found: 12 of 13 phone
# photos of a printed sample page (two phones, 2026-11-12) against 0.92 and more for simulated
# photos, which are planar. ``estimate_bend`` measures what the plane fit left over, block by
# block and coarse to fine, and gives two fields from the same measurements. The fine one only
# answers "is this the master page?": the gate reads the correlation after it. The smooth one
# resamples the image for the decoders. It averages over BEND_SMOOTH_MM, more than a word group
# and several text rows, so it cannot follow (and so erase) the shift marks.
BEND_BELOW = 0.9          # a plane fit that correlates at least this well is kept as it is
# Levels: resolution (dpi, at most the analysis dpi), block side (mm), search range (mm). The
# search ranges add up to 5.6 mm: no content is ever looked for further from the plane fit.
BEND_LEVELS = ((60.0, 20.0, 3.5), (125.0, 13.0, 1.2), (300.0, 13.0, 0.5), (300.0, 6.5, 0.4))
BEND_MIN_BLOCK_PX = 32    # a block is at least this many pixels across ...
BEND_MIN_SEARCH_PX = 2    # ... and is searched at least this far
BEND_MIN_TEXT = 0.03      # blocks whose master ink varies less than this (blank paper) are not measured
BEND_MIN_PEAK = 0.45      # a block whose best correlation is below this says nothing
BEND_MIN_BLOCKS = 6       # a level with fewer measured blocks is skipped
BEND_OUTLIER = 1.0 / 3.0  # a block this share of the search range off its neighbours' median is dropped ...
BEND_OUTLIER_PX = 1.5     # ... when that is more than this many pixels
BEND_FINE_STEPS = 1.2     # Gaussian sigma of a level's measurements, in grid steps (half blocks)
BEND_SMOOTH_MM = 15.0     # Gaussian sigma of the field the decoders' image is resampled with
BEND_LATTICE_MM = 2.0     # spacing of the lattice the fields are kept on
BEND_GAIN = 0.02          # the bent page must correlate this much better than the plane fit


def parabolic_peak(c_m: float, c_0: float, c_p: float) -> float:
    """Sub-sample offset of a peak from three samples around it."""
    den = c_m - 2.0 * c_0 + c_p
    return 0.0 if den >= 0 else 0.5 * (c_m - c_p) / den


def _block_shifts(template: np.ndarray, warped: np.ndarray, block: int,
                  search: int) -> tuple[np.ndarray, np.ndarray]:
    """Where each block of ``template`` (half-overlapping, ``block`` px) is found in ``warped``
    within ``search`` px: shifts (ny, nx, 2) and weights (ny, nx), zero for blocks that say
    nothing (blank, weak or at the edge of the search range) or disagree with their neighbours."""
    hh, ww = template.shape
    step = block // 2
    ny, nx = max(1, (hh - block) // step + 1), max(1, (ww - block) // step + 1)
    d = np.zeros((ny, nx, 2), dtype=np.float32)
    wgt = np.zeros((ny, nx), dtype=np.float32)
    for r in range(ny):
        for c in range(nx):
            y0, x0 = r * step, c * step
            tb = template[y0:y0 + block, x0:x0 + block]
            if float(tb.std()) < BEND_MIN_TEXT:
                continue
            ys0, xs0 = max(0, y0 - search), max(0, x0 - search)
            res = cv2.matchTemplate(warped[ys0:min(hh, y0 + block + search), xs0:min(ww, x0 + block + search)],
                                    tb, cv2.TM_CCOEFF_NORMED)
            _, peak, _, (ix, iy) = cv2.minMaxLoc(res)
            if peak < BEND_MIN_PEAK or not (0 < ix < res.shape[1] - 1 and 0 < iy < res.shape[0] - 1):
                continue
            d[r, c] = (ix + parabolic_peak(res[iy, ix - 1], res[iy, ix], res[iy, ix + 1]) - (x0 - xs0),
                       iy + parabolic_peak(res[iy - 1, ix], res[iy, ix], res[iy + 1, ix]) - (y0 - ys0))
            wgt[r, c] = peak - BEND_MIN_PEAK + 0.05
    measured = wgt > 0
    limit = max(BEND_OUTLIER_PX, BEND_OUTLIER * search)
    for r, c in zip(*np.nonzero(measured)):
        near = (slice(max(0, r - 1), r + 2), slice(max(0, c - 1), c + 2))
        if measured[near].sum() >= 3 and float(np.abs(d[r, c] - np.median(d[near][measured[near]], axis=0)).max()) > limit:
            wgt[r, c] = 0.0
    return d, wgt


def _correlation(a: np.ndarray, b: np.ndarray, where: np.ndarray) -> float:
    """Correlation coefficient of two images over the pixels ``where``."""
    if int(where.sum()) < 2:
        return -1.0
    x, y = a[where] - a[where].mean(), b[where] - b[where].mean()
    den = float(np.sqrt((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / den) if den > 0 else -1.0


def estimate_bend(image_ink: np.ndarray, template_ink: np.ndarray, h_page_to_img: np.ndarray, dpi: float,
                  page_size: tuple[float, float], log: dict | None = None) -> tuple[Bend, Bend, float] | None:
    """What a plane fit left over on a page that does not lie in a plane.

    ``image_ink`` and ``template_ink`` are ``_prep`` of the evidence and of the master page at
    the analysis ``dpi``, ``h_page_to_img`` the plane fit (page pixels at ``dpi`` to image).
    Level by level (``BEND_LEVELS``) the evidence is resampled with the field so far, each block
    of the master is looked for around its place, and the blocks' shifts, smoothed and filled
    in where nothing was measured, are added to the field. Returns (fine, smooth, correlation):
    the field as measured, the same field averaged over ``BEND_SMOOTH_MM`` (what the decoders'
    image is resampled with, see above), and the correlation of the evidence resampled with the
    fine field with the master. None when no level could be measured. ``log``, when given,
    receives ``levels`` (per level its resolution and the measured share of its blocks).
    """
    hh, ww = template_ink.shape
    size = (ww, hh)
    mm = dpi / 25.4
    fw, fh = max(2, int(np.ceil(ww / (BEND_LATTICE_MM * mm)))), max(2, int(np.ceil(hh / (BEND_LATTICE_MM * mm))))
    field = np.zeros((fh, fw, 2), dtype=np.float32)  # page pixels at ``dpi``
    gx, gy = (np.arange(fw) + 0.5) * ww / fw, (np.arange(fh) + 0.5) * hh / fh
    notes: list[dict] = []
    for level_dpi, block_mm, search_mm in BEND_LEVELS:
        lv = min(1.0, level_dpi / dpi)
        block = max(BEND_MIN_BLOCK_PX, int(round(block_mm * mm * lv)))
        search = max(BEND_MIN_SEARCH_PX, int(round(search_mm * mm * lv)))
        t = cv2.resize(template_ink, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else template_ink
        i = cv2.resize(image_ink, None, fx=lv, fy=lv, interpolation=cv2.INTER_AREA) if lv != 1.0 else image_ink
        level_size = (t.shape[1], t.shape[0])
        shift = Bend(field * (72.0 / dpi), page_size).pixels(level_size) if field.any() else \
            np.zeros((level_size[1], level_size[0], 2), dtype=np.float32)
        mx, my = _bend_maps(_scale_h(h_page_to_img, lv, lv), level_size, shift)
        warped = cv2.remap(i, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        d, wgt = _block_shifts(t, warped, block, search)
        measured = int((wgt > 0).sum())
        notes.append({"dpi": dpi * lv, "block": block, "search": search, "measured": measured, "blocks": int(wgt.size)})
        if measured < BEND_MIN_BLOCKS:
            continue
        num = cv2.GaussianBlur(d * wgt[..., None], (0, 0), BEND_FINE_STEPS, borderType=cv2.BORDER_REPLICATE)
        den = cv2.GaussianBlur(wgt, (0, 0), BEND_FINE_STEPS, borderType=cv2.BORDER_REPLICATE)
        smooth = np.where(den[..., None] > 1e-4, num / np.maximum(den, 1e-6)[..., None], 0.0).astype(np.float32)
        step = block // 2
        ix = np.interp(gx, (np.arange(d.shape[1]) * step + block / 2.0) / lv, np.arange(d.shape[1])).astype(np.float32)
        iy = np.interp(gy, (np.arange(d.shape[0]) * step + block / 2.0) / lv, np.arange(d.shape[0])).astype(np.float32)
        field += cv2.remap(smooth / lv, *np.meshgrid(ix, iy), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if log is not None:
        log["levels"] = notes
    if not field.any():
        return None
    fine = Bend(field * (72.0 / dpi), page_size)
    sigma = BEND_SMOOTH_MM / BEND_LATTICE_MM
    smooth_field = cv2.GaussianBlur(field, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)
    mx, my = _bend_maps(h_page_to_img, size, fine.pixels(size))
    warped = cv2.remap(image_ink, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    inside = (mx >= 0) & (my >= 0) & (mx <= image_ink.shape[1] - 1) & (my <= image_ink.shape[0] - 1)
    return fine, Bend(smooth_field * (72.0 / dpi), page_size), _correlation(warped, template_ink, inside)


# --- Rescue stage (research/registrasi) ---------------------------------------------------------
# It runs only when the stages of ``register`` find no page (no initial pose, or ECC below
# ``min_correlation``). Every setting below was fixed on development seeds before the held-out run.
PAPER_DELTA = 6.0             # gray levels below the paper level that still count as paper
PAPER_MEDIAN = 3              # median filter (px) against JPEG noise before the paper threshold
PAPER_FLAT_SHARE = 0.10       # share of the image at the paper level a screen capture has (a photo has less)
PAPER_PROFILE = 0.05          # page rows and columns: paper share at least this times the largest
PAPER_MIN_CHROME = 0.03       # chrome must cover this share of the image, or the whole image is page
PAPER_CHROME_PAPER = 0.02     # largest paper share outside the page rectangle
TEMPLATE_DPI = (30.0, 45.0)   # coarse and fine resolution of the template search
TEMPLATE_MIN_PX = 12          # a scaled crop narrower than this (px) is not searched at that resolution
TEMPLATE_MIN_AREA = 600       # ... nor one with fewer pixels
TEMPLATE_EFF_DPI = (16.0, 400.0)  # evidence resolutions the coarse search covers
TEMPLATE_STEP = 1.05          # scale step of the coarse search
TEMPLATE_FINE = (-0.06, 0.06, 0.015)  # relative scales tried around a coarse peak
TEMPLATE_PAD = 0.10           # the master is padded by this share of its size on every side
RESCUE_PRIOR = 2              # earlier initial poses refined again (best quick score first)
RESCUE_TEMPLATE = 3           # template poses refined when their score is at least ...
RESCUE_TEMPLATE_SHARE = 0.7   # ... this share of the best one; and always ...
RESCUE_PAGES = 4              # ... the best template pose of this many best pages (rivals for the ambiguity test) ...
RESCUE_RIVAL_SCALE = 1.25     # ... whose resolution is within this factor of the best pose's (a confusion keeps the scale)
RESCUE_SAME_PX = 10.0         # initial poses this close (page px at 100 dpi, visible centre) are refined once
RESCUE_MIN_SIDE = 64          # an ECC level is used only when the page part is this many pixels across
RESCUE_LEVELS = ((0.25, 60), (0.5, 40), (1.0, 15))  # ECC levels (scale, iterations) the rescue may use
RESCUE_NATIVE_DPI = 100.0     # evidence below this resolution is refined at its own resolution
RESCUE_AFFINE = True          # screen captures are refined with an affine map (no perspective)
RESCUE_MIN_AGREEMENT = 0.65   # verification: correlation with the master at the found pose (pilih.py, on dev)
RESCUE_AMBIGUITY = 0.05       # a rival pose this close in agreement makes the registration ambiguous (pilih.py)
RESCUE_DISTINCT_PT = 14.0     # poses that put the visible centre this far apart (pt) are rivals
RESCUE_MIN_PIXELS = 400       # evidence pixels the verification needs
RESCUE_HP_PT = 16.0           # verification: each row's local mean along x (Gaussian, this many pt) is taken off
RESCUE_SCALE_CHANGE = 1.25    # ECC may change the initial pose's scale by at most this factor ...
RESCUE_SCALE_SPREAD = 1.6     # ... and leave local scales over the page part within this ratio (no blow-up)
RESCUE_FOOTPRINT = True       # a tilted initial pose is also refined against the master cut to its footprint ...
RESCUE_FOOTPRINT_MARGIN = 0.15  # ... enlarged by this share of its size on every side; tilted: rotated by more
RESCUE_TILT_DEG = 1.0         # than this, or foreshortened (local scales over the page part differing by more ...
RESCUE_TILT_SPREAD = 1.02     # ... than this ratio): the perspective of a photo, which an affine map cannot follow
RESCUE_FOOTPRINT_SPAN = 4.0   # a footprint pose whose page-centre resolution is this far off the initial pose's is not sane
RESCUE_MAX_BLUR = 16.0        # verification: master pixels per evidence pixel at the page centre, at most


def _paper_levels(image: np.ndarray) -> tuple[float, np.ndarray, float]:
    """(paper level, median-filtered image, share of the image within 2 levels of the paper)."""
    g = np.asarray(image, dtype=np.float32)
    paper = float(np.percentile(g, 99))
    smooth = cv2.medianBlur(np.clip(g, 0, 255).astype(np.uint8), PAPER_MEDIAN).astype(np.float32)
    return paper, smooth, float(np.mean(smooth >= paper - 2.0))


def is_screen_capture(image: np.ndarray) -> bool:
    """True when the image shows paper at one exact level, as a screen capture does: at least
    ``PAPER_FLAT_SHARE`` of it within 2 gray levels of its paper level (99th percentile, after a
    ``PAPER_MEDIAN`` median filter). A photo's paper follows the light and gives False, unless it
    is so overexposed that the paper clips to one level."""
    paper, _, flat = _paper_levels(image)
    return paper >= 128.0 and flat >= PAPER_FLAT_SHARE


def paper_mask(image: np.ndarray) -> np.ndarray | None:
    """The rectangle of a screen capture that shows the page (uint8, 1 on the page), or None.

    The paper is the brightest level of the image (its 99th percentile); after a
    ``PAPER_MEDIAN`` median filter against JPEG noise, pixels within ``PAPER_DELTA`` of it are
    paper. Only a screen capture (``is_screen_capture``) gets a rectangle; a photo, whose paper
    brightness follows the light, gets None. The page rows and columns are the longest runs whose
    paper share is at least ``PAPER_PROFILE`` times the largest (the margins and the gaps between
    words and lines keep a page row above that even where text is dense; toolbar, window
    background, page border and shadow are darker than paper in light and dark themes alike). The
    rectangle is kept only when the rest of the image, chrome, covers at least
    ``PAPER_MIN_CHROME`` of it and holds at most ``PAPER_CHROME_PAPER`` paper; otherwise the whole
    image is page (None).
    """
    h, w = image.shape
    paper, smooth, flat = _paper_levels(image)
    if paper < 128.0 or flat < PAPER_FLAT_SHARE:
        return None
    bright = smooth >= paper - PAPER_DELTA

    def run(frac: np.ndarray) -> tuple[int, int]:
        on = np.append(frac >= PAPER_PROFILE * float(frac.max()), False)
        best, start = (0, 0), None
        for i, v in enumerate(on):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start > best[1] - best[0]:
                    best = (start, i)
                start = None
        return best

    r0, r1 = run(bright.mean(axis=1))
    c0, c1 = run(bright.mean(axis=0))
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[r0:r1, c0:c1] = 1
    outside = mask == 0
    if int(outside.sum()) < PAPER_MIN_CHROME * h * w or float(bright[outside].mean()) > PAPER_CHROME_PAPER:
        return None
    return mask


def _resize_map(sx: float, sy: float) -> np.ndarray:
    """Coordinate map of ``cv2.resize`` by (sx, sy): x' = (x + 0.5) * sx - 0.5."""
    return np.array([[sx, 0.0, 0.5 * sx - 0.5], [0.0, sy, 0.5 * sy - 0.5], [0.0, 0.0, 1.0]])


def _match(master_ink: np.ndarray, crop: np.ndarray, f: float) -> tuple[float, tuple[int, int], float, float] | None:
    """Best normalized cross-correlation of ``crop`` scaled by ``f`` inside ``master_ink``:
    (score, top-left location, exact x scale, exact y scale), or None when the scaled crop is
    smaller than ``TEMPLATE_MIN_PX`` (or ``TEMPLATE_MIN_AREA``), larger than the master, or flat.
    Master windows without ink variation (blank paper, the padding) are not candidates: their
    normalized correlation is undefined."""
    ch, cw = crop.shape
    w, h = int(round(cw * f)), int(round(ch * f))
    if (min(w, h) < TEMPLATE_MIN_PX or w * h < TEMPLATE_MIN_AREA
            or w > master_ink.shape[1] or h > master_ink.shape[0]):
        return None
    small = cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA if f < 1.0 else cv2.INTER_LINEAR)
    if float(small.std()) < 1e-3:
        return None
    res = cv2.matchTemplate(master_ink, small, cv2.TM_CCOEFF_NORMED)
    s1 = cv2.integral(master_ink.astype(np.float64))
    s2 = cv2.integral(master_ink.astype(np.float64) ** 2)
    n = float(w * h)
    win1 = s1[h:, w:] - s1[:-h, w:] - s1[h:, :-w] + s1[:-h, :-w]
    win2 = s2[h:, w:] - s2[:-h, w:] - s2[h:, :-w] + s2[:-h, :-w]
    var = win2 / n - (win1 / n) ** 2
    res = np.where(var > 1e-4 * max(float(master_ink.var()), 1e-12), np.clip(res, -1.0, 1.0), -1.0)
    _, score, _, loc = cv2.minMaxLoc(res.astype(np.float32))
    return float(score), (int(loc[0]), int(loc[1])), w / cw, h / ch


def template_poses(ink: np.ndarray, mask: np.ndarray | None, pdf_bytes: bytes, n_pages: int,
                   probe_dpi: float = 100.0, per_page: int = 2) -> list[tuple[float, int, np.ndarray]]:
    """Initial page-to-image homographies (page pixels at ``probe_dpi``) from multi-scale template
    matching: the evidence ink (``_prep``; inside the bounding box of ``mask`` when given) is
    searched inside the ink of every master page by normalized cross-correlation over scale and
    offset, coarse to fine.

    The coarse search runs at ``TEMPLATE_DPI[0]`` over the evidence resolutions
    ``TEMPLATE_EFF_DPI`` in steps of ``TEMPLATE_STEP``; the ``per_page`` best scales of every page
    (more than 10 % apart) are searched again at ``TEMPLATE_DPI[1]`` over ``TEMPLATE_FINE``.
    Scale and offset only, as on a screen capture; the rotation and perspective of a photo are
    left to ECC. Returns (fine score, page, homography), best first. Uses the master only.
    """
    if mask is not None and mask.any():
        ys, xs = np.nonzero(mask)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    else:
        x0, y0, x1, y1 = 0, 0, ink.shape[1], ink.shape[0]
    crop = np.ascontiguousarray(ink[y0:y1, x0:x1], dtype=np.float32)
    d0, d1 = TEMPLATE_DPI
    out: list[tuple[float, int, np.ndarray]] = []
    for page in range(n_pages):
        masters = []
        for d in (d0, d1):
            m = master_ink(pdf_bytes, page, d)
            pad = int(round(TEMPLATE_PAD * max(m.shape)))
            masters.append((np.pad(m, pad).astype(np.float32), pad))
        (coarse, pad0), (fine, pad1) = masters
        peaks: list[tuple[float, float]] = []
        eff = TEMPLATE_EFF_DPI[1]
        while eff >= TEMPLATE_EFF_DPI[0]:
            r = _match(coarse, crop, d0 / eff)
            if r is not None:
                peaks.append((r[0], eff))
            eff /= TEMPLATE_STEP
        chosen: list[float] = []
        for score, e in sorted(peaks, reverse=True):
            if all(abs(np.log(e / c)) > np.log(1.1) for c in chosen):
                chosen.append(e)
            if len(chosen) >= per_page:
                break
        lo, hi, step = TEMPLATE_FINE
        for e in chosen:
            best = None
            for rel in np.arange(lo, hi + step / 2, step):
                r = _match(fine, crop, d1 / (e * (1.0 + rel)))
                if r is not None and (best is None or r[0] > best[0]):
                    best = r
            if best is None:
                continue
            score, (lx, ly), sx, sy = best
            # page px at probe -> page px at d1 -> padded master px -> scaled crop px -> crop px -> image px
            h = (np.array([[1.0, 0.0, x0], [0.0, 1.0, y0], [0.0, 0.0, 1.0]]) @ np.linalg.inv(_resize_map(sx, sy))
                 @ np.array([[1.0, 0.0, pad1 - lx], [0.0, 1.0, pad1 - ly], [0.0, 0.0, 1.0]])
                 @ _resize_map(d1 / probe_dpi, d1 / probe_dpi))
            out.append((score, page, h / h[2, 2]))
    out.sort(key=lambda c: c[0], reverse=True)
    return out


def pose_agreement(image_ink: np.ndarray, mask: np.ndarray | None, master_ink: np.ndarray,
                   h_page_to_img: np.ndarray, dpi: float) -> tuple[float, int]:
    """Verification of a pose: the correlation between the evidence ink and the master ink
    (``_prep``, master rendered at ``dpi``) warped onto the evidence at that pose, measured at
    the evidence's own resolution over the evidence pixels that show the page (inside ``mask``
    when given). The master is blurred down to the evidence's resolution first, so a correct
    pose of a 24 dpi capture agrees about as well as one of a 150 dpi capture. Both sides lose
    their local mean along image rows (a Gaussian of ``RESCUE_HP_PT`` points along x) before
    the correlation: lines of text that merely lie at the same heights (another document or
    paragraph set in the same font and margins) then agree little, words that line up agree
    fully. Returns (correlation, pixels measured); (-1, pixels) when fewer than
    ``RESCUE_MIN_PIXELS`` or either side is flat, and (-1, 0) when the pose puts the page centre
    at less than 1 / ``RESCUE_MAX_BLUR`` of the analysis resolution.
    """
    hh, ww = image_ink.shape
    eff = effective_dpi(h_page_to_img, master_ink.shape[1], master_ink.shape[0], dpi)
    k = dpi / max(eff, 1e-6)  # master pixels per evidence pixel
    if not np.isfinite(k) or k > RESCUE_MAX_BLUR:
        # a pose that puts the page centre at a tiny fraction of its own resolution (a homography
        # run off far from the page part) cannot be verified; its blur would not fit in memory
        return -1.0, 0
    t = cv2.GaussianBlur(master_ink, (0, 0), float(np.sqrt(k * k - 1.0))) if k > 1.05 else master_ink
    warped = cv2.warpPerspective(t, h_page_to_img, (ww, hh), flags=cv2.INTER_LINEAR, borderValue=0)
    inside = cv2.warpPerspective(np.ones(t.shape, dtype=np.uint8), h_page_to_img, (ww, hh),
                                 flags=cv2.INTER_NEAREST, borderValue=0).astype(bool)
    region = inside if mask is None else inside & mask.astype(bool)
    n = int(region.sum())
    if n < RESCUE_MIN_PIXELS:
        return -1.0, n
    sx = max(1.0, RESCUE_HP_PT * eff / 72.0)

    def rows_detrended(a: np.ndarray) -> np.ndarray:
        a = a.astype(np.float32)
        return a - cv2.GaussianBlur(a, (0, 0), sigmaX=sx, sigmaY=0.01)

    a = rows_detrended(warped)[region].astype(np.float64)
    b = rows_detrended(image_ink)[region].astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return (float((a * b).sum() / den) if den > 1e-12 else -1.0), n


def _invertible(h: np.ndarray) -> bool:
    """False for a singular (degenerate) homography, which numpy cannot invert."""
    try:
        np.linalg.inv(np.asarray(h, dtype=np.float64))
    except np.linalg.LinAlgError:
        return False
    return True


def local_scales(h_page_to_img: np.ndarray, points_img: np.ndarray, dpi: float) -> np.ndarray:
    """Image pixels per page point (square root of the local area scale) of a page-to-image map
    (page pixels at ``dpi``) at the page points that land on the given image points (n, 1, 2)."""
    h = np.asarray(h_page_to_img, dtype=np.float64)
    if not _invertible(h):  # a degenerate map has no local scale
        return np.full(len(points_img), np.nan)
    q = cv2.perspectiveTransform(np.asarray(points_img, dtype=np.float64), np.linalg.inv(h)).reshape(-1, 2)
    out = []
    for x, y in q:
        w = h[2, 0] * x + h[2, 1] * y + h[2, 2]
        if w <= 0:  # the image point lies beyond the map's horizon
            out.append(np.nan)
            continue
        u = (h[0, 0] * x + h[0, 1] * y + h[0, 2]) / w
        v = (h[1, 0] * x + h[1, 1] * y + h[1, 2]) / w
        jac = np.array([[h[0, 0] - h[2, 0] * u, h[0, 1] - h[2, 1] * u],
                        [h[1, 0] - h[2, 0] * v, h[1, 1] - h[2, 1] * v]]) / w
        out.append(np.sqrt(abs(np.linalg.det(jac))) * dpi / 72.0)
    return np.array(out)


def pose_is_sane(h_init: np.ndarray, dpi_init: float, h_found: np.ndarray, dpi_found: float,
                 points_img: np.ndarray) -> bool:
    """False when ECC blew a pose up: its median local scale over the page part (``local_scales``
    at the given image points) differs from the initial pose's by more than
    ``RESCUE_SCALE_CHANGE``, or its local scales spread wider than ``RESCUE_SCALE_SPREAD`` (more
    than the perspective of a photo). Either way the pose is not verified."""
    s0 = local_scales(h_init, points_img, dpi_init)
    s1 = local_scales(h_found, points_img, dpi_found)
    if not (np.all(np.isfinite(s1)) and np.all(s1 > 0) and np.all(np.isfinite(s0)) and np.all(s0 > 0)):
        return False
    change = float(np.median(s1) / np.median(s0))
    return 1.0 / RESCUE_SCALE_CHANGE <= change <= RESCUE_SCALE_CHANGE and float(s1.max() / s1.min()) <= RESCUE_SCALE_SPREAD


def rescue_threads(jobs: int) -> int:
    """Threads for the rescue tries: the available CPUs (at most 4, and at most
    ``TAPAK_WORKERS``), never more than the tries."""
    from tapak.config import pool_size

    return pool_size(jobs, min(4, jobs) if jobs else 1)


def _tilted(h_page_to_img: np.ndarray, points_img: np.ndarray, dpi: float) -> bool:
    """True when a pose looks like a photo taken at an angle over the page part (``points_img``,
    see ``_visible_box``): rotated by more than RESCUE_TILT_DEG, or foreshortened so that its
    local scales differ by more than RESCUE_TILT_SPREAD. A screen capture has neither, and a
    downscaled photo can look as flat as one (``is_screen_capture``)."""
    h = np.asarray(h_page_to_img, dtype=np.float64)
    if not _invertible(h):
        return False
    scales = local_scales(h, points_img, dpi)
    if not np.all(np.isfinite(scales)) or np.any(scales <= 0):
        return False
    q = cv2.perspectiveTransform(np.asarray(points_img[:1], dtype=np.float64), np.linalg.inv(h)).reshape(2)
    ends = np.array([[[q[0], q[1]]], [[q[0] + 10.0, q[1]]]])
    a, b = cv2.perspectiveTransform(ends, h).reshape(2, 2)
    angle = abs(np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])))
    return bool(min(angle, 180.0 - angle) > RESCUE_TILT_DEG or scales.max() / scales.min() > RESCUE_TILT_SPREAD)


def _footprint(h_page_to_img: np.ndarray, image_shape: tuple[int, int], template_shape: tuple[int, int],
               margin: float) -> tuple[int, int, int, int] | None:
    """Box (x0, y0, x1, y1) of master pixels that the image covers under a pose, enlarged by
    ``margin`` of its size on every side and clipped to the master; None when the pose cannot be
    inverted, sends the image corners behind the camera, or covers less than RESCUE_MIN_SIDE /
    4 pixels across."""
    if not _invertible(h_page_to_img):
        return None
    hh, ww = image_shape
    corners = np.array([[[0.0, 0.0]], [[ww - 1.0, 0.0]], [[ww - 1.0, hh - 1.0]], [[0.0, hh - 1.0]]])
    inv = np.linalg.inv(np.asarray(h_page_to_img, dtype=np.float64))
    hom = np.c_[corners.reshape(4, 2), np.ones(4)] @ inv.T
    if np.any(hom[:, 2] <= 0):
        return None
    pts = hom[:, :2] / hom[:, 2:3]
    m = margin * max(float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1])))
    th, tw = template_shape
    x0, y0 = max(0, int(np.floor(pts[:, 0].min() - m))), max(0, int(np.floor(pts[:, 1].min() - m)))
    x1, y1 = min(tw, int(np.ceil(pts[:, 0].max() + m))), min(th, int(np.ceil(pts[:, 1].max() + m)))
    if min(x1 - x0, y1 - y0) < RESCUE_MIN_SIDE // 4:
        return None
    return x0, y0, x1, y1


def _visible_box(mask: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
    """Image points (5, 1, 2) of the page part: its centre and four corners (of the mask's box,
    or of the image)."""
    if mask is not None and mask.any():
        ys, xs = np.nonzero(mask)
        x0, y0, x1, y1 = float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())
    else:
        x0, y0, x1, y1 = 0.0, 0.0, float(shape[1] - 1), float(shape[0] - 1)
    return np.array([[[(x0 + x1) / 2.0, (y0 + y1) / 2.0]], [[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]])


def rescue_register(image: np.ndarray, pdf_bytes: bytes, page_sizes: list[tuple[float, float]],
                    prior: list[tuple[float, int, np.ndarray, str]], log: dict | None = None) -> Registration | None:
    """The rescue stage: find the page when ``register``'s stages did not, and refuse a pose
    that cannot be verified.

    1. ``paper_mask`` finds the page part of a screen capture; outside it the image is set to
       paper, so viewer chrome adds no false ink.
    2. Initial poses: the ``RESCUE_PRIOR`` best earlier ones (``prior``: quick score, page,
       homography at 100 dpi, method) and the template poses of ``template_poses`` (up to
       ``RESCUE_TEMPLATE`` within ``RESCUE_TEMPLATE_SHARE`` of the best score, and the best one
       of each of the ``RESCUE_PAGES`` best pages at a resolution within ``RESCUE_RIVAL_SCALE`` of
       the best pose's, so another page is tried as a rival where a confusion is possible).
    3. Each is refined with ECC restricted to the page part (``ecc_refine`` with the mask),
       coarse levels only where the part is at least ``RESCUE_MIN_SIDE`` pixels across. A tilted
       initial pose (``_tilted``: a photo taken at an angle) is also refined with a homography
       against the master cut to its footprint (``RESCUE_FOOTPRINT``; origin "<origin>:jejak"):
       on small, low-resolution photos of part of a page, which can look as flat as a screen
       capture, the affine or whole-page ECC drifted off initial poses that were right to
       within a pixel. The tries run side by side (``rescue_threads``) and are kept
       in a fixed order, so the threads do not change the outcome.
    4. Each refined pose is verified: ``pose_is_sane`` (ECC did not blow the pose up) and
       ``pose_agreement`` (row-detrended correlation with the master). The best is kept only when it agrees
       with the master to at least ``RESCUE_MIN_AGREEMENT`` and no rival (another page, or a
       pose ``RESCUE_DISTINCT_PT`` away on the same page) comes within ``RESCUE_AMBIGUITY`` of
       it: a wrong or ambiguous pose is refused rather than decoded.

    Code-blind: it uses the evidence and the master PDF only. ``log`` receives the tries and
    the outcome ("terdaftar", "tanpa_pose", "tidak_terverifikasi" or "ambigu").
    """
    probe = 100.0
    log = {} if log is None else log
    mask = paper_mask(image)
    screen = RESCUE_AFFINE and is_screen_capture(image)
    paper = float(np.percentile(image, 99))
    work = image if mask is None else np.where(mask > 0, image, np.float32(paper)).astype(np.float32)
    ink = _prep(work)
    pool: list[tuple[str, int, np.ndarray]] = []
    box = _visible_box(mask, image.shape)
    centre = box[:1]
    log.update(mask=mask is not None, screen=screen, centre=[float(v) for v in centre[0, 0]], tries=[], outcome=None)

    def same(page: int, h0: np.ndarray) -> bool:
        """An initial pose already in the pool: same page, page part mapped within RESCUE_SAME_PX."""
        p0 = cv2.perspectiveTransform(box, np.linalg.inv(h0))
        for _, pg, h1 in pool:
            if pg == page and float(np.abs(cv2.perspectiveTransform(box, np.linalg.inv(h1)) - p0).max()) < RESCUE_SAME_PX:
                return True
        return False

    # A degenerate (singular) initial pose, which SIFT or Tesseract matches can give, is skipped.
    for _, page, h0, method in sorted(prior, key=lambda c: c[0], reverse=True)[:RESCUE_PRIOR]:
        if _invertible(h0) and not same(page, h0):
            pool.append((method, page, h0))
    poses = template_poses(ink, mask, pdf_bytes, len(page_sizes), probe)
    per_page: dict[int, tuple[float, int, np.ndarray]] = {}
    for pose in poses:  # best first
        per_page.setdefault(pose[1], pose)
    picked = [p for p in poses[:RESCUE_TEMPLATE] if p[0] >= RESCUE_TEMPLATE_SHARE * poses[0][0]]
    if poses:
        def eff(pose: tuple[float, int, np.ndarray]) -> float:
            w_pt, h_pt = page_sizes[pose[1]]
            return effective_dpi(pose[2], w_pt * probe / 72.0, h_pt * probe / 72.0, probe)

        e0 = eff(poses[0])
        picked += [p for p in list(per_page.values())[:RESCUE_PAGES]
                   if 1.0 / RESCUE_RIVAL_SCALE <= eff(p) / max(e0, 1e-6) <= RESCUE_RIVAL_SCALE]
    for _, page, h0 in picked:
        if _invertible(h0) and not same(page, h0):
            pool.append(("templat", page, h0))
    if mask is not None:
        ys, xs = np.nonzero(mask)
        part = (int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    else:
        part = (image.shape[1], image.shape[0])

    def attempt(job: tuple[str, int, np.ndarray, bool]) -> dict:
        """Refine one initial pose and verify the result (the whole master, or its footprint)."""
        origin, page, h0, footprint = job
        w_pt, h_pt = page_sizes[page]
        wp, hp = w_pt * probe / 72.0, h_pt * probe / 72.0
        eff0 = effective_dpi(h0, wp, hp, probe)
        dpi = float(np.clip(round(eff0 / 10) * 10, DPI_MIN, DPI_MAX))
        # Evidence below the analysis resolution is refined against a master drawn at its own
        # resolution (measured in its own pixels), then mapped to the analysis resolution.
        edpi = dpi if eff0 >= RESCUE_NATIVE_DPI else float(max(TEMPLATE_EFF_DPI[0], round(eff0)))
        s = edpi / probe
        side = min(part) * edpi / max(eff0, 1e-6)
        levels = tuple((lv, it) for lv, it in RESCUE_LEVELS if lv == 1.0 or side * lv >= RESCUE_MIN_SIDE)
        template = render_page(pdf_bytes, page, edpi)
        template_ink = master_ink(pdf_bytes, page, edpi)
        h0e = h0 @ np.diag([1 / s, 1 / s, 1.0])
        if screen and not footprint:  # an affine start: drop the perspective terms of the initial pose
            h0e = h0e / h0e[2, 2]
            h0e[2, :2] = 0.0
        if footprint:
            # A small photo of part of a page: ECC against the whole page can drift off a pose
            # that was already right, so the master is cut to where the photo lies under the
            # initial pose (enlarged by RESCUE_FOOTPRINT_MARGIN) and the pose refined there.
            cut = _footprint(h0e, work.shape, template.shape, RESCUE_FOOTPRINT_MARGIN)
            if cut is None:
                return {"origin": f"{origin}:jejak", "page": page, "dpi": dpi, "ecc_dpi": edpi, "cc": -1.0,
                        "sane": False, "agreement": -1.0, "pixels": 0, "h": h0e / h0e[2, 2]}
            x0, y0, x1, y1 = cut
            shift = np.array([[1.0, 0.0, x0], [0.0, 1.0, y0], [0.0, 0.0, 1.0]])
            h_c, cc = ecc_refine(template[y0:y1, x0:x1], work, h0e @ shift, levels, mask=mask, image_ink=ink)
            h_e = h_c @ np.linalg.inv(shift)
            origin = f"{origin}:jejak"
        else:
            h_e, cc = ecc_refine(template, work, h0e, levels, mask=mask, affine=screen, template_ink=template_ink,
                                 image_ink=ink)
        sane = cc > 0 and pose_is_sane(h0e, edpi, h_e, edpi, box)
        if sane and footprint:
            # fitted on part of the page, a homography can run off far from it: the page centre's
            # resolution must stay within RESCUE_FOOTPRINT_SPAN of the initial pose's
            e = effective_dpi(h_e, w_pt * edpi / 72.0, h_pt * edpi / 72.0, edpi)
            sane = bool(np.isfinite(e) and eff0 / RESCUE_FOOTPRINT_SPAN <= e <= eff0 * RESCUE_FOOTPRINT_SPAN)
        agree, n = pose_agreement(ink, mask, template_ink, h_e, edpi) if sane else (-1.0, 0)
        h = h_e @ _resize_map(edpi / dpi, edpi / dpi)
        return {"origin": origin, "page": page, "dpi": dpi, "ecc_dpi": edpi, "cc": float(cc), "sane": bool(sane),
                "agreement": agree, "pixels": n, "h": h / h[2, 2]}

    jobs = [(origin, page, h0, False) for origin, page, h0 in pool]
    if RESCUE_FOOTPRINT:
        jobs += [(origin, page, h0, True) for origin, page, h0 in pool if _tilted(h0, box, probe)]
    # The tries are independent: they run side by side (OpenCV releases the GIL), and their
    # results are kept in the order above, so the outcome does not depend on the threads.
    with ThreadPoolExecutor(max_workers=rescue_threads(len(jobs))) as ex:
        tries = list(ex.map(attempt, jobs))
    log["tries"].extend(tries)
    best, outcome, rival = rescue_decision(tries, centre)
    log["rival"] = rival
    if best is not None:
        log.update(page=best["page"], h=best["h"], dpi=best["dpi"], agreement=best["agreement"], origin=best["origin"])
    if outcome != "terdaftar":
        log["outcome"] = outcome
        return None
    log["outcome"] = "terdaftar"
    page, h, dpi = best["page"], best["h"], best["dpi"]
    w_pt, h_pt = page_sizes[page]
    size = (int(round(w_pt * dpi / 72.0)), int(round(h_pt * dpi / 72.0)))
    rect, valid = warp_to_page(image, h, size)
    if mask is not None:  # chrome is not page: its pixels are not decoded
        shown = cv2.warpPerspective(mask, h, size, flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
        valid &= shown.astype(bool)
    return Registration(page=page, dpi=dpi, h_page_to_img=h, correlation=best["cc"], method=f"penyelamat:{best['origin']}",
                        rectified=rect, valid=valid, effective_dpi=effective_dpi(h, size[0], size[1], dpi))


def rescue_decision(tries: list[dict], centre: np.ndarray) -> tuple[dict | None, str, float | None]:
    """The verdict of the rescue stage on its tries: (best try or None, outcome, best rival's
    agreement or None). The best try is the one that agrees most with the master; it is refused
    below RESCUE_MIN_AGREEMENT ("tidak_terverifikasi") and when a rival (another page, or a pose
    putting the visible ``centre`` RESCUE_DISTINCT_PT away) comes within RESCUE_AMBIGUITY of it
    ("ambigu"); "tanpa_pose" when no try was verified at all, else "terdaftar"."""
    if not tries or max(t["agreement"] for t in tries) <= -1.0:
        return None, "tanpa_pose", None
    best = max(tries, key=lambda t: t["agreement"])
    p_best = cv2.perspectiveTransform(centre, np.linalg.inv(best["h"]))[0, 0] * 72.0 / best["dpi"]
    rivals = [t["agreement"] for t in tries if t is not best and t["agreement"] > -1.0 and (
        t["page"] != best["page"]
        or np.linalg.norm(cv2.perspectiveTransform(centre, np.linalg.inv(t["h"]))[0, 0] * 72.0 / t["dpi"] - p_best)
        > RESCUE_DISTINCT_PT)]
    rival = max(rivals) if rivals else None
    if best["agreement"] < RESCUE_MIN_AGREEMENT:
        return best, "tidak_terverifikasi", rival
    if rival is not None and rival >= best["agreement"] - RESCUE_AMBIGUITY:
        return best, "ambigu", rival
    return best, "terdaftar", rival


def _rescue(image: np.ndarray, pdf_bytes: bytes, page_sizes: list[tuple[float, float]],
            cands: list[tuple[float, int, np.ndarray, str]], log: dict) -> Registration | None:
    """Run ``rescue_register`` after the earlier stages failed; its log goes to ``log["rescue"]``."""
    log["rescue"] = {}
    return rescue_register(image, pdf_bytes, page_sizes, cands, log["rescue"])


def register(image: np.ndarray, pdf_bytes: bytes, page_sizes: list[tuple[float, float]],
             min_correlation: float = 0.75, diag: dict | None = None, rescue: bool = True) -> Registration | None:
    """Find the best-matching master page and the precise page-to-image transform.

    Candidate (page, initial transform) pairs are scored cheaply at 30 dpi; only the best is
    refined with full ECC. Initial transforms come from the page outline, then SIFT
    features, then Tesseract word matching, each tried only if the previous gave nothing
    convincing. When none of them gives a page (no initial pose, or ECC below
    ``min_correlation``), the rescue stage ``rescue_register`` runs (``rescue`` False skips it,
    which reproduces the pipeline before ``research/registrasi``); its registrations carry the
    method "penyelamat:<origin of the initial pose>".

    ``diag`` (research and tests), when given, is filled with what each stage did: ``quad``
    (the outline found, or None), ``candidates`` (method, page, quick score and initial
    homography at 100 dpi of every candidate), ``refined`` (method, page, analysis dpi, ECC
    correlation and homography of every ECC run), ``outcome`` of the earlier stages
    ("terdaftar", "tanpa_kandidat" or "korelasi_rendah"), ``bend`` (when the plane fit stayed
    below ``BEND_BELOW``: its correlation, the bent page's, and the largest displacements) and
    ``rescue`` (the rescue stage's log, when it ran). It never changes the result.

    A plane fit below ``BEND_BELOW`` is followed by ``estimate_bend``: a real sheet of paper does
    not lie in a plane. When the bent page correlates better by ``BEND_GAIN``, that correlation
    is the one ``min_correlation`` is compared with, the image is resampled with the smooth
    field (``Registration.bend``) and the method ends in "+lengkung".
    """
    probe_dpi, score_dpi = 100.0, 30.0
    log: dict = {} if diag is None else diag
    log.update(quad=None, candidates=[], refined=[], outcome=None)
    img_ink = _prep(image)
    lo = [master_ink(pdf_bytes, p, score_dpi) for p in range(len(page_sizes))]

    def corners_h(page: int, quad: np.ndarray) -> np.ndarray:
        w_pt, h_pt = page_sizes[page]
        src = page_corners(w_pt * probe_dpi / 72.0, h_pt * probe_dpi / 72.0).astype(np.float32)
        return cv2.getPerspectiveTransform(src, quad.astype(np.float32)).astype(np.float64)

    cands: list[tuple[float, int, np.ndarray, str]] = []

    def add(page: int, h0: np.ndarray, method: str) -> None:
        score = quick_score(img_ink, h0, lo[page], score_dpi, probe_dpi)
        cands.append((score, page, h0, method))
        log["candidates"].append({"method": method, "page": page, "score": score, "h": h0})

    quad = detect_page_quad(image)
    log["quad"] = quad
    if quad is not None:
        for page in range(len(page_sizes)):
            add(page, corners_h(page, quad), "kontur")
    if not cands or max(c[0] for c in cands) < 0.6:
        feats = evidence_features(image)  # once for every page
        for page in range(len(page_sizes)):
            fh = feature_homography(render_page(pdf_bytes, page, probe_dpi), image,
                                    master_features(pdf_bytes, page, probe_dpi), feats)
            if fh is not None:
                add(page, fh, "fitur")
    if not cands or max(c[0] for c in cands) < 0.4:
        from tapak.decoder.lines import ocr_words, tesseract_homography

        words = ocr_words(image)  # once for every page
        for page in range(len(page_sizes)):
            th = tesseract_homography(image, pdf_bytes, page, probe_dpi, words=words)
            if th is not None:
                add(page, th, "tesseract")
    if not cands:
        log["outcome"] = "tanpa_kandidat"
        return _rescue(image, pdf_bytes, page_sizes, cands, log) if rescue else None
    cands.sort(key=lambda c: c[0], reverse=True)
    best: tuple[float, int, np.ndarray, str, float] | None = None
    for _, page, h0, method in cands[:2]:
        w_pt, h_pt = page_sizes[page]
        wp, hp = w_pt * probe_dpi / 72.0, h_pt * probe_dpi / 72.0
        dpi = float(np.clip(round(effective_dpi(h0, wp, hp, probe_dpi) / 10) * 10, DPI_MIN, DPI_MAX))
        s = dpi / probe_dpi
        h, cc = ecc_refine(render_page(pdf_bytes, page, dpi), image, h0 @ np.diag([1 / s, 1 / s, 1.0]),
                           template_ink=master_ink(pdf_bytes, page, dpi), image_ink=img_ink)
        log["refined"].append({"method": method, "page": page, "dpi": dpi, "cc": cc, "h": h})
        if best is None or cc > best[0]:
            best = (cc, page, h, method, dpi)
        if cc > 0.85:
            break
    assert best is not None
    cc, page, h, method, dpi = best
    bend: Bend | None = None
    if 0.0 < cc < BEND_BELOW:  # a real sheet of paper does not lie in a plane
        log["bend"] = {"plane": cc}
        found = estimate_bend(img_ink, master_ink(pdf_bytes, page, dpi), h, dpi, page_sizes[page], log["bend"])
        if found is not None:
            log["bend"].update(cc=found[2], fine_mm=found[0].largest_mm(), smooth_mm=found[1].largest_mm())
            if found[2] >= cc + BEND_GAIN:
                bend, cc, method = found[1], found[2], f"{method}+lengkung"
    if cc < min_correlation:
        log["outcome"] = "korelasi_rendah"
        return _rescue(image, pdf_bytes, page_sizes, cands, log) if rescue else None
    log["outcome"] = "terdaftar"
    w_pt, h_pt = page_sizes[page]
    size = (int(round(w_pt * dpi / 72.0)), int(round(h_pt * dpi / 72.0)))
    rect, valid = warp_to_page(image, h, size, bend)
    return Registration(page=page, dpi=dpi, h_page_to_img=h, correlation=cc, method=method,
                        rectified=rect, valid=valid,
                        effective_dpi=effective_dpi(h, size[0], size[1], dpi), bend=bend)
