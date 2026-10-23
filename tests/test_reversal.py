"""Reversal check (``tapak.decoder.reversal``) and the merged warning (``tapak.decoder.manipulation``).

Marks that follow the opposite of the bias vector where every copy almost surely agrees are the
trace of a reversal. Two code-blind statistics measure it: the background decoder's pilot sums
of the image pages, and A / sqrt(B) over the fused read. The tests cover both statistics on
synthetic inputs (the pilot's Rademacher bound, page combination, honest coalitions of at most
three against reversed agreeing positions), the rule and its rate, code-blindness, that the
verdict, the scores and the thresholds never change, the merged warning and its rendering.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from tapak.decoder.ch_background import pilot_parts, pilot_z
from tapak.decoder.fuse import fuse
from tapak.decoder.manipulation import MANIPULATION_LEAD, ONLY_A_WARNING, is_manipulation_note, manipulation_note
from tapak.decoder.reversal import (
    REVERSAL_ALARM_RATE,
    REVERSAL_MAX_COALITION,
    REVERSAL_NOTE,
    REVERSAL_STATISTICS,
    REVERSAL_Z,
    ReversalCheck,
    pilot_statistic,
    reversal_check,
    reversal_note,
    sign_statistic,
)
from tapak.decoder.softbits import SoftBits
from tapak.tardos.attacks import STRATEGIES, add_channel_noise
from tapak.tardos.code import random_code
from tapak.tardos.params import TardosParams

EM_DASH = chr(0x2014)
C3 = TardosParams(c=3, eps=1e-6, n_max=20)


def _read(y: np.ndarray, w: np.ndarray, llr: float = 6.0):
    """A fused read with decisions y and weights about w (as LLRs of the matching size)."""
    w = np.clip(np.asarray(w, dtype=np.float64), 0.0, 0.999999)
    mag = 2.0 * np.arctanh(w)
    signed = np.where(np.asarray(y) == 1, mag, -mag)
    return fuse([SoftBits("shift", np.arange(len(y)), signed)], len(y))


def _bg(page: int, total: float, var: float) -> SoftBits:
    return SoftBits("background", np.zeros(0, dtype=np.int64), np.zeros(0),
                    {"page": page, "pilot_sum": total, "pilot_var": var})


# --- constants and the pilot ---------------------------------------------------------------


def test_rate_and_threshold_are_fixed():
    assert REVERSAL_ALARM_RATE == 1e-3 and REVERSAL_STATISTICS == ("pilot", "tanda")
    assert REVERSAL_Z == pytest.approx(math.sqrt(2 * math.log(2000)), rel=1e-12) and 3.89 < REVERSAL_Z < 3.91
    assert math.exp(-REVERSAL_Z ** 2 / 2) == pytest.approx(REVERSAL_ALARM_RATE / 2)
    assert REVERSAL_MAX_COALITION == 3


def test_pilot_parts_add_up_to_pilot_z():
    rng = np.random.default_rng(1)
    u, e = rng.normal(size=500), rng.uniform(-1, 1, 500)
    total, var = pilot_parts(u, e)
    assert total == pytest.approx(float(np.sum(u * e))) and var == pytest.approx(float(np.sum((u * e) ** 2)))
    assert pilot_z(u, e) == pytest.approx(total / math.sqrt(var))
    assert pilot_parts(np.zeros(3), np.ones(3)) == (0.0, 0.0)


def test_pilot_without_pattern_is_within_the_rademacher_bound():
    """Cells with keyed random signs and any noise: the joint pilot of two pages rarely goes
    below -t, never more often than exp(-t^2 / 2)."""
    rng = np.random.default_rng(2)
    zs = []
    for _ in range(4000):
        obs = []
        for page in (0, 1):
            m = rng.standard_t(3, 400) * rng.uniform(0.5, 2.0)  # heavy-tailed noise, any scale
            e = rng.uniform(-1, 1, 400)
            u = rng.choice([-1.0, 1.0], 400) * m
            obs.append(_bg(page, *pilot_parts(u, e)))
        zs.append(pilot_statistic(obs)[0])
    zs = np.array(zs)
    for t in (1.0, 2.0, 3.0):
        assert np.mean(zs <= -t) <= math.exp(-t * t / 2)
    assert abs(np.mean(zs)) < 0.1 and 0.85 < np.std(zs) < 1.15


def test_pilot_combines_pages_and_bounds_repeated_reads():
    two_pages = pilot_statistic([_bg(0, 3.0, 4.0), _bg(1, -1.0, 5.0)])
    assert two_pages == (pytest.approx(2.0 / 3.0), 2)
    # Two reads of the same page share their keyed signs: spreads add (Minkowski), not variances.
    same = pilot_statistic([_bg(0, 3.0, 4.0), _bg(0, 3.0, 4.0)])
    assert same == (pytest.approx(6.0 / 4.0), 2)
    no_pilot = [SoftBits("shift", [1], [1.0]), SoftBits("background", [1], [1.0], {"page": 0})]
    assert pilot_statistic(no_pilot) == (None, 0)
    assert pilot_statistic([_bg(0, 0.0, 0.0)]) == (None, 1)
    with pytest.raises(ValueError):
        pilot_statistic([_bg(0, 1.0, -1.0)])


# --- the sign statistic --------------------------------------------------------------------


def test_honest_coalitions_stay_positive_and_reversal_turns_negative():
    """Code level: coalitions of 1 to 3 that obey the marking assumption, every strategy, with
    read errors and uneven weights, never reach -REVERSAL_Z (their mean is positive); reversing
    the positions where the colluders agree drives the statistic far below it."""
    rng = np.random.default_rng(3)
    m = 1500
    low = math.inf
    for k in (1, 2, 3):
        for name in sorted(STRATEGIES):
            for _ in range(15):
                p, x = random_code(C3, k, rng, m)
                y, w = STRATEGIES[name](x, rng) if k > 1 else (x[0].copy(), np.ones(m))
                y, w = add_channel_noise(y, w * rng.uniform(0.2, 1.0, m), rng, ber=0.1, erasure=0.3)
                z, n = sign_statistic(_read(y, w), p)
                low = min(low, z)
                agree = np.all(x == x[:1], axis=0)
                flipped = np.where(agree, 1 - y, y)
                assert sign_statistic(_read(flipped, w), p)[0] < -REVERSAL_Z
    assert low > 0


def test_unmarked_reads_are_within_the_bound():
    """A read that does not depend on the code (an unmarked page): the statistic is a Rademacher
    sum in the signs of 2p - 1, whatever the read, so its lower tail obeys exp(-t^2 / 2)."""
    rng = np.random.default_rng(4)
    y = (rng.random(800) < 0.8).astype(np.uint8)  # a read biased to 1, the same for every code
    w = rng.uniform(0, 1, 800)
    zs = np.array([sign_statistic(_read(y, w), random_code(C3, 1, rng, 800)[0])[0] for _ in range(3000)])
    for t in (1.0, 2.0, 3.0):
        assert np.mean(zs <= -t) <= math.exp(-t * t / 2)


def test_sign_statistic_edge_cases():
    p = np.full(10, 0.9)
    assert sign_statistic(_read(np.ones(10, dtype=np.uint8), np.zeros(10)), p) == (None, 0)
    z, n = sign_statistic(_read(np.ones(10, dtype=np.uint8), np.full(10, 0.9)), p)
    assert n == 10 and z == pytest.approx(math.sqrt(10))
    with pytest.raises(ValueError):
        sign_statistic(_read(np.ones(10, dtype=np.uint8), np.ones(10)), np.full(11, 0.5))


def test_check_text_and_note():
    check = ReversalCheck(-54.2, 1, -12.31, 2987, -REVERSAL_Z, REVERSAL_ALARM_RATE, True)
    assert check.text() == ("z pilot = -54,20 dari 1 halaman gambar dan z tanda = -12,31 dari 2.987 posisi terbaca, "
                            "ambang -3,90 untuk masing-masing")
    pdf = dataclasses.replace(check, z_pilot=None, pilot_pages=0)
    assert pdf.text() == "z tanda = -12,31 dari 2.987 posisi terbaca, ambang -3,90"
    assert dataclasses.replace(pdf, z_signs=None).text().startswith("tidak diperiksa")
    note = reversal_note(check)
    assert note == manipulation_note(None, None, check) and note.startswith(f"{MANIPULATION_LEAD}: {REVERSAL_NOTE}.")
    for part in ("membalik tanda di tempat salinannya sama", "satu salinan membalik semua tandanya",
                 "koalisi lebih dari 3 orang", "masalah pembacaan bukti", "10^-3", "z pilot = -54,20"):
        assert part in note
    assert note.endswith(ONLY_A_WARNING) and is_manipulation_note(note) and EM_DASH not in note
    with pytest.raises(ValueError):
        reversal_note(dataclasses.replace(check, flagged=False))


def test_merged_note_states_each_finding_once():
    from tapak.decoder.contradiction import CONTRADICTION_NOTE, ContradictionCheck
    from tapak.decoder.erasure import ERASURE_ALARM_RATE, ERASURE_NOTE, ERASURE_Z, ErasureCheck

    rev = ReversalCheck(None, 0, -20.0, 2900, -REVERSAL_Z, REVERSAL_ALARM_RATE, True)
    era = ErasureCheck(-9.5, 1981, -ERASURE_Z, ERASURE_ALARM_RATE, True, {"latar": 1942})
    con = ContradictionCheck(-12.3, True, 5, 1e-3, 0.3, 2987, 2950.0, 5e-8, True)
    note = manipulation_note(era, con, rev)
    assert note.startswith(f"{MANIPULATION_LEAD}: {REVERSAL_NOTE}; {ERASURE_NOTE}; {CONTRADICTION_NOTE}.")
    for part in (REVERSAL_NOTE, ERASURE_NOTE, CONTRADICTION_NOTE, "Kemungkinan penyebab", "hanya peringatan",
                 "menghapus, membalik, atau mengacak"):
        assert note.count(part) == 1, part
    # The reversal bound covers coalitions of at most three whatever c: the cause names the smaller.
    assert "koalisi lebih dari 3 orang" in note and "koalisi paling banyak 5 penerima" in note
    assert manipulation_note(None, None, dataclasses.replace(rev, flagged=False)) is None
    assert manipulation_note(None, None, None) is None


# --- on real evidence ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def reversed_pdf(issued_seeded, ctx_seeded):
    from tapak.collusion import attack

    out, manifest = issued_seeded
    pdfs = [(out / manifest.copies[s - 1].file).read_bytes() for s in (4, 12)]
    forged, _, _ = attack(ctx_seeded.master, pdfs, "acak", 1.0, rng=np.random.default_rng(6), neutralize="balik")
    return forged


def test_honest_pdf_is_positive_and_reversed_pdf_is_flagged(issued_seeded, ctx_seeded, reversed_pdf, monkeypatch):
    from tapak.decoder import trace as trace_mod
    from tapak.decoder.trace import collect_file, run_trace

    out, manifest = issued_seeded
    ctx = ctx_seeded
    obs, notes = collect_file("salinan.pdf", (out / manifest.copies[3].file).read_bytes(), ctx)
    honest = run_trace(obs, ctx, notes)
    assert honest.named_seqs == {4} and not honest.reversal.flagged
    assert honest.reversal.z_signs > 20 and honest.reversal.z_pilot is None and honest.reversal.pilot_pages == 0
    assert not any(is_manipulation_note(n) for n in honest.notes)
    obs, notes = collect_file("bukti.pdf", reversed_pdf, ctx)
    result = run_trace(obs, ctx, notes)
    assert not result.named_seqs and result.reversal.flagged and result.reversal.z_signs < -20
    assert result.reversal == reversal_check(obs, fuse(obs, ctx.params.length), ctx.p)
    assert result.to_dict()["reversal"]["flagged"] is True
    warnings = [n for n in result.notes if is_manipulation_note(n)]
    assert len(warnings) == 1 and REVERSAL_NOTE in warnings[0]
    monkeypatch.setattr(trace_mod, "reversal_check", lambda *a, **k: None)
    plain = run_trace(obs, ctx, notes)
    a, b = result.to_dict(), plain.to_dict()
    for key in ("verdict", "candidates", "channels", "conflicts", "stages", "erasure", "contradiction"):
        assert a[key] == b[key]
    assert {k: v for k, v in a["threshold"].items() if k != "fixed_at"} == \
        {k: v for k, v in b["threshold"].items() if k != "fixed_at"}


def test_check_does_not_depend_on_codewords(ctx_seeded, reversed_pdf):
    from tapak.decoder.trace import collect_file, run_trace

    obs, notes = collect_file("bukti.pdf", reversed_pdf, ctx_seeded)
    rng = np.random.default_rng(7)
    fake = dataclasses.replace(ctx_seeded, codewords=rng.integers(0, 2, ctx_seeded.codewords.shape)
                               .astype(ctx_seeded.codewords.dtype))
    real, other = run_trace(obs, ctx_seeded, notes), run_trace(obs, fake, notes)
    assert real.reversal == other.reversal and real.reversal.flagged


@pytest.mark.slow
def test_reversed_screenshot_is_flagged_by_the_pilot(issued_seeded, ctx_seeded, reversed_pdf):
    """Through a screenshot the background decoder reads the reversed pattern as no pattern, but
    its pilot sum is far below zero; an honest screenshot's pilot is far above."""
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import run_trace
    from tapak.marker.render import render_pages
    from tapak.photos import ScreenshotParams, screenshot_jpeg

    out, manifest = issued_seeded
    ctx = ctx_seeded
    for pdf, sign in ((reversed_pdf, -1), ((out / manifest.copies[3].file).read_bytes(), 1)):
        page = render_pages(pdf, 200, [0])[0]
        data, _ = screenshot_jpeg(page, np.random.default_rng(8), ScreenshotParams(render_dpi=200.0, long_side=1600))
        result = run_trace(collect_from_image(data, ctx), ctx)
        assert result.reversal.pilot_pages == 1 and sign * result.reversal.z_pilot > 20
        assert result.reversal.flagged == (sign < 0)
        bg = next(sb for sb in collect_from_image(data, ctx) if sb.channel == "background")
        assert bg.meta["pilot_var"] > 0 and math.isfinite(bg.meta["pilot_sum"])
