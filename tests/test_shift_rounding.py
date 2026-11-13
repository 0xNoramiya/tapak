"""Rows whose baselines a PDF viewer rounded to the screen's pixels (ch_shift.rounded_rows).

MuPDF and Poppler's Splash draw every baseline on a whole device pixel, so in a screenshot that
was not rescaled a 0.05 mm row shift is either rounded away or moves the row by a whole pixel.
The lattice model must read the second kind with confidence, give the first an LLR of 0, stay
code-blind, and leave every other evidence exactly as the Gaussian model decodes it.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tapak.decoder.ch_shift import (
    GRID_MIN_CONCENTRATION,
    PixelGrid,
    decode_displacements,
    grid_concentration,
    lattice_row_llrs,
    measure_vector,
    rounded_rows,
)
from tapak.marker.plan import CHANNEL_SHIFT


def _grid(render_dpi: float, phase: float, dpi: float = 100.0) -> PixelGrid:
    k = render_dpi / dpi
    return PixelGrid(np.array([[k, 0.0, 0.0], [0.0, k, phase], [0.0, 0.0, 1.0]]), dpi, render_dpi)


def _rounded(disp: dict, master, render_dpi: float, phase: float, step: float = 1.0) -> dict:
    """Displacements of a capture whose renderer put every baseline on a grid of ``step`` pixels
    at render_dpi (1: MuPDF and Splash, 0.25: Cairo)."""
    k = render_dpi / 72.0
    out = {}
    for wid, (dx, dy) in disp.items():
        y = master.shift_layout.word(wid).glyphs[0].y
        out[wid] = (dx, (np.round(((y + dy) * k + phase) / step) * step - phase) / k - y)
    return out


def _row_positions(ctx) -> dict[int, object]:
    return {s.positions[0]: s for s in ctx.plan.channel(CHANNEL_SHIFT) if len(s.ref) == 1}


# --- small functions -----------------------------------------------------------------------


def test_grid_concentration_is_one_on_the_grid_and_small_off_it():
    rng = np.random.default_rng(1)
    assert grid_concentration(np.arange(20) * 13.0 + 0.3) == pytest.approx(1.0)
    assert grid_concentration(rng.uniform(0, 500, 400)) < 0.15
    assert grid_concentration(np.array([])) == 0.0


def _page(rng: np.random.Generator, k: float, phi: float, delta: float = 0.1417, rows: int = 41,
          jitter: float = 0.02, offset: float = 0.3):
    """A synthetic page: baselines with an uneven pitch, every other row a data row with a random
    sign, each row drawn at pixel round(k y + phi) and measured with jitter plus a fixed offset."""
    y = 60.0 + np.cumsum(rng.uniform(12.0, 16.5, rows))
    s = np.zeros(rows)
    data = np.arange(1, rows - 1, 2)
    s[data] = rng.choice([-1.0, 1.0], data.size)
    z = np.round(k * (y + s * delta) + phi) + offset + rng.normal(0.0, jitter, rows)
    ctrl = np.setdiff1d(np.arange(rows), data)
    truth_moved = np.round(k * (y[data] + delta) + phi) != np.round(k * (y[data] - delta) + phi)
    return y[ctrl], z[ctrl], y[data], z[data], s[data], truth_moved


def test_lattice_row_llrs_read_crossings_and_erase_the_rest():
    """A row whose shift crossed a pixel boundary is read with the right sign; a row whose shift
    was rounded away mostly gets an LLR near 0 (the control rows leave some doubt about where the
    boundaries lie, so not always exactly 0)."""
    rng = np.random.default_rng(4)
    away = away_sure = crossed = crossed_sure = crossed_wrong = 0
    for k, phi in ((1.0, 0.31), (4 / 3, 0.77), (5 / 3, 0.05), (0.75, 0.6)) * 5:
        cy, cz, dy, dz, s, moved = _page(rng, k, phi)
        llr, explained, info = lattice_row_llrs(cy, cz, dy, dz, 0.1417)
        assert explained.all()
        assert info["pixel_per_pt"][0] <= k <= info["pixel_per_pt"][1]
        assert np.abs(llr).max() <= np.log(1.01 / 0.01) + 1e-9   # the floor caps the confidence
        away += int((~moved).sum())
        away_sure += int((~moved & (np.abs(llr) >= 1.0)).sum())
        crossed += int(moved.sum())
        crossed_sure += int((moved & (np.abs(llr) >= 2.0)).sum())
        crossed_wrong += int((moved & (np.abs(llr) > 0) & (np.sign(llr) != s)).sum())
    assert away_sure <= 0.1 * away
    assert crossed_sure >= 0.5 * crossed and crossed_wrong == 0


def test_lattice_row_llrs_are_calibrated_on_random_pages():
    """Random scales, offsets, pitches and signs: in every LLR band the measured error rate stays at
    or below what the LLR promises."""
    rng = np.random.default_rng(9)
    llrs, signs = [], []
    for _ in range(400):
        k = rng.uniform(0.55, 2.1)
        cy, cz, dy, dz, s, _ = _page(rng, k, rng.uniform(0, 1), jitter=0.04)
        found = lattice_row_llrs(cy, cz, dy, dz, 0.1417)
        assert found is not None
        llr, explained, _ = found
        llrs.append(llr[explained])
        signs.append(s[explained])
    llr, s = np.concatenate(llrs), np.concatenate(signs)
    for lo, hi in ((0.3, 1.5), (1.5, 3.0), (3.0, 5.0)):
        band = (np.abs(llr) >= lo) & (np.abs(llr) < hi)
        assert band.sum() > 200
        wrong = np.mean(np.sign(llr[band]) != s[band])
        promised = np.mean(1.0 / (1.0 + np.exp(np.abs(llr[band]))))
        assert wrong <= promised + 0.02


def test_lattice_row_llrs_refuse_rows_off_the_lattice():
    rng = np.random.default_rng(2)
    cy, cz, dy, dz, _, _ = _page(rng, 1.25, 0.4)
    dz = dz.copy()
    dz[0] += 0.5                                   # half a pixel off: not a lattice point
    llr, explained, _ = lattice_row_llrs(cy, cz, dy, dz, 0.1417)
    assert not explained[0] and llr[0] == 0.0
    bad = cz.copy()
    bad[3] += 1.0                                   # a control a whole pixel off: no (k, phi) fits all
    assert lattice_row_llrs(cy, bad, dy, dz, 0.1417) is None
    with pytest.raises(ValueError):
        lattice_row_llrs(cy, cz[:-1], dy, dz, 0.1417)
    with pytest.raises(ValueError):
        lattice_row_llrs(cy, cz, dy, dz, 0.0)


def test_report_names_the_rounding_step_of_rows():
    from tapak.decoder.report import channel_observations
    from tapak.decoder.softbits import SoftBits

    sb = SoftBits(CHANNEL_SHIFT, np.array([1, 2]), np.array([0.5, -2.0]),
                  {"sigma_pt": {"kata": 0.031}, "row_model": {"pages": [{"page": 0, "q_pt": 0.75}]}})
    noise = channel_observations([sb])[0]["noise"]
    assert "sigma kata" in noise and "baris dibulatkan ke piksel" in noise
    plain = SoftBits(CHANNEL_SHIFT, np.array([1]), np.array([0.5]), {"sigma_pt": {"kata": 0.031, "baris": 0.05}})
    assert "dibulatkan" not in channel_observations([plain])[0]["noise"]


def test_pixel_grid_maps_page_points_and_checks_its_input():
    g = _grid(72.0, 0.25)
    assert g.pixel_pt == pytest.approx(1.0)
    assert np.allclose(g.image_y(np.array([10.0, 20.0]), np.array([100.0, 200.5])), [100.25, 200.75])
    with pytest.raises(ValueError):
        PixelGrid(np.eye(2), 100.0, 72.0)
    with pytest.raises(ValueError):
        PixelGrid(np.eye(3), 100.0, 0.0)


# --- rows of an issued copy ----------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["v2", "v1"])
def test_rounded_rows_read_whole_pixel_moves_of_an_issued_copy(scheme, issued, ctx, issued_v1, ctx_v1):
    folder, manifest = issued if scheme == "v2" else issued_v1
    c = ctx if scheme == "v2" else ctx_v1
    seq = 4
    pdf = (folder / manifest.copies[seq - 1].file).read_bytes()
    exact = measure_vector(pdf, c.master)
    x = c.codewords[seq - 1]
    rows = _row_positions(c)
    confident = correct = some = some_wrong = 0
    promised = 0.0  # wrong bits the confident LLRs themselves allow: sum of 1 / (1 + e^|LLR|)
    for render_dpi, phase in ((72.0, 0.31), (96.0, 0.77), (120.0, 0.5)):
        disp = _rounded(exact, c.master, render_dpi, phase)
        found = rounded_rows(c.master, c.plan, disp, c.shift, c.excluded, _grid(render_dpi, phase))
        assert found is not None
        pages, pos, llr, model = found
        assert all(p["concentration"] > 0.999 for p in model["pages"] if p["page"] in pages)
        assert set(int(p) for p in pos) <= set(rows)
        right = (llr > 0).astype(int) == x[pos]
        conf = np.abs(llr) >= 2
        confident += int(conf.sum())
        correct += int(right[conf].sum())
        promised += float(np.sum(1.0 / (1.0 + np.exp(np.abs(llr[conf])))))
        some += int((np.abs(llr) >= 1).sum())
        some_wrong += int((~right & (np.abs(llr) >= 1)).sum())
        # word_model="gauss": the rows alone change here (image word groups: tests/test_shift_words.py)
        sb = decode_displacements(c.master, c.plan, disp, c.shift, c.excluded, grid=_grid(render_dpi, phase),
                                  word_model="gauss")
        assert sb.meta["row_model"]["pages"] and "baris" not in sb.meta["sigma_pt"]
        plain = decode_displacements(c.master, c.plan, disp, c.shift, c.excluded)
        words = [int(p) not in rows for p in plain.positions]
        assert np.array_equal(plain.positions[words], sb.positions[:int(np.sum(words))])  # word groups untouched
    # Copy ids (and so the marks) differ per test issuance; an LLR of 2 to 4.6 still allows the odd
    # wrong sign where the control rows leave the pixel boundary uncertain. A fixed 5 % failed
    # one run in a few with 2 wrong of 37, so the bound is what the LLRs promise, with a margin.
    assert confident >= 10 and confident - correct <= 3 * promised + 1
    assert some >= 10 and some_wrong <= 0.35 * some  # an LLR of 1 promises at most 27 % wrong


def test_quarter_pixel_baselines_are_read_on_a_quarter_pixel_grid(issued, ctx):
    """Cairo puts baselines on quarter pixels: the whole-pixel test fails, the quarter-pixel one
    passes, and the rows are read on that grid with the copy's bits."""
    folder, manifest = issued
    seq = 5
    exact = measure_vector((folder / manifest.copies[seq - 1].file).read_bytes(), ctx.master)
    x = ctx.codewords[seq - 1]
    confident = wrong = 0
    for render_dpi, phase in ((56.0, 0.13), (84.0, 0.62)):
        disp = _rounded(exact, ctx.master, render_dpi, phase, step=0.25)
        pages, pos, llr, model = rounded_rows(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded,
                                              _grid(render_dpi, phase))
        used = [p for p in model["pages"] if "q_pt" in p]
        assert used and all(p["pitch_px"] == 0.25 for p in used)
        assert used[0]["q_pt"] == pytest.approx(0.25 * 72.0 / render_dpi, rel=1e-4)
        conf = np.abs(llr) >= 2
        confident += int(conf.sum())
        wrong += int(((llr[conf] > 0).astype(int) != x[pos[conf]]).sum())
    assert confident >= 10 and wrong <= max(1, 0.05 * confident)


