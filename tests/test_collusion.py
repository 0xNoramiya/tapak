"""The agreement-targeted collusion attack of ``tapak.collusion`` (research tool).

The coalition must see exactly where its copies agree (background cells and shift units) from
the copies alone, estimate the master position of agreeing data units from typography, and
produce a PDF in which those marks are neutralized while the disagreeing ones follow the rule.
The geser-v1 tests use a geser-v1 issuance (the scheme of every document issued before
geser-v2); the geser-v2 tests use the default issuance, where every word group is a data unit.
"""

from __future__ import annotations

import numpy as np
import pytest

from tapak.collusion import (
    CHANNELS,
    RULES,
    CoalitionView,
    ForgeryPlan,
    ShiftUnit,
    agreement_posterior,
    anchored_sign,
    attack,
    coalition_view,
    copy_backgrounds,
    copy_displacements,
    forge_copy,
    image_cell_levels,
    image_cell_values,
    plan_forgery,
    row_signs,
    shift_units,
    typographic_shift,
)
from tapak.marker.background import PageGrid, SCREEN_BACKGROUND, pattern_image
from tapak.marker.pdf_shift import SCHEME_V1, SCHEME_V2
from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

MEMBERS = (4, 12)


@pytest.fixture(scope="module")
def coalition(issued_v1):
    """Two copies of the geser-v1 issuance."""
    out, manifest = issued_v1
    return [(out / manifest.copies[s - 1].file).read_bytes() for s in MEMBERS]


@pytest.fixture(scope="module")
def coalition_v2(issued):
    """Two copies of the default (geser-v2) issuance."""
    out, manifest = issued
    assert manifest.shift_scheme == SCHEME_V2
    return [(out / manifest.copies[s - 1].file).read_bytes() for s in MEMBERS]


def _true_cell_levels(ctx, page: int, x: np.ndarray) -> np.ndarray:
    from tapak.marker.background import cell_levels, page_grids

    grid = page_grids([(p.width, p.height) for p in ctx.master.layout.pages], ctx.key, ctx.background)[page]
    return cell_levels(grid, ctx.plan.channel(CHANNEL_BACKGROUND), x)


def test_image_cell_levels_reads_every_cell_exactly():
    rng = np.random.default_rng(0)
    grid = PageGrid(0, 595.0, 842.0, SCREEN_BACKGROUND, b"k")
    levels = rng.integers(-1, 2, size=(grid.ny, grid.nx)).astype(np.float64)
    got, base, amp = image_cell_levels(pattern_image(grid, levels))
    assert np.array_equal(got, levels) and base == 253.0 and amp == 2.0


def test_masked_cells_are_read_continuously_and_agreement_is_a_posterior():
    """A masked pattern (research/sepakat/samaran.py) shows continuous levels; the coalition
    inverts the upsampling and weighs each cell's agreement by Bayes' rule."""
    from tapak.marker.background import BackgroundSettings

    rng = np.random.default_rng(1)
    grid = PageGrid(0, 595.0, 842.0, BackgroundSettings(base=249.0, amplitude=2.0), b"k")
    levels = rng.uniform(-3.0, 3.0, size=(grid.ny, grid.nx))
    est = image_cell_values(pattern_image(grid, levels), 249.0, 2.0)
    assert np.sqrt(np.mean((est - levels) ** 2)) < 0.1 and np.abs(est - levels).max() < 0.4
    clear = agreement_posterior(np.array([[1.0, 2.6], [1.0, -2.6]]), 2.0)
    assert clear[0] > 0.7 and clear[1] < 1e-6
    exact = agreement_posterior(np.array([[1.0, 1.0], [1.0, -1.0]]), 1e-4, quant=0.05)
    assert exact[0] == pytest.approx(1.0) and exact[1] == pytest.approx(0.0, abs=1e-9)
    view = CoalitionView(copies=2, levels={0: np.array([[[1.0, -1.0]], [[1.0, 1.0]]])},
                         agree_prob={0: np.array([[0.6, 0.4]])})
    plan = plan_forgery(view, "salin", agree_threshold=0.5, rng=np.random.default_rng(0))
    assert plan.levels[0].tolist() == [[0.0, -1.0]]
    strict = plan_forgery(view, "salin", agree_threshold=0.9, rng=np.random.default_rng(0))
    assert strict.levels[0].tolist() == [[1.0, -1.0]]


