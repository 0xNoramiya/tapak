"""Background channel on photos of a screen (moire) and phone photos (sharpening halos).

On images the decoder removes narrowband periodic components from the paper modulation
(``suppress_periodic``) and masks bright outliers as well as dark ones. These steps look at
the evidence only, so the observations must not depend on any codeword, and a page without
moire must lose next to nothing. The photos come from the simulator with fixed seeds, of copies
issued with fixed copy ids, so every run decodes the same pixels.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

import tapak.decoder.ch_background as bg
from tapak.decoder.accuse import VERDICT_IDENTIFIED
from tapak.decoder.image import collect_from_image
from tapak.decoder.trace import run_trace
from tapak.marker.plan import CHANNEL_BACKGROUND
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, photo_jpeg, screen_photo_jpeg
from tapak.ponsel import ScreenParams, isp_profile
from test_background_clipping import _issue_fixed


@pytest.fixture(scope="module")
def fixed(tmp_path_factory, sample_pdf, secret):
    out = tmp_path_factory.mktemp("moire")
    manifest, ctx = _issue_fixed(out, sample_pdf, secret)
    return (out, manifest), ctx


def _page(issued, seq: int) -> np.ndarray:
    out, manifest = issued
    return render_pages((out / manifest.copies[seq - 1].file).read_bytes(), 200, [0])[0]


def _monitor_photo(issued, seq: int, isp=None) -> bytes:
    """The 27 inch QHD monitor head-on at 30 cm: the pixel grid aliases (grid frequency above
    0.5 cycles per output pixel) and the plain camera tail keeps the paper below white."""
    params = PhotoParams(angle_deg=0.0, exposure=(0.9, 0.9))
    data, meta = screen_photo_jpeg(_page(issued, seq), np.random.default_rng(41), params,
                                   ScreenParams(monitor="qhd27", distance_cm=30.0), isp=isp,
                                   isp_rng=np.random.default_rng(42))
    assert meta["screen"]["grid_frequency"][0] > 0.5 and meta["params"]["paper_clip_frac"] < 0.05
    return data


def _background(obs):
    return next(o for o in obs if o.channel == CHANNEL_BACKGROUND)


def _errors(sb, x) -> int:
    return int(np.sum((sb.llr > 0) != (x[sb.positions] == 1)))


def test_suppress_periodic_removes_a_sinusoid_and_keeps_the_pattern():
    rng = np.random.default_rng(1)
    h, w = 900, 700
    cells = rng.choice([-1.0, 1.0], (h // 10 + 1, w // 10 + 1)).repeat(10, 0).repeat(10, 1)[:h, :w] * 0.008
    yy, xx = np.mgrid[0:h, 0:w]
    moire = 0.03 * np.cos(2 * np.pi * (0.061 * xx + 0.017 * yy))
    usable = rng.random((h, w)) > 0.2  # ink and other holes
    noise = rng.normal(0, 0.01, (h, w))
    mod = np.where(usable, cells + moire + noise, 0.0)
    out, found = bg.suppress_periodic(mod, usable)
    assert found > 0 and np.all(out[~usable] == 0.0)

    def gain(a, ref):
        return float(np.sum(a * ref * usable) / np.sum(ref * ref * usable))

    assert gain(out, moire) < 0.3 and gain(mod, moire) > 0.95  # most of the moire is gone
    assert gain(out, cells) > 0.95  # the broadband pattern stays
    # Without any periodic component nothing is found and the modulation is returned as it was.
    clean = np.where(usable, cells + noise, 0.0)
    same, none = bg.suppress_periodic(clean, usable)
    assert none == 0 and np.allclose(same, clean)
    # Tiny pages are padded, not refused.
    small, _ = bg.suppress_periodic(clean[:40, :50], usable[:40, :50])
    assert small.shape == (40, 50)


def test_moire_photo_observations_do_not_depend_on_codewords(fixed):
    """The periodic filter and the outlier mask use the evidence only: replacing every codeword
    of the context by random bits changes no observation."""
    issued, ctx = fixed
    data = _monitor_photo(issued, 2, isp=isp_profile("ponsel"))
    real = collect_from_image(data, ctx)
    assert _background(real).meta["periodic_bins"] > 0 and len(_background(real)) > 0
    rng = np.random.default_rng(7)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    assert not np.array_equal(fake.codewords, ctx.codewords)
    other = collect_from_image(data, fake)
    assert [o.channel for o in real] == [o.channel for o in other]
    for a, b in zip(real, other):
        assert np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)
        assert a.meta == b.meta


def test_filter_lowers_bit_errors_on_a_moire_photo(fixed, monkeypatch):
    """The filter was chosen with the noise model of its time (one noise level per saturation
    stratum, ``"kejenuhan"``), which is compared here. With the noise model of
    ``research/kalibrasi`` this photo reads every bit right with and without the filter."""
    issued, ctx = fixed
    seq = 3
    data = _monitor_photo(issued, seq)
    x = ctx.codewords[seq - 1]
    shipped = collect_from_image(data, ctx)
    result = run_trace(shipped, ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]
    monkeypatch.setattr(bg, "NOISE_MODEL", "kejenuhan")
    with_filter = collect_from_image(data, ctx)
    real_filter = bg.suppress_periodic
    monkeypatch.setattr(bg, "suppress_periodic", lambda mod, usable, **kw: (mod, 0))
    without = collect_from_image(data, ctx)
    b_with, b_without = _background(with_filter), _background(without)
    assert b_with.meta["periodic_bins"] > 0 and b_without.meta["periodic_bins"] == 0
    assert _errors(b_with, x) < _errors(b_without, x)
    assert b_with.meta["signal_z"] > b_without.meta["signal_z"]
    monkeypatch.setattr(bg, "NOISE_MODEL", "pasangan_irls_batas")
    shipped_without = collect_from_image(data, ctx)
    monkeypatch.setattr(bg, "suppress_periodic", real_filter)
    assert _errors(_background(shipped), x) <= _errors(_background(shipped_without), x)


def test_forwarded_pdf_pages_are_decoded_as_before(fixed, monkeypatch):
    """A rendered PDF page (no bias vector) skips the periodic filter and the bright-outlier mask."""
    issued, ctx = fixed
    from tapak.decoder.trace import collect_background_from_pdf

    out, manifest = issued
    pdf = (out / manifest.copies[0].file).read_bytes()
    calls = []
    real = bg.suppress_periodic
    monkeypatch.setattr(bg, "suppress_periodic", lambda *a, **k: calls.append(1) or real(*a, **k))
    sb = collect_background_from_pdf(pdf, ctx)[0]
    assert calls == [] and "periodic_bins" not in sb.meta
    assert np.mean((sb.llr > 0) == (ctx.codewords[0][sb.positions] == 1)) > 0.99


@pytest.mark.slow
def test_unmarked_master_on_a_monitor_reads_no_pattern(fixed, sample_pdf):
    _, ctx = fixed
    page = render_pages(sample_pdf, 200, [0])[0]
    data, _ = screen_photo_jpeg(page, np.random.default_rng(43), PhotoParams(angle_deg=0.0, exposure=(0.9, 0.9)),
                                ScreenParams(monitor="qhd27", distance_cm=30.0))
    obs = collect_from_image(data, ctx)
    assert _background(obs).meta["periodic_bins"] > 0
    assert run_trace(obs, ctx).accused == []


@pytest.mark.slow
def test_phone_photo_with_halos_identified(fixed):
    issued, ctx = fixed
    seq = 4
    data, meta = photo_jpeg(_page(issued, seq), np.random.default_rng(44), PhotoParams(angle_deg=10.0),
                            isp=isp_profile("ponsel"), isp_rng=np.random.default_rng(45))
    assert meta["params"]["isp"]["sharpen_overshoot"] >= 0.10
    result = run_trace(collect_from_image(data, ctx), ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]
