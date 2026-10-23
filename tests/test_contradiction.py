"""Contradiction check (``tapak.decoder.contradiction``) and the rate-ceiling bound behind it.

A clear read that names nobody contradicts ``detection.read_miss_ceiling``: under (C1) and (C2)
a coalition of at most c would be named almost surely. The tests cover the bound (box corners
and rate ceilings never understate it), the rule (a clear read without a name warns, a weak one
does not, a named one is not checked), code-blindness, that verdicts and scores never change,
one warning next to the erasure warning without repeated sentences, and the rendering in the
CLI summary, the JSON, the berita acara and the web page.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from tapak.decoder.accuse import VERDICT_INSUFFICIENT, attribute, is_caveat
from tapak.decoder.contradiction import (
    CONTRADICTION_BOXES,
    CONTRADICTION_NOTE,
    CONTRADICTION_RATE,
    CONTRADICTION_TEMPERING,
    ContradictionCheck,
    contradiction_check,
    contradiction_note,
    format_bound,
    is_manipulation_note,
    manipulation_note,
)
from tapak.decoder.erasure import ERASURE_ALARM_RATE, ERASURE_NOTE, ERASURE_Z, ErasureCheck, erasure_note
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.decoder.softbits import SoftBits
from tapak.tardos import detection as det
from tapak.tardos.code import random_code
from tapak.tardos.detection import (
    READ_BOXES,
    calibrated_error_rates,
    proven_read_miss_ceiling,
    read_miss_bound,
    read_miss_ceiling,
    tempered_error_rates,
)
from tapak.tardos.params import TardosParams

C3 = TardosParams(c=3, eps=1e-6, n_max=20)
EM_DASH = chr(0x2014)


# --- the bound ---------------------------------------------------------------------------


def test_tempered_rates_are_calibrated_at_one_and_higher_below():
    llr = np.array([-12.0, -3.0, 0.0, 0.5, 4.0, 40.0])
    assert np.allclose(tempered_error_rates(llr, 1.0), calibrated_error_rates(np.tanh(np.abs(llr) / 2)), atol=1e-12)
    half = tempered_error_rates(llr, 0.5)
    assert np.all(half >= tempered_error_rates(llr, 1.0)) and half[2] == 0.5 and 0 < half[-1] < 1e-8
    for bad in (0.0, -0.5, 1.5, math.nan):
        with pytest.raises(ValueError):
            tempered_error_rates(llr, bad)


def test_factor_is_log_convex_in_the_weight_and_convex_in_the_rate():
    """The two facts the box bound rests on, at several (alpha, lam0): the factor at any point
    of a box never exceeds the largest factor at the box's corners."""
    rng = np.random.default_rng(3)
    for c in (1, 3):
        itg = det._Integrand(c, C3.cutoff, det._PANELS, det._ORDER)
        kappa = c * (1 + det.Z_SLACK)
        for alpha, lam0 in ((0.02, 0.05), (0.3, 0.2), (1.0, 0.5)):
            w_lo, w_hi, e_hi = 0.4, 0.9, 0.2
            corners = itg.log_g_channel(alpha, lam0, kappa, np.array([w_lo, w_lo, w_hi, w_hi]),
                                        np.array([0.0, e_hi, 0.0, e_hi]))
            inside = itg.log_g_channel(alpha, lam0, kappa, rng.uniform(w_lo, w_hi, 200), rng.uniform(0, e_hi, 200))
            assert inside.max() <= corners.max() + 1e-12
            grid = itg.log_g_channel(alpha, lam0, kappa, np.linspace(0.01, 1, 60), np.zeros(60))
            assert np.diff(grid, 2).min() > -1e-12


def test_ceiling_bound_never_below_the_exact_read_bound():
    rng = np.random.default_rng(4)
    llr = np.clip(rng.normal(0, 6, C3.length), -24, 24)
    w = np.tanh(np.abs(llr) / 2)
    w[np.abs(llr) < 0.25] = 0
    e = tempered_error_rates(llr, 1.0)
    exact = read_miss_bound(C3, w, e, 3)
    boxed = [read_miss_ceiling(C3, w, e, 3, boxes=b) for b in (1, 16, READ_BOXES)]
    assert all(b.conditional and b.observed == exact.observed for b in boxed)
    assert all(b.log_bound >= exact.log_bound - 1e-9 for b in boxed)
    assert boxed[0].log_bound >= boxed[2].log_bound  # one box is the loosest
    assert boxed[2].log10_bound - exact.log10_bound < 0.5  # 64 boxes stay close
    hard = read_miss_ceiling(C3, np.ones(1500), 0.0, 3)
    assert hard.log_bound == pytest.approx(read_miss_bound(C3, np.ones(1500), 0.0, 3).log_bound, rel=1e-3)
    nothing = read_miss_ceiling(C3, np.zeros(40))
    assert nothing.bound == 1.0 and nothing.observed == 0
    with pytest.raises(ValueError):
        read_miss_ceiling(C3, w, e, boxes=0)