def test_typographic_shift_rounds_or_declines():
    d = 0.14
    assert typographic_shift(3.0 + d, 3.0 - d, d) == d
    assert typographic_shift(3.0 - d, 3.0 + d, d) == -d
    assert typographic_shift(3.0, 3.0, d) is None          # no shift visible: not a data unit pattern
    assert typographic_shift(6.0 + d, 3.0 - d, d) is None  # unequal gaps in the master
    unit = ShiftUnit((0, 1, 1), "kata", np.array([10.0, 10.0]))
    assert unit.agree and not ShiftUnit((0, 1, 1), "kata", np.array([10.0, 10.28])).agree


def test_coalition_sees_agreement_exactly(ctx_v1, coalition):
    ctx = ctx_v1
    view = coalition_view(coalition)
    assert isinstance(view, CoalitionView) and view.copies == 2 and abs(view.delta_pt - ctx.shift.word_pt) < 1e-3
    x = ctx.codewords[[s - 1 for s in MEMBERS]].astype(np.int64)
    for page, stack in view.levels.items():
        for j in range(2):
            assert np.array_equal(stack[j], _true_cell_levels(ctx, page, x[j]))
    slots = {(s.page,) + s.ref: s.positions[0] for s in ctx.plan.channel(CHANNEL_SHIFT)}
    assert len(view.units) == len(slots)
    disp = copy_displacements(coalition[0], ctx.master)
    right = 0
    for u in view.units:
        q = slots[u.ref]
        assert u.agree == (x[0, q] == x[1, q])
        if u.typographic is None:
            continue
        row = ctx.master.layout.pages[u.ref[0]].rows[u.ref[1]]
        if u.kind == "kata":
            true = np.mean([disp[row.words[i].id][0] for i in row.groups[u.ref[2]].word_indices])
        else:
            true = np.median([disp[w.id][1] for w in row.words])
        assert abs(true - u.typographic) < 1e-3
        right += 1
    assert right > 0.8 * len(view.units)
    units, delta = shift_units([__import__("tapak.marker.layout", fromlist=["x"]).extract_layout(coalition[0])] * 2)
    assert all(u.agree for u in units) and delta > 0


def test_plan_follows_the_rule_and_the_channels(coalition):
    view = coalition_view(coalition)
    with pytest.raises(ValueError):
        plan_forgery(view, "lain")
    with pytest.raises(ValueError):
        plan_forgery(view, "acak", channels=("teks",))
    salin = plan_forgery(view, "salin", rng=np.random.default_rng(0))
    for page, stack in view.levels.items():
        agree = np.all(stack == stack[:1], axis=0)
        assert np.all(salin.levels[page][agree] == 0) and np.array_equal(salin.levels[page][~agree], stack[0][~agree])
    assert salin.counts["sel_sama_dihapus"] == salin.counts["sel_sama"] > 0
    assert all(u.ref in salin.moves for u in view.units if u.agree and u.typographic is not None)
    assert not any(u.ref in salin.moves for u in view.units if not u.agree)
    rata = plan_forgery(view, "rata", rng=np.random.default_rng(0))
    assert all(np.all(lv == 0) for lv in rata.levels.values())  # two copies: average of +/- is 0
    shift_only = plan_forgery(view, "acak", channels=("geser",), rng=np.random.default_rng(0))
    assert shift_only.counts["sel_sama_dihapus"] == 0 and shift_only.counts["unit_sama_dinetralkan"] > 0
    keep = plan_forgery(view, "acak", erase_fraction=0.0, channels=CHANNELS, rng=np.random.default_rng(0))
    assert keep.counts["sel_sama_dihapus"] == 0 and keep.counts["unit_sama_dinetralkan"] == 0
    assert set(RULES) == {"salin", "acak", "rata", "mayoritas", "minoritas"} and isinstance(keep, ForgeryPlan)


