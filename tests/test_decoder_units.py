"""Unit tests for public decoder helpers not covered elsewhere (rectify, lines, background,
image shift measurement)."""

from __future__ import annotations

import subprocess
import tempfile

import cv2
import numpy as np
import pytest

from tapak.decoder import lines
from tapak.decoder.ch_background import cell_means, decode_background, ink_mask, relative_modulation
from tapak.decoder.ch_shift import measure_image, row_slope
from tapak.decoder.rectify import (
    ecc_refine,
    effective_dpi,
    feature_homography,
    flatten_illumination,
    load_gray,
    page_corners,
    quick_score,
    render_page,
    warp_to_page,
)
from tapak.marker.background import BackgroundSettings, PageGrid, cell_levels, page_grids, pattern_image
from tapak.marker.layout import extract_layout
from tapak.marker.plan import CHANNEL_BACKGROUND


def test_load_gray_roundtrip_and_error():
    img = (np.arange(100, dtype=np.uint8).reshape(10, 10))
    ok, buf = cv2.imencode(".png", img)
    assert np.array_equal(load_gray(buf.tobytes()), img.astype(np.float32))
    with pytest.raises(ValueError):
        load_gray(b"not an image")


def _heic(img: np.ndarray, orientation: int | None = None) -> bytes:
    """The array as a HEIC file, as an iPhone saves a photo (optionally with an EXIF orientation)."""
    import io

    import pillow_heif
    from PIL import Image

    options = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        options["exif"] = exif.tobytes()
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.fromarray(img).convert("RGB")).save(buf, quality=95, **options)
    return buf.getvalue()


def test_load_gray_reads_a_heic_photo_upright(sample_pdf):
    """HEIC is what an iPhone saves by default; OpenCV does not read it."""
    from tapak.decoder.rectify import image_size, is_heif

    page = np.clip(render_page(sample_pdf, 0, 60), 0, 255).astype(np.uint8)
    data = _heic(page)
    assert is_heif(data) and not is_heif(b"\x89PNG\r\n\x1a\n" + bytes(16)) and not is_heif(b"")
    assert image_size(data) == (page.shape[1], page.shape[0])
    gray = load_gray(data)
    assert gray.dtype == np.float32 and gray.shape == page.shape
    assert float(np.abs(gray - page).mean()) < 1.0  # lossy, but the page
    # a landscape frame the camera marked "rotate a quarter turn clockwise": its top-left corner shows top-right
    frame = np.zeros((200, 300), dtype=np.uint8)
    frame[:50, :80] = 255
    turned = load_gray(_heic(frame, orientation=6))
    assert turned.shape == (300, 200) and turned[:40, -40:].mean() > 250 and turned[:40, :40].mean() < 5
    broken = data[:12] + bytes(40)
    assert is_heif(broken) and image_size(broken) is None
    with pytest.raises(ValueError, match="tidak dapat dibaca"):
        load_gray(broken)


def test_a_heic_photo_is_traced_like_a_jpeg(issued, ctx):
    from tapak.decoder.report import evidence_type_for
    from tapak.decoder.trace import check_evidence_types, collect_file
    from tapak.marker.render import render_pages

    folder, manifest = issued
    page = render_pages((folder / manifest.copies[2].file).read_bytes(), 100, [0])[0]
    check_evidence_types(["IMG_0042.HEIC", "foto.heif"])
    assert evidence_type_for("IMG_0042.HEIC") == "foto"
    obs, notes = collect_file("IMG_0042.HEIC", _heic(np.clip(page, 0, 255).astype(np.uint8)), ctx)
    assert any("dipetakan ke halaman 1" in n for n in notes)
    shift = next(sb for sb in obs if sb.channel == "shift")
    right = (shift.llr > 0) == (ctx.codewords[2][shift.positions] == 1)
    assert len(shift) > 100 and right.mean() > 0.9


def test_render_page_size_and_supersampling(sample_pdf):
    a = render_page(sample_pdf, 0, 72)
    assert a.shape == (842, 595)
    assert a.dtype == np.float32 and a.max() <= 255 and a.min() < 50


def test_flatten_illumination_removes_gradient():
    paper = np.tile(np.linspace(120, 240, 400, dtype=np.float32), (300, 1))
    flat = flatten_illumination(paper, sigma=20)
    assert np.abs(flat[50:-50, 50:-50] - 1.0).max() < 0.05


