"""Overexposed photos: paper clipped to white must neither dilute nor bias the background channel.

The photos come from the simulator with fixed seeds, of copies issued with fixed copy ids
(``fixed``), so pattern, photo and decode are the same on every run. "Old" means the
background decoder without the bias vector, which is exactly the decoder before saturation
strata and the pilot test (a single amplitude, decoy test only).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import cv2
import numpy as np
import pytest

from tapak.decoder import ch_background as bg
from tapak.decoder.accuse import VERDICT_IDENTIFIED, VERDICT_INSUFFICIENT
from tapak.decoder.ch_shift import decode_displacements, measure_image
from tapak.decoder.image import collect_from_image
from tapak.decoder.rectify import load_gray, register, render_page
from tapak.decoder.softbits import SoftBits
from tapak.decoder.trace import TraceContext, load_context, run_trace
from tapak.marker.background import BackgroundSettings, PageGrid, page_grids
from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, issue
from tapak.marker.plan import CHANNEL_BACKGROUND
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, photo_jpeg

# (copy seq, rng seed, camera exposure): most of the paper clips to white and the decoy test
# alone (the old gate) misses the pattern, but enough cells keep it for the pilot test.
CLIPPED = (1, 15, 1.5)
CLIPPED_MORE = [(2, 21, 1.5), (3, 12, 1.5), (4, 15, 1.5)]


def _issue_fixed(out: Path, sample_pdf: bytes, secret: bytes) -> tuple[IssueManifest, TraceContext]:
    """Four copies with fixed copy ids (normally random), coded for 20 recipients like the
    shared fixture, and their trace context."""
    import tapak.marker.issue as issue_module
    from tests_support import SAMPLE

    ids = iter(f"{i:016x}" for i in range(1, 1000))
    recipients = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji") for i in range(1, 5)]
    mp = pytest.MonkeyPatch()
    mp.setattr(issue_module.secrets, "token_hex", lambda n=8: next(ids))
    try:
        manifest = issue(SAMPLE, recipients, out, secret, IssueSettings(n_max=20, workers=1), issuer="pytest")
    finally:
        mp.undo()
    return manifest, load_context(sample_pdf, manifest, secret)


@pytest.fixture(scope="module")
def fixed(tmp_path_factory, sample_pdf, secret):
    out = tmp_path_factory.mktemp("fixed")
    manifest, ctx = _issue_fixed(out, sample_pdf, secret)
    return (out, manifest), ctx


def _page(issued, seq: int) -> np.ndarray:
    out, manifest = issued
    return render_pages((out / manifest.copies[seq - 1].file).read_bytes(), 200, [0])[0]


def _photo(issued, seq: int, seed: int, exposure: float) -> tuple[bytes, dict]:
    params = PhotoParams(angle_deg=10.0, exposure=(exposure, exposure))
    return photo_jpeg(_page(issued, seq), np.random.default_rng(seed), params)


def _background(obs: list[SoftBits]) -> SoftBits:
    return next(o for o in obs if o.channel == CHANNEL_BACKGROUND)


def _old_and_new(data: bytes, ctx) -> tuple[list[SoftBits], list[SoftBits]]:
    """Shift bits plus the background decoded without (old) and with (new) the bias vector."""
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    reg = register(load_gray(data), ctx.master.pdf_bytes, sizes)
    assert reg is not None
    master = render_page(ctx.master.pdf_bytes, reg.page, reg.dpi)
    disp = measure_image(reg.rectified, reg.valid, master, ctx.master, reg.page, reg.dpi)
    shift = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
    grid = page_grids(sizes, ctx.key, ctx.background)[reg.page]
    slots = ctx.plan.channel(CHANNEL_BACKGROUND)
    old = bg.decode_background(reg.rectified, reg.valid, master, reg.dpi, grid, slots)
    new = bg.decode_background(reg.rectified, reg.valid, master, reg.dpi, grid, slots, bias=ctx.p)
    return [shift, old], [shift, new]


def _agreement(sb: SoftBits, x: np.ndarray, min_llr: float = 0.0) -> float:
    m = np.abs(sb.llr) > min_llr
    return float(np.mean((sb.llr[m] > 0) == (x[sb.positions[m]] == 1)))


def test_clipped_photo_old_decoder_misses_new_decoder_reads(fixed):
    issued, ctx = fixed
    seq, seed, exposure = CLIPPED
    data, meta = _photo(issued, seq, seed, exposure)
    assert meta["params"]["paper_clip_frac"] > 0.9
    old, new = _old_and_new(data, ctx)
    assert old[1].meta["pattern_found"] is False and len(old[1]) == 0
    assert run_trace(old, ctx).verdict == VERDICT_INSUFFICIENT
    b = new[1]
    assert b.meta["decoy_z"] < bg.SIGNAL_Z <= b.meta["pilot_z"]
    assert b.meta["pattern_found"] is True and len(b) > 500 and b.meta["clipped_share"] > 0.3
    x = ctx.codewords[seq - 1]
    assert _agreement(b, x) > 0.55
    assert _agreement(b, x, min_llr=3.0) > 0.9  # confident bits are right: the noise model is honest
    result = run_trace(new, ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]
    # The full image path (collect_from_image) gives the same background bits.
    via_image = _background(collect_from_image(data, ctx))
    assert np.array_equal(via_image.positions, b.positions) and np.allclose(via_image.llr, b.llr)


def test_background_llrs_do_not_depend_on_codewords(fixed):
    """Replacing every codeword of the context by random bits changes no observation."""
    issued, ctx = fixed
    seq, seed, exposure = CLIPPED
    data, _ = _photo(issued, seq, seed, exposure)
    real = collect_from_image(data, ctx)
    rng = np.random.default_rng(99)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    assert not np.array_equal(fake.codewords, ctx.codewords)
    other = collect_from_image(data, fake)
    assert [o.channel for o in real] == [o.channel for o in other]
    for a, b in zip(real, other):
        assert np.array_equal(a.positions, b.positions)
        assert np.array_equal(a.llr, b.llr)
    assert len(_background(real)) > 0


def test_unclipped_photo_same_verdict_as_before(fixed):
    issued, ctx = fixed
    seq = 2
    data, meta = _photo(issued, seq, 7, 0.95)
    assert meta["params"]["paper_clip_frac"] == 0.0
    old, new = _old_and_new(data, ctx)
    x = ctx.codewords[seq - 1]
    for obs in (old, new):
        result = run_trace(obs, ctx)
        assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]
        assert _agreement(obs[1], x) > 0.95
    assert len(new[1]) == len(old[1]) == old[1].meta["bits_total"]


def test_fully_white_photo_reads_nothing_and_accuses_nobody(fixed):
    issued, ctx = fixed
    seq = 3
    data, meta = _photo(issued, seq, 11, 2.5)  # all paper clips; the text stays dark enough to register
    assert meta["params"]["paper_clip_frac"] > 0.99
    obs = collect_from_image(data, ctx)
    b = _background(obs)
    assert "registered" not in b.meta  # the page was found and the background decoded
    assert len(b) == 0 and b.meta["pattern_found"] is False and b.meta["clipped_share"] > 0.9
    result = run_trace(obs, ctx)
    assert result.verdict == VERDICT_INSUFFICIENT and result.accused == []
    # Brighter still, the text washes out too: the page is not found and nothing is read.
    data, meta = _photo(issued, seq, 11, 4.0)
    obs = collect_from_image(data, ctx)
    assert all(len(o) == 0 for o in obs)
    assert run_trace(obs, ctx).accused == []
    # A white frame: no page, no reads, no accusation.
    ok, png = cv2.imencode(".png", np.full((1100, 800), 255, np.uint8))
    obs = collect_from_image(png.tobytes(), ctx)
    assert all(len(o) == 0 for o in obs)
    assert run_trace(obs, ctx).accused == []


def test_decode_background_on_white_page_reports_nothing(fixed):
    _, ctx = fixed
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    grid = page_grids(sizes, ctx.key, ctx.background)[0]
    dpi = 100.0
    master = render_page(ctx.master.pdf_bytes, 0, dpi)
    white = np.full(master.shape, 255.0, np.float32)
    sb = bg.decode_background(white, np.ones(white.shape, bool), master, dpi, grid,
                              ctx.plan.channel(CHANNEL_BACKGROUND), bias=ctx.p)
    assert len(sb) == 0 and sb.meta["pattern_found"] is False and sb.meta["clipped_share"] == 1.0


def test_pilot_z_is_calibrated_without_pattern_and_grows_with_one():
    rng = np.random.default_rng(5)
    p = np.clip(0.5 - 0.5 * np.cos(np.pi * rng.random(4000)), 1e-3, 1 - 1e-3)  # arcsine bias
    e = 2 * p - 1
    zs = []
    for _ in range(600):
        m = rng.standard_t(3, e.size) * rng.choice([0.1, 1.0, 5.0], e.size)  # uneven, heavy-tailed noise
        zs.append(bg.pilot_z(rng.choice([-1.0, 1.0], e.size) * m, e))
    zs = np.array(zs)
    assert abs(zs.mean()) < 0.15 and 0.85 < zs.std() < 1.15 and np.mean(zs >= bg.SIGNAL_Z) < 0.01
    s = np.where(rng.random(e.size) < p, 1.0, -1.0)  # bits drawn with the bias, as in a copy
    u = 0.3 * s + rng.normal(0, 1, e.size)
    assert bg.pilot_z(u, e) > 6
    assert bg.pilot_z(np.zeros(5), np.ones(5)) == 0.0


def test_stratum_gains_follow_the_signal_per_stratum():
    rng = np.random.default_rng(6)
    n = 30000
    stratum = rng.integers(0, 4, n)
    stratum[:20] = 4  # a stratum too small to be trusted
    true_gain = np.array([1.0, 0.5, 0.1, 0.0, 1.0])
    noise = np.array([1.0, 0.8, 0.3, 0.2, 1.0])
    p = np.clip(0.5 - 0.5 * np.cos(np.pi * rng.random(n)), 1e-3, 1 - 1e-3)
    s = np.where(rng.random(n) < p, 1.0, -1.0)
    u = true_gain[stratum] * s + noise[stratum] * rng.normal(0, 1, n)
    gain, var = bg.stratum_gains(u, 2 * p - 1, stratum, 5)
    assert gain[:3] == pytest.approx(true_gain[:3], abs=0.05)
    assert gain[3] < 0.03 and gain[4] == 0.0
    assert np.sqrt(var[:4]) == pytest.approx(noise[:4], rel=0.1)


def test_saturation_helpers():
    assert list(bg.saturation_strata(np.array([0.0, 0.01, 0.05, 0.3, 0.97, 0.99, 1.0]))) == [0, 0, 1, 3, 6, 7, 7]
    assert bg.robust_bound(np.zeros(0)) == 0.0
    t = np.concatenate([np.random.default_rng(0).normal(0, 1, 1000), [1e6]])
    assert 2.0 < bg.robust_bound(t) < 10.0  # one outlier does not move the bound
    grid = PageGrid(0, 595.28, 841.89, BackgroundSettings(), b"k" * 32)
    dpi = 72.0
    h, w = int(round(841.89)), int(round(595.28))
    img = np.full((h, w), 200.0)
    img[:, w // 2:] = 255.0  # right half clipped to white
    usable = np.ones((h, w), bool)
    _, frac = bg.cell_means(np.zeros((h, w)), usable, grid, dpi)
    share = bg.saturated_share(img, usable, grid, dpi, frac)
    assert share.shape == (grid.ny, grid.nx)
    assert share[:, :3].max() < 0.01 and share[:, -3:].min() > 0.99


def test_photo_meta_reports_clipped_paper(fixed):
    issued, _ = fixed
    _, dark = _photo(issued, 1, 0, 0.9)
    _, bright = _photo(issued, 1, 0, 1.6)
    assert dark["params"]["paper_clip_frac"] == 0.0
    assert 0.5 < bright["params"]["paper_clip_frac"] <= 1.0
    # The desk around the page is dark, so the paper clips more often than the whole frame.
    assert bright["params"]["paper_clip_frac"] >= bright["params"]["highlight_clip_frac"]


@pytest.mark.slow
def test_more_clipped_photos_no_false_accusation(fixed):
    """Further overexposed photos: the new decoder reads the pattern where the old one does
    not, and nobody but the source copy is ever accused."""
    issued, ctx = fixed
    for seq, seed, exposure in CLIPPED_MORE:
        data, meta = _photo(issued, seq, seed, exposure)
        old, new = _old_and_new(data, ctx)
        assert len(new[1]) > 0 and len(old[1]) == 0, (seq, seed, meta["params"]["paper_clip_frac"])
        for obs in (old, new):
            assert all(c.copy.seq == seq for c in run_trace(obs, ctx).accused)
        assert [c.copy.seq for c in run_trace(new, ctx).accused] == [seq]