def test_vote_rules_and_randomized_agreeing_marks(issued_v1):
    """Three copies: ``mayoritas`` takes the level two copies share at every disagreeing cell and
    ``minoritas`` the other; without neutralization agreeing cells keep copy 1's level. The
    randomized neutralization (``acak``) keeps every agreeing cell at full strength with a random
    sign and puts every agreeing data unit at its own or its mirrored position."""
    out, manifest = issued_v1
    view = coalition_view([(out / manifest.copies[s - 1].file).read_bytes() for s in (3, 8, 15)])
    for rule, sign in (("mayoritas", 1.0), ("minoritas", -1.0)):
        plan = plan_forgery(view, rule, erase_fraction=0.0, rng=np.random.default_rng(0))
        for page, stack in view.levels.items():
            agree = np.all(stack == stack[:1], axis=0)
            want = sign * np.sign(stack.sum(axis=0))
            assert np.array_equal(plan.levels[page][~agree], want[~agree])
            assert np.array_equal(plan.levels[page][agree], stack[0][agree])
        for u in view.units:
            if not u.agree:
                target = float(u.positions[0]) + plan.moves[u.ref]
                same = int(np.sum(np.abs(u.positions - target) <= 0.01))
                assert same == (2 if rule == "mayoritas" else 1)
    rnd = plan_forgery(view, "acak", rng=np.random.default_rng(1), neutralize="acak")
    flips = []
    for page, stack in view.levels.items():
        agree = np.all(stack == stack[:1], axis=0) & (stack[0] != 0)
        assert np.array_equal(np.abs(rnd.levels[page][agree]), np.abs(stack[0][agree]))
        flips.append(np.mean(rnd.levels[page][agree] != stack[0][agree]))
    assert 0.4 < float(np.mean(flips)) < 0.6
    moved = [rnd.moves[u.ref] / u.typographic for u in view.units if u.agree and u.typographic is not None]
    assert set(np.round(moved, 6)) <= {0.0, -2.0} and 0.3 < np.mean(np.array(moved) == 0.0) < 0.7


def test_forged_pdf_carries_the_plan(ctx_v1, coalition):
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tapak.marker.pdf_zerowidth import ZW_CHARS

    ctx = ctx_v1
    forged, view, plan = attack(ctx.master, coalition, "salin", 1.0, rng=np.random.default_rng(2))
    assert view.scheme == SCHEME_V1  # the scheme the master is grouped for
    images = copy_backgrounds(forged)
    assert sorted(images) == sorted(view.levels)
    for page, img in images.items():
        assert np.array_equal(image_cell_levels(img)[0], plan.levels[page])
    assert not any(ch in extract_pdf_text(forged) for ch in ZW_CHARS)
    disp = copy_displacements(forged, ctx.master)
    for u in view.units:
        if u.agree and u.typographic is not None and u.kind == "kata":
            row = ctx.master.layout.pages[u.ref[0]].rows[u.ref[1]]
            assert abs(np.mean([disp[row.words[i].id][0] for i in row.groups[u.ref[2]].word_indices])) < 1e-3
    again = forge_copy(ctx.master, coalition, plan)
    assert copy_backgrounds(again).keys() == images.keys()


def test_reversal_keeps_every_mark_and_escapes_the_erasure_check(ctx_v1, coalition):
    """``neutralize="balik"``: agreeing cells are negated and agreeing data units mirrored about
    their master position, so every unit stays fully marked. The erasure check (which reads how
    clearly units are marked) does not fire, the coalition is not named, and nobody else is."""
    from tapak.collusion import NEUTRALIZE
    from tapak.decoder.trace import collect_file, run_trace

    ctx = ctx_v1
    view = coalition_view(coalition)
    with pytest.raises(ValueError):
        plan_forgery(view, "acak", neutralize="lain")
    plan = plan_forgery(view, "salin", rng=np.random.default_rng(0), neutralize="balik")
    for page, stack in view.levels.items():
        agree = np.all(stack == stack[:1], axis=0)
        assert np.array_equal(plan.levels[page][agree], -stack[0][agree])
        assert np.array_equal(plan.levels[page][~agree], stack[0][~agree])
    for u in view.units:
        if u.agree and u.typographic is not None:
            assert plan.moves[u.ref] == pytest.approx(-2.0 * u.typographic)
    assert set(NEUTRALIZE) == {"hapus", "balik", "acak"}
    forged, _, _ = attack(ctx.master, coalition, "acak", 1.0, rng=np.random.default_rng(1), neutralize="balik")
    obs, notes = collect_file("bukti.pdf", forged, ctx)
    result = run_trace(obs, ctx, notes)
    assert result.erasure.z is not None and not result.erasure.flagged
    assert not result.named_seqs
    # The reversed read is as clear as an honest one, so naming nobody contradicts the bound,
    # and its marks follow the opposite of the bias vector, which the reversal check sees.
    assert result.contradiction is not None and result.contradiction.flagged
    assert result.reversal.flagged and result.reversal.z_signs < -10