def test_page_corners_and_effective_dpi():
    c = page_corners(100, 200)
    assert c.tolist() == [[0, 0], [99, 0], [99, 199], [0, 199]]
    h = np.diag([2.0, 2.0, 1.0])
    assert effective_dpi(h, 100, 200, 100) == pytest.approx(200.0)


def test_ecc_quick_score_and_warp(sample_pdf):
    page = render_page(sample_pdf, 0, 60)
    h_true = np.array([[1.0, 0.0, 12.0], [0.0, 1.0, 7.0], [0.0, 0.0, 1.0]])
    img = cv2.warpPerspective(page, h_true, (page.shape[1] + 40, page.shape[0] + 40), borderValue=255)
    h0 = np.array([[1.0, 0.0, 9.0], [0.0, 1.0, 9.0], [0.0, 0.0, 1.0]])
    h, cc = ecc_refine(page, img, h0)
    assert cc > 0.95 and abs(h[0, 2] - 12) < 0.3 and abs(h[1, 2] - 7) < 0.3
    from tapak.decoder.rectify import _prep

    good = quick_score(_prep(img), h_true, _prep(page), 60, 60)
    bad = quick_score(_prep(img), np.array([[1, 0, 80.0], [0, 1, 50.0], [0, 0, 1]]), _prep(page), 60, 60)
    assert good > 0.9 > bad
    rect, valid = warp_to_page(img, h_true, (page.shape[1], page.shape[0]))
    assert valid.all() and np.abs(rect[50:-50, 50:-50] - page[50:-50, 50:-50]).mean() < 3


def test_feature_homography_on_scaled_render(sample_pdf):
    page = render_page(sample_pdf, 0, 100)
    img = cv2.resize(page, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_CUBIC)
    h = feature_homography(page, img)
    assert h is not None
    p = cv2.perspectiveTransform(np.array([[[300.0, 500.0]]]), h)[0, 0]
    assert np.allclose(p, [390.0, 650.0], atol=3.0)
    assert feature_homography(page, np.full((200, 200), 128, np.float32)) is None


TSV = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
       "1\t1\t0\t0\t0\t0\t0\t0\t800\t600\t-1\t\n"
       "5\t1\t1\t1\t1\t1\t10\t20\t60\t14\t96.4\tKomandan\n"
       "5\t1\t1\t1\t1\t2\t80\t20\t20\t14\t95.0\tdi\n"
       "5\t1\t1\t1\t1\t3\t110\t20\t50\t14\t59.9\tlatihan\n"
       "5\t1\t1\t1\t1\t4\t170\t20\t50\t14\t60.0\tlapangan\n"
       "5\t1\t1\t1\t1\t5\t230\t20\t40\t14\t-1")


def test_parse_words_keeps_confident_words():
    # conf truncated to an integer as pytesseract did (59.9 is out); short and empty words are out
    assert lines.parse_words(TSV) == [("Komandan", 40.0, 27.0, 14.0), ("lapangan", 195.0, 27.0, 14.0)]
    assert lines.parse_words("") == [] and lines.parse_words(TSV.split("\n")[0]) == []


def test_tesseract_tsv_streams_and_falls_back(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, capture_output=False, timeout=None, env=None):  # noqa: A002
        calls.append((cmd, input, env))
        code = 1 if "-l" in cmd else 0  # the language data is missing: retried without it
        return subprocess.CompletedProcess(cmd, code, stdout=b"" if code else TSV.encode(), stderr=b"")

    monkeypatch.setattr(lines, "tesseract_available", lambda: True)
    monkeypatch.setattr(lines.subprocess, "run", fake_run)
    assert lines.ocr_words(np.full((20, 30), 255.0)) == lines.parse_words(TSV)
    (first, png, env), (second, _, _) = calls
    assert first[1:3] == ["stdin", "stdout"] and second[1:3] == ["stdin", "stdout"]  # no file on disk
    assert first[first.index("-l") + 1] == "ind+eng" and "-l" not in second
    assert first[-2:] == ["-c", "tessedit_create_tsv=1"] and second[-2:] == ["-c", "tessedit_create_tsv=1"]
    assert png.startswith(b"\x89PNG") and env["OMP_THREAD_LIMIT"] == "1"
    monkeypatch.setattr(lines.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b""))
    assert lines.tesseract_tsv(np.zeros((5, 5), np.uint8), "ind") is None and lines.ocr_words(np.zeros((5, 5))) == []


