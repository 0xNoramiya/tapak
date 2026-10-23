"""The registration rescue stage (rectify.rescue_register, research/registrasi): the paper mask of
screen captures, multi-scale template matching, masked and affine ECC, the pose verification,
and the rule that the rescue runs only when the earlier stages find no page."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from tapak.decoder import rectify
from tapak.decoder.rectify import (
    ecc_refine,
    is_screen_capture,
    paper_mask,
    pose_agreement,
    register,
    render_page,
    rescue_register,
    template_poses,
)

A4 = (595.28, 841.89)


def _in_chrome(part: np.ndarray, dark: bool) -> tuple[np.ndarray, int, int]:
    """A page part inside viewer chrome: toolbar, window background, page border."""
    bg, bar = (60, 40) if dark else (210, 238)
    h, w = part.shape
    canvas = np.full((50 + h, w + 80), bg, dtype=np.float32)
    canvas[:40] = bar
    for b in range(4):
        cv2.rectangle(canvas, (10 + 40 * b, 8), (40 + 40 * b, 32), 200 if dark else 90, 2)
    canvas[48:48 + h, 40:40 + w] = part
    cv2.rectangle(canvas, (39, 47), (40 + w, 48 + h), 150, 1)
    return canvas, 40, 48


def _err(h_found: np.ndarray, dpi: float, h_true: np.ndarray, pts_pt: np.ndarray) -> float:
    """Largest image distance between where two page-to-image maps put page points (pt)."""
    def to_img(h, d):
        px = np.hstack([pts_pt * d / 72.0 - 0.5, np.ones((len(pts_pt), 1))]) @ np.asarray(h).T
        return px[:, :2] / px[:, 2:3]
    return float(np.abs(to_img(h_found, dpi) - to_img(h_true, 72.0)).max())


def _crop_truth(dpi: float, x0: int, y0: int, ox: int = 0, oy: int = 0) -> np.ndarray:
    """Truth map (page px at 72 dpi -> image px) of a crop starting at (x0, y0) of a render at dpi,
    placed at (ox, oy) of the image."""
    s = dpi / 72.0
    pt_to_px = np.array([[s, 0.0, 0.5 * s - 0.5], [0.0, s, 0.5 * s - 0.5], [0.0, 0.0, 1.0]])
    return np.array([[1.0, 0.0, ox - x0], [0.0, 1.0, oy - y0], [0.0, 0.0, 1.0]]) @ pt_to_px


def test_paper_mask_finds_the_page_part_in_light_and_dark_chrome(sample_pdf):
    page = render_page(sample_pdf, 0, 60)
    part = page[200:420]
    for dark in (True, False):
        img, ox, oy = _in_chrome(part, dark)
        mask = paper_mask(img)
        assert mask is not None
        ys, xs = np.nonzero(mask)
        assert abs(xs.min() - ox) <= 2 and abs(ys.min() - oy) <= 2
        assert abs(xs.max() + 1 - (ox + part.shape[1])) <= 2 and abs(ys.max() + 1 - (oy + part.shape[0])) <= 2
    assert paper_mask(page) is None  # no chrome: the whole image is page


def test_screen_capture_test_and_photo_gets_no_mask(sample_pdf):
    page = render_page(sample_pdf, 0, 60)
    assert is_screen_capture(page)
    light = np.linspace(0.6, 1.0, page.shape[1], dtype=np.float32)[None, :]
    photo = page * light + np.random.default_rng(1).normal(0, 2, page.shape).astype(np.float32)
    assert not is_screen_capture(photo)
    assert paper_mask(photo) is None
    assert not is_screen_capture(np.full((50, 50), 40.0, dtype=np.float32))  # no paper at all


def test_template_poses_finds_a_crop_by_scale_and_offset(sample_pdf):
    dpi = 50.0
    page = render_page(sample_pdf, 0, dpi)
    y0 = 300
    crop = page[y0:y0 + 230]
    poses = template_poses(rectify._prep(crop), None, sample_pdf, 2, 100.0)
    score, pg, h0 = poses[0]
    assert pg == 0 and score > 0.6
    pts = np.array([[150.0, (y0 + 60) * 72 / dpi], [450.0, (y0 + 180) * 72 / dpi]])
    assert _err(h0, 100.0, _crop_truth(dpi, 0, y0), pts) < 3.0  # within the fine search step


def test_ecc_refine_with_mask_ignores_chrome_and_affine_keeps_no_perspective(sample_pdf):
    dpi = 60.0
    page = render_page(sample_pdf, 0, dpi)
    y0 = 250
    img, ox, oy = _in_chrome(page[y0:y0 + 260], dark=True)
    mask = paper_mask(img)
    truth = _crop_truth(dpi, 0, y0, ox, oy)
    h_true_dpi = truth @ np.linalg.inv(_crop_truth(dpi, 0, 0))  # page px at dpi -> image px
    start = h_true_dpi @ np.array([[1.0, 0.0, 2.0], [0.0, 1.0, -2.0], [0.0, 0.0, 1.0]])
    work = np.where(mask > 0, img, 255.0).astype(np.float32)
    h, cc = ecc_refine(page, work, start, ((0.5, 40), (1.0, 15)), mask=mask, affine=True)
    assert cc > 0.9
    assert np.allclose(h[2, :2], 0.0)
    pts = np.array([[200.0, (y0 + 50) * 72 / dpi], [400.0, (y0 + 200) * 72 / dpi]])
    assert _err(h, dpi, truth, pts) < 0.5


def test_pose_agreement_is_high_at_the_true_pose_and_low_elsewhere(sample_pdf):
    dpi = 60.0
    page = render_page(sample_pdf, 0, dpi)
    y0 = 250
    crop = page[y0:y0 + 260]
    ink = rectify._prep(crop)
    master = rectify._prep(render_page(sample_pdf, 0, 100.0))
    s = 100.0 / dpi
    h_true = np.array([[1 / s, 0.0, 0.0], [0.0, 1 / s, -y0], [0.0, 0.0, 1.0]])  # page px at 100 dpi -> crop px
    good, n = pose_agreement(ink, None, master, h_true, 100.0)
    off = h_true @ np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 40.0], [0.0, 0.0, 1.0]])  # two text lines down
    bad, _ = pose_agreement(ink, None, master, off, 100.0)
    assert good > 0.8 > 0.5 > bad
    assert n > 10_000
    none, n0 = pose_agreement(ink, None, master, np.array([[1, 0, 1e5], [0, 1, 1e5], [0, 0, 1.0]]), 100.0)
    assert none == -1.0 and n0 == 0


def test_pose_agreement_tells_aligned_words_from_aligned_lines(sample_pdf):
    """Lines of another paragraph at the same heights agree little after the row detrending."""
    dpi = 60.0
    page = render_page(sample_pdf, 0, dpi)
    crop = page[250:510]
    ink = rectify._prep(crop)
    master = rectify._prep(render_page(sample_pdf, 0, 100.0))
    s = 100.0 / dpi
    h_true = np.array([[1 / s, 0.0, 0.0], [0.0, 1 / s, -250.0], [0.0, 0.0, 1.0]])
    pitch = 15.9 * 100.0 / 72.0  # one row pitch of the sample, page px at 100 dpi
    other = h_true @ np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 4 * pitch], [0.0, 0.0, 1.0]])
    good, _ = pose_agreement(ink, None, master, h_true, 100.0)
    lines, _ = pose_agreement(ink, None, master, other, 100.0)
    assert good > 0.8 and lines < 0.5


def test_local_scales_and_pose_sanity():
    points = np.array([[[10.0, 10.0]], [[300.0, 10.0]], [[300.0, 200.0]], [[10.0, 200.0]]])
    h = np.diag([0.5, 0.5, 1.0])  # 100 dpi page px -> image px at 50 dpi
    assert np.allclose(rectify.local_scales(h, points, 100.0), 50.0 / 72.0)
    tilt = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [2e-4, 0.0, 1.0]])
    sc = rectify.local_scales(tilt, points, 100.0)
    assert sc.max() / sc.min() > 1.05
    assert rectify.pose_is_sane(h, 100.0, h @ np.diag([1.05, 1.05, 1.0]), 100.0, points)
    assert not rectify.pose_is_sane(h, 100.0, h @ np.diag([2.0, 2.0, 1.0]), 100.0, points)  # blown up
    blown = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [1e-3, 0.0, 1.0]])  # local scale 4x across the part
    assert not rectify.pose_is_sane(h, 100.0, blown, 100.0, points)  # local scales spread too wide
    beyond = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [4e-3, 0.0, 1.0]])  # horizon at image x = 125
    assert np.isnan(rectify.local_scales(beyond, points, 100.0)).any()
    assert not rectify.pose_is_sane(h, 100.0, beyond, 100.0, points)


def test_rescue_registers_a_chrome_crop_the_earlier_stages_miss(sample_pdf):
    """A 40 % crop in dark viewer chrome at 48 dpi: the stages before the rescue are pulled off by
    the chrome; the rescue finds the page with the mask and verifies the pose."""
    dpi = 48.0
    page = render_page(sample_pdf, 0, dpi, supersample=1)
    y0 = 180
    img, ox, oy = _in_chrome(page[y0:y0 + 225], dark=True)
    truth = _crop_truth(dpi, 0, y0, ox, oy)
    log: dict = {}
    reg = rescue_register(img, sample_pdf, [A4, A4], [], log)
    assert reg is not None, log
    assert reg.page == 0 and reg.method.startswith("penyelamat:")
    assert log["outcome"] == "terdaftar" and log["mask"] and log["screen"]
    assert log["agreement"] >= rectify.RESCUE_MIN_AGREEMENT
    pts = np.array([[150.0, (y0 + 40) * 72 / dpi], [450.0, (y0 + 200) * 72 / dpi]])
    assert _err(reg.h_page_to_img, reg.dpi, truth, pts) < 1.5
    # chrome is not page: the toolbar region mapped onto the page is not valid
    assert not reg.valid[: int((y0 - 30) * reg.dpi / dpi)].any()


def test_rescue_refuses_what_it_cannot_verify(sample_pdf):
    rng = np.random.default_rng(3)
    noise = cv2.GaussianBlur(rng.uniform(0, 255, (400, 300)).astype(np.float32), (0, 0), 2)
    log: dict = {}
    assert rescue_register(noise, sample_pdf, [A4, A4], [], log) is None
    assert log["outcome"] in ("tanpa_pose", "tidak_terverifikasi", "ambigu")
    blank = np.full((300, 400), 255.0, dtype=np.float32)
    assert rescue_register(blank, sample_pdf, [A4, A4], [], {}) is None


def test_register_runs_the_rescue_only_when_the_earlier_stages_fail(sample_pdf, monkeypatch):
    page = render_page(sample_pdf, 0, 120)
    h_true = np.array([[1.05, 0.04, 40.0], [-0.03, 1.02, 30.0], [2e-5, 1e-5, 1.0]])
    img = cv2.warpPerspective(page, h_true, (int(page.shape[1] * 1.2), int(page.shape[0] * 1.15)), borderValue=70)
    called = []
    monkeypatch.setattr(rectify, "rescue_register", lambda *a, **k: called.append(1))
    diag: dict = {}
    assert register(img, sample_pdf, [A4, A4], diag=diag) is not None
    assert diag["outcome"] == "terdaftar" and not called and "rescue" not in diag
    monkeypatch.undo()
    dpi = 48.0
    small = render_page(sample_pdf, 0, dpi, supersample=1)
    crop, _, _ = _in_chrome(small[180:405], dark=True)
    off: dict = {}
    on: dict = {}
    before = register(crop, sample_pdf, [A4, A4], diag=off, rescue=False)
    after = register(crop, sample_pdf, [A4, A4], diag=on)
    assert off["outcome"] != "terdaftar" and before is None and "rescue" not in off
    assert after is not None and on["rescue"]["outcome"] == "terdaftar" and after.method.startswith("penyelamat:")


@pytest.mark.parametrize("dark", [True, False])
def test_paper_mask_survives_messenger_jpeg(sample_pdf, dark):
    page = render_page(sample_pdf, 0, 48, supersample=1)
    img, ox, oy = _in_chrome(page[100:380], dark)
    for q in (70, 60):
        ok, buf = cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, q])
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE).astype(np.float32)
    mask = paper_mask(img)
    assert mask is not None
    ys, xs = np.nonzero(mask)
    assert abs(xs.min() - ox) <= 2 and abs(ys.min() - oy) <= 2
