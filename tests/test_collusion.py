"""The agreement-targeted collusion attack of ``tapak.collusion`` (research tool).

The coalition must see exactly where its copies agree (background cells and shift units) from
the copies alone, estimate the master position of agreeing data units from typography, and
produce a PDF in which those marks are neutralized while the disagreeing ones follow the rule.
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
    attack,
    coalition_view,
    copy_backgrounds,
    copy_displacements,
    forge_copy,
    image_cell_levels,
    image_cell_values,
    plan_forgery,
    shift_units,
    typographic_shift,
)
from tapak.marker.background import PageGrid, SCREEN_BACKGROUND, pattern_image
from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

MEMBERS = (4, 12)


@pytest.fixture(scope="module")
def coalition(issued):
    out, manifest = issued
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


def test_coalition_sees_agreement_exactly(ctx, coalition):
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
    assert set(RULES) == {"salin", "acak", "rata"} and isinstance(keep, ForgeryPlan)


def test_forged_pdf_carries_the_plan(ctx, coalition):
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tapak.marker.pdf_zerowidth import ZW_CHARS

    forged, view, plan = attack(ctx.master, coalition, "salin", 1.0, rng=np.random.default_rng(2))
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


def test_reversal_keeps_every_mark_and_escapes_the_erasure_check(ctx, coalition):
    """``neutralize="balik"``: agreeing cells are negated and agreeing data units mirrored about
    their master position, so every unit stays fully marked. The erasure check (which reads how
    clearly units are marked) does not fire, the coalition is not named, and nobody else is."""
    from tapak.collusion import NEUTRALIZE
    from tapak.decoder.trace import collect_file, run_trace

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
    assert set(NEUTRALIZE) == {"hapus", "balik"}
    forged, _, _ = attack(ctx.master, coalition, "acak", 1.0, rng=np.random.default_rng(1), neutralize="balik")
    obs, notes = collect_file("bukti.pdf", forged, ctx)
    result = run_trace(obs, ctx, notes)
    assert result.erasure.z is not None and not result.erasure.flagged
    assert not result.named_seqs
