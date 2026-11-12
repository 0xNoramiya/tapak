"""Registration work done once (master ink and features, the evidence's features and OCR), the
rescue tries side by side, and the footprint try of tilted photos (research/fotopotong)."""

from __future__ import annotations

import numpy as np
import pytest

from tapak.decoder import rectify
from tapak.decoder.rectify import (_footprint, _prep, _tilted, ecc_refine, evidence_features, feature_homography,
                                   master_features, master_ink, render_page, rescue_decision, rescue_threads,
                                   sift_features)


def test_master_ink_is_prep_of_the_render_and_cached(sample_pdf):
    ink = master_ink(sample_pdf, 0, 60.0)
    assert np.array_equal(ink, _prep(render_page(sample_pdf, 0, 60.0)))
    assert master_ink(sample_pdf, 0, 60.0) is ink and not ink.flags.writeable


def test_features_once_give_the_same_homography(sample_pdf):
    page = render_page(sample_pdf, 0, 100.0)
    img = np.ascontiguousarray(page[200:900, 50:700])
    pts, desc = sift_features(np.clip(page, 0, 255).astype(np.uint8))
    assert len(pts) == len(desc) > 100 and pts.shape[1] == 2
    feats = evidence_features(img)
    assert feats[1] == 1.0
    a = feature_homography(page, img)
    b = feature_homography(page, img, master_features(sample_pdf, 0, 100.0), feats)
    assert a is not None and np.array_equal(a, b)


def test_ecc_refine_with_inks_given_is_the_same(sample_pdf):
    page = render_page(sample_pdf, 0, 60.0)
    img = np.ascontiguousarray(page[40:400, 30:420])
    h0 = np.array([[1.0, 0.0, -28.0], [0.0, 1.0, -41.0], [0.0, 0.0, 1.0]])
    a = ecc_refine(page, img, h0, ((1.0, 20),))
    b = ecc_refine(page, img, h0, ((1.0, 20),), template_ink=master_ink(sample_pdf, 0, 60.0), image_ink=_prep(img))
    assert np.array_equal(a[0], b[0]) and a[1] == b[1]


def test_tesseract_words_read_once(sample_pdf, monkeypatch):
    from tapak.decoder import lines

    calls = []
    real = lines.ocr_words
    monkeypatch.setattr(lines, "ocr_words", lambda image, *a, **k: calls.append(1) or real(image, *a, **k))
    page = render_page(sample_pdf, 0, 100.0)
    words = real(page)
    h = lines.tesseract_homography(page, sample_pdf, 0, 100.0, words=words)
    assert not calls and (h is None or h.shape == (3, 3))


def test_rescue_threads_respect_the_limit(monkeypatch):
    monkeypatch.setenv("TAPAK_WORKERS", "2")
    assert rescue_threads(7) == 2 and rescue_threads(1) == 1
    monkeypatch.delenv("TAPAK_WORKERS")
    assert 1 <= rescue_threads(9) <= 4
    # masters refined side by side stay within RESCUE_PARALLEL_MP megapixels together
    assert rescue_threads(9, 3.9) == 1 and rescue_threads(9, 8.7) == 1
    assert rescue_threads(9, 1.0) == rescue_threads(9)


def _try(page, agreement, dx=0.0, dpi=100.0):
    return {"page": page, "agreement": agreement, "dpi": dpi, "origin": "x", "cc": 0.9,
            "h": np.array([[1.0, 0.0, dx], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])}


def test_rescue_decision():
    centre = np.array([[[100.0, 100.0]]])
    assert rescue_decision([], centre) == (None, "tanpa_pose", None)
    assert rescue_decision([_try(0, -1.0)], centre)[1] == "tanpa_pose"
    best, outcome, rival = rescue_decision([_try(0, 0.9), _try(1, 0.5)], centre)
    assert outcome == "terdaftar" and best["page"] == 0 and rival == 0.5
    assert rescue_decision([_try(0, 0.9), _try(1, 0.88)], centre)[1] == "ambigu"
    assert rescue_decision([_try(0, 0.9), _try(0, 0.89, dx=2.0)], centre)[1] == "terdaftar"  # same pose, 2 px
    assert rescue_decision([_try(0, 0.9), _try(0, 0.89, dx=300.0)], centre)[1] == "ambigu"  # 216 pt away
    assert rescue_decision([_try(0, 0.5)], centre)[1] == "tidak_terverifikasi"


def test_tilted_and_footprint():
    box = np.array([[[200.0, 150.0]], [[0.0, 0.0]], [[400.0, 0.0]], [[400.0, 300.0]], [[0.0, 300.0]]])
    flat = np.array([[0.5, 0.0, 10.0], [0.0, 0.5, 20.0], [0.0, 0.0, 1.0]])
    c, s = np.cos(np.radians(5)), np.sin(np.radians(5))
    turned = np.array([[0.5 * c, -0.5 * s, 10.0], [0.5 * s, 0.5 * c, 20.0], [0.0, 0.0, 1.0]])
    keystone = flat.copy()
    keystone[2, 1] = 2e-4
    assert not _tilted(flat, box, 100.0) and _tilted(turned, box, 100.0) and _tilted(keystone, box, 100.0)
    assert not _tilted(np.zeros((3, 3)), box, 100.0)
    x0, y0, x1, y1 = _footprint(flat, (300, 400), (1200, 900), 0.1)
    assert (x0, y0, x1, y1) == (0, 0, 858, 638)  # page (-20, -40) to (778, 558), plus 79.8 px
    tight = _footprint(np.array([[2.0, 0.0, -200.0], [0.0, 2.0, -100.0], [0.0, 0.0, 1.0]]), (300, 400), (1200, 900), 0.0)
    assert tight == (100, 50, 300, 200)
    assert _footprint(np.zeros((3, 3)), (300, 400), (1200, 900), 0.1) is None


def test_rescue_footprint_tries_only_for_tilted_poses(sample_pdf, monkeypatch):
    """An untilted crop gets no footprint try; turning the rescue's footprint off changes nothing then."""
    page = render_page(sample_pdf, 0, 60.0)
    crop = np.ascontiguousarray(page[300:520, :])
    sizes = [(595.0, 842.0), (595.0, 842.0)]
    log: dict = {}
    first = rectify.rescue_register(crop, sample_pdf, sizes, [], log)
    assert not any(t["origin"].endswith(":jejak") for t in log["tries"])
    monkeypatch.setattr(rectify, "RESCUE_FOOTPRINT", False)
    log2: dict = {}
    second = rectify.rescue_register(crop, sample_pdf, sizes, [], log2)
    assert (first is None) == (second is None) and log["outcome"] == log2["outcome"]
    if first is not None:
        assert np.array_equal(first.h_page_to_img, second.h_page_to_img)


def test_pose_agreement_refuses_a_pose_that_runs_off(sample_pdf):
    """A pose that puts the page centre at a sliver of its resolution cannot be verified (its
    blur would not fit in memory): (-1, 0) instead of an allocation error."""
    from tapak.decoder.rectify import pose_agreement

    ink = master_ink(sample_pdf, 0, 60.0)
    img = np.ascontiguousarray(ink[100:400, 50:400])
    shrink = np.array([[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 1.0]])
    assert pose_agreement(img, None, ink, shrink, 60.0) == (-1.0, 0)
