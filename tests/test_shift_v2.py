"""Shift scheme geser-v2 (every word group carries a bit, decoded jointly per row) and the
compatibility of geser-v1, the scheme of every document issued before it.

Copies here are issued with fixed copy ids (normally random), so every observation is the same
on every run. The geser-v1 digests were computed with the code before geser-v2 existed (same
copy ids, same evidence), so they pin "documents issued before this change decode exactly as
today".
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tapak.decoder.ch_shift import (
    LOCAL_FIELD_MM,
    MAX_JOINT_GROUPS,
    PixelGrid,
    choose_local_field,
    decode_displacements,
    fit_page_field,
    joint_decode,
    joint_measurements,
    joint_strengths,
    joint_word_llrs,
    local_field,
    measure_vector,
    row_projector,
    row_sign_llrs,
    screen_row,
)
from tapak.decoder.image import collect_from_image
from tapak.decoder.trace import collect_file, load_context, run_trace
from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, issue
from tapak.marker.pdf_shift import (
    MIN_JOINT_GROUPS,
    SCHEME_V1,
    SCHEME_V2,
    V2_MAX_WORD_SHIFT_MM,
    ShiftSettings,
    shift_slot_refs,
    word_slot_groups,
)
from tapak.marker.plan import CHANNEL_SHIFT
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, ScreenshotParams, photo_jpeg, screenshot_jpeg

# Shift observations of copy 2 (fixed copy ids, n_max 20) under geser-v1, computed with the code
# before geser-v2 existed: sha256 prefix of positions and LLRs (6 decimals), and their count.
V1_DIGESTS = {"pdf": "c99d1799c1259bea:183", "screenshot": "56ce80aabe4272fa:103", "photo": "53fa18cf8798df26:102"}
V1_MANIFEST_KEYS = ["background", "canary_domain", "channels", "copies", "doc_hash", "doc_name", "elapsed_s",
                    "excluded_rows", "gate", "issued_at", "issuer", "params", "plan_summary", "semantic_digest",
                    "shift_mm", "threshold_full"]


def _digest(obs) -> str:
    sb = next(o for o in obs if o.channel == CHANNEL_SHIFT)
    payload = {"pos": [int(q) for q in sb.positions], "llr": [round(float(v), 6) for v in sb.llr]}
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:16] + f":{len(sb)}"


def _issue_fixed(out: Path, secret: bytes, shift: ShiftSettings) -> IssueManifest:
    import tapak.marker.issue as issue_module
    from tests_support import SAMPLE

    ids = iter(f"{i:016x}" for i in range(1, 1000))
    recipients = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji") for i in range(1, 4)]
    mp = pytest.MonkeyPatch()
    mp.setattr(issue_module.secrets, "token_hex", lambda n=8: next(ids))
    try:
        return issue(SAMPLE, recipients, out, secret, IssueSettings(n_max=20, workers=1, shift=shift), issuer="pytest")
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def v1_fixed(tmp_path_factory, sample_pdf, secret):
    out = tmp_path_factory.mktemp("v1")
    manifest = _issue_fixed(out, secret, ShiftSettings())
    return out, manifest, load_context(sample_pdf, manifest, secret)


@pytest.fixture(scope="module")
def v2_fixed(tmp_path_factory, sample_pdf, secret):
    out = tmp_path_factory.mktemp("v2")
    manifest = _issue_fixed(out, secret, ShiftSettings.for_scheme(SCHEME_V2))
    return out, manifest, load_context(sample_pdf, manifest, secret)


def _raw_displacements(pdf: bytes, ctx):
    """Glyph-origin displacements of a copy against the master, without fitting a page frame."""
    from tapak.decoder.ch_shift import PageFrame, match_words
    from tapak.marker.layout import extract_layout

    pages = len(ctx.master.layout.pages)
    return match_words(ctx.master.layout, extract_layout(pdf), {i: PageFrame(i) for i in range(pages)})


def _copy(fixed, seq: int) -> bytes:
    out, manifest, _ = fixed
    return (out / manifest.copies[seq - 1].file).read_bytes()


# --- compatibility --------------------------------------------------------------------------


def test_v1_issuance_decodes_exactly_as_before(v1_fixed):
    out, manifest, ctx = v1_fixed
    assert sorted(json.loads((out / "manifest.json").read_text(encoding="utf-8"))) == V1_MANIFEST_KEYS
    assert manifest.shift_scheme is None and ctx.shift.scheme == SCHEME_V1
    pdf = _copy(v1_fixed, 2)
    obs, _ = collect_file("c.pdf", pdf, ctx)
    page = render_pages(pdf, 200, [0])[0]
    shot, _ = screenshot_jpeg(page, np.random.default_rng(5), ScreenshotParams(render_dpi=200.0))
    photo, _ = photo_jpeg(page, np.random.default_rng(7), PhotoParams(angle_deg=10.0))
    got = {"pdf": _digest(obs), "screenshot": _digest(collect_from_image(shot, ctx)),
           "photo": _digest(collect_from_image(photo, ctx))}
    assert got == V1_DIGESTS


def test_old_manifest_without_scheme_is_v1(v1_fixed, sample_pdf, secret):
    out, manifest, ctx = v1_fixed
    d = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "shift_scheme" not in d
    old = IssueManifest.from_json(json.dumps(d))
    assert old.shift_settings == ShiftSettings(word_mm=0.05, row_mm=0.05, scheme=SCHEME_V1)
    again = load_context(sample_pdf, old, secret)
    assert again.plan.channel(CHANNEL_SHIFT) == ctx.plan.channel(CHANNEL_SHIFT)
    # geser-v1 word slots are the data groups (odd groups with a right neighbour) of every row.
    for slot in ctx.plan.channel(CHANNEL_SHIFT):
        if len(slot.ref) == 2:
            row = ctx.master.layout.pages[slot.page].rows[slot.ref[0]]
            assert slot.ref[1] % 2 == 1 and slot.ref[1] < len(row.groups) - 1


def test_v2_manifest_records_only_the_scheme_name(v2_fixed):
    out, manifest, ctx = v2_fixed
    d = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert d["shift_scheme"] == SCHEME_V2 and sorted(d) == sorted(V1_MANIFEST_KEYS + ["shift_scheme"])
    assert d["shift_mm"] == {"word_mm": V2_MAX_WORD_SHIFT_MM, "row_mm": 0.05}
    assert IssueManifest.from_json(json.dumps(d)).shift_settings.scheme == SCHEME_V2
    assert ctx.shift.scheme == SCHEME_V2


def test_shift_settings_validation():
    assert ShiftSettings.for_scheme(SCHEME_V2) == ShiftSettings(word_mm=0.025, row_mm=0.05, scheme=SCHEME_V2)
    assert ShiftSettings.for_scheme(SCHEME_V1, 0.04) == ShiftSettings(word_mm=0.04, row_mm=0.04)
    with pytest.raises(ValueError):
        ShiftSettings(word_mm=0.05, scheme=SCHEME_V2)  # a word gap could change by 0.10 mm
    with pytest.raises(ValueError):
        ShiftSettings(scheme="geser-v9")


# --- plan and marks -----------------------------------------------------------------------


def test_v2_moves_every_group_of_rows_with_three_or_more(v2_fixed, v1_fixed):
    _, _, ctx = v2_fixed
    layout = ctx.master.layout
    for row in layout.rows():
        expect = list(range(len(row.groups))) if len(row.groups) >= MIN_JOINT_GROUPS else []
        assert word_slot_groups(row, SCHEME_V2) == expect
    refs_v1 = shift_slot_refs(layout, set())
    refs_v2 = shift_slot_refs(layout, set(), scheme=SCHEME_V2)
    rows_v1 = [r for r in refs_v1 if len(r[1]) == 1]
    assert rows_v1 == [r for r in refs_v2 if len(r[1]) == 1]  # row slots are the same in both schemes
    assert len(refs_v2) > 2 * len(refs_v1) - len(rows_v1)
    # Every glyph of a geser-v2 copy moves by exactly +/-0.025 mm horizontally (glyph origins).
    disp = _raw_displacements(_copy(v2_fixed, 1), ctx)
    moved = {round(abs(dx) * 25.4 / 72.0, 4) for dx, _ in disp.values()}
    assert moved <= {0.0, 0.025}


def test_v2_word_gap_change_within_v1_bound(v2_fixed):
    """Neighbouring groups may move apart or together, but no word gap changes by more than
    the geser-v1 bound (0.05 mm) and no glyph moves more than 0.025 mm."""
    _, _, ctx = v2_fixed
    disp = _raw_displacements(_copy(v2_fixed, 2), ctx)
    mm = 25.4 / 72.0
    for row in ctx.master.layout.rows():
        words = [w for w in row.words if w.id in disp]
        for a, b in zip(words, words[1:]):
            assert abs(disp[b.id][0] - disp[a.id][0]) * mm <= 0.05 + 1e-4
            assert abs(disp[b.id][1] - disp[a.id][1]) * mm <= 1e-4  # no vertical step on a baseline


# --- joint decoder ------------------------------------------------------------------------


def test_row_projector_removes_the_nuisance():
    x = np.array([0.0, 30.0, 70.0, 100.0, 160.0])
    p1, p2 = row_projector(x, 1), row_projector(x, 2)
    assert np.allclose(p1 @ (3.0 + 0.2 * x), 0) and np.allclose(p2 @ (1.0 - 0.1 * x + 0.003 * x * x), 0)
    assert np.allclose(p1 @ p1, p1) and np.allclose(p1, p1.T)
    with pytest.raises(ValueError):
        row_projector(x[:2], 1)


def test_row_sign_llrs_exact_marginals():
    rng = np.random.default_rng(3)
    x = np.array([0.0, 40.0, 75.0, 120.0, 150.0, 210.0])
    s = np.array([1, -1, -1, 1, 1, -1])
    delta, sigma = 0.07, 0.02
    d = 0.5 + 0.001 * x + delta * s + rng.normal(0, sigma, x.size)
    llr = row_sign_llrs(x, d, delta, sigma)
    assert np.array_equal(np.sign(llr), s)
    # Brute force: every pattern, residual after projecting out offset and slope.
    p = row_projector(x, 1)
    pats = np.array(np.meshgrid(*[[-1, 1]] * x.size, indexing="ij")).reshape(x.size, -1).T
    ll = np.array([-np.sum((p @ (d - delta * q)) ** 2) / (2 * sigma**2) for q in pats])
    for g in range(x.size):
        ref = np.logaddexp.reduce(ll[pats[:, g] > 0]) - np.logaddexp.reduce(ll[pats[:, g] < 0])
        assert llr[g] == pytest.approx(ref, rel=1e-9, abs=1e-9)
    # All groups moved the same way: indistinguishable from the opposite pattern, LLR 0.
    same = row_sign_llrs(x, 0.3 + delta * np.ones(x.size), delta, sigma)
    assert np.allclose(same, 0.0, atol=1e-6)
    with pytest.raises(ValueError):
        row_sign_llrs(x, d, delta, 0.0)
    with pytest.raises(ValueError):
        row_sign_llrs(np.arange(MAX_JOINT_GROUPS + 1.0), np.zeros(MAX_JOINT_GROUPS + 1), delta, sigma)


def test_screen_row_drops_a_slipped_match():
    x = np.array([0.0, 40.0, 75.0, 120.0, 150.0, 210.0])
    delta = 0.07
    d = delta * np.array([1, -1, -1, 1, 1, -1]) + 0.2
    assert screen_row(x, d, delta).all()
    d[3] += 1.5  # the matcher locked onto the wrong letter
    keep = screen_row(x, d, delta)
    assert keep.tolist() == [True, True, True, False, True, True]


def test_joint_word_llrs_fits_sigma_and_splits_long_rows():
    rng = np.random.default_rng(11)
    delta, sigma = 0.07, 0.025
    rows, signs = [], []
    for g in [3, 5, 8, 2, 20] * 6:
        x = np.sort(rng.uniform(0, 400, g))
        s = rng.choice([-1, 1], g)
        rows.append((x, 1.0 + 0.002 * x + delta * s + rng.normal(0, sigma, g)))
        signs.append(s)
    llrs, fitted = joint_word_llrs(rows, delta, floor=0.05 * delta)
    assert fitted == pytest.approx(sigma, rel=0.15)
    assert all(np.all(l == 0) for l, (x, _) in zip(llrs, rows) if len(x) <= 2)
    right = [np.sign(l) == s for l, s in zip(llrs, signs) if len(l) >= 8]
    assert np.mean(np.concatenate(right)) > 0.85
    # Quadratic nuisance: a bowed row is read once the curvature is projected out.
    x = np.linspace(0, 400, 9)
    s = np.array([1, -1, 1, 1, -1, -1, 1, -1, 1])
    bow = 4e-6 * (x - 200) ** 2
    l2, _ = joint_word_llrs([(x, bow + delta * s)], delta, floor=0.005, degree=2)
    assert np.array_equal(np.sign(l2[0]), s)


def test_joint_strengths_mean_what_geser_v1_strengths_mean():
    """A group's strength is its offset from the row line through the other groups once their
    expected marks are taken off, in noise units, as the geser-v1 offset from the line through
    two control neighbours: a clear group scores about delta / sigma, a group put back at its
    master position about 0, a dropped group exactly 0. Nothing but the evidence enters."""
    rng = np.random.default_rng(11)
    delta, sigma = 0.07, 0.006
    x = np.linspace(50.0, 500.0, 9)
    s = np.array([1, -1, -1, 1, 1, -1, 1, -1, 1], dtype=float)
    tilt = 0.02 + 1e-4 * x  # an affine nuisance along the row: it does not enter the strength
    d = tilt + delta * s + rng.normal(0.0, sigma, 9)
    erased = d - delta * s * (np.arange(9) == 4)
    llrs, fitted = joint_word_llrs([(x, d), (x, erased)], delta, floor=0.05 * delta)
    rows = [[(10 + k, 0, float(x[k]), float(d[k])) for k in range(9)],
            [(30 + k, 1, float(x[k]), float(erased[k])) for k in range(9)]]
    st = joint_strengths(rows, llrs, fitted, delta, dropped=[99])
    assert st.positions.tolist() == list(range(10, 19)) + list(range(30, 39)) + [99]
    clear = st.values[:9, 0]
    assert np.allclose(clear * fitted, delta, atol=4 * sigma)
    assert st.values[13, 0] == st.values[9:18, 0].min() and st.values[13, 0] * fitted < 4 * sigma
    assert st.values[-1, 0] == 0.0
    # Exact marks and exact LLRs: the offset is exactly delta, whichever way the group moved.
    exact = joint_strengths([[(k, 0, float(x[k]), float(delta * s[k])) for k in range(9)]],
                            [s * 50.0], sigma, delta)
    assert np.allclose(exact.values[:, 0], delta / sigma)
    long_row = [(k, 0, float(k), float(delta * (-1) ** k)) for k in range(MAX_JOINT_GROUPS + 3)]
    assert len(joint_strengths([long_row], [np.array([50.0 * (-1) ** k for k in range(len(long_row))])],
                               sigma, delta)) == len(long_row)
    with pytest.raises(ValueError):
        joint_strengths(rows, llrs[:1], fitted, delta)
    with pytest.raises(ValueError):
        joint_strengths(rows, llrs, 0.0, delta)


def test_fit_page_field_takes_the_smooth_part_only():
    rng = np.random.default_rng(5)
    x, y = rng.uniform(50, 550, 240), rng.uniform(60, 780, 240)
    field = 0.02 + 1e-4 * x - 3e-7 * (x - 300) ** 2 + 2e-7 * x * y
    signs = 0.07 * rng.choice([-1, 1], x.size)
    d = field + signs
    d[7] += 3.0  # a slipped match does not bend the field
    fit = fit_page_field(x, y, d, degree=3)
    assert np.sqrt(np.mean((fit - field) ** 2)) < 0.02  # the random signs average out (expected 0.014)
    resid = d - fit
    assert np.mean(np.sign(resid[np.arange(x.size) != 7]) == np.sign(signs[np.arange(x.size) != 7])) > 0.97
    assert np.all(fit_page_field(x[:30], y[:30], d[:30], degree=3) == 0)  # too few points: no field


def test_v2_pdf_copy_reads_every_unambiguous_bit(v2_fixed):
    out, manifest, ctx = v2_fixed
    for seq in (1, 3):
        pdf = _copy(v2_fixed, seq)
        disp = measure_vector(pdf, ctx.master)
        rows, dropped = joint_measurements(ctx.master, ctx.plan, disp, ctx.shift.word_pt)
        assert dropped == 0 and len(rows) >= 40
        # The iterated page field leaves no trace of the marks on an exact copy.
        rows, llrs, sigma, dropped = joint_decode(ctx.master, ctx.plan, disp, ctx.shift.word_pt,
                                                  floor=0.05 * ctx.shift.word_pt)
        signs = [(np.sign(v) * (1 - 2 * u[1]), x_bit) for r, rl in zip(rows, llrs) for u, v in zip(r, rl)
                 if abs(v) > 1e-6 for x_bit in [2 * int(ctx.codewords[seq - 1][u[0]]) - 1]]
        assert len(signs) >= 340 and all(a == b for a, b in signs) and sigma < 0.2 * ctx.shift.word_pt
        sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
        x = ctx.codewords[seq - 1]
        assert np.all((sb.llr > 0) == (x[sb.positions] == 1))
        assert sb.meta["scheme"] == SCHEME_V2 and sb.meta["word_slots_read"] >= 340
        result = run_trace(collect_file("c.pdf", pdf, ctx)[0], ctx)
        assert [c.copy.seq for c in result.accused] == [seq]


def test_v2_screen_photo_names_the_copy(v2_fixed):
    _, _, ctx = v2_fixed
    page = render_pages(_copy(v2_fixed, 2), 200, [0])[0]
    data, _ = photo_jpeg(page, np.random.default_rng(7), PhotoParams(angle_deg=10.0))
    obs = collect_from_image(data, ctx)
    shift = next(o for o in obs if o.channel == CHANNEL_SHIFT)
    x = ctx.codewords[1]
    right = (shift.llr > 0) == (x[shift.positions] == 1)
    weight = np.tanh(np.abs(shift.llr) / 2)
    assert len(shift) > 150 and np.mean(right) > 0.75 and np.sum(weight * right) / np.sum(weight) > 0.8
    assert [c.copy.seq for c in run_trace(obs, ctx).accused] == [2]


def test_v2_shift_llrs_do_not_depend_on_codewords(v2_fixed):
    """Replacing every codeword of the context by random bits changes no observation."""
    _, _, ctx = v2_fixed
    pdf = _copy(v2_fixed, 2)
    page = render_pages(pdf, 200, [0])[0]
    data, _ = screenshot_jpeg(page, np.random.default_rng(5), ScreenshotParams(render_dpi=200.0))
    rng = np.random.default_rng(99)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    assert not np.array_equal(fake.codewords, ctx.codewords)
    for collect in (lambda c: collect_file("c.pdf", pdf, c)[0], lambda c: collect_from_image(data, c)):
        real, other = collect(ctx), collect(fake)
        assert [o.channel for o in real] == [o.channel for o in other]
        for a, b in zip(real, other):
            assert np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)
        assert len(next(o for o in real if o.channel == CHANNEL_SHIFT)) > 100


def test_v2_unmarked_master_accuses_nobody(v2_fixed, sample_pdf):
    _, _, ctx = v2_fixed
    obs, _ = collect_file("induk.pdf", sample_pdf, ctx)
    assert not run_trace(obs, ctx).accused


def test_v2_survives_affine_distortion_and_curvature(v2_fixed):
    """A smooth displacement field on top of the marks (affine plus a bow along the rows, as a
    photo leaves after rectification, evaluated where each word is measured) is taken out by
    the page field and the row nuisance, and the LLRs stay calibrated: about as many confident
    bits are wrong as their LLRs promise."""
    _, _, ctx = v2_fixed
    disp = measure_vector(_copy(v2_fixed, 3), ctx.master)
    rng = np.random.default_rng(0)
    distorted = {}
    for wid, (dx, dy) in disp.items():
        w = ctx.master.layout.word(wid)
        x, y = 0.5 * (w.x0 + w.x1), w.glyphs[0].y
        distorted[wid] = (dx + 0.9 + 0.004 * x + 0.002 * y + 2e-6 * (x - 300) ** 2 + rng.normal(0, 0.01),
                          dy - 1.3 + 0.003 * x - 0.001 * y + rng.normal(0, 0.01))
    sb = decode_displacements(ctx.master, ctx.plan, distorted, ctx.shift)
    right = (sb.llr > 0) == (ctx.codewords[2][sb.positions] == 1)
    sure = np.abs(sb.llr) > 2
    assert len(sb) > 380 and sure.sum() > 300 and np.mean(right) > 0.97
    # Expected errors among confident bits: sum of 1 / (1 + e^|LLR|); allow a generous margin.
    expected = float(np.sum(1.0 / (1.0 + np.exp(np.abs(sb.llr[sure])))))
    assert int(np.sum(~right[sure])) <= 3 * expected + 3


def test_local_field_reads_a_group_from_the_other_rows_only():
    x = np.tile(np.array([100.0, 130.0, 160.0, 190.0]), 3)
    y = np.repeat(np.array([200.0, 214.0, 228.0]), 4)
    row = np.repeat(np.array([4, 5, 6]), 4)
    cockle = 0.3 * np.sin(x / 40.0)
    marked = cockle.copy()
    marked[row == 5] += 0.07 * np.array([1, -1, -1, 1])  # the middle row carries marks
    field = local_field(x, y, row, marked, 20.0)
    assert np.allclose(field[row == 5], local_field(x, y, row, cockle, 20.0)[row == 5])  # own marks do not enter
    assert np.abs(field - cockle)[row == 5].max() < 0.06  # ... and the sheet's shape is read off the neighbours
    alone = local_field(np.append(x, 500.0), np.append(y, 700.0), np.append(row, 30), np.append(marked, 0.1), 20.0)
    assert alone[-1] == 0.0  # nothing nearby: no local field
    slipped = marked.copy()
    slipped[row == 4] = [cockle[0], cockle[1] + 5.0, cockle[2], cockle[3]]  # one match far off in the row above
    assert np.abs(local_field(x, y, row, slipped, 20.0) - cockle)[row == 5].max() < 0.25  # clipped, not followed
    assert local_field(np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0), 20.0).size == 0
    with pytest.raises(ValueError):
        local_field(x, y, row[:5], marked, 20.0)
    with pytest.raises(ValueError):
        local_field(x, y, row, marked, 0.0)


def test_choose_local_field_takes_the_kernel_that_predicts_best_or_none():
    rng = np.random.default_rng(11)
    cols = np.arange(60.0, 540.0, 30.0)
    x = np.tile(cols, 20)
    y = np.repeat(np.arange(100.0, 100.0 + 14.0 * 20, 14.0), cols.size)
    row = np.repeat(np.arange(20), cols.size)
    marks = 0.07 * rng.choice([-1.0, 1.0], x.size)
    noise = rng.normal(0, 0.02, x.size)
    wave = 0.25 * np.sin(x / 30.0 + y / 26.0)  # changes over about a centimetre
    kernels = tuple(mm * 72.0 / 25.4 for mm in LOCAL_FIELD_MM)
    field, kernel = choose_local_field(x, y, row, wave + marks + noise, kernels)
    assert kernel in kernels[:2]  # the short kernels follow it, the long ones average it away
    assert np.sqrt(np.mean((field - wave) ** 2)) < 0.5 * wave.std()
    resid = wave + marks + noise - field
    assert np.mean(np.sign(resid) == np.sign(marks)) > np.mean(np.sign(wave + marks + noise) == np.sign(marks)) + 0.1
    # nothing shared between the rows: no kernel predicts better than zero, and nothing is taken off
    flat, none = choose_local_field(x, y, row, marks + noise, kernels)
    assert none is None and not flat.any()
    empty, none = choose_local_field(np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0), kernels)
    assert empty.size == 0 and none is None


def _cockled(v2_fixed, seq: int, seed: int) -> dict:
    """The exact displacements of a copy on a sheet whose print is displaced as the first real
    prints were (research/fotoasli): waves of about 0.09 pt rms that change over a few
    centimetres, more than the mark (0.071 pt), which no cubic page field follows."""
    _, _, ctx = v2_fixed
    disp = measure_vector(_copy(v2_fixed, seq), ctx.master)
    rng = np.random.default_rng(seed)
    out = {}
    for wid, (dx, dy) in disp.items():
        w = ctx.master.layout.word(wid)
        x, y = 0.5 * (w.x0 + w.x1), w.glyphs[0].y
        wave = 0.10 * np.sin(x / 40.0 + y / 45.0) + 0.08 * np.cos(x / 28.0 - y / 60.0)
        out[wid] = (dx + wave + rng.normal(0, 0.02), dy)
    return out


def test_v2_local_field_reads_marks_through_cockled_paper(v2_fixed):
    """A print displaced like the real ones costs the row model alone a third of the word bits;
    reading each group also against the groups of the other rows nearby gives a good part of
    them back (measured here: 32 % wrong without, 22 % with)."""
    _, _, ctx = v2_fixed
    cockled = _cockled(v2_fixed, 3, 1)
    delta = ctx.shift.word_pt

    def wrong(local_mm):
        rows, llrs, _, _ = joint_decode(ctx.master, ctx.plan, cockled, delta, 0.05 * delta, local_mm=local_mm)
        bits = [((v > 0) != (w == 1)) == (ctx.codewords[2][q] == 1) for r, rl in zip(rows, llrs)
                for (q, w, _, _), v in zip(r, rl) if abs(v) > 1e-6]
        return 1.0 - float(np.mean(bits)), len(bits)

    plain, n = wrong(None)
    local, m = wrong(LOCAL_FIELD_MM)
    assert n > 300 and m > 300
    assert plain > 0.25 and local < 0.8 * plain


def test_v2_image_evidence_is_read_against_the_local_field_and_a_pdf_is_not(v2_fixed, monkeypatch):
    """decode_displacements takes the local field on image evidence (a pixel grid is given) and
    says which kernel each page chose; the same displacements as a PDF's are read as before."""
    _, _, ctx = v2_fixed
    cockled = _cockled(v2_fixed, 3, 2)
    x = ctx.codewords[2]
    grid = PixelGrid(np.diag([300.0 / 72.0, 300.0 / 72.0, 1.0]), 300.0, 300.0)
    image = decode_displacements(ctx.master, ctx.plan, cockled, ctx.shift, ctx.excluded, grid=grid)
    pdf = decode_displacements(ctx.master, ctx.plan, cockled, ctx.shift, ctx.excluded)
    kernels = image.meta["word_local_field_mm"]
    assert set(kernels) == {"0", "1"} and kernels["0"] in LOCAL_FIELD_MM
    assert "word_local_field_mm" not in pdf.meta

    def wrong(sb):
        words = sb.llr[:sb.meta["word_slots_read"]], sb.positions[:sb.meta["word_slots_read"]]
        return float(np.mean((words[0] > 0) != (x[words[1]] == 1)))

    assert wrong(image) < 0.9 * wrong(pdf)
    # an exact copy has nothing for the field to follow: no kernel is chosen and nothing changes
    exact = measure_vector(_copy(v2_fixed, 3), ctx.master)
    sb = decode_displacements(ctx.master, ctx.plan, exact, ctx.shift, ctx.excluded, grid=grid)
    assert sb.meta["word_local_field_mm"] == {"0": None, "1": None} and sb.meta["word_slots_read"] >= 340
    sure = np.abs(sb.llr) > 1
    assert sure.sum() > 380 and np.all((sb.llr[sure] > 0) == (x[sb.positions[sure]] == 1))
    monkeypatch.setattr("tapak.decoder.ch_shift.LOCAL_FIELD_MM", ())
    off = decode_displacements(ctx.master, ctx.plan, exact, ctx.shift, ctx.excluded, grid=grid)
    assert np.array_equal(off.positions, sb.positions) and np.array_equal(off.llr, sb.llr)
    assert "word_local_field_mm" not in off.meta


