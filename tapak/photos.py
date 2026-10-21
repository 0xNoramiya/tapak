"""Synthetic phone photos and screenshots of issued copies ("make photos", M2).

The image decoder must be regression-tested without a phone, so this module turns rendered
pages of issued PDF copies into the kind of images that reach an investigator:

* ``photo``: a phone photo of a printed page lying on a desk. A pinhole camera looks at
  the page plane from a view angle up to ``max_angle_deg``; the scene gets uneven light,
  lens and motion blur, sensor noise, phone sharpening and a tone curve (bright paper may
  clip to white), then the user crops the outer margin and WhatsApp downscales the long
  side and recompresses it (JPEG twice). The print step itself is not modeled: the page keeps
  the rendered gray levels, including the +/-2 background pattern that real printers drop
  (see the limitations in docs/keamanan.md).
* ``screenshot``: a screen capture of a PDF viewer (96 to 150 dpi, optional gray viewer
  chrome) forwarded twice on WhatsApp. No perspective.

Every image comes with its ground truth: the homography from page pixel coordinates to
output image coordinates and every random parameter that was drawn. Pixel coordinates
follow the OpenCV convention (pixel centers at integer coordinates, x to the right, y
down), the same convention ``cv2.warpPerspective`` and ``cv2.resize`` use, so the
homography maps exactly where the content went.

Everything is a pure function of the input page and the random generator: the same
seed always gives the same JPEG bytes. ``make_photo_set`` derives one generator per
output file from (seed, copy, page, kind, angle, index), so a subset of copies reproduces
the same files as the full set.

Data minimization: ``truth.json`` holds sequence numbers, copy ids and geometry only; no
recipient name, recipient id, issued file name or document text is ever written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from tapak.marker.issue import IssueManifest
from tapak.marker.render import render_pages

KIND_PHOTO = "photo"
KIND_SCREENSHOT = "screenshot"
_KIND_SEED = {KIND_PHOTO: 1, KIND_SCREENSHOT: 2}
INK_REFLECTANCE = 0.06  # printed black toner reflects a few percent of the light
MIN_LONG_SIDE = 64      # smallest accepted output long side (px)
DPI_RANGE = (72, 1200)  # accepted render resolutions of make_photo_set

# Output names written by make_photo_set (and removed again before a new run).
_OUTPUT_NAME = re.compile(r"(photo_s\d+_p\d+_a[0-9.e+-]+_\d+|screenshot_s\d+_p\d+_\d+)\.jpg")


class ManifestNotFoundError(FileNotFoundError):
    """The issued folder has no manifest.json (no copies were issued there)."""


@dataclass(frozen=True)
class PhotoParams:
    """Settings of a synthetic phone photo. A (low, high) pair is drawn uniformly.

    Attributes:
        angle_deg: exact view angle (camera axis vs. page normal); None draws it
            uniformly in [0, max_angle_deg].
        max_angle_deg: upper bound of the drawn view angle.
        max_roll_deg: bound of the small in-plane rotation of the phone.
        fill: size of the page bounding box relative to the frame, limiting axis (scale).
        focal_rel: focal length relative to the frame long side (0.75 is the 26 mm
            equivalent main camera; larger means a longer lens and weaker perspective).
        sensor_long_side: long side (px) of the simulated camera frame before WhatsApp;
            the frame is never smaller than ``long_side``.
        long_side: WhatsApp-like limit of the output long side (px).
        crop_max_frac: share of each outer margin the user may crop away.
        crop_into_page: if True, one or more sides are cropped into the page itself
            (robustness tests); by default the whole page stays visible.
        crop_into_max_frac: maximum depth of such a crop, as a share of the page size.
        paper_albedo: reflectance of the blank paper.
        exposure: gain of the camera. High values make bright paper clip to white, the
            way auto exposure over a dark desk often does, which wipes out faint marks;
            with the default range about a third of the photos clip on a large area.
        blur_sigma: Gaussian lens blur, px at output scale.
        motion_px: length of the linear motion blur, px at output scale (0 means none).
        noise_read: signal-independent sensor noise (gray levels, camera frame).
        noise_shot: signal-dependent noise variance per gray level (camera frame).
        sharpen: strength of the phone's unsharp mask (0 means none).
        sharpen_sigma: radius of the unsharp mask, px at output scale.
        gamma: exponent of the tone curve.
        jpeg_quality_1: first WhatsApp compression.
        jpeg_quality_2: second compression (the image is forwarded or re-sent).
        shadow_prob: probability of a soft shadow band across the scene.
    """

    angle_deg: float | None = None
    max_angle_deg: float = 30.0
    max_roll_deg: float = 4.0
    fill: tuple[float, float] = (0.72, 0.90)
    focal_rel: tuple[float, float] = (0.75, 1.10)
    sensor_long_side: int = 2400
    long_side: int = 1600
    crop_max_frac: float = 0.8
    crop_into_page: bool = False
    crop_into_max_frac: float = 0.10
    paper_albedo: tuple[float, float] = (0.88, 0.97)
    exposure: tuple[float, float] = (0.90, 1.40)
    blur_sigma: tuple[float, float] = (0.5, 1.5)
    motion_px: tuple[float, float] = (0.0, 2.0)
    noise_read: tuple[float, float] = (1.0, 3.0)
    noise_shot: tuple[float, float] = (0.02, 0.08)
    sharpen: tuple[float, float] = (0.0, 0.8)
    sharpen_sigma: float = 1.0
    gamma: tuple[float, float] = (0.85, 1.20)
    jpeg_quality_1: tuple[int, int] = (75, 85)
    jpeg_quality_2: tuple[int, int] = (65, 75)
    shadow_prob: float = 0.7


@dataclass(frozen=True)
class ScreenshotParams:
    """Settings of a synthetic screenshot of a PDF viewer.

    Attributes:
        render_dpi: resolution at which the input page was rendered. It cannot be read
            from the pixel array, so set it whenever the render is not at 200 dpi; the
            on-screen scale is ``screen_dpi / render_dpi``.
        screen_dpi: exact on-screen resolution; None draws it from ``dpi_range``.
        dpi_range: range of on-screen resolutions (zoom levels).
        chrome: draw gray viewer chrome (toolbar, background, page border); None draws
            it with probability ``chrome_prob``.
        chrome_prob: probability of viewer chrome when ``chrome`` is None.
        long_side: WhatsApp-like limit of the long side (px); None keeps the exact
            on-screen resolution.
        jpeg_quality_1: first WhatsApp compression (about 70).
        jpeg_quality_2: second compression when forwarded (about 60).
    """

    render_dpi: float = 200.0
    screen_dpi: float | None = None
    dpi_range: tuple[float, float] = (96.0, 150.0)
    chrome: bool | None = None
    chrome_prob: float = 0.7
    long_side: int | None = None
    jpeg_quality_1: tuple[int, int] = (68, 72)
    jpeg_quality_2: tuple[int, int] = (58, 62)


# ---------------------------------------------------------------------------------------
# Small helpers


def _uniform(rng: np.random.Generator, bounds: tuple[float, float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


def _quality(rng: np.random.Generator, bounds: tuple[int, int]) -> int:
    return int(rng.integers(bounds[0], bounds[1] + 1))


def _check_page(page_img: np.ndarray) -> None:
    if not isinstance(page_img, np.ndarray) or page_img.ndim != 2 or page_img.dtype != np.uint8:
        raise ValueError("gambar halaman harus berupa array grayscale uint8 dua dimensi")
    if min(page_img.shape) < 16:
        raise ValueError("gambar halaman terlalu kecil")


def _to_list(m: np.ndarray) -> list[list[float]]:
    return [[float(v) for v in row] for row in np.asarray(m, dtype=np.float64)]


def _settings(params: PhotoParams | ScreenshotParams) -> dict[str, object]:
    """Settings as plain JSON values (tuples become lists), so meta survives a JSON round trip."""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(params).items()}


def apply_homography(homography: np.ndarray | list[list[float]], points: np.ndarray) -> np.ndarray:
    """Map an (N, 2) array of (x, y) points with a 3x3 homography."""
    h = np.asarray(homography, dtype=np.float64)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    q = np.hstack([pts, np.ones((len(pts), 1))]) @ h.T
    return q[:, :2] / q[:, 2:3]


def view_angle_deg(homography: np.ndarray | list[list[float]],
                   camera_matrix: np.ndarray | list[list[float]]) -> float:
    """Angle (degrees) between the camera axis and the page normal.

    For a pinhole camera, homography = K [r1 r2 t] C with K the camera matrix, r1 and r2
    the page axes in camera coordinates and C a translation in the page plane; so the
    first two columns of inv(K) @ homography are proportional to r1 and r2 and their
    cross product is the page normal.
    """
    m = np.linalg.solve(np.asarray(camera_matrix, dtype=np.float64), np.asarray(homography, dtype=np.float64))
    normal = np.cross(m[:, 0], m[:, 1])
    cos_angle = abs(normal[2]) / float(np.linalg.norm(normal))
    return math.degrees(math.acos(min(1.0, cos_angle)))


def _resize_matrix(sx: float, sy: float) -> np.ndarray:
    """Coordinate map of ``cv2.resize`` by (sx, sy): x' = (x + 0.5) * sx - 0.5."""
    return np.array([[sx, 0.0, 0.5 * sx - 0.5], [0.0, sy, 0.5 * sy - 0.5], [0.0, 0.0, 1.0]])