def test_proven_ceiling_is_the_maximum_and_can_stop_early():
    rng = np.random.default_rng(5)
    w = rng.choice([0.0, 0.8, 1.0], size=C3.length)
    e = np.where(w > 0, 0.02, 0.0)
    per = [read_miss_ceiling(C3, w, e, k).bound for k in (1, 2, 3)]
    assert proven_read_miss_ceiling(C3, w, e) == max(per)
    weak = np.zeros(C3.length)
    weak[:700] = 1.0
    stopped = proven_read_miss_ceiling(C3, weak, 0.0, stop_above=1e-3)
    assert stopped > 1e-3 and stopped == read_miss_ceiling(C3, weak, 0.0, 3).bound


# --- the rule ----------------------------------------------------------------------------


def _read(llr: np.ndarray) -> object:
    return fuse([SoftBits("shift", np.arange(llr.size), llr)], llr.size)


def test_clear_read_without_a_name_warns_and_a_weak_one_does_not():
    rng = np.random.default_rng(6)
    clear = _read(np.where(rng.random(C3.length) < 0.5, 12.0, -12.0))
    check = contradiction_check(clear, C3, 1e-8, named=False)
    assert isinstance(check, ContradictionCheck) and check.flagged and check.complete
    assert check.log10_bound < -10 and check.rate == CONTRADICTION_RATE and check.coalition == 3
    assert check.observed == C3.length and check.tempering == CONTRADICTION_TEMPERING
    assert "tidak lebih dari 10^-3" in check.text() and check.bound == pytest.approx(10 ** check.log10_bound)
    weak = _read(np.where(rng.random(C3.length) < 0.5, 0.6, -0.6))
    soft = contradiction_check(weak, C3, 1e-8, named=False)
    assert not soft.flagged and not soft.complete and "di atas 10^-3" in soft.text()
    few = np.zeros(C3.length)
    few[:600] = 12.0
    assert not contradiction_check(_read(few), C3, 1e-8, named=False).flagged
    assert contradiction_check(clear, C3, 1e-8, named=True) is None
    empty = contradiction_check(_read(np.zeros(C3.length)), C3, 1e-8, named=False)
    assert not empty.flagged and empty.log10_bound == 0.0 and empty.observed == 0


def test_honest_simulated_reads_rarely_warn():
    """Calibrated channel noise on reads of honest coalitions (code level): warnings need nobody
    named, which the bound makes rare; here none of 60 reads warns."""
    rng = np.random.default_rng(7)
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    from tapak.tardos.accuse import scores, threshold

    for _ in range(60):
        p, x = random_code(params, 3, rng)
        y = np.where(rng.random(params.length) < 0.5, x[0], x[1])  # obeys the marking assumption
        flip = rng.random(params.length) < 0.05
        llr = np.where((y ^ flip) == 1, 2.94, -2.94)  # calibrated for a 5 % flip rate
        est = _read(llr)
        named = bool((scores(x, est.y, p, est.weights) >= threshold(p, params.eps1, est.weights)).any())
        check = contradiction_check(est, params, params.eps1, named)
        assert named or not check.flagged


def test_format_bound():
    assert format_bound(0.0) == "1" and format_bound(0.3) == "1" and format_bound(-math.inf) == "0"
    assert format_bound(math.log10(0.4123)) == "0,42" and format_bound(math.log10(0.0999)) == "0,10"
    assert format_bound(math.log10(2.04e-9)) == "2,1 x 10^-9" and format_bound(math.log10(9.96e-5)) == "1,0 x 10^-4"


# --- notes -------------------------------------------------------------------------------


def _check(flagged: bool = True) -> ContradictionCheck:
    return ContradictionCheck(-12.3, True, 3, CONTRADICTION_RATE, CONTRADICTION_TEMPERING, 2987, 2950.0, 5e-8, flagged)