def test_rows_off_the_pixel_grid_keep_the_gaussian_model(issued, ctx):
    """Displacements with no rounding (a photo, a rescaled capture): the gate does not open and the
    observations are exactly those without a grid."""
    folder, manifest = issued
    pdf = (folder / manifest.copies[1].file).read_bytes()
    exact = measure_vector(pdf, ctx.master)
    rng = np.random.default_rng(3)
    noisy = {w: (dx + rng.normal(0, 0.01), dy + rng.normal(0, 0.03)) for w, (dx, dy) in exact.items()}
    grid = _grid(73.3, 0.4)
    assert rounded_rows(ctx.master, ctx.plan, noisy, ctx.shift, ctx.excluded, grid) is None
    a = decode_displacements(ctx.master, ctx.plan, noisy, ctx.shift, ctx.excluded, grid=grid, word_model="gauss")
    b = decode_displacements(ctx.master, ctx.plan, noisy, ctx.shift, ctx.excluded)
    # image evidence also looks for a local field between the rows: this noise has none
    assert set(a.meta.pop("word_local_field_mm").values()) == {None}
    assert np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr) and a.meta == b.meta
    # the image word model (default on image evidence) changes the word-group LLRs and nothing else
    from tapak.decoder.ch_shift import IMAGE_WORD_MODEL

    d = decode_displacements(ctx.master, ctx.plan, noisy, ctx.shift, ctx.excluded, grid=grid)
    words = {s.positions[0] for s in ctx.plan.channel("shift") if len(s.ref) == 2}
    rows_b = {int(q): v for q, v in zip(b.positions, b.llr) if int(q) not in words}
    rows_d = {int(q): v for q, v in zip(d.positions, d.llr) if int(q) not in words}
    assert d.meta["word_model"] == IMAGE_WORD_MODEL and rows_d == rows_b
    assert {int(q) for q in d.positions} - set(rows_d) <= words and d.meta["word_slots_read"] > 100
    assert np.array_equal(d.strengths.values, b.strengths.values)