def test_registry_records_and_checks_the_shift_scheme(tmp_path, v2_fixed):
    """A geser-v2 document entry carries the scheme name (and only for geser-v2); a manifest
    edited back to geser-v1 no longer matches the registry, and an unknown name is refused."""
    import copy

    from tapak.config import Settings
    from tapak.registry.chain import Registry, registry_from_manifest, shift_scheme_problems
    from tapak.registry.verify import verify_registry
    from tapak.service import check_registry, ensure_keys

    _, manifest, _ = v2_fixed
    s = Settings(data_dir=tmp_path / "data", key_dir=tmp_path / "keys", canary_domain="")
    keys = ensure_keys(s)
    with Registry.open(s.registry_path) as reg:
        entries = registry_from_manifest(manifest, reg, signer=keys.signer, code_secret=keys.code_secret)
        assert entries[0].payload["shift_scheme"] == SCHEME_V2
        base = {k: entries[0].payload[k] for k in ("doc_hash", "doc_name", "params", "channels", "shift_mm",
                                                    "excluded_rows", "plan_summary", "threshold_rule",
                                                    "threshold_full", "issuer", "issued_at")}
        with pytest.raises(ValueError, match="skema geser"):
            reg.record_document(**dict(base, doc_hash="cd" * 32), shift_scheme="geser-v9")
    assert verify_registry(s.registry_path, keys.public_key_hex).ok
    assert shift_scheme_problems(SCHEME_V1) and not shift_scheme_problems(SCHEME_V2)
    assert "shift_scheme" not in check_registry(s, manifest).document_mismatch
    edited = copy.deepcopy(manifest)
    edited.shift_scheme = None  # the record rewritten to geser-v1
    assert "shift_scheme" in check_registry(s, edited).document_mismatch


def test_cli_issues_v2_by_default_and_v1_on_request(tmp_path, capsys, monkeypatch):
    from tapak.cli import build_parser, main
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.chdir(tmp_path)
    assert build_parser().parse_args(["issue", "a.pdf", "b.csv"]).geser == "v2"
    for flag, scheme in (("v2", SCHEME_V2), ("v1", None)):
        data = tmp_path / flag
        rc = main(["--data", str(data), "--keys", str(tmp_path / "keys"), "issue", str(SAMPLE), str(RECIPIENTS),
                   "--no-registry", "--canary-domain", "", "--workers", "1", "--geser", flag])
        out = capsys.readouterr().out
        assert rc == 0 and f"Skema geser: geser-{flag}" in out
        manifest = json.loads(next((data / "dokumen").glob("*/manifest.json")).read_text(encoding="utf-8"))
        assert manifest.get("shift_scheme") == scheme