def test_one_warning_for_either_or_both_checks():
    erased = ErasureCheck(-9.5, 1981, -ERASURE_Z, ERASURE_ALARM_RATE, True, {"latar": 1942})
    calm = dataclasses.replace(erased, z=0.4, flagged=False)
    assert manipulation_note(None, None) is None and manipulation_note(calm, _check(False)) is None
    assert manipulation_note(erased, None) == erasure_note(erased) == manipulation_note(erased, _check(False))
    alone = manipulation_note(calm, _check())
    assert alone == contradiction_note(_check()) and alone.startswith(CONTRADICTION_NOTE)
    for part in ("10^-3", "koalisi lebih dari 3 orang", "masalah pembacaan bukti", "dua salinan atau lebih",
                 "tidak ada nama yang disebut", "5,1 x 10^-13"):
        assert part in alone
    both = manipulation_note(erased, _check())
    assert both.startswith(ERASURE_NOTE) and both.count(CONTRADICTION_NOTE) == 1
    assert both.count("hanya peringatan") == 1 and both.count("putusan, ambang") == 1
    assert "Keduanya hanya peringatan" in both and "z = -9,50" in both and "Ini hanya peringatan" in alone
    for note in (alone, both, erasure_note(erased)):
        assert is_manipulation_note(note) and is_caveat(note) and EM_DASH not in note
    assert not is_manipulation_note("catatan biasa")


# --- on real evidence --------------------------------------------------------------------


@pytest.fixture(scope="module")
def reversed_pdf(issued_seeded, ctx_seeded):
    from tapak.collusion import attack

    out, manifest = issued_seeded
    pdfs = [(out / manifest.copies[s - 1].file).read_bytes() for s in (3, 11)]
    forged, _, _ = attack(ctx_seeded.master, pdfs, "acak", 1.0, rng=np.random.default_rng(2), neutralize="balik")
    return forged


def test_reversed_pdf_warns_without_naming_and_changes_nothing(ctx_seeded, reversed_pdf, monkeypatch):
    from tapak.decoder import trace as trace_mod
    from tapak.decoder.trace import collect_file, run_trace

    ctx = ctx_seeded
    obs, notes = collect_file("bukti.pdf", reversed_pdf, ctx)
    result = run_trace(obs, ctx, notes)
    assert result.verdict == VERDICT_INSUFFICIENT and not result.named_seqs
    assert result.contradiction.flagged and result.contradiction.log10_bound < -8
    assert result.contradiction.eps1 == result.threshold.eps1
    assert not result.erasure.flagged  # every reversed mark reads as clearly as an honest one
    warnings = [n for n in result.notes if is_manipulation_note(n)]
    assert len(warnings) == 1 and warnings[0].startswith(CONTRADICTION_NOTE)
    # The same trace without the check: identical verdict, threshold, scores and other notes.
    monkeypatch.setattr(trace_mod, "contradiction_check", lambda *a, **k: None)
    plain = run_trace(obs, ctx, notes)
    assert plain.contradiction is None and not any(is_manipulation_note(n) for n in plain.notes)
    a, b = result.to_dict(), plain.to_dict()
    for key in ("verdict", "candidates", "channels", "conflicts", "stages", "erasure"):
        assert a[key] == b[key]
    assert {k: v for k, v in a["threshold"].items() if k != "fixed_at"} == \
        {k: v for k, v in b["threshold"].items() if k != "fixed_at"}
    assert [n for n in result.notes if not is_manipulation_note(n)] == plain.notes
    direct = attribute(fuse(obs, ctx.params.length), fuse_by_physical_channel(obs, ctx.params.length), ctx.p,
                       ctx.codewords, ctx.refs, ctx.params)
    assert [c.score for c in direct.candidates] == [c.score for c in result.candidates]


