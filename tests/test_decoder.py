"""Decoder tests: soft bits, channel 3 round trip (M1 acceptance), shift readout, fusion,
attribution and the insufficient-evidence path."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from tapak.decoder.accuse import VERDICT_IDENTIFIED, VERDICT_INSUFFICIENT
from tapak.decoder.ch_shift import decode_displacements, decode_vector, estimate_sigma, match_words, measure_vector
from tapak.decoder.ch_zerowidth import align_tokens, decode_text, extract_pdf_text, tokenize
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.decoder.softbits import LLR_CLIP, SoftBits, gaussian_llr
from tapak.decoder.trace import TraceError, collect_from_pdf, load_context, run_trace, trace_file
from tapak.marker.layout import extract_layout
from tapak.marker.pdf_zerowidth import ZW_CHARS, normalize_text
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_SHIFT, CHANNEL_ZW
from tapak.tardos.code import derive_codeword


def _copy_bytes(issued, seq):
    out, manifest = issued
    return (out / manifest.copies[seq - 1].file).read_bytes()


def _check_bits(sb: SoftBits, x: np.ndarray) -> None:
    assert len(sb) > 0
    assert np.array_equal((sb.llr > 0).astype(np.uint8), x[sb.positions])


# --- soft bits -----------------------------------------------------------------------


def test_softbits_basics():
    sb = SoftBits("zw", [1, 2], [100.0, -3.0])
    assert sb.llr.tolist() == [LLR_CLIP, -3.0] and len(sb) == 2
    assert len(SoftBits.empty("x")) == 0
    both = SoftBits.concat("zw", [sb, sb])
    assert both.positions.tolist() == [1, 2, 1, 2]
    assert len(SoftBits.concat("zw", [])) == 0
    with pytest.raises(ValueError):
        SoftBits("zw", [1], [1.0, 2.0])
    assert gaussian_llr(np.array([0.1]), 0.1, 0.1)[0] == pytest.approx(2.0)
    with pytest.raises(ValueError):
        gaussian_llr(np.array([1.0]), 1.0, 0.0)


# --- channel 3: text layer -----------------------------------------------------------


def test_tokenize_separates_prefix_and_suffix():
    zw = "\u200c\u200b"
    toks = tokenize(zw + "satu\u200d\u2060 dua \u2061ti\u2063ga")
    assert [t.raw for t in toks] == ["satu", "dua", "tiga"]
    assert (toks[0].prefix, toks[0].suffix) == (zw, "\u200d\u2060")
    assert (toks[1].prefix, toks[1].suffix, toks[1].broken) == ("", "", False)
    assert toks[2].prefix == "\u2061" and toks[2].broken


def test_align_tokens_handles_excerpts():
    toks = tokenize("x c d e y")
    pairs = align_tokens(toks, ["a", "b", "c", "d", "e", "f"])
    assert pairs == [(1, 2), (2, 3), (3, 4)]


def test_channel3_roundtrip_mupdf_copy_paste(issued, ctx):
    """M1 acceptance: the whole text layer copied with MuPDF decodes to the codeword."""
    for seq in (1, 7, 13):
        x = ctx.codewords[seq - 1]
        text = extract_pdf_text(_copy_bytes(issued, seq))
        zw, hg = decode_text(text, ctx.master, ctx.plan)
        _check_bits(zw, x)
        _check_bits(hg, x)
        assert zw.meta["slots_read"] == zw.meta["slots_total"] and zw.meta["slots_broken"] == 0
        assert len(set(zw.positions.tolist())) == ctx.params.length
        result = run_trace([zw, hg], ctx)
        assert result.verdict == VERDICT_IDENTIFIED
        assert [c.copy.seq for c in result.accused] == [seq]


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler not installed")
def test_channel3_roundtrip_poppler(issued, ctx, tmp_path):
    """Same through poppler (the text engine behind Evince, Okular and many converters)."""
    f = tmp_path / "c.pdf"
    f.write_bytes(_copy_bytes(issued, 5))
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(f), "-"], capture_output=True,
                          text=True, check=True).stdout
    zw, hg = decode_text(text, ctx.master, ctx.plan)
    _check_bits(zw, ctx.codewords[4])
    _check_bits(hg, ctx.codewords[4])
    assert [c.copy.seq for c in run_trace([zw, hg], ctx).accused] == [5]


def test_channel3_partial_paste_and_stripping(issued, ctx):
    x = ctx.codewords[8]
    text = extract_pdf_text(_copy_bytes(issued, 9))
    tokens = text.split()
    paragraph = " ".join(tokens[120:200])   # an excerpt of 80 words
    zw, hg = decode_text(paragraph, ctx.master, ctx.plan)
    _check_bits(zw, x)
    assert 100 < len(set(zw.positions.tolist())) < ctx.params.length
    assert [c.copy.seq for c in run_trace([zw, hg], ctx).accused] == [9]
    # Zero-width symbols stripped: homoglyphs still carry the mark.
    no_zw = "".join(ch for ch in text if ch not in ZW_CHARS)
    zw2, hg2 = decode_text(no_zw, ctx.master, ctx.plan)
    assert len(zw2) == 0 and len(hg2) > 100
    assert [c.copy.seq for c in run_trace([zw2, hg2], ctx).accused] == [9]
    # Fully normalized text: nothing left in channel 3, and the decoder says so.
    zw3, hg3 = decode_text(normalize_text(text), ctx.master, ctx.plan)
    assert len(zw3) == 0 and len(hg3) == 0
    assert run_trace([zw3, hg3], ctx).verdict == VERDICT_INSUFFICIENT


def test_text_collusion_accuses_both_and_nobody_else(issued, ctx):
    """First half of copy A's text + second half of copy B's text."""
    ta = extract_pdf_text(_copy_bytes(issued, 3)).splitlines()
    tb = extract_pdf_text(_copy_bytes(issued, 16)).splitlines()
    half = len(ta) // 2
    mixed = "\n".join(ta[:half] + tb[half:])
    result = run_trace(decode_text(mixed, ctx.master, ctx.plan), ctx)
    assert sorted(c.copy.seq for c in result.accused) == [3, 16]


# --- channel 1: shifts ----------------------------------------------------------------


def test_shift_vector_readout_recovers_codeword(issued, ctx):
    data = _copy_bytes(issued, 11)
    sb = decode_vector(data, ctx.master, ctx.plan, ctx.shift)
    _check_bits(sb, ctx.codewords[10])
    if ctx.shift.scheme == "geser-v1":
        assert sb.meta["slots_read"] == sb.meta["slots_total"]
    else:  # geser-v2: a row whose groups all moved the same way cannot be read, and says so (LLR 0)
        assert sb.meta["slots_read"] >= 0.85 * sb.meta["slots_total"]
    # Under geser-v1 about 180 shift positions put the leaker's expected score (~117) right at
    # the threshold for that many positions (~105); geser-v2 carries about 400. The channel alone
    # may or may not suffice, but it can never point at anyone else.
    result = run_trace([sb], ctx)
    assert result.candidates[0].copy.seq == 11
    assert [c.copy.seq for c in result.accused] in ([11], [])


def test_shift_decoding_survives_affine_distortion(issued_v1, ctx_v1):
    """Relative encoding (geser-v1): a smooth affine displacement field on top of the marks cancels."""
    issued, ctx = issued_v1, ctx_v1
    disp = measure_vector(_copy_bytes(issued, 4), ctx.master)
    rng = np.random.default_rng(0)
    distorted = {}
    for wid, (dx, dy) in disp.items():
        w = ctx.master.layout.word(wid)
        x, y = w.glyphs[0].x, w.glyphs[0].y
        distorted[wid] = (dx + 0.9 + 0.004 * x + 0.002 * y + rng.normal(0, 0.01),
                          dy - 1.3 + 0.003 * x - 0.001 * y + rng.normal(0, 0.01))
    sb = decode_displacements(ctx.master, ctx.plan, distorted, ctx.shift)
    _check_bits(sb, ctx.codewords[3])
    assert sb.meta["sigma_pt"]["kata"] < 0.05


def test_estimate_sigma_recovers_noise():
    rng = np.random.default_rng(1)
    s = rng.choice([-1.0, 1.0], 4000) * 0.14 + rng.normal(0, 0.05, 4000)
    assert estimate_sigma(s, 0.14, 0.001) == pytest.approx(0.05, rel=0.1)
    assert estimate_sigma(np.array([]), 0.14, 0.01) == pytest.approx(0.14)


def test_match_words_identity(sample_pdf):
    layout = extract_layout(sample_pdf)
    disp = match_words(layout, layout)
    assert len(disp) == sum(1 for _ in layout.words())
    assert all(d == (0.0, 0.0) for d in disp.values())


# --- fusion and attribution ------------------------------------------------------------


def test_fuse_adds_llrs_and_detects_conflicts():
    a = SoftBits(CHANNEL_ZW, np.arange(50), np.full(50, 5.0))
    b = SoftBits(CHANNEL_SHIFT, np.arange(50), np.full(50, -5.0))
    c = SoftBits(CHANNEL_HOMOGLYPH, [60], [0.1])
    f = fuse([a, c], 100)
    assert f.n_observed == 50 and f.y[:50].all() and f.weights[60] == 0.0
    assert f.weights[0] == pytest.approx(np.tanh(2.5))
    g = fuse([a, b], 100)
    assert g.n_observed == 0  # opposite evidence cancels
    assert g.conflicts["geser|teks"] == (50, 50)
    per = fuse_by_physical_channel([a, b, c], 100)
    assert set(per) == {"teks", "geser"}
    with pytest.raises(ValueError):
        fuse([SoftBits(CHANNEL_ZW, [100], [1.0])], 100)


def test_insufficient_evidence_never_names_anyone(ctx):
    rng = np.random.default_rng(2)
    noise = SoftBits(CHANNEL_SHIFT, rng.integers(0, ctx.params.length, 150), rng.normal(0, 2, 150))
    result = run_trace([noise], ctx)
    assert result.verdict == VERDICT_INSUFFICIENT and result.accused == []
    text = "\n".join(result.summary_lines())
    for ref in ctx.refs:
        assert ref.nama not in text
    empty = run_trace([], ctx)
    assert empty.verdict == VERDICT_INSUFFICIENT
    assert any("tidak ada tanda" in n for n in empty.notes)


def test_named_copy_always_has_numbers(issued, ctx):
    result = run_trace(collect_from_pdf(_copy_bytes(issued, 2), ctx), ctx)
    top = result.accused[0]
    assert top.copy.seq == 2 and top.false_accusation_probability < 1e-20
    # Background and text layer always suffice alone; the shift channel (~180 positions) is
    # borderline on its own (see test_shift_vector_readout_recovers_codeword).
    assert {"latar", "teks"} <= set(top.channels_agreeing) <= {"geser", "latar", "teks"}
    line = [ln for ln in result.summary_lines() if top.copy.nama in ln][0]
    assert "skor" in line and "Z" in line and "peluang tuduhan salah" in line
    assert result.threshold.fixed_at and result.threshold.n_observed > 0


def test_trace_file_and_integrity_checks(issued, ctx, sample_pdf, secret, tmp_path):
    out, manifest = issued
    result, obs = trace_file(out / manifest.copies[6].file, ctx)
    assert result.accused[0].copy.seq == 7
    assert any("identik" in n for n in result.notes)
    txt = tmp_path / "bocor.txt"
    txt.write_text(extract_pdf_text(_copy_bytes(issued, 8)), encoding="utf-8")
    assert trace_file(txt, ctx)[0].accused[0].copy.seq == 8
    with pytest.raises(TraceError):
        load_context(sample_pdf, manifest, b"\x01" * 32)        # wrong code secret
    other = (sample_pdf[:-10] + b"%%EOF\n")
    with pytest.raises(TraceError):
        load_context(other, manifest, secret)                   # different master bytes
    with pytest.raises(TraceError):
        trace_file(tmp_path / "x.xyz", ctx) if (tmp_path / "x.xyz").write_text("a") else None


def test_regenerated_codewords_match_commitments(ctx, secret):
    for ref, x in zip(ctx.refs, ctx.codewords):
        assert np.array_equal(x, derive_codeword(secret, ctx.master.doc_hash, ref.copy_id, ctx.p))