# --- geser-v2: every word group is a data unit ---------------------------------------------


def test_row_signs_reads_equal_gaps_and_splits_at_a_tab():
    """All gaps of a row are equal in the master, so the gaps of a copy give the sign pattern;
    a gap no pattern explains (a label) splits the row, and a uniform piece stays undecided
    unless a known (disagreeing) sign anchors it."""
    d = 0.07
    s = [1, -1, -1, 1, 1, -1]
    gaps = [3.0 + d * (s[i + 1] - s[i]) for i in range(5)]
    assert row_signs(gaps, d) == s
    assert row_signs([g + 0.02 for g in gaps], d) == s  # within delta / 2 of the pattern
    tab = [20.0] + gaps[1:]
    assert row_signs(tab, d) == [None] + s[1:]
    assert row_signs(tab, d, known=[1, None, None, None, None, None]) == s
    assert row_signs([3.0] * 4, d) == [None] * 5
    assert row_signs([3.0] * 4, d, known=[None, -1, None, None, None]) == [-1] * 5
    assert row_signs([], d, known=[1]) == [1] and row_signs([], d) == [None]
    with pytest.raises(ValueError):
        row_signs(gaps, d, known=[None])
    with pytest.raises(ValueError):
        shift_units([], scheme="geser-v9")


def test_anchored_sign_uses_shared_column_edges_and_line_pitches():
    """A unit takes the sign that puts it on master values shared by at least two known units
    (a column edge, a line pitch); no such value, a single anchor, or both signs fitting leave
    it undecided."""
    d = 0.07
    margin = np.array([72.0, 72.0, 72.0, 150.0])
    assert anchored_sign([(72.0 + d, 1, margin)], d) == 1
    assert anchored_sign([(72.0 - d, 1, margin)], d) == -1
    assert anchored_sign([(80.0, 1, margin)], d) is None            # not on a shared edge
    assert anchored_sign([(150.0 + d, 1, margin)], d) is None       # one anchor is not a column
    assert anchored_sign([(72.0 + d, 1, margin), (300.0, 1, margin)], d) == 1  # one reading fits
    pitches = np.array([14.0, 14.0, 14.0, 20.0, 20.0])
    # a data row moved by +d: its pitch above grows by d and its pitch below shrinks by d
    assert anchored_sign([(14.0 + d, 1, pitches), (20.0 - d, -1, pitches)], d) == 1
    assert anchored_sign([(14.0 - d, 1, pitches), (14.0 + d, -1, pitches)], d) == -1
    both = np.array([14.0, 14.0, 14.0 + 2 * d, 14.0 + 2 * d])        # master pitches 2 d apart
    assert anchored_sign([(14.0 + d, 1, both)], d) is None
    assert anchored_sign([], d) is None
    with pytest.raises(ValueError):
        anchored_sign([(72.0, 1, margin)], 0.0)


def test_v2_coalition_sees_agreement_and_reads_rows(ctx, coalition_v2):
    """geser-v2: every slot of the plan is a coalition unit, agreement is exact, word and row
    deltas are told apart, and the typographic estimate (row by row, then anchored on column
    edges and line pitches) decides nearly every agreeing unit and is right for all of them."""
    view = coalition_view(coalition_v2, scheme=SCHEME_V2)
    assert view.scheme == SCHEME_V2 and abs(view.delta_pt - ctx.shift.word_pt) < 1e-3
    x = ctx.codewords[[s - 1 for s in MEMBERS]].astype(np.int64)
    slots = {(s.page,) + s.ref: s.positions[0] for s in ctx.plan.channel(CHANNEL_SHIFT)}
    assert len(view.units) == len(slots) and all(u.ref in slots for u in view.units)
    disp = copy_displacements(coalition_v2[0], ctx.master)
    agreeing = decided = right = 0
    for u in view.units:
        q = slots[u.ref]
        assert u.agree == (x[0, q] == x[1, q])
        if u.kind == "baris" and not u.agree:
            assert abs(np.ptp(u.positions) - 2 * ctx.shift.row_pt) < 1e-3
        if not u.agree:
            continue
        agreeing += 1
        if u.typographic is None:
            continue
        decided += 1
        row = ctx.master.layout.pages[u.ref[0]].rows[u.ref[1]]
        if u.kind == "kata":
            true = np.mean([disp[row.words[i].id][0] for i in row.groups[u.ref[2]].word_indices])
        else:
            true = np.median([disp[w.id][1] for w in row.words])
        right += int(abs(true - u.typographic) < 1e-3)
    assert decided >= 0.95 * agreeing and right == decided