@pytest.mark.skipif(not lines.tesseract_available(), reason="tesseract not installed")
def test_tesseract_helpers(sample_pdf, tmp_path, monkeypatch):
    def no_temp_files(*args, **kwargs):
        raise AssertionError("the OCR fallback must not write temporary files")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", no_temp_files)
    monkeypatch.setattr(tempfile, "mkstemp", no_temp_files)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    page = render_page(sample_pdf, 0, 150)
    words = lines.ocr_words(page)
    assert list(tmp_path.iterdir()) == []
    texts = {w[0].lower() for w in words}
    assert {"komandan", "latihan"} & texts
    h = lines.tesseract_homography(page, sample_pdf, 0, 150)
    assert h is not None
    pts = np.array([[[100.0, 100.0]], [[800.0, 1500.0]]])
    assert np.abs(cv2.perspectiveTransform(pts, h) - pts).max() < 2.0
    layout = extract_layout(sample_pdf)
    page_texts = [" ".join(r.text for r in p.rows) for p in layout.pages]
    assert lines.identify_page_by_text(page, page_texts) == 0


def test_background_cell_statistics_recover_pattern():
    settings = BackgroundSettings()
    grid = PageGrid(0, 595.28, 841.89, settings, b"k" * 32)
    rng = np.random.default_rng(0)
    level = rng.choice([-1.0, 1.0], size=(grid.ny, grid.nx))
    img = pattern_image(grid, level).astype(np.float32)
    dpi = 72.0 * img.shape[1] / (grid.nx * grid.cell_pt)
    usable = np.ones_like(img, dtype=bool)
    mod = relative_modulation(img, usable, sigma_px=30)
    # Pad to page size at this dpi so the grid offset maps correctly.
    page = np.full((int(round(841.89 * dpi / 72)), int(round(595.28 * dpi / 72))), 0.0)
    ox, oy = grid.offset_pt
    y0, x0 = int(round(oy * dpi / 72)), int(round(ox * dpi / 72))
    page[y0:y0 + mod.shape[0], x0:x0 + mod.shape[1]] = mod
    valid = np.zeros_like(page, dtype=bool)
    valid[y0:y0 + mod.shape[0], x0:x0 + mod.shape[1]] = True
    means, frac = cell_means(page, valid, grid, dpi)
    assert frac.mean() > 0.9
    assert np.mean(np.sign(means) == level) > 0.95


def test_ink_mask_marks_text(sample_pdf):
    page = render_page(sample_pdf, 0, 100)
    mask = ink_mask(page)
    assert mask.mean() < 0.3 and mask[page < 100].all()


def test_decode_background_on_clean_render(issued, ctx):
    out, manifest = issued
    seq = 6
    page = render_page((out / manifest.copies[seq - 1].file).read_bytes(), 0, 120)
    master = render_page(ctx.master.pdf_bytes, 0, 120)
    grid = page_grids([(p.width, p.height) for p in ctx.master.layout.pages], ctx.key, ctx.background)[0]
    sb = decode_background(page, np.ones_like(page, dtype=bool), master, 120, grid,
                           ctx.plan.channel(CHANNEL_BACKGROUND))
    x = ctx.codewords[seq - 1]
    assert np.mean((sb.llr > 0) == (x[sb.positions] == 1)) > 0.99
    assert sb.meta["snr"] > 2
    levels = cell_levels(grid, ctx.plan.channel(CHANNEL_BACKGROUND), x)
    assert set(np.unique(levels)) <= {-1.0, 0.0, 1.0}


def test_measure_image_and_row_slope(issued, ctx):
    out, manifest = issued
    seq = 10
    dpi = 150.0
    page = render_page((out / manifest.copies[seq - 1].file).read_bytes(), 0, dpi)
    master = render_page(ctx.master.pdf_bytes, 0, dpi)
    disp = measure_image(page, np.ones_like(page, dtype=bool), master, ctx.master, 0, dpi)
    assert len(disp) > 150
    assert abs(row_slope(ctx.master.layout, disp, 0)) < 1e-3
    tilted = {k: (dx, dy + 0.002 * ctx.master.layout.word(k).glyphs[0].x) for k, (dx, dy) in disp.items()}
    assert row_slope(ctx.master.layout, tilted, 0) == pytest.approx(0.002, abs=3e-4)
