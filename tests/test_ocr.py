"""OCR of image evidence for the semantic and word-choice channels (``tapak/decoder/ocr.py``).

Covers the OCR path on rendered pages (skipped when Tesseract or its Indonesian data is not
installed), the rule that the same visible mark read from several evidence files counts once
(``fuse.combine_repeated_reads``), code-blindness, the missing-Tesseract note, the labels of the
OCR-read channels, and that no OCR text reaches the result, its JSON, the berita acara, the
diagnostics or the logs.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import subprocess

import cv2
import numpy as np
import pymupdf
import pytest

from tapak.decoder import ocr as ocr_mod
from tapak.decoder.accuse import ChannelEvidence
from tapak.decoder.ch_lexical import LexReference
from tapak.decoder.fuse import SAME_MARK_PHYSICAL, combine_repeated_reads, fuse, fuse_by_physical_channel
from tapak.decoder.image import collect_from_gray, collect_from_image
from tapak.decoder.ocr import (
    DEFAULT_OCR,
    OCR_SKIPPED,
    OcrSettings,
    OcrUnavailable,
    ocr_applies,
    ocr_languages,
    ocr_unavailable_reason,
    page_image,
    page_slots,
    read_page_text,
    read_visible_text,
    recognize,
)
from tapak.decoder.rectify import Registration
from tapak.decoder.softbits import SoftBits
from tapak.decoder.trace import (
    collect_file,
    collect_from_pdf,
    collect_from_text,
    load_context,
    ocr_missing_note,
    run_trace,
    trace_files,
)
from tapak.llm.provider import get_provider
from tapak.marker import lexical as lx
from tapak.marker.issue import IssueSettings, SemanticSelection, issue
from tapak.marker.master import load_master
from tapak.marker.plan import (
    CHANNEL_LEXICAL,
    CHANNEL_LEXICAL_OCR,
    CHANNEL_SEMANTIC,
    CHANNEL_SEMANTIC_OCR,
    OCR_SUBCHANNELS,
    PHYSICAL_CHANNEL,
)
from tapak.marker.render import render_pages
from tapak.marker.semantic import STATUS_APPROVED, find_candidate_units, generate_variant_set
from tests_support import SAMPLE

SECRET = bytes(range(32))
DPI = 150
HAVE_OCR = ocr_unavailable_reason() is None
needs_ocr = pytest.mark.skipif(not HAVE_OCR, reason="tesseract with Indonesian data not installed")


# --- fusion: one visible mark read twice counts once ---------------------------------------------


def test_combine_repeated_reads():
    agree = combine_repeated_reads([np.array([6.0, -2.0, 0.0]), np.array([6.0, -6.0, 0.0])])
    assert agree.tolist() == [6.0, -6.0, 0.0]  # the best single read, never the sum
    clash = combine_repeated_reads([np.array([6.0, 6.0]), np.array([-6.0, -2.0])])
    assert clash.tolist() == [0.0, 4.0]  # disagreement lowers confidence down to an erasure
    one = np.array([1.5, -3.25, 0.0])
    assert np.array_equal(combine_repeated_reads([one]), one)
    with pytest.raises(ValueError):
        combine_repeated_reads([])


def test_fuse_counts_a_visible_mark_once_across_evidence():
    assert SAME_MARK_PHYSICAL == {PHYSICAL_CHANNEL[CHANNEL_SEMANTIC], PHYSICAL_CHANNEL[CHANNEL_LEXICAL]}
    assert {PHYSICAL_CHANNEL[c] for c in OCR_SUBCHANNELS} == SAME_MARK_PHYSICAL
    text = SoftBits(CHANNEL_SEMANTIC, np.array([3, 4]), np.array([6.0, -6.0]))
    photo = SoftBits(CHANNEL_SEMANTIC_OCR, np.array([3, 4]), np.array([6.0, 2.0]))
    shift_a = SoftBits("shift", np.array([3]), np.array([1.0]))
    shift_b = SoftBits("shift", np.array([3]), np.array([1.5]))
    fused = fuse([text, shift_a, photo, shift_b], 10)
    assert fused.llr[3] == pytest.approx(6.0 + 2.5)  # semantic once, shift reads still add
    assert fused.llr[4] == pytest.approx(-4.0)
    assert fused.subchannels == sorted({CHANNEL_SEMANTIC, CHANNEL_SEMANTIC_OCR, "shift"})
    alone = fuse([text], 10)
    assert alone.llr[3] == 6.0 and alone.llr[4] == -6.0  # a single observation is unchanged
    per = fuse_by_physical_channel([text, photo, shift_a], 10)
    assert set(per) == {"semantik", "geser"} and per["semantik"].llr[3] == 6.0


def test_channel_evidence_source_label():
    ev = ChannelEvidence("leksikal", 5, 9.0, None, 0.0, [], subchannels=[CHANNEL_LEXICAL_OCR])
    assert ev.source_label == "OCR gambar" and ev.display_name == "leksikal (OCR gambar)"
    both = ChannelEvidence("semantik", 4, 9.0, None, 0.0, [], subchannels=[CHANNEL_SEMANTIC, CHANNEL_SEMANTIC_OCR])
    assert both.source_label == "teks dan OCR gambar"
    plain = ChannelEvidence("geser", 100, 50.0, 1, 3.0, [])
    assert plain.source_label == "" and plain.display_name == "geser"


# --- Tesseract -----------------------------------------------------------------------------------


def test_missing_tesseract_is_reported_not_fatal(monkeypatch):
    ocr_languages.cache_clear()
    monkeypatch.setattr(ocr_mod.shutil, "which", lambda name: None)
    try:
        assert ocr_unavailable_reason() == "Tesseract tidak terpasang"
        with pytest.raises(OcrUnavailable):
            recognize(np.full((20, 20), 255, np.uint8), 150)
    finally:
        ocr_languages.cache_clear()


def test_recognize_streams_through_stdin_and_stdout(monkeypatch):
    seen = {}

    def fake_run(cmd, input=None, capture_output=False, env=None, timeout=None):  # noqa: A002
        seen.update(cmd=cmd, input=input, env=env)
        return subprocess.CompletedProcess(cmd, 0, stdout="teks uji\n".encode(), stderr=b"")

    monkeypatch.setattr(ocr_mod, "ocr_languages", lambda: "ind+eng")
    monkeypatch.setattr(ocr_mod.subprocess, "run", fake_run)
    out = recognize(np.full((30, 40), 255, np.uint8), 149.6, psm=6)
    assert out == "teks uji\n"
    cmd = seen["cmd"]
    assert cmd[1:3] == ["stdin", "stdout"]  # no image or text file on disk
    assert cmd[cmd.index("-l") + 1] == "ind+eng" and cmd[cmd.index("--psm") + 1] == "6"
    assert cmd[cmd.index("--dpi") + 1] == "150" and seen["env"]["OMP_THREAD_LIMIT"] == "1"
    assert seen["input"].startswith(b"\x89PNG")


@needs_ocr
def test_recognize_tiny_rendered_page():
    assert ocr_languages().split("+")[0] == "ind"
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=60)
    page.insert_text((14, 36), "Demikian untuk dilaksanakan dan dilaporkan.", fontsize=14, fontname="helv")
    img = render_pages(doc.tobytes(), 200)[0]
    text = recognize(img, 200, DEFAULT_OCR.psm)
    assert "dilaksanakan" in text and "dilaporkan" in text


# --- the OCR path on an issued document -----------------------------------------------------------


@pytest.fixture(scope="module")
def visible(tmp_path_factory, recipients):
    """The nota dinas issued with every mock sentence variant and every word-choice point approved."""
    master = load_master(SAMPLE.read_bytes())
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, get_provider("mock")) for u in units]
    for vs in sets:
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED)
    sem = SemanticSelection(units, sets)
    lex = lx.scan_candidates(master)
    for p in lex.points:
        lex.set_status(p.point_id, STATUS_APPROVED)
    out = tmp_path_factory.mktemp("ocr")
    manifest = issue(SAMPLE, recipients, out, SECRET, IssueSettings(workers=2), semantic=sem, lexical=lex)
    ctx = load_context(SAMPLE.read_bytes(), manifest, SECRET, semantic=sem, lexical=lex)
    assert ctx.warnings == [] and ocr_applies(ctx)
    return out, manifest, ctx


def _page_render(visible, seq: int, page: int = 0) -> np.ndarray:
    out, manifest, _ = visible
    return render_pages((out / manifest.copies[seq - 1].file).read_bytes(), DPI, [page])[0]


def _perfect_registration(img: np.ndarray, page: int) -> Registration:
    """A registration that maps the page render onto itself (the rectified page is the render)."""
    return Registration(page=page, dpi=float(DPI), h_page_to_img=np.eye(3), correlation=1.0, method="uji",
                        rectified=img.astype(np.float32), valid=np.ones(img.shape, dtype=bool),
                        effective_dpi=float(DPI))


def test_page_slots_and_lex_reference_per_page(visible):
    _, _, ctx = visible
    for page in (0, 1):
        sem, lex = page_slots(ctx, page)
        assert sem and lex and all(s.page == page for s in sem + lex)
        ref = LexReference(ctx.master, ctx.lexical.carrying(), pages={page})
        on_page = {p.point_id for p in ctx.lexical.carrying() if p.page == page}
        assert set(ref.spans) == on_page
    full = LexReference(ctx.master, ctx.lexical.carrying())
    assert set(full.spans) == {p.point_id for p in ctx.lexical.carrying()}
    assert len(LexReference(ctx.master, ctx.lexical.carrying(), pages={0}).text) < len(full.text)


def test_page_image_settings(visible):
    _, _, ctx = visible
    img = _page_render(visible, 1)
    reg = _perfect_registration(img, 0)
    reg.valid[:, :40] = False  # outside the evidence image: white, not the replicated border
    p = ctx.master.layout.pages[0]
    out, dpi = page_image(img.astype(np.float32), reg, (p.width, p.height), OcrSettings())
    assert dpi == DPI and out.dtype == np.uint8 and out.shape == img.shape and (out[:, :40] == 255).all()
    big, dpi2 = page_image(img.astype(np.float32), reg, (p.width, p.height), OcrSettings(dpi=300.0))
    assert dpi2 == 300.0 and abs(big.shape[1] - round(p.width * 300 / 72)) <= 1
    flat, _ = page_image(img.astype(np.float32), reg, (p.width, p.height), OcrSettings(flatten=True))
    assert flat.dtype == np.uint8 and np.median(flat[reg.valid]) > 200  # paper stays white


@needs_ocr
def test_read_visible_text_on_a_rendered_page(visible):
    _, _, ctx = visible
    seq = 4
    x = ctx.codewords[seq - 1]
    for page in (0, 1):
        img = _page_render(visible, seq, page)
        obs = read_visible_text(img.astype(np.float32), _perfect_registration(img, page), ctx)
        assert {o.channel for o in obs} == {CHANNEL_SEMANTIC_OCR, CHANNEL_LEXICAL_OCR}
        sem, lex = page_slots(ctx, page)
        printed = {q for s in sem + lex for q in s.positions}
        for sb in obs:
            assert set(sb.positions.tolist()) <= printed  # only this page's marks
            assert np.array_equal((sb.llr > 0).astype(int), x[sb.positions])  # every bit read is right
            assert sb.meta["source"] == "ocr" and sb.meta["page"] == page and sb.meta["ocr_seconds"] >= 0
        assert sum(len(sb) for sb in obs) >= 0.8 * len(printed)


@needs_ocr
def test_ocr_readers_are_code_blind(visible):
    _, _, ctx = visible
    img = _page_render(visible, 7)
    reg = _perfect_registration(img, 0)
    rng = np.random.default_rng(5)
    other = dataclasses.replace(ctx, codewords=rng.integers(0, 2, ctx.codewords.shape, dtype=np.uint8))
    a = read_visible_text(img.astype(np.float32), reg, ctx)
    b = read_visible_text(img.astype(np.float32), reg, other)
    assert [o.channel for o in a] == [o.channel for o in b]
    for u, v in zip(a, b):
        assert np.array_equal(u.positions, v.positions) and np.array_equal(u.llr, v.llr)


def test_garbled_or_missing_text_is_an_erasure(visible):
    _, _, ctx = visible
    rng = np.random.default_rng(3)
    junk = " ".join("".join(chr(97 + k) for k in rng.integers(0, 26, rng.integers(2, 9))) for _ in range(400))
    for text in ("", junk):
        obs = read_page_text(text, 0, ctx)
        assert {o.channel for o in obs} == {CHANNEL_SEMANTIC_OCR, CHANNEL_LEXICAL_OCR}
        assert sum(len(o) for o in obs) == 0


# --- the trace: labels, notes, and no OCR text anywhere ----------------------------------------------


def _png(img: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", img)
    assert ok
    return data.tobytes()


def _page_words(ctx, page: int) -> set[str]:
    """Distinctive words printed on the page (what OCR text would contain)."""
    words = {w.text.strip(".,;:()").lower() for r in ctx.master.layout.pages[page].rows for w in r.words}
    return {w for w in words if len(w) >= 8 and w.isalpha()}


@needs_ocr
def test_trace_lists_ocr_channels_and_leaks_no_text(visible, caplog, tmp_path, monkeypatch):
    from tapak.decoder.report import ReportInfo, build_report_info, render_html
    from tapak.web.app import _agreeing_labels, _channel_label, _subchannel_summary

    out, manifest, ctx = visible
    seq = 9
    img = _page_render(visible, seq)
    data = _png(img)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    caplog.set_level(logging.DEBUG)
    result, obs = trace_files([("foto_salinan.png", data)], ctx)
    names = {o.channel for o in obs}
    assert {CHANNEL_SEMANTIC_OCR, CHANNEL_LEXICAL_OCR} <= names and not names & {"zw", "homoglyph"}
    rows = {ch.channel: ch for ch in result.channels}
    assert rows["leksikal"].source_label == "OCR gambar" and rows["semantik"].source_label == "OCR gambar"
    assert rows["geser"].source_label == ""
    summary = "\n".join(result.summary_lines())
    assert "Kanal leksikal (OCR gambar)" in summary and "Kanal semantik (OCR gambar)" in summary
    assert _channel_label(rows["leksikal"]) == "Leksikal (OCR gambar)"
    assert [c.copy.seq for c in result.accused] == [seq]
    labels = _agreeing_labels(result.accused[0], result)
    assert all(lab.endswith("(OCR gambar)") for lab in labels if lab.startswith(("Leksikal", "Semantik")))
    info: ReportInfo = build_report_info(ctx, "foto_salinan.png", data, obs, case_number="UJI-OCR",
                                         examiner_name="Pemeriksa Fiktif", examiner_rank="Uji")
    html = render_html(result, info)
    assert "dibaca dari OCR gambar" in html
    # No OCR text anywhere: the page's own words never appear in any output (words that the
    # same trace without OCR also prints, such as boilerplate, are not counted).
    baseline_obs = collect_from_gray(img.astype(np.float32), ctx, read_text=False)
    baseline = run_trace(baseline_obs, ctx)
    base_info = build_report_info(ctx, "foto_salinan.png", data, baseline_obs, case_number="UJI-OCR",
                                  examiner_name="Pemeriksa Fiktif", examiner_rank="Uji")
    base_text = (json.dumps(baseline.to_dict(), default=str) + "\n".join(baseline.summary_lines())
                 + render_html(baseline, base_info)).lower()
    words = {w for w in _page_words(ctx, 0) if w not in base_text}
    assert len(words) > 20
    outputs = {
        "json": json.dumps(result.to_dict(), default=str, ensure_ascii=False),
        "ringkasan": summary,
        "meta": json.dumps([o.meta for o in obs], default=str, ensure_ascii=False),
        "berita acara": html,
        "sub-kanal web": " ".join(_subchannel_summary(o) for o in obs),
        "log": "\n".join(r.getMessage() for r in caplog.records),
    }
    for where, text in outputs.items():
        found = sorted(w for w in words if re.search(r"\b" + re.escape(w) + r"\b", text.lower()))
        assert not found, (where, found[:5])
    assert list(tmp_path.iterdir()) == []  # no temporary image or text file


def test_trace_without_tesseract_notes_it_once(visible, monkeypatch):
    out, manifest, ctx = visible
    img = _page_render(visible, 2)
    monkeypatch.setattr(ocr_mod, "ocr_unavailable_reason", lambda: "Tesseract tidak terpasang")
    data = _png(img)
    result, obs = trace_files([("a.png", data), ("b.png", data)], ctx)
    assert not {o.channel for o in obs} & OCR_SUBCHANNELS
    assert all(o.meta.get("ocr_unavailable") for o in obs if "correlation" in o.meta)
    notes = [n for n in result.notes if OCR_SKIPPED in n]
    assert notes == ["Tesseract tidak terpasang: " + OCR_SKIPPED + " (OCR)"]
    assert result.threshold.n_observed > 0  # the other channels were read as usual
    assert ocr_missing_note([], ctx) is None  # no image page found: nothing to say


def test_text_evidence_never_runs_ocr(visible, monkeypatch):
    out, manifest, ctx = visible
    monkeypatch.setattr(ocr_mod, "recognize", lambda *a, **k: pytest.fail("OCR on text evidence"))
    pdf = (out / manifest.copies[0].file).read_bytes()
    obs, _ = collect_file("salinan.pdf", pdf, ctx)
    obs += collect_from_text("teks tempelan tanpa tanda", ctx)
    assert not {o.channel for o in obs} & OCR_SUBCHANNELS


@needs_ocr
def test_pdf_and_photo_of_one_copy_read_visible_marks_once(visible):
    out, manifest, ctx = visible
    seq = 11
    pdf_obs = collect_from_pdf((out / manifest.copies[seq - 1].file).read_bytes(), ctx)
    img_obs = collect_from_image(_png(_page_render(visible, seq)), ctx)
    obs = pdf_obs + img_obs
    m = ctx.params.length
    per = fuse_by_physical_channel(obs, m)
    for phys, text_ch, ocr_ch in (("semantik", CHANNEL_SEMANTIC, CHANNEL_SEMANTIC_OCR),
                                  ("leksikal", CHANNEL_LEXICAL, CHANNEL_LEXICAL_OCR)):
        a = next(o for o in obs if o.channel == text_ch)
        b = next(o for o in obs if o.channel == ocr_ch)
        assert np.intersect1d(a.positions, b.positions).size > 0
        la, lb = np.zeros(m), np.zeros(m)
        la[a.positions], lb[b.positions] = a.llr, b.llr
        assert np.array_equal(per[phys].llr, combine_repeated_reads([la, lb]))
        assert np.abs(per[phys].llr).max() <= 6.0  # one mark, not two: never above a single clean read
    result = run_trace(obs, ctx)
    sources = {ch.channel: ch.source_label for ch in result.channels}
    assert sources["semantik"] == "teks dan OCR gambar" and sources["leksikal"] == "teks dan OCR gambar"
    assert [c.copy.seq for c in result.accused] == [seq]
