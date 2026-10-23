"""Per-cell noise model of the background decoder (``research/kalibrasi``).

The decoder measures a page once (``measure_background``: cell means, valid fractions,
saturation share and each cell's distance to the master's ink, all code-blind) and turns the
measurements into soft bits with a per-cell noise model (``background_soft_bits``). The tests
check the pieces on synthetic data, that a model never changes the presence decision, the pilot
sum or the strengths, and that the observations do not depend on any codeword.
"""

from __future__ import annotations

import numpy as np
import pytest

import tapak.decoder.ch_background as bg
from tapak.marker.background import BackgroundSettings, PageGrid, cell_levels, page_grids, pattern_image
from tapak.marker.plan import CHANNEL_BACKGROUND

GRID = PageGrid(0, 595.28, 841.89, BackgroundSettings(), b"k" * 32)


def test_ink_distance_cells_measures_cells_to_the_nearest_ink():
    dpi = 72.0
    h, w = int(round(841.89)), int(round(595.28))
    master = np.full((h, w), 255.0)
    master[400:404, :] = 0.0  # one ink rule across the page
    dist = bg.ink_distance_cells(master, GRID, dpi)
    assert dist.shape == (GRID.ny, GRID.nx)
    cell_px = GRID.cell_pt * dpi / 72.0
    oy = GRID.offset_pt[1]
    centres = oy + (np.arange(GRID.ny) + 0.5) * GRID.cell_pt
    expected = np.clip(np.minimum(np.abs(centres - 400.0), np.abs(centres - 403.0)), 0, None) / cell_px
    far = np.abs(centres - 401.5) > 2 * cell_px
    # The central samples of a cell average the distance over half a cell: close to the centre's.
    assert np.allclose(dist[far, 0], expected[far], atol=0.3)
    assert dist[np.argmin(np.abs(centres - 401.5)), 0] < 0.5
    assert np.allclose(dist, dist[:, :1])  # the rule spans the page: the same in every column
    blank = bg.ink_distance_cells(np.full((h, w), 255.0), GRID, dpi)
    assert blank.min() >= 1e5  # no ink at all


def _synthetic_page(near_gain: float, near_noise: float, seed: int = 0):
    """A page measurement whose cells within one cell of a set of ink rules carry the pattern
    attenuated by ``near_gain`` and noise ``near_noise`` times stronger, as after JPEG; the
    pilot bias vector and the slots of a real plan are not needed: one slot per bit."""
    from tapak.marker.plan import Slot

    rng = np.random.default_rng(seed)
    n_bits = GRID.n_bits
    bits = rng.integers(0, 2, n_bits)
    p = np.clip(rng.beta(0.5, 0.5, n_bits), 0.01, 0.99)
    bits = (rng.random(n_bits) < p).astype(int)
    slots = [Slot(CHANNEL_BACKGROUND, 0, (b,), (b,), (0,)) for b in range(n_bits)]
    s_bit = 2.0 * bits - 1.0
    cb = GRID.cell_bit
    s_cell = np.where(cb >= 0, s_bit[np.clip(cb, 0, None)], 0.0)
    rows = np.arange(GRID.ny)[:, None] % 6 < 2  # a third of the rows next to text
    near = np.broadcast_to(rows, (GRID.ny, GRID.nx))
    distance = np.where(near, 0.3, 2.5)
    gain = np.where(near, near_gain, 1.0) * 0.004
    noise = np.where(near, near_noise, 1.0) * 0.004
    means = GRID.pn * (gain * s_cell + noise * rng.normal(size=(GRID.ny, GRID.nx)))
    measure = bg.BackgroundMeasure(means=means, frac=np.ones((GRID.ny, GRID.nx)),
                                   share=np.zeros((GRID.ny, GRID.nx)), periodic=0, ink_distance=distance)
    return measure, slots, p, bits


def test_background_measure_and_soft_bits_with_the_saturation_model():
    measure, slots, p, bits = _synthetic_page(1.0, 1.0)
    sb = bg.background_soft_bits(measure, GRID, slots, p, "kejenuhan")
    assert sb.meta["pattern_found"] and len(sb) == GRID.n_bits
    assert np.mean((sb.llr > 0) == (bits[sb.positions] == 1)) > 0.99
    # The named model, the module default and the function itself give the same output.
    same = bg.background_soft_bits(measure, GRID, slots, p, bg.saturation_noise)
    assert np.array_equal(sb.llr, same.llr)
    u = np.ones(50)
    g, v = bg.saturation_noise(u, u, np.zeros(50, dtype=int), u)
    assert g.shape == v.shape == (50,)
    with pytest.raises(KeyError):
        bg.background_soft_bits(measure, GRID, slots, p, "tidak-ada")


def test_a_noise_model_changes_only_the_llrs():
    measure, slots, p, bits = _synthetic_page(0.3, 3.0)
    before = bg.background_soft_bits(measure, GRID, slots, p, "kejenuhan")

    def flat(u, e, stratum, weight, distance, bits):
        assert bits.shape == u.shape and distance.shape == u.shape
        return np.full(u.size, 0.004), np.full(u.size, 1e-4)

    after = bg.background_soft_bits(measure, GRID, slots, p, flat)
    assert not np.array_equal(before.llr, after.llr)

    def capped(u, e, stratum, weight, distance, bits):
        return np.full(u.size, 0.004), np.full(u.size, 1e-4), 0.5

    small = bg.background_soft_bits(measure, GRID, slots, p, capped)
    # No cell adds more than the cap, so no bit exceeds the cap times its number of cells.
    per_bit = np.bincount(GRID.cell_bit[GRID.cell_bit >= 0], minlength=GRID.n_bits)
    assert np.all(np.abs(small.llr) <= 0.5 * per_bit[np.array([s.ref[0] for s in slots])] + 1e-9)
    assert np.mean(np.sign(small.llr) == np.sign(after.llr)) > 0.9
    for key in ("pattern_found", "presence", "decoy_z", "pilot_z", "pilot_sum", "pilot_var", "bits_read"):
        assert before.meta[key] == after.meta[key], key
    assert np.array_equal(before.strengths.values, after.strengths.values)
    # Without the bias vector (a page rendered from a PDF) no noise model is consulted.
    pdf_a = bg.background_soft_bits(measure, GRID, slots, None, "kejenuhan")
    pdf_b = bg.background_soft_bits(measure, GRID, slots, None, flat)
    assert np.array_equal(pdf_a.llr, pdf_b.llr)


def test_decode_background_is_measure_then_soft_bits(issued, ctx):
    from tapak.decoder.rectify import render_page

    out, manifest = issued
    page = render_page((out / manifest.copies[2].file).read_bytes(), 0, 100)
    master = render_page(ctx.master.pdf_bytes, 0, 100)
    grid = page_grids([(q.width, q.height) for q in ctx.master.layout.pages], ctx.key, ctx.background)[0]
    valid = np.ones_like(page, dtype=bool)
    slots = ctx.plan.channel(CHANNEL_BACKGROUND)
    for bias in (None, ctx.p):
        direct = bg.decode_background(page, valid, master, 100, grid, slots, bias)
        measure = bg.measure_background(page, valid, master, 100, grid, image=bias is not None)
        assert (measure.ink_distance is None) == (bias is None)
        staged = bg.background_soft_bits(measure, grid, slots, bias)
        assert np.array_equal(direct.llr, staged.llr) and np.array_equal(direct.positions, staged.positions)
    levels = cell_levels(grid, slots, ctx.codewords[2])
    assert pattern_image(grid, levels).shape[1] > 0