def test_rounded_rows_do_not_depend_on_codewords(issued, ctx):
    folder, manifest = issued
    pdf = (folder / manifest.copies[6].file).read_bytes()
    disp = _rounded(measure_vector(pdf, ctx.master), ctx.master, 64.0, 0.6)
    grid = _grid(64.0, 0.6)
    rng = np.random.default_rng(11)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    a = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded, grid=grid)
    b = decode_displacements(fake.master, fake.plan, disp, fake.shift, fake.excluded, grid=grid)
    assert "row_model" in a.meta
    assert np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)


def test_gate_threshold_is_far_above_chance():
    """Twenty control rows unrelated to the pixel grid almost never reach the gate."""
    rng = np.random.default_rng(5)
    values = [grid_concentration(rng.uniform(0, 1000, 20)) for _ in range(20000)]
    assert np.mean(np.array(values) >= GRID_MIN_CONCENTRATION) < 1e-3


def test_mupdf_screenshot_rows_use_the_rounding_model(issued, ctx):
    """A whole-page capture drawn by MuPDF at 120 dpi (lossless): the rows pass the gate, the rows
    read with confidence carry the copy's bits, and no codeword enters."""
    import pymupdf

    from tapak.decoder.image import collect_from_gray

    folder, manifest = issued
    seq = 9
    pdf = (folder / manifest.copies[seq - 1].file).read_bytes()
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(120 / 72, 120 / 72), colorspace=pymupdf.csGRAY, alpha=False)
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    obs = collect_from_gray(gray, ctx, read_text=False)
    shift = next(o for o in obs if o.channel == CHANNEL_SHIFT)
    pages = [p for p in shift.meta["row_model"]["pages"] if "q_pt" in p]
    assert pages and pages[0]["q_pt"] == pytest.approx(0.6, abs=0.01)
    rows = _row_positions(ctx)
    sel = np.array([int(p) in rows for p in shift.positions])
    llr, pos = shift.llr[sel], shift.positions[sel]
    conf = np.abs(llr) >= 2
    x = ctx.codewords[seq - 1]
    assert len(llr) >= 10 and np.all((llr[conf] > 0).astype(int) == x[pos[conf]])
    rng = np.random.default_rng(2)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    again = next(o for o in collect_from_gray(gray, fake, read_text=False) if o.channel == CHANNEL_SHIFT)
    assert np.array_equal(again.positions, shift.positions) and np.array_equal(again.llr, shift.llr)