def test_check_does_not_depend_on_codewords(ctx_seeded, reversed_pdf):
    """Codewords replaced by other codewords drawn from the same bias vector (copies nobody
    leaked): nobody is named either way, and the check, a function of the bias law and the fused
    read alone, is identical. Its bound never sees a codeword, so it is also unchanged when the
    replaced codewords do get named (then the check is simply not run)."""
    from tapak.decoder.trace import collect_file, run_trace

    obs, notes = collect_file("bukti.pdf", reversed_pdf, ctx_seeded)
    rng = np.random.default_rng(9)
    drawn = (rng.random(ctx_seeded.codewords.shape) < ctx_seeded.p).astype(ctx_seeded.codewords.dtype)
    fake = dataclasses.replace(ctx_seeded, codewords=drawn)
    real, other = run_trace(obs, ctx_seeded, notes), run_trace(obs, fake, notes)
    assert not real.named_seqs and not other.named_seqs
    assert real.contradiction == other.contradiction and real.contradiction.flagged
    uniform = dataclasses.replace(ctx_seeded, codewords=rng.integers(0, 2, ctx_seeded.codewords.shape)
                                  .astype(ctx_seeded.codewords.dtype))
    named = run_trace(obs, uniform, notes)
    assert named.named_seqs and named.contradiction is None and named.erasure == real.erasure
    fused = fuse(obs, ctx_seeded.params.length)
    assert contradiction_check(fused, ctx_seeded.params, real.threshold.eps1, False) == real.contradiction


def test_honest_copy_is_named_and_not_checked(issued_seeded, ctx_seeded):
    from tapak.decoder.trace import collect_file, run_trace

    out, manifest = issued_seeded
    obs, notes = collect_file("salinan.pdf", (out / manifest.copies[2].file).read_bytes(), ctx_seeded)
    result = run_trace(obs, ctx_seeded, notes)
    assert result.named_seqs == {3} and result.contradiction is None
    assert not any(is_manipulation_note(n) for n in result.notes)
    assert result.to_dict()["contradiction"] is None


def test_summary_json_berita_acara_and_web_show_one_warning(ctx_seeded, reversed_pdf):
    from tapak.decoder.report import render_html
    from tapak.decoder.trace import collect_file, run_trace
    from tapak.web.app import templates

    from test_report import _info

    obs, notes = collect_file("bukti.pdf", reversed_pdf, ctx_seeded)
    result = run_trace(obs, ctx_seeded, notes)
    lines = result.summary_lines()
    warn = [i for i, line in enumerate(lines) if line.startswith(f"  PERHATIAN: {CONTRADICTION_NOTE}")]
    none = [i for i, line in enumerate(lines) if "Tidak ada salinan yang mencapai ambang" in line]
    assert len(warn) == 1 and none and none[0] < warn[0]  # under the verdict
    assert any(line.startswith("  Pemeriksaan bacaan jelas tanpa nama: batas ") for line in lines)
    data = result.to_dict()["contradiction"]
    assert data["flagged"] is True and data["log10_bound"] < -8 and data["rate"] == CONTRADICTION_RATE
    html = render_html(result, _info(params=ctx_seeded.params, copies_issued=len(ctx_seeded.refs)))
    assert html.count(CONTRADICTION_NOTE) == 1 and html.index("TIDAK CUKUP BUKTI") < html.index(CONTRADICTION_NOTE)
    assert "Pemeriksaan bacaan jelas tanpa nama" in html and EM_DASH not in html
    tpl = templates.env.from_string("{% for n in peringatan_terlihat(notes) %}[P]{% endfor %}"
                                    "{% if a.contradiction %}{{ a.contradiction.text() }}{% endif %}")
    out = tpl.render(notes=result.notes, a=result)
    assert out.startswith("[P]") and out.count("[P]") == 1 and "batas " in out
    assert CONTRADICTION_BOXES == 64


def test_berita_acara_merges_both_warnings_into_one():
    from tapak.decoder.report import render_html

    from test_report import _info, _synthetic

    erased = ErasureCheck(-9.5, 1981, -ERASURE_Z, ERASURE_ALARM_RATE, True, {"latar": 1942, "geser": 103})
    note = manipulation_note(erased, _check())
    att = _synthetic(VERDICT_INSUFFICIENT, [], notes=["catatan lain", note])
    att.erasure, att.contradiction = erased, _check()
    html = render_html(att, _info())
    assert html.count(ERASURE_NOTE) == 1 and html.count(CONTRADICTION_NOTE) == 1
    assert html.count("hanya peringatan") == 1 and html.count('class="peringatan"') == 1
    assert "Pemeriksaan pola penghapusan disengaja" in html and "Pemeriksaan bacaan jelas tanpa nama" in html
    assert "batas 5,1 x 10^-13 untuk koalisi paling banyak 3 orang" in html
    assert html.index("TIDAK CUKUP BUKTI") < html.index(ERASURE_NOTE)
