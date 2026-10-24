"""Word groups of image evidence under the Student t row model (research/geser)."""

from __future__ import annotations

import numpy as np
import pytest

from tapak.decoder import ch_shift
from tapak.decoder.ch_shift import (WORD_MODELS, ImageWords, joint_word_llrs, quality_scales, robust_word_llrs)


def _rows(rng, n_rows=40, g=8, delta=0.07, sigma=0.02, slip=0.0):
    rows, signs = [], []
    for _ in range(n_rows):
        x = np.sort(rng.uniform(0, 400, g))
        s = rng.choice([-1, 1], g)
        d = 1.0 + 0.002 * x + delta * s + rng.normal(0, sigma, g)
        if slip:
            k = rng.integers(g)
            d[k] -= slip * s[k]  # a slipped match: past the other sign's mark
        rows.append((x, d))
        signs.append(s)
    return rows, signs


def test_robust_word_llrs_read_clean_rows_like_the_gaussian_model():
    rng = np.random.default_rng(3)
    rows, signs = _rows(rng)
    g_llrs, _ = joint_word_llrs(rows, 0.07, floor=0.0035)
    t_llrs, scale = robust_word_llrs(rows, 0.07, 0.0035, nu=3.0)
    assert scale == pytest.approx(0.02, rel=0.35)
    agree = np.mean(np.concatenate([np.sign(a) == np.sign(b) for a, b in zip(g_llrs, t_llrs)]))
    right = np.mean(np.concatenate([np.sign(l) == s for l, s in zip(t_llrs, signs)]))
    assert agree > 0.97 and right > 0.95


def test_robust_word_llrs_do_not_trust_a_slipped_match():
    """A group that slipped past the other sign's mark reads as a confident wrong sign under the
    Gaussian row model; the t model keeps its weight bounded."""
    rng = np.random.default_rng(5)
    rows, signs = _rows(rng, slip=0.16)
    g_llrs, _ = joint_word_llrs(rows, 0.07, floor=0.0035)
    t_llrs, _ = robust_word_llrs(rows, 0.07, 0.0035, nu=3.0)
    g_wrong = np.concatenate([np.abs(l)[np.sign(l) != s] for l, s in zip(g_llrs, signs)])
    t_wrong = np.concatenate([np.abs(l)[np.sign(l) != s] for l, s in zip(t_llrs, signs)])
    assert g_wrong.max() > 8.0 and t_wrong.max() < 0.6 * g_wrong.max()
    assert np.median(t_wrong) < np.median(g_wrong)


def test_robust_word_llrs_scales_and_short_rows():
    x = np.array([0.0, 100.0, 200.0, 300.0, 400.0])
    d = 0.07 * np.array([1, -1, 1, 1, -1]) + 0.004 * np.array([1, -1, 0, 1, 0])
    rows = [(x, d)] * 10 + [(x[:2], d[:2])]
    plain, _ = robust_word_llrs(rows, 0.07, 0.0035, nu=3.0)
    noisy = [np.array([1, 1, 1, 1, 4.0])] * 10 + [np.ones(2)]
    scaled, _ = robust_word_llrs(rows, 0.07, 0.0035, nu=3.0, scales=noisy)
    assert np.all(plain[-1] == 0)  # two groups: no information
    assert abs(scaled[0][4]) < abs(plain[0][4])  # the noisier group weighs less
    # all groups moved the same way: indistinguishable from an offset, LLR 0 as in the Gaussian model
    same, _ = robust_word_llrs([(x[:3], np.full(3, 0.07))], 0.07, 0.0035, nu=3.0)
    assert np.allclose(same[0], 0.0, atol=1e-6)
    with pytest.raises(ValueError):
        robust_word_llrs(rows, 0.07, 0.0035, nu=0.0)
    assert robust_word_llrs([], 0.07, 0.0035, nu=3.0) == ([], 0.07)


def test_robust_word_llrs_are_calibrated_on_t_noise():
    rng = np.random.default_rng(8)
    rows, signs = [], []
    for _ in range(300):
        x = np.sort(rng.uniform(0, 400, 7))
        s = rng.choice([-1, 1], 7)
        rows.append((x, 0.07 * s + 0.02 * rng.standard_t(3.0, 7)))
        signs.append(s)
    llrs, _ = robust_word_llrs(rows, 0.07, 0.0035, nu=3.0)
    lam = np.concatenate(llrs)
    wrong = np.concatenate([np.sign(l) != s for l, s in zip(llrs, signs)])
    ok = np.abs(lam) > 1e-6
    expected = np.sum(1.0 / (1.0 + np.exp(np.abs(lam[ok]))))
    assert wrong[ok].sum() <= 1.5 * expected + 10


def test_quality_scales_relative_clipped_and_off():
    rows = [[(1, 0, 10.0, 0.0), (2, 0, 20.0, 0.0), (3, 1, 30.0, 0.0)], [(4, 0, 5.0, 0.0)]]
    quality = {1: 0.95, 2: 0.9, 3: 0.5, 4: 0.999}
    out = quality_scales(rows, quality, 1.0)
    med = np.median([0.05, 0.1, 0.5, 0.001])
    assert out[0][0] == pytest.approx(0.05 / med) and out[0][2] == ch_shift.QUALITY_CLIP[1]
    assert out[1][0] == ch_shift.QUALITY_CLIP[0]
    assert quality_scales(rows, quality, 0.0) is None and quality_scales(rows, {}, 1.0) is None
    half = quality_scales(rows, quality, 0.5)
    assert half[0][0] == pytest.approx(np.sqrt(out[0][0]))


def test_word_models_and_image_words():
    assert WORD_MODELS["gauss"] is None and ch_shift.IMAGE_WORD_MODEL in WORD_MODELS
    for name, spec in WORD_MODELS.items():
        if spec is not None:
            assert spec["nu"] > 0 and spec["low_res"][1] <= 1.0 and spec["quality"] >= 0
    w = ImageWords("t3_redam", WORD_MODELS["t3_redam"], 40.0, {7: 0.9})
    assert w.effective_dpi == 40.0 and w.quality == {7: 0.9}
