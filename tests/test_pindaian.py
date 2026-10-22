"""Scanned masters (halaman pindaian): detection, pixel-domain marks, gates, tracing, drift.

The material is fictional: ``samplegen.scanned_sample`` renders the synthetic nota dinas like a
scan (gray JPEG pages, slight skew, paper tone, noise), keeping its "CONTOH SINTETIS - BUKAN
DOKUMEN ASLI" footer in every page image. Fast tests use one page at 200 dpi, the lowest
resolution TAPAK accepts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from tapak.decoder.accuse import VERDICT_IDENTIFIED
from tapak.decoder.trace import SCAN_SHIFT_SKIPPED, attach_recorded_scans, load_context, trace_files
from tapak.marker.background import BackgroundSettings, cell_levels, page_grids, paper_threshold
from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, build_document_plan, issue, marks_for_codeword
from tapak.marker.master import load_master
from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT, plan_key
from tapak.marker.raster import (
    MIN_SCAN_DPI,
    attach_scan_layout,
    boxes_digest,
    change_bounds,
    check_scan_change,
    detect_scans,
    group_rows,
    mark_scan_image,
    ocr_text_in,
    page_modes,
    parse_tsv,
    pattern_field,
    plan_lines,
    prepare_scans,
    require_markable,
    scan_boxes,
    scan_gate,
    scan_image,
)
from tapak.marker.render import CopyMarks, render_copy, visual_gate
from tapak.samplegen import scanned_sample
from tapak.tardos.code import derive_bias, derive_codeword

SECRET = bytes(range(32))


def _one_page(pdf: bytes, page: int = 0) -> bytes:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        doc.select([page])
        return doc.tobytes()


@pytest.fixture(scope="module")
def scan_one(sample_pdf) -> bytes:
    """Page 1 of the sample as a 200 dpi scan with an invisible OCR layer."""
    return scanned_sample(_one_page(sample_pdf), dpi=200, ocr_layer=True)


@pytest.fixture(scope="module")
def scan_issued(tmp_path_factory, scan_one):
    folder = tmp_path_factory.mktemp("pindaian")
    src = folder / "pindaian.pdf"
    src.write_bytes(scan_one)
    recipients = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji") for i in range(1, 5)]
    manifest = issue(src, recipients, folder / "salinan", SECRET, IssueSettings(workers=2, n_max=20), issuer="pytest")
    return folder / "salinan", manifest, scan_one


# --- detection -------------------------------------------------------------------------


def test_detects_text_scanned_ocr_and_mixed_pages(sample_pdf):
    variants = {
        "teks": (sample_pdf, {}, False),
        "pindaian": (scanned_sample(sample_pdf, dpi=100), {0, 1}, False),
        "pindaian_ocr": (scanned_sample(sample_pdf, dpi=100, ocr_layer=True), {0, 1}, True),
        "campuran": (scanned_sample(sample_pdf, dpi=100, scan_pages={1}), {1}, False),
    }
    for name, (pdf, pages, ocr) in variants.items():
        master = load_master(pdf)
        assert set(master.scans) == set(pages), name
        assert all(s.ocr_layer == ocr and s.problem is None for s in master.scans.values()), name
        assert page_modes(master) == ["pindaian" if i in pages else "teks" for i in range(2)], name
        for k in range(2):  # a scanned page has no text rows: its OCR layer is never redrawn or marked
            assert bool(master.layout.pages[k].rows) == (k not in pages), name
    # The invisible OCR text exists in the file but not in the master's text layer.
    assert ocr_text_in(variants["pindaian_ocr"][0], [0, 1]) > 500


def test_full_page_image_with_visible_text_stays_a_text_page(scan_one):
    doc = pymupdf.open(stream=scan_one, filetype="pdf")
    doc[0].insert_text((72, 60), "SALINAN", fontsize=12)  # visible text over the scan
    with_text = doc.tobytes()
    assert detect_scans(pymupdf.open(stream=with_text, filetype="pdf")) == {}
    blank = pymupdf.open()
    blank.new_page()
    assert detect_scans(blank) == {}


def test_low_resolution_scan_is_refused(sample_pdf, tmp_path, recipients):
    low = scanned_sample(_one_page(sample_pdf), dpi=150)
    master = load_master(low)
    assert master.scans[0].dpi == pytest.approx(150, abs=1)
    with pytest.raises(ValueError, match="minimal 200 dpi"):
        require_markable(master)
    src = tmp_path / "rendah.pdf"
    src.write_bytes(low)
    with pytest.raises(ValueError, match="Pindai ulang"):
        issue(src, recipients[:2], tmp_path / "o", SECRET)
    assert MIN_SCAN_DPI == 200


def test_rotated_scan_is_refused(scan_one):
    doc = pymupdf.open(stream=scan_one, filetype="pdf")
    doc[0].set_rotation(90)
    master = load_master(doc.tobytes())
    assert master.scans[0].problem and "diputar" in master.scans[0].problem
    with pytest.raises(ValueError, match="halaman 1"):
        require_markable(master)


# --- word boxes --------------------------------------------------------------------------


def test_parse_tsv_and_group_rows():
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "5\t1\t1\t1\t1\t1\t100\t100\t80\t30\t95\tKepada",
        "5\t1\t1\t1\t1\t2\t200\t102\t60\t28\t90\tYth.",
        "5\t1\t2\t1\t1\t1\t600\t101\t90\t30\t92\tNomor",     # same height, another block: same row
        "5\t1\t1\t1\t2\t1\t100\t200\t70\t30\t20\tblur",       # weak: dropped
        "5\t1\t1\t1\t2\t2\t200\t200\t5\t30\t96\t:",          # no letter or digit: dropped
        "5\t1\t1\t1\t2\t3\t300\t200\t90\t31\t96\tlatihan",
        "5\t1\t3\t1\t1\t1\t100\t400\t400\t300\t96\tLOGO",     # far taller than text: dropped
        "4\t1\t1\t1\t1\t0\t100\t100\t600\t30\t-1\t",          # a line row, not a word
    ]
    words = parse_tsv("\n".join([head] + rows))
    assert [w[7] for w in words] == [6, 4, 5, 7, 4]
    grouped = group_rows(words)
    assert [[w[0] for w in row] for row in grouped] == [[100, 200, 600], [300]]
    assert parse_tsv("") == [] and group_rows([]) == []


def test_scan_boxes_are_deterministic_and_only_their_digest_is_kept(scan_one):
    a, b = load_master(scan_one), load_master(scan_one)
    boxes_a = scan_boxes(a)
    assert len(boxes_a[0]) > 20 and sum(len(r) for r in boxes_a[0]) > 100
    assert boxes_digest(a, boxes_a) == boxes_digest(b, scan_boxes(b))
    attach_scan_layout(a, boxes_a)
    assert a.shift_layout is not a.layout and not a.layout.pages[0].rows
    words = list(a.shift_layout.words())
    assert words and all(set(w.text) == {"#"} for w in words)  # placeholders, never the recognized text


# --- marks and gates ---------------------------------------------------------------------


def test_paper_threshold_matches_white_and_scanned_paper():
    white = np.full((100, 100), 255.0)
    assert paper_threshold(white) == 235.0
    scan = np.full((100, 100), 243.0)
    assert paper_threshold(scan) == pytest.approx(223.0)
    assert paper_threshold(np.full((40, 40, 3), 243, np.uint8)) == pytest.approx(223.0)


def test_zero_mark_copy_is_pixel_identical(scan_one):
    master = load_master(scan_one)
    gate = visual_gate(master)
    assert gate.passed and gate.scan_identical is True
    img = scan_image(master, 0)
    same, moved = mark_scan_image(img, master.scans[0], [], {}, {}, None)
    assert np.array_equal(same, img) and not moved.any()
    # A copy whose page image differs by a single pixel fails the raster gate.
    doc = pymupdf.open(stream=render_copy(master, CopyMarks()), filetype="pdf")
    from tapak.marker.raster import write_scan_image

    changed = img.copy()
    changed[500, 500] ^= 1
    write_scan_image(doc, detect_scans(doc)[0], changed)  # saving renumbered the image object
    assert scan_gate(master, render_copy(master, CopyMarks())) is True
    assert scan_gate(master, doc.tobytes()) is False


def test_color_scan_gate_and_marks(scan_one):
    """An RGB scan goes through the same gate and bounds (the pattern on all three channels)."""
    import cv2

    gray = scan_image(load_master(scan_one), 0)
    rgb = np.dstack([gray, np.clip(gray.astype(int) - 3, 0, 255), gray]).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    doc = pymupdf.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_image(page.rect, stream=jpg.tobytes(), keep_proportion=False)
    master = load_master(doc.tobytes())
    assert set(master.scans) == {0} and scan_image(master, 0).shape == rgb.shape
    assert visual_gate(master).scan_identical is True
    prepare_scans(master)
    _, marks, _, _ = _marks_for(master, 2)
    img = scan_image(master, 0)
    marked, moved = mark_scan_image(img, master.scans[0], master.shift_layout.pages[0].rows, marks.group_dx,
                                    marks.row_dy, marks.scan_patterns[0])
    assert marked.shape == img.shape and check_scan_change(img, marked, moved) <= 4
    copy = render_copy(master, marks)
    assert detect_scans(pymupdf.open(stream=copy, filetype="pdf"))[0].problem is None


def _marks_for(master, seq_seed: int):
    from tapak.tardos.params import TardosParams

    params = TardosParams(c=3, eps=1e-6, n_max=20)
    channels = ("shift", "background")
    plan = build_document_plan(master, params, SECRET, channels, set(), BackgroundSettings())
    p = derive_bias(SECRET, master.doc_hash, params)
    x = derive_codeword(SECRET, master.doc_hash, f"copy{seq_seed}", p)
    grids = page_grids([(pg.width, pg.height) for pg in master.layout.pages], plan_key(SECRET, master.doc_hash),
                       BackgroundSettings())
    marks, _ = marks_for_codeword(master, plan, x, IssueSettings(channels=channels), grids)
    return plan, marks, grids, x


def test_marked_page_changes_only_within_channel_bounds(scan_one):
    master = load_master(scan_one)
    prepare_scans(master)
    plan, marks, grids, x = _marks_for(master, 1)
    assert plan.channel(CHANNEL_SHIFT) and set(marks.scan_patterns) == {0}
    assert not marks.page_hooks  # the vector pattern is never drawn under a scan
    img = scan_image(master, 0)
    scan = master.scans[0]
    marked, moved = mark_scan_image(img, scan, master.shift_layout.pages[0].rows, marks.group_dx, marks.row_dy,
                                    marks.scan_patterns[0])
    assert check_scan_change(img, marked, moved) <= 4
    lo, hi = change_bounds()
    diff = marked.astype(int) - img.astype(int)
    assert lo <= diff[~moved].min() and diff[~moved].max() <= hi
    assert 0.0 < moved.mean() < 0.3
    # Ink moves by the planned offset: centroid of the ink in moved groups (shift only).
    shifted, _ = mark_scan_image(img, scan, master.shift_layout.pages[0].rows, marks.group_dx, marks.row_dy, None)
    kx, ky = scan.scale
    errs = []
    for row in master.shift_layout.pages[0].rows:
        for g in row.groups:
            dx = marks.group_dx.get(g.id, 0.0) * kx
            if not dx or marks.row_dy.get(row.id, 0.0):
                continue
            x0, y0, x1, y1 = (int(g.bbox[0] * kx) - 4, int(g.bbox[1] * ky) - 4, int(g.bbox[2] * kx) + 4,
                              int(g.bbox[3] * ky) + 4)
            a = np.clip(220.0 - img[y0:y1, x0:x1], 0, None)
            b = np.clip(220.0 - shifted[y0:y1, x0:x1], 0, None)
            xs = np.arange(x1 - x0)[None, :]
            errs.append((b * xs).sum() / b.sum() - (a * xs).sum() / a.sum() - dx)
    assert len(errs) > 10 and np.sqrt(np.mean(np.square(errs))) < 0.1
    # A change beyond the pattern bounds outside the moved ink is refused.
    bad = marked.copy()
    y, xx = np.argwhere(~moved & (img > 230))[0]
    bad[y, xx] = min(255, int(img[y, xx]) + 9)
    with pytest.raises(RuntimeError, match="di luar batas"):
        check_scan_change(img, bad, moved)


def test_pattern_field_follows_the_cell_grid(scan_one):
    master = load_master(scan_one)
    scan = master.scans[0]
    grid = page_grids([(p.width, p.height) for p in master.layout.pages], b"k" * 32, BackgroundSettings())[0]
    level = np.zeros((grid.ny, grid.nx))
    level[10, 20] = 1.0
    field = pattern_field(grid, level, scan, (scan.height_px, scan.width_px))
    assert field.shape == (scan.height_px, scan.width_px) and field.min() >= 0.0 and field.max() <= 1.0
    cx, cy = grid.cell_centres_pt()
    kx, ky = scan.scale
    assert field[int(cy[10] * ky), int(cx[20] * kx)] > 0.9
    assert field[int(cy[14] * ky), int(cx[20] * kx)] == 0.0
    assert field[0, 0] == 0.0  # outside the cell grid


# --- issuance and tracing ----------------------------------------------------------------


def test_scan_issuance_record_and_no_ocr_text_in_copies(scan_issued):
    out, manifest, _ = scan_issued
    assert manifest.scan["pages"] == [0] and manifest.scan["dpi"] == [200]
    assert manifest.scan["ocr_layer_dropped"] == [0]
    assert manifest.gate["passed"] and manifest.gate["scan_identical"] is True
    assert manifest.plan_summary["shift"]["positions"] > 50
    assert manifest.plan_summary["background"]["positions"] > 1000
    assert not {"zw", "homoglyph", "semantic"} & set(manifest.plan_summary)
    assert manifest.copies[0].channels_used == ["shift", "background"]
    for c in manifest.copies:
        data = (out / c.file).read_bytes()
        assert ocr_text_in(data, [0]) == 0  # the master's invisible OCR words never reach a copy
        assert detect_scans(pymupdf.open(stream=data, filetype="pdf"))[0].dpi == pytest.approx(200, abs=1)
    lines = plan_lines(manifest.scan, 1)
    assert "1 halaman pindaian" in lines[0] and "tidak berlaku" in lines[1]
    assert any("OCR tak terlihat" in line for line in lines)
    assert plan_lines(None, 2) == ["Mode halaman: 2 halaman teks"]


def test_text_document_record_is_unchanged(issued):
    _, manifest = issued
    d = json.loads(manifest.to_json())
    assert "scan" not in d and "scan_identical" not in d["gate"]


def test_scan_copy_pdf_trace_names_the_copy(scan_issued):
    out, manifest, master_pdf = scan_issued
    ctx = load_context(master_pdf, manifest, SECRET)
    assert not ctx.warnings
    c = manifest.copies[2]
    result, obs = trace_files([(c.file, (out / c.file).read_bytes())], ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [a.copy.seq for a in result.accused] == [3]
    x = ctx.codewords[2]
    by = {sb.channel: sb for sb in obs if len(sb)}
    assert set(by) == {CHANNEL_SHIFT, CHANNEL_BACKGROUND}
    assert len(by[CHANNEL_SHIFT]) > 40
    for sb in by.values():
        assert np.mean((sb.llr > 0) == (x[sb.positions] == 1)) > 0.97
    assert any("halaman pindaian" in n for n in result.notes)


def test_box_drift_refuses_the_scan_shift_channel(scan_issued, monkeypatch):
    out, manifest, master_pdf = scan_issued
    # Same Tesseract, same boxes: attached, nothing to report.
    master = load_master(master_pdf)
    assert attach_recorded_scans(master, manifest) is None and master.scan_layout is not None
    # Another Tesseract would find other boxes: simulated by dropping one word.
    from tapak.marker import raster

    real = raster.ocr_words
    monkeypatch.setattr(raster, "ocr_words", lambda gray, dpi: real(gray, dpi)[1:])
    master = load_master(master_pdf)
    note = attach_recorded_scans(master, manifest)
    assert note and note.startswith(SCAN_SHIFT_SKIPPED) and "berbeda" in note
    assert master.scan_layout is None
    ctx = load_context(master_pdf, manifest, SECRET)
    assert any(SCAN_SHIFT_SKIPPED in w for w in ctx.warnings)
    assert not ctx.plan.channel(CHANNEL_SHIFT) and ctx.plan.channel(CHANNEL_BACKGROUND)
    c = manifest.copies[1]
    result, obs = trace_files([(c.file, (out / c.file).read_bytes())], ctx)
    assert [a.copy.seq for a in result.accused] == [2]  # the background alone still names the copy
    assert not [sb for sb in obs if sb.channel == CHANNEL_SHIFT and len(sb)]
    assert any(SCAN_SHIFT_SKIPPED in n for n in result.notes)
    # A record whose page set differs is refused the same way.
    edited = IssueManifest.from_json(manifest.to_json())
    edited.scan = dict(edited.scan, pages=[0, 1])
    assert SCAN_SHIFT_SKIPPED in attach_recorded_scans(load_master(master_pdf), edited)


def test_scan_record_holds_no_words_or_boxes(scan_issued, sample_pdf):
    from tapak.marker.layout import extract_layout
    from tapak.registry.chain import SCAN_RECORD_KEYS, scan_document_problems

    _, manifest, _ = scan_issued
    assert set(manifest.scan) == SCAN_RECORD_KEYS
    assert scan_document_problems(manifest.scan) == []
    assert scan_document_problems(dict(manifest.scan, boxes=[[1, 2, 3, 4]])) != []
    assert scan_document_problems(dict(manifest.scan, boxes_sha256="kata")) != []
    import re

    tokens = set(re.findall(r"[a-z]+", json.dumps(manifest.scan).lower()))  # all that scanned pages add
    words = {w.text.lower().strip(".,:;()") for w in extract_layout(_one_page(sample_pdf)).words()}
    leaked = sorted(w for w in words & tokens if len(w) >= 3)
    assert not leaked, leaked


def test_cli_and_registry_with_scanned_master(tmp_path, scan_one, capsys, monkeypatch):
    from tapak.cli import main

    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    src = tmp_path / "nota_pindaian.pdf"
    src.write_bytes(scan_one)
    csv = tmp_path / "penerima.csv"
    csv.write_text("recipient_id,nama,jabatan,satuan\nR1,Satu Fiktif,A,B\nR2,Dua Fiktif,A,B\n", encoding="utf-8")
    run = lambda *argv: main(["--data", str(tmp_path / "data"), "--keys", str(tmp_path / "keys"), *argv])  # noqa: E731
    assert run("keys", "init") == 0
    assert run("issue", str(src), str(csv), "--workers", "1") == 0
    out = capsys.readouterr().out
    assert "Mode halaman: 0 halaman teks, 1 halaman pindaian" in out
    assert "identik piksel demi piksel" in out and "Ukuran salinan" in out
    db = tmp_path / "data" / "registry.db"
    with sqlite3.connect(db) as con:
        payloads = [json.loads(r[0]) for r in con.execute("SELECT payload FROM entries WHERE kind = 'document'")]
    assert payloads[0]["scan"]["ocr_layer_dropped"] == [0]
    copy = next((tmp_path / "data" / "dokumen").glob("*/salinan/*salinan002_*.pdf"))
    assert run("trace", str(copy)) == 0
    out = capsys.readouterr().out
    assert "Salinan #2" in out and "TERIDENTIFIKASI" in out
    assert run("verify") == 0


@pytest.mark.slow
def test_photo_of_scanned_copy_names_the_copy(scan_issued):
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import run_trace
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, photo_jpeg

    out, manifest, master_pdf = scan_issued
    ctx = load_context(master_pdf, manifest, SECRET)
    for i, c in enumerate(manifest.copies[:2]):
        page = render_pages((out / c.file).read_bytes(), 200, [0])[0]
        data, _ = photo_jpeg(page, np.random.default_rng(700 + i), PhotoParams(angle_deg=15.0))
        result = run_trace(collect_from_image(data, ctx), ctx)
        assert [a.copy.seq for a in result.accused] == [c.seq], result.summary_lines()


def test_scanned_sample_keeps_the_synthetic_stamp(scan_one):
    import pytesseract

    from tapak.marker.raster import to_gray

    img = to_gray(scan_image(load_master(scan_one), 0))
    footer = img[int(img.shape[0] * 0.95):, :]
    text = pytesseract.image_to_string(footer, lang="ind")
    assert "CONTOH SINTETIS" in text and "BUKAN DOKUMEN ASLI" in text


def test_scanned_sample_is_deterministic(sample_pdf):
    one = _one_page(sample_pdf)
    assert scanned_sample(one, dpi=100) == scanned_sample(one, dpi=100)
    assert Path(__file__).exists()
