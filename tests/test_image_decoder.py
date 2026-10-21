"""M3 acceptance: decoding photos and screenshots, collusion composite, insufficient evidence."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from tapak.decoder.accuse import VERDICT_IDENTIFIED, VERDICT_INSUFFICIENT
from tapak.decoder.ch_background import estimate_mixture
from tapak.decoder.image import collect_from_image
from tapak.decoder.rectify import detect_page_quad, order_corners, register, render_page
from tapak.decoder.trace import run_trace
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, ScreenshotParams, photo_jpeg, screenshot_jpeg

PHOTO_CASES = [  # (copy seq, view angle in degrees)
    (13, 0), (7, 5), (1, 10), (20, 15), (5, 20), (11, 25), (13, 30), (7, 30), (16, 30), (3, 30),
]


def _copy_page(issued, seq: int, dpi: int = 200) -> np.ndarray:
    out, manifest = issued
    return render_pages((out / manifest.copies[seq - 1].file).read_bytes(), dpi, [0])[0]


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", np.clip(img, 0, 255).astype(np.uint8))
    assert ok
    return buf.tobytes()


def _double_jpeg(img: np.ndarray, q1: int = 75, q2: int = 65) -> bytes:
    for q in (q1, q2):
        ok, buf = cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, q])
        assert ok
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    return buf.tobytes()


@pytest.mark.slow
def test_photo_set_identifies_correct_copy_up_to_30_degrees(issued, ctx):
    """10 of 10 synthetic phone photos (WhatsApp size, double JPEG) name the right copy."""
    hits = []
    for i, (seq, angle) in enumerate(PHOTO_CASES):
        rng = np.random.default_rng(1000 + i)
        data, meta = photo_jpeg(_copy_page(issued, seq), rng, PhotoParams(angle_deg=float(angle)))
        result = run_trace(collect_from_image(data, ctx), ctx)
        hits.append([c.copy.seq for c in result.accused] == [seq])
        assert result.verdict == VERDICT_IDENTIFIED, (seq, angle, result.summary_lines())
        assert result.accused[0].false_accusation_probability < 1e-6
    assert sum(hits) == 10


@pytest.mark.slow
def test_double_jpeg_screenshots_identify_copy(issued, ctx):
    for i, (seq, dpi) in enumerate([(4, 96.0), (9, 120.0), (17, 150.0)]):
        rng = np.random.default_rng(2000 + i)
        data, _ = screenshot_jpeg(_copy_page(issued, seq), rng, ScreenshotParams(screen_dpi=dpi))
        result = run_trace(collect_from_image(data, ctx), ctx)
        assert [c.copy.seq for c in result.accused] == [seq], result.summary_lines()


@pytest.mark.slow
def test_collusion_top_half_a_bottom_half_b(issued, ctx):
    """A page assembled from the top half of copy A and the bottom half of copy B accuses
    both A and B and nobody else."""
    for a_seq, b_seq in [(4, 15), (2, 9)]:
        a, b = _copy_page(issued, a_seq, 150), _copy_page(issued, b_seq, 150)
        half = a.shape[0] // 2
        composite = np.vstack([a[:half], b[half:]])
        canvas = np.full((composite.shape[0] + 60, composite.shape[1] + 60), 80, np.uint8)
        canvas[30:-30, 30:-30] = composite
        result = run_trace(collect_from_image(_double_jpeg(canvas), ctx), ctx)
        assert sorted(c.copy.seq for c in result.accused) == sorted([a_seq, b_seq]), result.summary_lines()


@pytest.mark.slow
def test_insufficient_evidence_paths(ctx, sample_pdf):
    rng = np.random.default_rng(3000)
    # A photo of the unmarked master carries no fingerprint.
    master_page = render_pages(sample_pdf, 200, [0])[0]
    data, _ = photo_jpeg(master_page, rng, PhotoParams(angle_deg=15.0))
    result = run_trace(collect_from_image(data, ctx), ctx)
    assert result.verdict == VERDICT_INSUFFICIENT and result.accused == []
    # An image that is not this document at all.
    noise = (rng.random((900, 700)) * 255).astype(np.uint8)
    result = run_trace(collect_from_image(_png(noise), ctx), ctx)
    assert result.verdict == VERDICT_INSUFFICIENT and result.accused == []
    text = "\n".join(result.summary_lines())
    for ref in ctx.refs:
        assert ref.nama not in text


def test_detect_page_quad_and_order(sample_pdf):
    page = render_pages(sample_pdf, 100, [0])[0]
    canvas = np.full((page.shape[0] + 200, page.shape[1] + 200), 60, np.uint8)
    canvas[100:-100, 100:-100] = page
    quad = detect_page_quad(canvas.astype(np.float32))
    assert quad is not None
    expected = np.array([[100, 100], [99 + page.shape[1], 100], [99 + page.shape[1], 99 + page.shape[0]],
                         [100, 99 + page.shape[0]]])
    assert np.abs(quad - expected).max() < 6
    shuffled = expected[[2, 0, 3, 1]]
    assert np.array_equal(order_corners(shuffled), expected.astype(float))
    assert detect_page_quad(np.full((300, 300), 128, np.float32)) is None


def test_register_recovers_known_homography(sample_pdf):
    page = render_page(sample_pdf, 0, 120)
    h_true = np.array([[1.05, 0.04, 40.0], [-0.03, 1.02, 30.0], [2e-5, 1e-5, 1.0]])
    size = (int(page.shape[1] * 1.2), int(page.shape[0] * 1.15))
    img = cv2.warpPerspective(page, h_true, size, borderValue=70)
    reg = register(img, sample_pdf, [(595.28, 841.89), (595.28, 841.89)])
    assert reg is not None and reg.page == 0 and reg.correlation > 0.9
    s = reg.dpi / 120.0
    pts = np.array([[[100.0, 100.0]], [[500.0, 900.0]]])
    got = cv2.perspectiveTransform(pts * s, reg.h_page_to_img)
    want = cv2.perspectiveTransform(pts, h_true)
    assert np.abs(got - want).max() < 1.0


def test_estimate_mixture():
    rng = np.random.default_rng(4)
    t = rng.choice([-1.0, 1.0], 3000) * 0.5 + rng.normal(0, 0.2, 3000)
    mu, sigma = estimate_mixture(t)
    assert mu == pytest.approx(0.5, rel=0.05) and sigma == pytest.approx(0.2, rel=0.1)
    mu0, _ = estimate_mixture(rng.normal(0, 0.2, 3000))
    assert mu0 < 0.1
