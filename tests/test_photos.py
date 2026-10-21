"""Synthetic photo and screenshot set (M2): determinism, ground truth geometry, JPEG output."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from tapak.marker.render import render_pages
from tapak.photos import (
    PhotoParams,
    ScreenshotParams,
    apply_homography,
    decode_jpeg,
    main,
    make_photo_set,
    photo,
    photo_jpeg,
    screenshot,
    screenshot_jpeg,
    stale_outputs,
    view_angle_deg,
)

# Small frames keep the tests fast; the geometry does not depend on the size.
SMALL = PhotoParams(sensor_long_side=1400, long_side=1000)

# (outside the page, inside the page) pairs in page-relative coordinates; the inside points
# lie in the blank page margin of samples/nota_dinas.pdf.
EDGE_PAIRS = (
    [((-0.05, y), (0.05, y)) for y in (0.1, 0.5, 0.9)]
    + [((1.05, y), (0.95, y)) for y in (0.1, 0.5, 0.9)]
    + [((x, -0.04), (x, 0.03)) for x in (0.06, 0.94)]
    + [((x, 1.04), (x, 0.97)) for x in (0.06, 0.94)]
)


@pytest.fixture(scope="module")
def page(sample_pdf) -> np.ndarray:
    return render_pages(sample_pdf, 100, [0])[0]


@pytest.fixture(scope="module")
def page200(sample_pdf) -> np.ndarray:
    return render_pages(sample_pdf, 200, [0])[0]


def _corners(img: np.ndarray) -> np.ndarray:
    h, w = img.shape
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=float)


def _to_page(rel: tuple[float, float], page: np.ndarray) -> list[float]:
    h, w = page.shape
    return [rel[0] * (w - 1), rel[1] * (h - 1)]


def _patch_mean(img: np.ndarray, xy: np.ndarray, r: int = 2) -> float | None:
    x, y = int(round(xy[0])), int(round(xy[1]))
    h, w = img.shape
    if not (r + 1 <= x < w - r - 1 and r + 1 <= y < h - r - 1):
        return None
    return float(img[y - r:y + r + 1, x - r:x + r + 1].mean())


def _pose_columns(meta: dict) -> tuple[np.ndarray, np.ndarray]:
    """Columns r1, r2 of inv(K) @ H: the page axes in camera coordinates (up to scale)."""
    m = np.linalg.solve(np.array(meta["camera_matrix"]), np.array(meta["homography"]))
    return m[:, 0], m[:, 1]


def _subpixel_offset(img: np.ndarray, page: np.ndarray, homography: list) -> np.ndarray:
    """Shift (dx, dy) in output px of the image content relative to where ``homography`` puts it.

    The page is forward-warped with T @ H for unit shifts T around zero, compared with the
    image by normalized cross-correlation of high-passed pixels inside the page, and a
    parabola through the three scores per axis gives the sub-pixel peak.
    """
    def highpass(a: np.ndarray) -> np.ndarray:
        a = a.astype(np.float32)
        return a - cv2.GaussianBlur(a, (0, 0), 4)

    hom = np.asarray(homography, dtype=float)
    h, w = img.shape
    inside = cv2.warpPerspective(np.ones(page.shape, np.uint8), hom, (w, h), flags=cv2.INTER_NEAREST)
    inside = cv2.erode(inside, np.ones((31, 31), np.uint8)) > 0  # page interior, away from its edge
    target = highpass(img)[inside]
    blurred = cv2.GaussianBlur(page.astype(np.float32), (0, 0), 1.0)

    def score(dx: float, dy: float) -> float:
        shift = np.array([[1.0, 0, dx], [0, 1.0, dy], [0, 0, 1.0]])
        pred = highpass(cv2.warpPerspective(blurred, shift @ hom, (w, h)))[inside]
        return float(pred @ target / math.sqrt((pred @ pred) * (target @ target)))

    s0 = score(0, 0)
    sx_m, sx_p, sy_m, sy_p = score(-1, 0), score(1, 0), score(0, -1), score(0, 1)
    return np.array([0.5 * (sx_m - sx_p) / (sx_m - 2 * s0 + sx_p),
                     0.5 * (sy_m - sy_p) / (sy_m - 2 * s0 + sy_p)])


def _angle_from_homography(homography: list, page_size: list) -> float:
    """View angle (degrees) estimated from the homography alone (no camera matrix).

    Model: K = [[f, 0, cx], [0, f, cy], [0, 0, 1]] with square pixels; the principal point
    (cx, cy) is where the page center lands, because the generator aims the camera axis at
    the page center. The columns m1, m2 of inv(K) @ H are the page axes, so they must be
    orthogonal and equally long; both conditions are linear in g = 1/f^2 and solved by
    least squares (as in Zhang's calibration). The angle follows from the normal m1 x m2.
    """
    hom = np.asarray(homography, dtype=float)
    pw, ph = page_size
    cx, cy = apply_homography(hom, np.array([[(pw - 1) / 2, (ph - 1) / 2]]))[0]
    u, v, w = hom[0] - cx * hom[2], hom[1] - cy * hom[2], hom[2]
    if np.allclose(w[:2], 0.0, atol=1e-12):
        return 0.0  # no projective term: frontal view
    a = np.array([u[0] * u[1] + v[0] * v[1], u[0] ** 2 + v[0] ** 2 - u[1] ** 2 - v[1] ** 2])
    c = np.array([w[0] * w[1], w[0] ** 2 - w[1] ** 2])
    g = -(a @ c) / (a @ a)
    m1 = np.array([u[0] * math.sqrt(g), v[0] * math.sqrt(g), w[0]])
    m2 = np.array([u[1] * math.sqrt(g), v[1] * math.sqrt(g), w[1]])
    normal = np.cross(m1, m2)
    return math.degrees(math.acos(min(1.0, abs(normal[2]) / np.linalg.norm(normal))))


def _fake_issued(src: Path, dst: Path, edit=None, copy_seqs: tuple[int, ...] = ()) -> Path:
    """A copy of the issued folder with an optionally edited manifest and only some PDFs."""
    data = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    if edit is not None:
        edit(data)
    dst.mkdir(parents=True)
    (dst / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    for c in data["copies"]:
        if c["seq"] in copy_seqs:
            shutil.copy(src / c["file"], dst / c["file"])
    return dst


def test_photo_is_deterministic(page):
    data_a, meta_a = photo_jpeg(page, np.random.default_rng(7), SMALL)
    data_b, meta_b = photo_jpeg(page, np.random.default_rng(7), SMALL)
    assert data_a == data_b
    assert meta_a == meta_b
    data_c, _ = photo_jpeg(page, np.random.default_rng(8), SMALL)
    assert data_c != data_a
    img, meta = photo(page, np.random.default_rng(7), SMALL)
    assert np.array_equal(img, decode_jpeg(data_a))
    assert meta == meta_a
    assert json.loads(json.dumps(meta)) == meta  # ground truth is plain JSON


def test_photo_meta_records_random_parameters(page):
    _, meta = photo_jpeg(page, np.random.default_rng(3), SMALL)
    drawn = meta["params"]
    for key in ("view_angle_deg", "tilt_axis_deg", "roll_deg", "fill", "focal_rel", "crop_px",
                "desk_level", "light_gradient", "shadow_depth", "vignette", "blur_sigma_px", "motion_px",
                "noise_read", "gamma", "jpeg_quality_1", "jpeg_quality_2", "downscale", "paper_albedo",
                "exposure", "sharpen", "highlight_clip_frac"):
        assert key in drawn, key
    assert 0.0 <= drawn["view_angle_deg"] <= 30.0
    assert 0.5 <= drawn["blur_sigma_px"] <= 1.5
    assert 75 <= drawn["jpeg_quality_1"] <= 85 and 65 <= drawn["jpeg_quality_2"] <= 75
    assert drawn["downscale"] <= 1.0
    assert 0.90 <= drawn["exposure"] <= 1.40 and 0.0 <= drawn["sharpen"] <= 0.8
    assert 0.0 <= drawn["highlight_clip_frac"] <= 1.0
    assert meta["page_size"] == [page.shape[1], page.shape[0]]
    hom = np.array(meta["homography"])
    assert hom.shape == (3, 3)
    # Normalized: H[2, 2] = 1, so the last column is where page pixel (0, 0) lands.
    assert hom[2, 2] == 1.0
    assert np.allclose(apply_homography(hom, np.array([[0.0, 0.0]]))[0], hom[:2, 2])


def test_motion_blur_is_applied_whenever_recorded(page):
    """A short motion blur changes the pixels, so the recorded motion_px is the truth."""
    still = replace(SMALL, angle_deg=10, motion_px=(0.0, 0.0))
    moved = replace(SMALL, angle_deg=10, motion_px=(0.3, 0.3))
    data_still, meta_still = photo_jpeg(page, np.random.default_rng(9), still)
    data_moved, meta_moved = photo_jpeg(page, np.random.default_rng(9), moved)
    assert meta_still["params"]["motion_px"] == 0.0 and meta_moved["params"]["motion_px"] == 0.3
    assert data_still != data_moved


def test_overexposed_paper_clips_to_white(page):
    img, meta = photo(page, np.random.default_rng(0), replace(SMALL, angle_deg=10, exposure=(1.4, 1.4)))
    assert meta["params"]["highlight_clip_frac"] > 0.01
    assert int(img.max()) == 255


@pytest.mark.parametrize("angle", [0, 15, 30])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_photo_homography_matches_content(page, angle, seed):
    params = replace(SMALL, angle_deg=angle)
    img, meta = photo(page, np.random.default_rng(seed), params)
    h, w = img.shape
    assert max(h, w) <= params.long_side
    assert meta["image_size"] == [w, h]
    corners = apply_homography(meta["homography"], _corners(page))
    assert np.all(corners >= 0) and np.all(corners[:, 0] <= w - 1) and np.all(corners[:, 1] <= h - 1)

    tested = 0
    for outside, inside in EDGE_PAIRS:
        assert page[int(_to_page(inside, page)[1]), int(_to_page(inside, page)[0])] >= 250  # blank margin
        pts = apply_homography(meta["homography"], np.array([_to_page(outside, page), _to_page(inside, page)]))
        paper, background = _patch_mean(img, pts[1]), _patch_mean(img, pts[0])
        assert paper is not None
        if background is None:  # cropped away together with the outer margin
            continue
        assert paper > background + 25, (outside, paper, background)
        tested += 1
    assert tested >= 2


def test_homography_is_subpixel_exact(page, page200):
    cases = [
        (page, photo(page, np.random.default_rng(11), replace(SMALL, angle_deg=25))),
        (page, photo(page, np.random.default_rng(3), replace(SMALL, angle_deg=30))),
        # 200 dpi into a small frame: the page is shrunk before the warp.
        (page200, photo(page200, np.random.default_rng(5), replace(SMALL, angle_deg=15))),
        (page, screenshot(page, np.random.default_rng(11), ScreenshotParams(render_dpi=100, screen_dpi=80))),
        (page200, screenshot(page200, np.random.default_rng(2),
                             ScreenshotParams(render_dpi=200, chrome=True, long_side=1000))),
    ]
    for src, (img, meta) in cases:
        offset = _subpixel_offset(img, src, meta["homography"])
        assert np.all(np.abs(offset) < 0.1), (meta["kind"], offset)

    # The estimator is sensitive: a homography that is off by (0.3, -0.2) px is detected.
    img, meta = cases[0][1]
    wrong = np.array([[1.0, 0, 0.3], [0, 1.0, -0.2], [0, 0, 1.0]]) @ np.array(meta["homography"])
    assert np.allclose(_subpixel_offset(img, page, wrong), [-0.3, 0.2], atol=0.08)


@pytest.mark.parametrize("angle", [0, 10, 20, 30])
def test_requested_view_angle_is_respected(page, angle):
    for seed in range(4):
        _, meta = photo_jpeg(page, np.random.default_rng(100 + seed), replace(SMALL, angle_deg=angle))
        r1, r2 = _pose_columns(meta)
        # A true pinhole view of a plane: the page axes are orthogonal and equally scaled.
        assert abs(r1 @ r2) / (np.linalg.norm(r1) * np.linalg.norm(r2)) < 1e-9
        assert np.linalg.norm(r1) == pytest.approx(np.linalg.norm(r2), rel=1e-9)
        normal = np.cross(r1, r2)
        estimated = np.degrees(np.arccos(abs(normal[2]) / np.linalg.norm(normal)))
        assert estimated == pytest.approx(angle, abs=1e-6)
        assert view_angle_deg(meta["homography"], meta["camera_matrix"]) == pytest.approx(angle, abs=1e-6)
        # Independent estimate from H alone; the residual comes from the x and y output
        # scales differing by less than 0.1 % after rounding the output size.
        assert _angle_from_homography(meta["homography"], meta["page_size"]) == pytest.approx(angle, abs=0.5)
        hom = np.array(meta["homography"])
        if angle == 0:  # frontal view: no projective distortion at all
            assert np.allclose(hom[2, :2] / hom[2, 2], 0.0, atol=1e-12)


def test_drawn_angle_stays_below_maximum(page):
    for seed in range(6):
        _, meta = photo_jpeg(page, np.random.default_rng(seed), replace(SMALL, max_angle_deg=20))
        estimated = view_angle_deg(meta["homography"], meta["camera_matrix"])
        assert 0.0 <= estimated <= 20.0 + 1e-6
        assert estimated == pytest.approx(meta["view_angle_deg"], abs=1e-6)


def test_crop_into_page_hides_part_of_the_page(page):
    for seed in range(4):
        img, meta = photo(page, np.random.default_rng(seed), replace(SMALL, angle_deg=10, crop_into_page=True))
        h, w = img.shape
        corners = apply_homography(meta["homography"], _corners(page))
        outside = (corners[:, 0] < 0) | (corners[:, 0] > w - 1) | (corners[:, 1] < 0) | (corners[:, 1] > h - 1)
        assert outside.any()
        assert meta["params"]["crop_into_page_sides"]


def test_photo_outputs_jpeg_and_long_side_is_a_parameter(page):
    data, meta = photo_jpeg(page, np.random.default_rng(5), PhotoParams(sensor_long_side=1200, long_side=2400))
    assert data[:3] == b"\xff\xd8\xff" and data[-2:] == b"\xff\xd9"
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.ndim == 2 and img.dtype == np.uint8
    assert 1600 < max(img.shape) <= 2400  # the camera frame grows to the requested limit
    small = decode_jpeg(photo_jpeg(page, np.random.default_rng(5), replace(SMALL, long_side=600))[0])
    assert max(small.shape) <= 600


def test_screenshot_size_matches_dpi(page200):
    params = ScreenshotParams(render_dpi=200, screen_dpi=120, chrome=False)
    data, meta = screenshot_jpeg(page200, np.random.default_rng(1), params)
    assert data[:3] == b"\xff\xd8\xff"
    img = decode_jpeg(data)
    h, w = page200.shape
    assert img.shape == (round(h * 0.6), round(w * 0.6))
    assert meta["effective_dpi"] == pytest.approx(120, rel=2e-3)
    assert meta["scale"] == pytest.approx([0.6, 0.6], rel=2e-3)
    corners = apply_homography(meta["homography"], _corners(page200))
    assert np.allclose(corners, _corners(img), atol=0.6)
    hom = np.array(meta["homography"])
    assert np.allclose(hom[2], [0, 0, 1]) and hom[0, 1] == 0 and hom[1, 0] == 0  # no perspective
    assert screenshot_jpeg(page200, np.random.default_rng(1), params)[0] == data


def test_screenshot_with_chrome_and_whatsapp_limit(page200):
    img, meta = screenshot(page200, np.random.default_rng(4), ScreenshotParams(chrome=True, screen_dpi=150))
    assert meta["params"]["chrome"] is True
    assert meta["scale"] == pytest.approx([0.75, 0.75], rel=2e-3)
    ox, oy = meta["offset"]
    assert ox > 10 and oy > 30  # page sits below a toolbar and inside a gray background
    assert img.shape[0] > round(page200.shape[0] * 0.75) and img.shape[1] > round(page200.shape[1] * 0.75)
    inside = apply_homography(meta["homography"], np.array([[0.05 * page200.shape[1], 0.5 * page200.shape[0]]]))[0]
    assert _patch_mean(img, inside) > 240
    viewer_background = _patch_mean(img, np.array([ox / 2, img.shape[0] / 2]), r=1)
    assert viewer_background < 230  # gray, not paper

    limited, lmeta = screenshot(page200, np.random.default_rng(4), ScreenshotParams(screen_dpi=150, long_side=1000))
    assert max(limited.shape) <= 1000
    assert lmeta["effective_dpi"] < 150
    corners = apply_homography(lmeta["homography"], _corners(page200))
    assert np.all(corners >= -0.5) and np.all(corners[:, 0] <= limited.shape[1]) and np.all(corners[:, 1] <= limited.shape[0])
    for seed in range(5):
        _, m = screenshot_jpeg(page200, np.random.default_rng(seed))
        assert 96 <= m["screen_dpi"] <= 150
        assert 68 <= m["params"]["jpeg_quality_1"] <= 72 and 58 <= m["params"]["jpeg_quality_2"] <= 62


FAST = PhotoParams(sensor_long_side=1200)


def test_make_photo_set_writes_files_and_truth_without_names(issued, tmp_path):
    issued_dir, manifest = issued
    out = tmp_path / "photos"
    items = make_photo_set(issued_dir, out, seqs=[7, 3], per_copy=1, angles=(0, 30), seed=2026, dpi=150,
                           long_side=900, photo_params=FAST)
    expected = {f"photo_s{s:03d}_p1_a{a}_0.jpg" for s in (7, 3) for a in (0, 30)}
    expected |= {f"screenshot_s{s:03d}_p1_0.jpg" for s in (7, 3)}
    assert {it["file"] for it in items} == expected
    assert {p.name for p in out.iterdir()} == expected | {"truth.json"}

    text = (out / "truth.json").read_text(encoding="utf-8")
    truth = json.loads(text)
    assert truth["doc_hash"] == manifest.doc_hash and truth["items"] == items
    assert text.isascii()
    for c in manifest.copies:  # no name, recipient id or issued file name (which holds the id)
        assert c.recipient.nama not in text
        assert c.recipient.recipient_id not in text
        assert c.file not in text
    assert "nama" not in text and "recipient" not in text and "Penerima" not in text

    by_seq = {c.seq: c for c in manifest.copies}
    for it in items:
        data = (out / it["file"]).read_bytes()
        assert data[:3] == b"\xff\xd8\xff"
        img = decode_jpeg(data)
        assert max(img.shape) <= 900 and it["image_size"] == [img.shape[1], img.shape[0]]
        assert it["copy_id"] == by_seq[it["seq"]].copy_id and it["page"] == 1
        assert np.array(it["homography"]).shape == (3, 3) and "params" in it
        if it["kind"] == "photo":
            assert view_angle_deg(it["homography"], it["camera_matrix"]) == pytest.approx(it["angle"], abs=1e-6)
            assert _angle_from_homography(it["homography"], it["page_size"]) == pytest.approx(it["angle"], abs=0.5)
        else:
            assert it["kind"] == "screenshot" and it["angle"] is None

    # One generator per file: a subset reproduces exactly the same files.
    again = tmp_path / "again"
    make_photo_set(issued_dir, again, seqs=[3], per_copy=1, angles=(30,), seed=2026, dpi=150, long_side=900,
                   photo_params=FAST, screenshots=False)
    assert (again / "photo_s003_p1_a30_0.jpg").read_bytes() == (out / "photo_s003_p1_a30_0.jpg").read_bytes()

    with pytest.raises(ValueError, match="tidak ada di manifest"):
        make_photo_set(issued_dir, tmp_path / "bad", seqs=[999])


def test_make_photo_set_all_pages(issued, tmp_path):
    issued_dir, _ = issued
    out = tmp_path / "all"
    items = make_photo_set(issued_dir, out, seqs=[4], per_copy=1, angles=(10,), dpi=100, long_side=700,
                           all_pages=True, photo_params=FAST)
    pages = sorted({it["page"] for it in items})
    assert pages == [1, 2]  # samples/nota_dinas.pdf has two pages
    for page_no in pages:
        assert (out / f"photo_s004_p{page_no}_a10_0.jpg").exists()
        assert (out / f"screenshot_s004_p{page_no}_0.jpg").exists()
    assert len(items) == 4


def test_make_photo_set_checks_inputs(issued, tmp_path):
    issued_dir, _ = issued
    bad_inputs = [({"dpi": 0}, "resolusi render"), ({"dpi": 5000}, "resolusi render"),
                  ({"long_side": 0}, "sisi panjang"), ({"long_side": -5}, "sisi panjang"),
                  ({"seed": -1}, "benih acak"), ({"per_copy": -1}, "tidak boleh negatif"),
                  ({"angles": (10, 85)}, "sudut pandang")]
    for kwargs, message in bad_inputs:
        with pytest.raises(ValueError, match=message):
            make_photo_set(issued_dir, tmp_path / "x", seqs=[1], **kwargs)
    assert not (tmp_path / "x").exists()  # nothing is written before the inputs are checked
    with pytest.raises(ValueError, match="sisi panjang"):
        photo_jpeg(np.full((100, 80), 255, np.uint8), np.random.default_rng(0), PhotoParams(long_side=10))
    with pytest.raises(ValueError, match="resolusi render"):
        screenshot_jpeg(np.full((100, 80), 255, np.uint8), np.random.default_rng(0), ScreenshotParams(render_dpi=0))

    # Repeated seqs and angles are produced once, so truth.json never lists a file twice.
    items = make_photo_set(issued_dir, tmp_path / "dup", seqs=[5, 5], per_copy=1, angles=(10, 10.0), dpi=100,
                           long_side=600, screenshots=False, photo_params=FAST)
    assert [it["file"] for it in items] == ["photo_s005_p1_a10_0.jpg"]


def test_make_photo_set_checks_manifest_and_copy_files(issued, tmp_path):
    issued_dir, manifest = issued
    out = tmp_path / "out"
    out.mkdir()
    (out / "photo_s001_p1_a0_0.jpg").write_bytes(b"old")  # must survive every refused run

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{bukan json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.json rusak"):
        make_photo_set(broken, out)
    (broken / "manifest.json").write_text('{"copies": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.json rusak"):
        make_photo_set(broken, out)

    def set_file(name: str):
        def edit(data: dict) -> None:
            data["copies"][0]["file"] = name
        return edit

    outside = tmp_path / "rahasia.pdf"
    shutil.copy(issued_dir / manifest.copies[0].file, outside)
    for i, name in enumerate([str(outside), "../rahasia.pdf", "sub/" + manifest.copies[0].file, ".."]):
        tampered = _fake_issued(issued_dir, tmp_path / f"tampered{i}", set_file(name))
        with pytest.raises(ValueError, match="nama berkas salinan tidak valid"):
            make_photo_set(tampered, out, seqs=[1])

    missing = _fake_issued(issued_dir, tmp_path / "missing", copy_seqs=(1,))
    with pytest.raises(FileNotFoundError, match="berkas salinan tidak ditemukan"):
        make_photo_set(missing, out, seqs=[1, 2])

    swapped = _fake_issued(issued_dir, tmp_path / "swapped")
    shutil.copy(issued_dir / manifest.copies[1].file, swapped / manifest.copies[0].file)  # copy 2 posing as 1
    with pytest.raises(ValueError, match="sha256 berbeda"):
        make_photo_set(swapped, out, seqs=[1])

    assert (out / "photo_s001_p1_a0_0.jpg").read_bytes() == b"old"


def test_make_photo_set_replaces_old_outputs(issued, tmp_path):
    issued_dir, _ = issued
    out = tmp_path / "out"
    out.mkdir()
    stale = ["photo_s002_p2_a10_0.jpg", "screenshot_s009_p1_1.jpg", "photo_s003_p1_a7.5_0.jpg"]
    for name in stale:
        (out / name).write_bytes(b"old")
    for name in ("catatan.txt", "photo_liburan.jpg"):
        (out / name).write_text("milik pengguna", encoding="utf-8")
    (out / "truth.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in stale_outputs(out)] == sorted(stale)

    items = make_photo_set(issued_dir, out, seqs=[2], per_copy=1, angles=(0,), dpi=100, long_side=600,
                           screenshots=False, photo_params=FAST)
    names = {p.name for p in out.iterdir()}
    assert names == {"photo_s002_p1_a0_0.jpg", "truth.json", "catatan.txt", "photo_liburan.jpg"}
    assert json.loads((out / "truth.json").read_text(encoding="utf-8"))["items"] == items


def test_main_cli(issued, tmp_path, capsys):
    issued_dir, manifest = issued
    out = tmp_path / "cli"
    out.mkdir()
    (out / "screenshot_s011_p1_0.jpg").write_bytes(b"old")
    code = main(["--issued", str(issued_dir), "--out", str(out), "--seqs", "2", "--per-copy", "1",
                 "--angles", "20", "--dpi", "100", "--long-side", "800", "--no-screenshots"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "Selesai: 1 foto dan 0 tangkapan layar" in printed
    assert "1 gambar lama" in printed
    assert (out / "photo_s002_p1_a20_0.jpg").exists() and (out / "truth.json").exists()
    assert not (out / "screenshot_s011_p1_0.jpg").exists()

    assert main(["--issued", str(tmp_path / "kosong"), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "manifest.json tidak ditemukan" in err and "tapak issue" in err
    assert main(["--issued", str(issued_dir), "--out", str(out), "--seqs", "999"]) == 2
    assert "tidak ada di manifest" in capsys.readouterr().err

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("[1, 2", encoding="utf-8")
    assert main(["--issued", str(broken), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "manifest.json rusak" in err and "tapak issue" not in err

    missing = _fake_issued(issued_dir, tmp_path / "missing")
    assert main(["--issued", str(missing), "--out", str(out), "--seqs", "1"]) == 2
    err = capsys.readouterr().err
    assert "berkas salinan tidak ditemukan" in err and "tapak issue" not in err and "Errno" not in err

    for flag, value, message in [("--dpi", "0", "resolusi render"), ("--long-side", "0", "sisi panjang"),
                                 ("--seed", "-1", "benih acak")]:
        assert main(["--issued", str(issued_dir), "--out", str(out), "--seqs", "1", flag, value]) == 2
        assert message in capsys.readouterr().err