def _translation(dx: float, dy: float) -> np.ndarray:
    return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])


def encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    """Baseline JPEG bytes of a uint8 image at ``quality`` (1 to 100)."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("pengodean JPEG gagal")
    return buf.tobytes()


def decode_jpeg(data: bytes) -> np.ndarray:
    """Decode JPEG bytes to a grayscale uint8 array."""
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("berkas bukan JPEG yang valid")
    return img


def _double_jpeg(img: np.ndarray, q1: int, q2: int) -> bytes:
    """Compress, decode and compress again (what a forwarded chat image goes through)."""
    return encode_jpeg(decode_jpeg(encode_jpeg(img, q1)), q2)


# ---------------------------------------------------------------------------------------
# Photo: geometry


def _camera_rotation(tilt_axis_deg: float, angle_deg: float, roll_deg: float) -> np.ndarray:
    """Rotation of the page plane into camera coordinates.

    The page is tilted by ``angle_deg`` about an in-plane axis at ``tilt_axis_deg`` from the
    page's horizontal (0: horizontal axis, top edge leans away; 90: vertical axis), then
    rotated by ``roll_deg`` about the camera axis (the phone is held slightly crooked).
    """
    a, t, r = (math.radians(v) for v in (tilt_axis_deg, angle_deg, roll_deg))
    k = np.array([math.cos(a), math.sin(a), 0.0])
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    tilt = np.eye(3) + math.sin(t) * kx + (1.0 - math.cos(t)) * (kx @ kx)  # Rodrigues
    roll = np.array([[math.cos(r), -math.sin(r), 0.0], [math.sin(r), math.cos(r), 0.0], [0.0, 0.0, 1.0]])
    return roll @ tilt


@dataclass(frozen=True)
class _Geometry:
    """Transforms of one photo, all in OpenCV pixel coordinates."""

    frame_size: tuple[int, int]            # camera frame (width, height)
    h_frame: np.ndarray                    # page px -> camera frame px
    crop_box: tuple[int, int, int, int]    # x0, y0, x1, y1 in the camera frame (end exclusive)
    down: float                            # WhatsApp downscale factor (<= 1)
    out_size: tuple[int, int]              # output (width, height)
    homography: np.ndarray                 # page px -> output px
    camera_matrix: np.ndarray              # pinhole intrinsics in output px
    view_angle_deg: float                  # camera axis vs. page normal


def _photo_geometry(page_shape: tuple[int, int], params: PhotoParams, rng: np.random.Generator,
                    drawn: dict[str, object]) -> _Geometry:
    """Draw the camera pose, framing and crop; return all transforms (no pixels yet)."""
    ph, pw = page_shape
    if params.angle_deg is None:
        angle = _uniform(rng, (0.0, params.max_angle_deg))
    else:
        angle = float(params.angle_deg)
    if not 0.0 <= angle < 80.0:
        raise ValueError("sudut pandang harus di antara 0 dan 80 derajat")
    mode = str(rng.choice(["horizontal", "vertical", "both"]))
    if mode == "horizontal":
        axis = float(rng.choice([0.0, 180.0]))
    elif mode == "vertical":
        axis = float(rng.choice([90.0, 270.0]))
    else:
        axis = _uniform(rng, (0.0, 360.0))
    roll = _uniform(rng, (-params.max_roll_deg, params.max_roll_deg))
    fill = _uniform(rng, params.fill)
    focal_rel = _uniform(rng, params.focal_rel)
    jitter_x = _uniform(rng, (0.2, 0.8))
    jitter_y = _uniform(rng, (0.2, 0.8))
    drawn.update(view_angle_deg=angle, tilt_mode=mode, tilt_axis_deg=axis, roll_deg=roll, fill=fill,
                 focal_rel=focal_rel, offset_jitter=[jitter_x, jitter_y])

    # Camera frame: 4:3 like a phone sensor, oriented like the page.
    long_px = max(params.sensor_long_side, params.long_side)
    short_px = int(round(long_px * 3 / 4))
    cw, ch = (short_px, long_px) if ph >= pw else (long_px, short_px)

    # Pinhole camera with unit focal length; the page center lies on the optical axis at
    # distance D, chosen so that an untilted page would fill ``fill`` of the frame.
    rot = _camera_rotation(axis, angle, roll)
    distance = focal_rel * max(ph, pw) / fill
    center = _translation(-(pw - 1) / 2.0, -(ph - 1) / 2.0)
    pose = np.column_stack([rot[:, 0], rot[:, 1], [0.0, 0.0, distance]])
    corners = np.array([[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]], dtype=np.float64)
    cam = np.hstack([corners, np.ones((4, 1))]) @ (pose @ center).T
    if np.any(cam[:, 2] <= 0):
        raise ValueError("pose kamera tidak valid: halaman berada di belakang kamera")
    uv = cam[:, :2] / cam[:, 2:3]
    umin, vmin = uv.min(axis=0)
    bw, bh = uv.max(axis=0) - uv.min(axis=0)

    # Zoom so the page bounding box fills ``fill`` of the limiting axis, then place it.
    s = fill * min(cw / bw, ch / bh)
    left = (cw - s * bw) * jitter_x
    top = (ch - s * bh) * jitter_y
    intrinsics = np.array([[s, 0.0, left - s * umin], [0.0, s, top - s * vmin], [0.0, 0.0, 1.0]])
    h_frame = intrinsics @ pose @ center
    box = (left, top, left + s * bw, top + s * bh)

    # Crop: by default only the desk margin, keeping a few pixels of desk around the page.
    safety = max(4.0, 0.01 * long_px)
    margins = {"left": box[0], "top": box[1], "right": cw - box[2], "bottom": ch - box[3]}
    crop: dict[str, int] = {}
    for side, margin in margins.items():
        crop[side] = int(math.floor(_uniform(rng, (0.0, params.crop_max_frac)) * max(0.0, margin - safety)))
    into: list[str] = []
    if params.crop_into_page:
        sides = list(margins)
        into = [side for side in sides if rng.random() < 0.5] or [sides[int(rng.integers(4))]]
        for side in into:
            extent = (box[2] - box[0]) if side in ("left", "right") else (box[3] - box[1])
            depth = _uniform(rng, (0.02, params.crop_into_max_frac)) * extent
            crop[side] = int(math.floor(max(0.0, margins[side]) + depth))
    drawn.update(crop_px=crop, crop_into_page_sides=into)
    x0, y0 = crop["left"], crop["top"]
    x1, y1 = cw - crop["right"], ch - crop["bottom"]

    # WhatsApp downscale of the cropped image to at most ``long_side``.
    down = min(1.0, params.long_side / max(x1 - x0, y1 - y0))
    out_w = max(1, int(round((x1 - x0) * down)))
    out_h = max(1, int(round((y1 - y0) * down)))
    to_output = _resize_matrix(out_w / (x1 - x0), out_h / (y1 - y0)) @ _translation(-x0, -y0)
    # Scale so H[2, 2] = 1: then H[0, 2], H[1, 2] are where page pixel (0, 0) lands. H[2, 2]
    # is the depth of that page corner, which the check above keeps positive.
    homography = to_output @ h_frame
    homography = homography / homography[2, 2]
    return _Geometry(frame_size=(cw, ch), h_frame=h_frame, crop_box=(x0, y0, x1, y1), down=down,
                     out_size=(out_w, out_h), homography=homography,
                     camera_matrix=to_output @ intrinsics, view_angle_deg=angle)


# ---------------------------------------------------------------------------------------
# Photo: pixels


def _desk(rng: np.random.Generator, w: int, h: int, drawn: dict[str, object]) -> np.ndarray:
    """A darker textured desk surface (reflectance in [0, 1]): blotches plus wood grain."""
    base = _uniform(rng, (25.0, 80.0))
    blotch_amp = _uniform(rng, (3.0, 9.0))
    grain_amp = _uniform(rng, (2.0, 7.0))
    grain_angle = _uniform(rng, (0.0, math.pi))
    grain_period = _uniform(rng, (0.006, 0.03)) * max(w, h)
    fine_amp = _uniform(rng, (1.0, 3.0))
    drawn.update(desk_level=base, desk_blotch=blotch_amp, desk_grain=grain_amp,
                 desk_grain_angle_deg=math.degrees(grain_angle), desk_grain_period_px=grain_period,
                 desk_fine=fine_amp)
    coarse = rng.standard_normal((h // 64 + 3, w // 64 + 3)).astype(np.float32)
    blotch = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)
    xs = np.arange(w, dtype=np.float32)[None, :]
    ys = np.arange(h, dtype=np.float32)[:, None]
    phase = (xs * math.cos(grain_angle) + ys * math.sin(grain_angle)) * np.float32(2 * math.pi / grain_period)
    grain = np.sin(phase + 1.5 * blotch)
    fine = rng.standard_normal((h, w), dtype=np.float32)
    desk = base + blotch_amp * blotch + grain_amp * grain + fine_amp * fine
    return np.clip(desk, 0.0, 255.0) / np.float32(255.0)


def _illumination(rng: np.random.Generator, w: int, h: int, params: PhotoParams,
                  drawn: dict[str, object]) -> np.ndarray:
    """Multiplicative light field: smooth gradient, optional soft shadow band, vignetting."""
    grad_dir = _uniform(rng, (0.0, 2 * math.pi))
    grad_strength = _uniform(rng, (0.05, 0.25))
    has_shadow = bool(rng.random() < params.shadow_prob)
    shadow_dir = _uniform(rng, (0.0, math.pi))
    shadow_pos = _uniform(rng, (-0.6, 0.6))
    shadow_width = _uniform(rng, (0.06, 0.25))
    shadow_depth = _uniform(rng, (0.10, 0.35)) if has_shadow else 0.0
    vignette = _uniform(rng, (0.10, 0.30))
    drawn.update(light_gradient_dir_deg=math.degrees(grad_dir), light_gradient=grad_strength,
                 shadow=has_shadow, shadow_dir_deg=math.degrees(shadow_dir), shadow_pos=shadow_pos,
                 shadow_width=shadow_width, shadow_depth=shadow_depth, vignette=vignette)
    half_diag = np.float32(0.5 * math.hypot(w, h))
    xs = (np.arange(w, dtype=np.float32)[None, :] - np.float32(w / 2)) / half_diag
    ys = (np.arange(h, dtype=np.float32)[:, None] - np.float32(h / 2)) / half_diag
    along = xs * math.cos(grad_dir) + ys * math.sin(grad_dir)            # in [-1, 1]
    light = 1.0 - grad_strength * (0.5 + 0.5 * along)
    across = xs * math.cos(shadow_dir) + ys * math.sin(shadow_dir)
    light *= 1.0 - shadow_depth * np.exp(-0.5 * ((across - shadow_pos) / shadow_width) ** 2)
    light *= 1.0 - vignette * (xs * xs + ys * ys)
    return light.astype(np.float32)


def _motion_kernel(length: float, angle_deg: float) -> np.ndarray:
    """Normalized line kernel of ``length`` px centered on the middle pixel.

    The segment is sampled densely and every sample is spread over its four neighbouring
    pixels with bilinear weights, so fractional lengths and any angle are reproduced.
    """
    size = 2 * int(math.ceil(length / 2.0)) + 3
    kernel = np.zeros((size, size), dtype=np.float32)
    c = (size - 1) / 2.0
    cos_a, sin_a = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    for t in np.linspace(-length / 2.0, length / 2.0, 8 * int(math.ceil(length)) + 1):
        x, y = c + t * cos_a, c + t * sin_a
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - x0, y - y0
        kernel[y0, x0] += (1 - fx) * (1 - fy)
        kernel[y0, x0 + 1] += fx * (1 - fy)
        kernel[y0 + 1, x0] += (1 - fx) * fy
        kernel[y0 + 1, x0 + 1] += fx * fy
    return kernel / kernel.sum()


def photo_jpeg(page_img: np.ndarray, rng: np.random.Generator,
               params: PhotoParams | None = None) -> tuple[bytes, dict[str, object]]:
    """Simulate a phone photo of a printed page; return the final JPEG bytes and meta.

    ``meta`` holds ``homography`` (page pixel coordinates to output image coordinates,
    3x3 list), ``camera_matrix`` (pinhole intrinsics in output pixels, so that
    ``view_angle_deg(homography, camera_matrix)`` recovers the view angle),
    ``page_size`` and ``image_size`` as [width, height], ``settings`` (the PhotoParams)
    and ``params`` (every random value drawn, plus ``highlight_clip_frac``, the share of
    camera pixels that clipped to white).
    """
    _check_page(page_img)
    params = params or PhotoParams()
    if params.long_side < MIN_LONG_SIDE:
        raise ValueError(f"sisi panjang gambar minimal {MIN_LONG_SIDE} piksel")
    drawn: dict[str, object] = {}
    geo = _photo_geometry(page_img.shape, params, rng, drawn)
    cw, ch = geo.frame_size
    h_frame, down = geo.h_frame, geo.down

    albedo = _uniform(rng, params.paper_albedo)
    exposure = _uniform(rng, params.exposure)
    drawn.update(paper_albedo=albedo, exposure=exposure)

    # Scene reflectance: the page (ink and paper) composited over the desk.
    page = INK_REFLECTANCE + (albedo - INK_REFLECTANCE) * (page_img.astype(np.float32) / 255.0)
    warp = h_frame
    center = np.array([[page_img.shape[1] / 2.0, page_img.shape[0] / 2.0]])
    jac_pts = apply_homography(h_frame, np.vstack([center, center + [1.0, 0.0], center + [0.0, 1.0]]))
    (ax, ay), (bx, by) = jac_pts[1] - jac_pts[0], jac_pts[2] - jac_pts[0]
    local_scale = math.sqrt(abs(ax * by - ay * bx))  # sqrt of the Jacobian determinant
    if local_scale < 0.8:  # shrink first with area averaging so the warp does not alias text
        k = min(1.0, 1.25 * local_scale)
        small_w = max(2, int(round(page.shape[1] * k)))
        small_h = max(2, int(round(page.shape[0] * k)))
        sx, sy = small_w / page.shape[1], small_h / page.shape[0]
        page = cv2.resize(page, (small_w, small_h), interpolation=cv2.INTER_AREA)
        warp = h_frame @ np.linalg.inv(_resize_matrix(sx, sy))
    warped = cv2.warpPerspective(page, warp, (cw, ch), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    mask = cv2.warpPerspective(np.ones(page.shape, dtype=np.float32), warp, (cw, ch),
                               flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    scene = warped + (1.0 - mask) * _desk(rng, cw, ch, drawn)
    del warped, mask

    # Light, optics, sensor, tone curve.
    img = scene * _illumination(rng, cw, ch, params, drawn) * np.float32(255.0 * exposure)
    del scene
    blur_out = _uniform(rng, params.blur_sigma)
    motion_out = _uniform(rng, params.motion_px)
    motion_angle = _uniform(rng, (0.0, 180.0))
    noise_read = _uniform(rng, params.noise_read)
    noise_shot = _uniform(rng, params.noise_shot)
    sharpen = _uniform(rng, params.sharpen)
    gamma = _uniform(rng, params.gamma)
    q1 = _quality(rng, params.jpeg_quality_1)
    q2 = _quality(rng, params.jpeg_quality_2)
    drawn.update(blur_sigma_px=blur_out, motion_px=motion_out, motion_angle_deg=motion_angle,
                 noise_read=noise_read, noise_shot=noise_shot, sharpen=sharpen, gamma=gamma,
                 jpeg_quality_1=q1, jpeg_quality_2=q2, downscale=down)
    img = cv2.GaussianBlur(img, (0, 0), sigmaX=blur_out / down)
    if motion_out > 0.0:  # the kernel reproduces fractional lengths, so any length is applied
        img = cv2.filter2D(img, -1, _motion_kernel(motion_out / down, motion_angle))
    sigma = np.sqrt(noise_read ** 2 + noise_shot * np.clip(img, 0.0, None))
    img += sigma * rng.standard_normal(img.shape, dtype=np.float32)
    # Phone image processing: unsharp mask, then bright paper clips to white.
    if sharpen > 0.0:
        img += np.float32(sharpen) * (img - cv2.GaussianBlur(img, (0, 0), sigmaX=params.sharpen_sigma / down))
    drawn["highlight_clip_frac"] = float(np.mean(img >= 255.0))
    img = np.clip(img, 0.0, 255.0)
    img = 255.0 * np.power(img / np.float32(255.0), np.float32(gamma))
    camera_img = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    del img, sigma

    # User crop, WhatsApp downscale, two compressions.
    x0, y0, x1, y1 = geo.crop_box
    out = camera_img[y0:y1, x0:x1]
    out_w, out_h = geo.out_size
    if (out_w, out_h) != (x1 - x0, y1 - y0):
        out = cv2.resize(out, (out_w, out_h), interpolation=cv2.INTER_AREA)
    data = _double_jpeg(np.ascontiguousarray(out), q1, q2)

    meta: dict[str, object] = {
        "kind": KIND_PHOTO,
        "homography": _to_list(geo.homography),
        "camera_matrix": _to_list(geo.camera_matrix),
        "view_angle_deg": geo.view_angle_deg,
        "page_size": [int(page_img.shape[1]), int(page_img.shape[0])],
        "image_size": [int(out_w), int(out_h)],
        "settings": _settings(params),
        "params": drawn,
    }
    return data, meta


def photo(page_img: np.ndarray, rng: np.random.Generator,
          params: PhotoParams | None = None) -> tuple[np.ndarray, dict[str, object]]:
    """Simulate a phone photo of a printed page; return the decoded image and meta.

    The image is the grayscale decode of the JPEG that ``photo_jpeg`` produces with the
    same generator state; see there for the contents of ``meta``.
    """
    data, meta = photo_jpeg(page_img, rng, params)
    return decode_jpeg(data), meta


# ---------------------------------------------------------------------------------------
# Screenshot


def screenshot_jpeg(page_img: np.ndarray, rng: np.random.Generator,
                    params: ScreenshotParams | None = None) -> tuple[bytes, dict[str, object]]:
    """Simulate a screen capture of a PDF viewer; return the final JPEG bytes and meta.

    The page is downscaled from ``params.render_dpi`` to the on-screen resolution,
    optionally framed by gray viewer chrome, optionally limited to ``long_side`` and
    compressed twice. ``render_dpi`` must be the resolution ``page_img`` was rendered at
    (default 200, the default of ``make_photo_set``); a wrong value gives a wrong scale.
    ``meta`` holds ``homography`` (a pure scale and offset), ``scale``, ``offset``,
    ``screen_dpi``, ``effective_dpi`` (after any downscale), ``page_size``,
    ``image_size``, ``settings`` and ``params`` (every random value drawn).
    """
    _check_page(page_img)
    params = params or ScreenshotParams()
    if params.render_dpi <= 0:
        raise ValueError("resolusi render harus lebih dari 0 dpi")
    if params.long_side is not None and params.long_side < MIN_LONG_SIDE:
        raise ValueError(f"sisi panjang gambar minimal {MIN_LONG_SIDE} piksel")
    drawn: dict[str, object] = {}
    dpi = float(params.screen_dpi) if params.screen_dpi is not None else _uniform(rng, params.dpi_range)
    if dpi <= 0:
        raise ValueError("resolusi layar harus lebih dari 0 dpi")
    chrome = params.chrome if params.chrome is not None else bool(rng.random() < params.chrome_prob)
    drawn.update(screen_dpi=dpi, chrome=chrome)
    ph, pw = page_img.shape
    k = dpi / params.render_dpi
    sw, sh = max(1, int(round(pw * k))), max(1, int(round(ph * k)))
    shown = cv2.resize(page_img, (sw, sh), interpolation=cv2.INTER_AREA)

    if chrome:
        dark = bool(rng.random() < 0.5)
        background = int(rng.integers(45, 80)) if dark else int(rng.integers(195, 220))
        bar_level = int(rng.integers(30, 50)) if dark else int(rng.integers(225, 245))
        bar_h = int(rng.integers(36, 65))
        side = int(rng.integers(16, 81))
        gap_top = int(rng.integers(8, 25))
        gap_bottom = int(rng.integers(8, 41))
        n_buttons = int(rng.integers(3, 8))
        drawn.update(chrome_dark=dark, chrome_background=background, chrome_bar=bar_level,
                     chrome_bar_px=bar_h, chrome_side_px=side, chrome_gap_top_px=gap_top,
                     chrome_gap_bottom_px=gap_bottom, chrome_buttons=n_buttons)
        canvas = np.full((bar_h + gap_top + sh + gap_bottom, sw + 2 * side), background, dtype=np.uint8)
        canvas[:bar_h] = bar_level
        button = 200 if dark else 90
        for b in range(n_buttons):
            x = 12 + b * (bar_h + 6)
            if x + bar_h - 12 < canvas.shape[1]:
                cv2.rectangle(canvas, (x, 8), (x + bar_h - 16, bar_h - 9), button, thickness=2)
        ox, oy = side, bar_h + gap_top
        shadow = max(0, background - 35)
        canvas[oy + 3:oy + sh + 3, ox + 3:ox + sw + 3] = shadow
        canvas[oy:oy + sh, ox:ox + sw] = shown
        cv2.rectangle(canvas, (ox - 1, oy - 1), (ox + sw, oy + sh), 150, thickness=1)
    else:
        canvas, ox, oy = shown, 0, 0
    homography = _translation(ox, oy) @ _resize_matrix(sw / pw, sh / ph)

    down = 1.0
    if params.long_side is not None and max(canvas.shape) > params.long_side:
        down = params.long_side / max(canvas.shape)
        new_w = max(1, int(round(canvas.shape[1] * down)))
        new_h = max(1, int(round(canvas.shape[0] * down)))
        homography = _resize_matrix(new_w / canvas.shape[1], new_h / canvas.shape[0]) @ homography
        canvas = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_AREA)
    q1 = _quality(rng, params.jpeg_quality_1)
    q2 = _quality(rng, params.jpeg_quality_2)
    drawn.update(downscale=down, jpeg_quality_1=q1, jpeg_quality_2=q2)
    data = _double_jpeg(np.ascontiguousarray(canvas), q1, q2)
    meta: dict[str, object] = {
        "kind": KIND_SCREENSHOT,
        "homography": _to_list(homography),
        "scale": [float(homography[0, 0]), float(homography[1, 1])],
        "offset": [float(homography[0, 2]), float(homography[1, 2])],
        "screen_dpi": dpi,
        "effective_dpi": params.render_dpi * float(homography[0, 0]),
        "page_size": [int(pw), int(ph)],
        "image_size": [int(canvas.shape[1]), int(canvas.shape[0])],
        "settings": _settings(params),
        "params": drawn,
    }
    return data, meta


def screenshot(page_img: np.ndarray, rng: np.random.Generator,
               params: ScreenshotParams | None = None) -> tuple[np.ndarray, dict[str, object]]:
    """Simulate a screen capture of a PDF viewer; return the decoded image and meta.

    Set ``params.render_dpi`` to the resolution of ``page_img`` (default 200); see
    ``screenshot_jpeg`` for the contents of ``meta``.
    """
    data, meta = screenshot_jpeg(page_img, rng, params)
    return decode_jpeg(data), meta


# ---------------------------------------------------------------------------------------
# Photo set for regression tests


def _file_rng(seed: int, seq: int, page: int, kind: str, angle: float, index: int) -> np.random.Generator:
    """One generator per output file, independent of which other files are produced."""
    return np.random.default_rng([seed, seq, page, _KIND_SEED[kind], int(round(angle * 1000)), index])


def stale_outputs(out_dir: Path | str) -> list[Path]:
    """Images in ``out_dir`` named like make_photo_set output (they are replaced on a new run).

    Only names of the exact form ``photo_s013_p1_a30_0.jpg`` or ``screenshot_s013_p1_0.jpg``
    match; any other file in the folder is left alone.
    """
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    return sorted(p for p in out_dir.iterdir() if p.is_file() and _OUTPUT_NAME.fullmatch(p.name))


def _check_set_inputs(per_copy: int, angles: tuple[float, ...], seed: int, dpi: int, long_side: int) -> None:
    """Refuse numeric inputs that would crash later or write wrong ground truth."""
    if not DPI_RANGE[0] <= dpi <= DPI_RANGE[1]:
        raise ValueError(f"resolusi render harus di antara {DPI_RANGE[0]} dan {DPI_RANGE[1]} dpi")
    if long_side < MIN_LONG_SIDE:
        raise ValueError(f"sisi panjang gambar minimal {MIN_LONG_SIDE} piksel")
    if not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("benih acak harus bilangan bulat tidak negatif")
    if per_copy < 0:
        raise ValueError("jumlah gambar per salinan tidak boleh negatif")
    if any(not 0 <= a < 80 for a in angles):
        raise ValueError("sudut pandang harus di antara 0 dan 80 derajat")


def _load_manifest(issued_dir: Path) -> IssueManifest:
    """Parse ``issued_dir/manifest.json`` with Indonesian errors for a missing or broken file."""
    manifest_path = issued_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestNotFoundError(f"manifest.json tidak ditemukan di {issued_dir}")
    try:
        return IssueManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"manifest.json rusak atau tidak dikenali di {issued_dir}") from exc


def _read_copy(issued_dir: Path, name: object, sha256: str) -> bytes:
    """Bytes of one issued copy PDF, checked against the manifest.

    The manifest may name only a plain file inside ``issued_dir`` (no folder part, no
    absolute path), so a tampered manifest cannot make this tool read other PDFs. The
    bytes must match the recorded sha256, so the copy_id in truth.json is the copy shown.
    """
    if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name:
        raise ValueError(f"nama berkas salinan tidak valid di manifest: {name!r}")
    path = issued_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"berkas salinan tidak ditemukan: {name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"berkas salinan tidak cocok dengan manifest (sha256 berbeda): {name}")
    return data


def make_photo_set(
    issued_dir: Path | str,
    out_dir: Path | str,
    seqs: list[int] | None = None,
    per_copy: int = 2,
    angles: tuple[float, ...] = (0, 10, 20, 30),
    seed: int = 2026,
    dpi: int = 200,
    long_side: int = 1600,
    *,
    all_pages: bool = False,
    screenshots: bool = True,
    photo_params: PhotoParams | None = None,
    screenshot_params: ScreenshotParams | None = None,
) -> list[dict[str, object]]:
    """Write synthetic photos and screenshots of issued copies plus ``truth.json``.

    For every selected copy (``seqs``; all copies if None) page 1 (or every page with
    ``all_pages``) is rendered at ``dpi``; for every angle ``per_copy`` photos are written
    as ``photo_s013_p1_a30_0.jpg`` and ``per_copy`` screenshots as
    ``screenshot_s013_p1_0.jpg``. Pages are numbered from 1. Both kinds are limited to
    ``long_side`` pixels like WhatsApp. ``photo_params`` and ``screenshot_params`` are
    templates; the angle, ``long_side`` and render dpi are set per file. Repeated seqs
    and angles are produced once.

    All inputs and every selected copy PDF are checked before anything is written. Then
    images left in ``out_dir`` by an earlier run (see ``stale_outputs``) and the old
    ``truth.json`` are deleted, so the folder always matches its ``truth.json``.

    ``truth.json`` is ``{"doc_hash", "doc_name", "seed", "dpi", "long_side", "items"}``
    where each item has file, seq, copy_id, page, kind, angle, homography, page_size,
    image_size, settings and params (photos also camera_matrix and view_angle_deg;
    screenshots scale, offset, screen_dpi and effective_dpi). The items are returned.
    No recipient name, recipient id, issued file name or document text is written.
    """
    issued_dir, out_dir = Path(issued_dir), Path(out_dir)
    _check_set_inputs(per_copy, angles, seed, dpi, long_side)
    unique_angles: dict[str, float] = {}  # keyed by the file name token, so no name repeats
    for a in angles:
        unique_angles.setdefault(f"{float(a):g}", float(a))
    manifest = _load_manifest(issued_dir)
    by_seq = {c.seq: c for c in manifest.copies}
    if seqs is None:
        selected = sorted(by_seq)
    else:
        missing = [s for s in seqs if s not in by_seq]
        if missing:
            raise ValueError("nomor salinan tidak ada di manifest: " + ", ".join(str(s) for s in missing))
        selected = list(dict.fromkeys(seqs))
    pdfs = {seq: _read_copy(issued_dir, by_seq[seq].file, by_seq[seq].file_sha256) for seq in selected}
    base_photo = photo_params or PhotoParams()
    base_shot = screenshot_params or ScreenshotParams()

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in stale_outputs(out_dir):
        old.unlink()
    (out_dir / "truth.json").unlink(missing_ok=True)

    items: list[dict[str, object]] = []
    for seq in selected:
        copy = by_seq[seq]
        renders = render_pages(pdfs[seq], dpi, None if all_pages else [0])
        for page_no, page_img in enumerate(renders, start=1):
            jobs = [(KIND_PHOTO, a, i) for a in unique_angles.values() for i in range(per_copy)]
            if screenshots:
                jobs += [(KIND_SCREENSHOT, 0.0, i) for i in range(per_copy)]
            for kind, angle, index in jobs:
                rng = _file_rng(seed, seq, page_no, kind, angle, index)
                if kind == KIND_PHOTO:
                    params = replace(base_photo, angle_deg=angle, long_side=long_side)
                    data, meta = photo_jpeg(page_img, rng, params)
                    name = f"photo_s{seq:03d}_p{page_no}_a{angle:g}_{index}.jpg"
                    angle_field: float | None = angle
                else:
                    sparams = replace(base_shot, render_dpi=float(dpi), long_side=long_side)
                    data, meta = screenshot_jpeg(page_img, rng, sparams)
                    name = f"screenshot_s{seq:03d}_p{page_no}_{index}.jpg"
                    angle_field = None
                (out_dir / name).write_bytes(data)
                item: dict[str, object] = {"file": name, "seq": seq, "copy_id": copy.copy_id, "page": page_no,
                                           "kind": kind, "angle": angle_field, "render_dpi": dpi}
                item.update({k: v for k, v in meta.items() if k != "kind"})
                items.append(item)

    truth = {
        "doc_hash": manifest.doc_hash,
        "doc_name": manifest.doc_name,
        "seed": seed,
        "dpi": dpi,
        "long_side": long_side,
        "items": items,
    }
    # ASCII JSON: any non-ASCII character of doc_name is written as a \u escape.
    (out_dir / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return items


# ---------------------------------------------------------------------------------------
# Command line


def _int_list(text: str) -> list[int]:
    try:
        return [int(t) for t in text.split(",") if t.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"daftar bilangan bulat tidak valid: {text}") from exc


def _float_list(text: str) -> list[float]:
    try:
        return [float(t) for t in text.split(",") if t.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"daftar sudut tidak valid: {text}") from exc


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m tapak.photos --issued out/salinan --out samples/photos ...``."""
    ap = argparse.ArgumentParser(
        prog="python -m tapak.photos",
        description="Buat set foto ponsel dan tangkapan layar sintetis dari salinan terbit, "
                    "untuk uji regresi dekoder gambar tanpa ponsel.",
    )
    ap.add_argument("--issued", default="out/salinan", help="folder salinan terbit (berisi manifest.json)")
    ap.add_argument("--out", default="samples/photos", help="folder keluaran gambar dan truth.json")
    ap.add_argument("--seqs", type=_int_list, default=None, help="nomor salinan, mis. 13,7 (bawaan: semua)")
    ap.add_argument("--per-copy", type=int, default=2, help="jumlah gambar per sudut per salinan")
    ap.add_argument("--angles", type=_float_list, default=[0.0, 10.0, 20.0, 30.0],
                    help="sudut pandang foto dalam derajat, mis. 0,10,20,30")
    ap.add_argument("--seed", type=int, default=2026, help="benih acak (hasil selalu sama untuk benih sama)")
    ap.add_argument("--dpi", type=int, default=200, help="resolusi render halaman")
    ap.add_argument("--long-side", type=int, default=1600, help="sisi panjang maksimum gambar (piksel)")
    ap.add_argument("--all-pages", action="store_true", help="semua halaman, bukan hanya halaman 1")
    ap.add_argument("--crop-into-page", action="store_true", help="potong sebagian halaman (uji ketahanan)")
    ap.add_argument("--no-screenshots", action="store_true", help="tanpa tangkapan layar")
    args = ap.parse_args(argv)

    photo_params = PhotoParams(crop_into_page=args.crop_into_page)
    print(f"Membuat foto sintetis dari {args.issued} (benih {args.seed}, sisi panjang {args.long_side} px) ...")
    n_old = len(stale_outputs(args.out))
    try:
        items = make_photo_set(args.issued, args.out, seqs=args.seqs, per_copy=args.per_copy,
                               angles=tuple(args.angles), seed=args.seed, dpi=args.dpi,
                               long_side=args.long_side, all_pages=args.all_pages,
                               screenshots=not args.no_screenshots, photo_params=photo_params)
    except ManifestNotFoundError as exc:
        print(f"Galat: {exc}. Terbitkan salinan dulu dengan 'tapak issue'.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Galat: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Errors raised by this module carry an Indonesian message and no errno; for an
        # operating-system error print an Indonesian sentence with the path instead.
        detail = str(exc) if exc.errno is None else f"gagal membaca atau menulis berkas {exc.filename}"
        print(f"Galat: {detail}", file=sys.stderr)
        return 2
    if n_old:
        print(f"{n_old} gambar lama dari proses sebelumnya dihapus agar folder sesuai truth.json.")
    n_photo = sum(1 for it in items if it["kind"] == KIND_PHOTO)
    n_shot = len(items) - n_photo
    n_copies = len({it["seq"] for it in items})
    print(f"Selesai: {n_photo} foto dan {n_shot} tangkapan layar dari {n_copies} salinan ditulis ke {args.out}")
    print(f"Kebenaran dasar (homografi dan parameter acak): {Path(args.out) / 'truth.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