def test_v2_forgery_puts_agreeing_groups_back_and_lowers_their_strengths(ctx, coalition_v2):
    """The forged geser-v2 PDF has its decided agreeing groups at their master positions; the
    decoder reads those groups less clearly than the groups that kept a mark, so the erasure
    statistic of the shift observations turns negative, the coalition is not named and nobody
    else is. Reversing instead keeps every group marked and is not flagged.

    On the shift units of one page alone the statistic is not reliably past the threshold
    (Z -1.4 to -5.2 over random codes): where most groups of a row are back at their master
    positions, the row's offset makes them look like groups that all moved the same way. The
    issuance here has random copy ids, so only what holds for every code is asserted."""
    from tapak.decoder.erasure import erasure_check
    from tapak.decoder.trace import collect_file, run_trace

    forged, view, plan = attack(ctx.master, coalition_v2, "acak", 1.0, channels=("geser",),
                                rng=np.random.default_rng(2))
    assert view.scheme == SCHEME_V2 and plan.counts["unit_sama_dinetralkan"] >= 0.95 * plan.counts["unit_sama"]
    disp = copy_displacements(forged, ctx.master)
    back_home = []
    for u in view.units:
        if u.agree and u.typographic is not None and u.kind == "kata":
            row = ctx.master.layout.pages[u.ref[0]].rows[u.ref[1]]
            back_home.append(abs(np.mean([disp[row.words[i].id][0] for i in row.groups[u.ref[2]].word_indices])) < 1e-3)
    assert len(back_home) > 200 and np.mean(back_home) >= 0.98  # a wrong typographic sign moves a group to 2 delta
    obs, notes = collect_file("bukti.pdf", forged, ctx)
    shift = [o for o in obs if o.channel == CHANNEL_SHIFT]
    check = erasure_check(shift, ctx.p)
    assert check.z is not None and check.z < 0 and check.units == {"geser": len(shift[0].strengths)}
    st = shift[0].strengths
    strength = dict(zip(st.positions.tolist(), np.asarray(st.values).reshape(len(st), -1)[:, 0].tolist()))
    slot_of = {(s.page,) + s.ref: s.positions[0] for s in ctx.plan.channel(CHANNEL_SHIFT)}

    def strengths(units):
        return [strength[slot_of[u.ref]] for u in units if slot_of[u.ref] in strength]

    put_back = strengths(u for u in view.units if u.kind == "kata" and u.agree and u.typographic is not None)
    kept = strengths(u for u in view.units if u.kind == "kata" and not u.agree)
    assert len(put_back) > 200 and len(kept) > 50 and np.median(put_back) < 0.75 * np.median(kept)
    honest = [o for o in collect_file("salinan.pdf", coalition_v2[0], ctx)[0] if o.channel == CHANNEL_SHIFT]
    assert not erasure_check(honest, ctx.p).flagged
    x = ctx.codewords[[s - 1 for s in MEMBERS]].astype(np.int64)
    agree = x[0] == x[1]

    def signed(sb):
        w = np.tanh(np.abs(sb.llr) / 2) * np.where((sb.llr > 0) == (x[0][sb.positions] == 1), 1.0, -1.0)
        return float(np.sum(w[agree[sb.positions]]))

    assert signed(shift[0]) < 0.25 * signed(honest[0])
    result = run_trace(obs, ctx, notes)
    assert result.named_seqs <= set(MEMBERS)
    flipped, _, back = attack(ctx.master, coalition_v2, "acak", 1.0, rng=np.random.default_rng(3), neutralize="balik")
    for u in view.units:
        if u.agree and u.typographic is not None:
            assert back.moves[u.ref] == pytest.approx(-2.0 * u.typographic)
    obs2, notes2 = collect_file("bukti.pdf", flipped, ctx)
    reversed_ = run_trace(obs2, ctx, notes2)
    assert reversed_.erasure.z is not None and not reversed_.erasure.flagged
    assert not reversed_.named_seqs and reversed_.reversal.flagged
