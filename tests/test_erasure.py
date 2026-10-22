"""Erasure check (``tapak.decoder.erasure``) and the code-blind strengths it reads.

The check correlates how clearly every code position was read with q = (2p - 1)^2. Honest
evidence has strengths independent of the bias vector, so Z is standard; an erasure that
follows the colluders' agreement makes it strongly negative. The tests cover the statistic
on synthetic strengths, the decoders' strengths (also when no background pattern is found),
code-blindness, the warning next to the verdict (CLI summary, berita acara, web) and the rule
that the check never changes a verdict.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tapak.decoder.accuse import THRESHOLD_RULE, VERDICT_INSUFFICIENT, Attribution, ThresholdRecord, is_caveat
from tapak.decoder.erasure import (
    ERASURE_ALARM_RATE,
    ERASURE_MIN_POSITIONS,
    ERASURE_NOTE,
    ERASURE_Z,
    SILENT_BACKGROUND_RULE,
    ErasureCheck,
    agreement_score,
    background_pattern_seen,
    erasure_check,
    erasure_note,
    erasure_z,
    format_rate,
    position_scores,
    rank_scores,
)
from tapak.decoder.contradiction import CONTRADICTION_NOTE
from tapak.decoder.softbits import SoftBits, Strengths
from tapak.tardos.code import random_code
from tapak.tardos.params import TardosParams


def _obs(positions, values, channel="background") -> SoftBits:
    return SoftBits(channel, np.zeros(0, dtype=np.int64), np.zeros(0), {}, Strengths(positions, values))


def test_agreement_score_and_rank_scores():
    assert np.allclose(agreement_score(np.array([0.5, 0.0, 1.0, 0.25])), [0.0, 1.0, 1.0, 0.25])
    r = rank_scores(np.arange(1000.0))
    assert abs(r.mean()) < 1e-12 and abs(r.var() - 1.0) < 1e-3
    tied = rank_scores(np.array([0.0, 0.0, 1.0, 1.0]))
    assert tied[0] == tied[1] < 0 < tied[2] == tied[3]
    assert rank_scores(np.zeros(0)).size == 0


def test_erasure_z_sign_and_degenerate_inputs():
    q = np.linspace(0, 1, 500)
    assert erasure_z(-q, q) < -20 and erasure_z(q, q) > 20
    assert erasure_z(np.ones(500), q) == 0.0 and erasure_z(q, np.ones(500)) == 0.0
    assert erasure_z(np.array([1.0, 2.0]), np.array([0.0, 1.0])) == 0.0


def test_position_scores_ranks_each_measure_and_skips_constant_ones():
    obs = [_obs([0, 1, 2, 3], [[1.0, 5.0], [2.0, 5.0], [3.0, 5.0], [4.0, 5.0]]),
           _obs([3, 4], [7.0, 7.0], channel="shift"),
           SoftBits("zw", np.array([1]), np.array([8.0]))]
    pos, scores, units = position_scores(obs, 10)
    assert list(pos) == [0, 1, 2, 3]
    assert np.allclose(scores, rank_scores(np.array([1.0, 2.0, 3.0, 4.0])))
    assert units == {"latar": 4}
    with pytest.raises(ValueError):
        position_scores([_obs([0, 11], [1.0, 2.0])], 10)


def test_null_distribution_is_standard_and_targeted_erasure_is_flagged():
    """Strengths drawn independently of p: Z has mean 0 and spread 1, alarms are rare. Strengths
    set to 0 where two simulated colluders agree: Z far below the threshold."""
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    rng = np.random.default_rng(5)
    zs, flagged = [], []
    for _ in range(300):
        p, x = random_code(params, 2, rng, 1500)
        st = np.abs(rng.normal(1.0, 0.5, 1500))
        check = erasure_check([_obs(np.arange(1500), st)], p)
        zs.append(check.z)
        agree = x[0] == x[1]
        attacked = np.where(agree, np.abs(rng.normal(0.0, 0.3, 1500)), st)
        flagged.append(erasure_check([_obs(np.arange(1500), attacked)], p).flagged)
    zs = np.array(zs)
    assert abs(zs.mean()) < 0.2 and 0.85 < zs.std() < 1.15 and np.mean(zs <= -ERASURE_Z) < 0.02
    assert all(flagged)


def test_too_few_positions_are_not_checked():
    p = np.full(50, 0.3)
    check = erasure_check([_obs(np.arange(50), np.linspace(0, 1, 50))], p)
    assert check.z is None and not check.flagged and check.positions == 50 < ERASURE_MIN_POSITIONS
    assert "tidak diperiksa" in check.text()


def test_note_and_text_say_it_changes_nothing():
    check = ErasureCheck(-12.345, 2987, -ERASURE_Z, ERASURE_ALARM_RATE, True, {"latar": 2987})
    thr = f"{-ERASURE_Z:.2f}".replace(".", ",")
    assert check.text() == f"z = -12,35 (ambang {thr}; 2.987 posisi terukur)"
    note = erasure_note(check)
    assert note.startswith(ERASURE_NOTE) and "putusan, ambang, dan skor tidak berubah" in note
    assert "10^-3" in note and "untuk dokumen tertentu" in note and is_caveat(note) and not is_caveat("catatan biasa")
    assert format_rate(1e-3) == "10^-3" and format_rate(0.0025) == "0,0025"
    assert chr(0x2014) not in note and ERASURE_Z >= 3.09


def test_strengths_container_and_concat():
    a = Strengths([1, 2], [0.5, 1.5])
    assert a.values.shape == (2, 1) and len(a) == 2
    b = Strengths([3], [[1.0]])
    merged = SoftBits.concat("shift", [SoftBits("shift", [1], [1.0], {}, a), SoftBits("shift", [3], [2.0], {}, b),
                                       SoftBits("shift", [4], [1.0])])
    assert list(merged.strengths.positions) == [1, 2, 3] and merged.strengths.values.shape == (3, 1)
    assert SoftBits.concat("shift", [SoftBits("shift", [4], [1.0])]).strengths is None
    with pytest.raises(ValueError):
        Strengths([1, 2], [1.0])


def test_shift_strengths_mark_implausible_units_as_erased(issued_v1, ctx_v1):
    """geser-v1: one strength per read unit, |s| / sigma, and 0 for an implausible offset."""
    from tapak.decoder.ch_shift import decode_displacements, measure_vector

    out, manifest = issued_v1
    ctx = ctx_v1
    disp = measure_vector((out / manifest.copies[0].file).read_bytes(), ctx.master)
    sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
    assert len(sb.strengths) == len(sb) > 100 and np.all(sb.strengths.values > 1.0)
    odd = {row.words[i].id for page in ctx.master.layout.pages for row in page.rows
           for g in row.groups[1::2] for i in g.word_indices}
    bumped = {k: (v[0] + (1.0 if k in odd else 0.0), v[1]) for k, v in disp.items()}  # data groups far off
    sb2 = decode_displacements(ctx.master, ctx.plan, bumped, ctx.shift, ctx.excluded)
    assert sb2.meta["slots_implausible"] > 0 and np.sum(sb2.strengths.values == 0.0) >= sb2.meta["slots_implausible"]


def test_v2_shift_strengths_cover_every_decoded_group(issued, ctx):
    """geser-v2: every decoded word group has a strength (also one whose sign the row cannot
    tell apart), groups read as bits are clear on a PDF, a slipped match reads 0."""
    from tapak.decoder.ch_shift import decode_displacements, measure_vector
    from tapak.marker.pdf_shift import SCHEME_V2

    out, manifest = issued
    assert manifest.shift_scheme == SCHEME_V2
    disp = measure_vector((out / manifest.copies[0].file).read_bytes(), ctx.master)
    sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
    strength = dict(zip(sb.strengths.positions.tolist(), sb.strengths.values[:, 0].tolist()))
    assert len(strength) == len(sb.strengths) >= len(sb) > 300
    read = [strength[q] for q in sb.positions.tolist()]
    assert np.mean(np.array(read) > 5.0) > 0.95 and np.median(read) > 10.0
    groups = [g for page in ctx.master.shift_layout.pages for row in page.rows for g in row.groups[:1]
              if len(row.groups) >= 3]
    moved = {row_word for g in groups[::4] for row_word in
             [ctx.master.shift_layout.pages[g.id[0]].rows[g.id[1]].words[i].id for i in g.word_indices]}
    bumped = {k: (v[0] + (1.0 if k in moved else 0.0), v[1]) for k, v in disp.items()}  # slipped matches
    sb2 = decode_displacements(ctx.master, ctx.plan, bumped, ctx.shift, ctx.excluded)
    zeros = int(np.sum(sb2.strengths.values == 0.0))
    assert sb2.meta["slots_implausible"] >= len(groups[::4]) - 2 and zeros >= sb2.meta["slots_implausible"]


def test_background_strengths_are_reported_without_a_pattern(ctx):
    """The decoder still reports strengths when it finds no pattern; the shipped check leaves
    them out (``SILENT_BACKGROUND_RULE``), rule "semua" counts them as before."""
    from tapak.decoder.trace import collect_background_from_pdf

    plain = collect_background_from_pdf(ctx.master.pdf_bytes, ctx)[0]  # the master has no pattern
    assert len(plain) == 0 and len(plain.strengths) > 3000 and plain.strengths.values.shape[1] == 2
    assert plain.meta["pattern_found"] is False and plain.meta["presence"] is False
    assert not background_pattern_seen(plain.meta) and background_pattern_seen(plain.meta, "semua")
    assert position_scores([plain], ctx.params.length)[0].size == 0
    assert position_scores([plain], ctx.params.length, "semua")[0].size > 2000
    assert erasure_check([plain], ctx.p).z is None and erasure_check([plain], ctx.p, "semua").z is not None


def test_background_rule_readings():
    meta = {"pattern_found": False, "presence": True}
    assert SILENT_BACKGROUND_RULE in ("pola", "uji")
    assert not background_pattern_seen(meta, "pola") and background_pattern_seen(meta, "uji")
    assert background_pattern_seen({}, "pola") and background_pattern_seen({}, "uji")  # older outputs count
    with pytest.raises(ValueError):
        background_pattern_seen(meta, "lain")
    silent = SoftBits("background", np.zeros(0, dtype=np.int64), np.zeros(0), dict(meta),
                      Strengths(np.arange(200), np.linspace(0, 1, 200)))
    shift = _obs(np.arange(200, 400), np.linspace(0, 1, 200), channel="shift")
    assert set(position_scores([silent, shift], 500, "pola")[2]) == {"geser"}
    assert set(position_scores([silent, shift], 500, "uji")[2]) == {"geser", "latar"}


def test_pdf_pages_without_a_pattern_are_kept_apart(issued, ctx):
    """A forwarded copy whose page 2 lost its background: one output per kind of page, so only
    the strengths of page 2 are left out."""
    import pymupdf

    from tapak.decoder.trace import collect_background_from_pdf

    out, manifest = issued
    with pymupdf.open(stream=(out / manifest.copies[0].file).read_bytes(), filetype="pdf") as doc:
        page = doc[1]
        xref = max(page.get_images(full=True), key=lambda i: max(r.width * r.height for r in page.get_image_rects(i[0])))[0]
        pix = pymupdf.Pixmap(doc, xref)
        flat = bytes([int(np.median(np.frombuffer(pix.samples, dtype=np.uint8)))]) * (pix.width * pix.height)
        page.replace_image(xref, pixmap=pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, flat, False))
        data = doc.tobytes()
    parts = collect_background_from_pdf(data, ctx)
    assert [p.meta["pattern_found"] for p in parts] == [True, False] and [p.meta["pages"] for p in parts] == [1, 1]
    assert len(parts[0]) > 1000 and len(parts[1]) == 0 and len(parts[1].strengths) > 1000
    whole = collect_background_from_pdf((out / manifest.copies[0].file).read_bytes(), ctx)
    assert len(whole) == 1 and whole[0].meta["pages"] == 2 and whole[0].meta["pattern_found"] is True


def test_strengths_and_check_do_not_depend_on_codewords(issued, ctx):
    """Replacing every codeword of the context by random bits changes no observation, no
    strength and not the erasure check."""
    from tapak.decoder.trace import collect_from_pdf, run_trace

    out, manifest = issued
    pdf = (out / manifest.copies[4].file).read_bytes()
    real = collect_from_pdf(pdf, ctx)
    rng = np.random.default_rng(3)
    fake = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
    other = collect_from_pdf(pdf, fake)
    for a, b in zip(real, other):
        assert a.channel == b.channel and np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)
        assert (a.strengths is None) == (b.strengths is None)
        if a.strengths is not None:
            assert np.array_equal(a.strengths.positions, b.strengths.positions)
            assert np.array_equal(a.strengths.values, b.strengths.values)
    assert run_trace(real, ctx).erasure == run_trace(other, fake).erasure


def test_attacked_pdf_is_flagged_and_the_verdict_is_the_accusation_alone(issued_seeded, ctx_seeded):
    """Erasure of the agreeing marks of three copies (a seeded issuance, so the numbers are the
    same in every session): the background still shows its pattern at the positions where the
    copies differ, so its strengths count, and the erasure is plain. The read that is left is
    too weak for the contradiction check (its bound is above 10^-3), so the warning is the
    erasure warning alone."""
    from tapak.collusion import attack
    from tapak.decoder.accuse import attribute
    from tapak.decoder.fuse import fuse, fuse_by_physical_channel
    from tapak.decoder.trace import collect_file, run_trace

    out, manifest = issued_seeded
    ctx = ctx_seeded
    members = [2, 9, 14]
    pdfs = [(out / manifest.copies[s - 1].file).read_bytes() for s in members]
    forged, _, _ = attack(ctx.master, pdfs, "acak", 1.0, rng=np.random.default_rng(1))
    obs, notes = collect_file("bukti.pdf", forged, ctx)
    result = run_trace(obs, ctx, notes)
    assert result.erasure.flagged and result.erasure.z < -5 and set(result.erasure.units) == {"geser", "latar"}
    assert erasure_check(obs, ctx.p, "semua") == result.erasure
    warnings = [n for n in result.notes if n.startswith(ERASURE_NOTE)]
    assert warnings == [erasure_note(result.erasure)] and not result.contradiction.flagged
    assert CONTRADICTION_NOTE not in warnings[0] and result.contradiction.log10_bound > -3
    plain = attribute(fuse(obs, ctx.params.length), fuse_by_physical_channel(obs, ctx.params.length), ctx.p,
                      ctx.codewords, ctx.refs, ctx.params)
    assert result.verdict == plain.verdict and [c.score for c in result.candidates] == [c.score for c in plain.candidates]
    assert result.threshold.threshold == plain.threshold.threshold
    assert result.named_seqs <= set(members)
    lines = result.summary_lines()
    assert any(line.startswith(f"  PERHATIAN: {ERASURE_NOTE}") for line in lines)
    assert any("Pemeriksaan pola penghapusan disengaja: z = " in line for line in lines)
    honest, n2 = collect_file("salinan.pdf", pdfs[0], ctx)
    clean = run_trace(honest, ctx, n2)
    assert not clean.erasure.flagged and not any(n.startswith(ERASURE_NOTE) for n in clean.notes)
    assert clean.to_dict()["erasure"]["flagged"] is False


def test_berita_acara_and_web_show_the_warning_for_both_verdicts():
    from tapak.decoder.report import render_html
    from tapak.web.app import templates

    from test_report import _info, _synthetic

    check = ErasureCheck(-9.5, 1981, -ERASURE_Z, ERASURE_ALARM_RATE, True, {"latar": 1942, "geser": 103})
    note = erasure_note(check)
    att: Attribution = _synthetic(VERDICT_INSUFFICIENT, [], notes=["catatan lain", note])
    att.erasure = check
    html = render_html(att, _info())
    assert html.count(ERASURE_NOTE) == 1 and 'class="peringatan"' in html
    assert "Pemeriksaan pola penghapusan disengaja" in html and "z = -9,50" in html
    assert html.index("TIDAK CUKUP BUKTI") < html.index(ERASURE_NOTE)
    plain = _synthetic(VERDICT_INSUFFICIENT, [])
    plain.erasure = ErasureCheck(0.4, 1981, -ERASURE_Z, ERASURE_ALARM_RATE, False)
    plain_html = render_html(plain, _info())
    assert ERASURE_NOTE not in plain_html and "z = 0,40" in plain_html
    tpl = templates.env.from_string("{% for n in peringatan_terlihat(notes) %}[P]{{ n[:20] }}{% endfor %}")
    assert tpl.render(notes=["catatan lain", note]) == "[P]" + note[:20]
    assert isinstance(ThresholdRecord(THRESHOLD_RULE, 1e-6, 1e-7, 10, 1, 1.0, 1.0, "t"), ThresholdRecord)
