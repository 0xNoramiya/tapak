"""Exact master templates (rectify.render_page_exact): rendered without glyph snapping and used
by the shift decoder for images."""

from __future__ import annotations

import numpy as np

from tapak.decoder.ch_shift import measure_image, template_boxes
from tapak.decoder.rectify import render_page, render_page_exact
from tapak.marker.master import load_master

UM_PER_PT = 25400.0 / 72.0


def _residual(disp: dict, layout, page: int) -> np.ndarray:
    """Group displacements (um) after removing an affine trend in x and y; a scale difference
    of the frame cancels in the decoder's relative offsets, a per-group bias does not."""
    words = {w.id: w for r in layout.pages[page].rows for w in r.words}
    pts = np.array([[words[k].glyphs[0].x, words[k].glyphs[0].y, *v] for k, v in disp.items()])
    a = np.column_stack([pts[:, 0], pts[:, 1], np.ones(len(pts))])
    res = pts[:, 2:] - a @ np.linalg.lstsq(a, pts[:, 2:], rcond=None)[0]
    return res * UM_PER_PT


def test_exact_template_has_no_glyph_snapping(sample_pdf):
    """The unmarked master rendered exactly at 4800 dpi and measured against the exact template
    (3200 dpi and up) moves no group by 1 um or more, and every group is measured. The
    supersampled render the decoder used before carries per-group offsets of several um."""
    master = load_master(sample_pdf)
    page, dpi = 0, 150
    template = render_page_exact(sample_pdf, page, dpi)
    assert template.shape == render_page(sample_pdf, page, dpi).shape and template.dtype == np.float32
    evidence = render_page_exact(sample_pdf, page, dpi, min_dpi=4800.0, cache=False)
    valid = np.ones(template.shape, dtype=bool)
    disp = measure_image(evidence, valid, template, master, page, dpi)
    group_words = {r.words[i].id for r in master.layout.pages[page].rows for g in r.groups for i in g.word_indices}
    assert set(disp) == group_words
    d = np.abs(np.array(list(disp.values()))) * UM_PER_PT
    assert d.max() < 1.0
    old = measure_image(evidence, valid, render_page(sample_pdf, page, dpi), master, page, dpi)
    assert np.abs(_residual(old, master.layout, page)).max() > 5.0


def test_exact_template_is_cached_per_page_and_dpi(sample_pdf):
    from tapak.decoder.rectify import _EXACT_CACHE

    a = render_page_exact(sample_pdf, 0, 150)  # rendered by the test above (same page and dpi)
    a[:] = 0  # callers get a copy: the cached template stays intact
    b = render_page_exact(sample_pdf, 0, 150)
    assert b.min() < 128 < b.max() == 255.0
    hits = _EXACT_CACHE.hits
    render_page_exact(sample_pdf, 0, 150)
    assert _EXACT_CACHE.hits == hits + 1


def test_template_boxes_cover_every_group_window(sample_pdf):
    """Each group window measure_image reads, plus the reach of its blur, lies inside one box;
    the boxes do not overlap and leave out the page margins."""
    master = load_master(sample_pdf)
    for page, dpi in ((0, 150.0), (1, 230.0)):
        boxes = template_boxes(master, page, dpi)
        s = dpi / 72.0
        for row in master.layout.pages[page].rows:
            for g in row.groups:
                x0, y0 = int(np.floor(g.bbox[0] * s)) - 3 - 3, int(np.floor(g.bbox[1] * s)) - 3 - 3
                x1, y1 = int(np.ceil(g.bbox[2] * s)) + 3 + 3, int(np.ceil(g.bbox[3] * s)) + 3 + 3
                assert any(b[0] <= x0 and b[1] <= y0 and x1 <= b[2] and y1 <= b[3] for b in boxes)
        assert all(a[3] < b[1] for a, b in zip(boxes, boxes[1:]))
        page_px = master.layout.pages[page].width * master.layout.pages[page].height * s * s
        assert sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes) < 0.8 * page_px


def test_template_restricted_to_boxes_gives_the_same_displacements(sample_pdf):
    """Rendering only the bands and columns of the boxes reproduces the whole-page exact template
    bit for bit inside them (same band grid), leaves paper elsewhere, and so measures the same
    displacements while rendering less."""
    from tapak.decoder.rectify import _EXACT_CACHE, EXACT_MIN_DPI

    master = load_master(sample_pdf)
    page, dpi = 0, 150
    full = render_page_exact(sample_pdf, page, dpi)  # cached by the first test
    boxes = template_boxes(master, page, dpi)
    part = render_page_exact(sample_pdf, page, dpi, boxes=boxes)
    inside = np.zeros(full.shape, dtype=bool)
    for x0, y0, x1, y1 in boxes:
        inside[y0:y1, x0:x1] = True
    assert np.array_equal(full[inside], part[inside])
    rendered = np.zeros(full.shape, dtype=bool)
    for y0, x0, block in _EXACT_CACHE.get((sample_pdf, page, float(dpi), EXACT_MIN_DPI, boxes))[1]:
        rendered[y0:y0 + block.shape[0], x0:x0 + block.shape[1]] = True
    assert rendered[inside].all() and rendered.mean() < 0.85
    assert part[~rendered].min() == 255.0
    evidence = render_page(sample_pdf, page, dpi) + np.random.default_rng(3).normal(0, 4, full.shape).astype(np.float32)
    valid = np.ones(full.shape, dtype=bool)
    d_full = measure_image(evidence, valid, full, master, page, dpi)
    assert d_full and measure_image(evidence, valid, part, master, page, dpi) == d_full


def test_exact_template_cache_holds_a_scanned_document(sample_pdf):
    """Nine (page, dpi) templates, as a 9-page scan gives, traced twice: the second trace renders
    nothing (an 8-entry LRU missed every one of them)."""
    import pymupdf

    from tapak.decoder.rectify import _EXACT_CACHE

    src = pymupdf.open(stream=sample_pdf, filetype="pdf")
    doc = pymupdf.open()
    for _ in range(5):
        doc.insert_pdf(src)
    pdf = doc.tobytes()
    keys = [(p, 200.0) for p in range(9)]
    for page, dpi in keys:  # min_dpi lowered only to keep the renders fast
        render_page_exact(pdf, page, dpi, min_dpi=400.0)
    hits = _EXACT_CACHE.hits
    for page, dpi in keys:
        render_page_exact(pdf, page, dpi, min_dpi=400.0)
    assert _EXACT_CACHE.hits == hits + 9


def test_byte_budget_cache_evicts_least_recently_used():
    from tapak.decoder.rectify import _ByteBudgetCache

    def entry(n: int):
        return ((1, n), [(0, 0, np.zeros((1, n), dtype=np.float32))])

    c = _ByteBudgetCache(max_bytes=100)
    c.put("a", entry(10))  # 40 bytes
    c.put("b", entry(10))
    assert c.get("a") is not None  # "b" is now the least recently used
    c.put("c", entry(10))  # 120 bytes: "b" goes
    assert c.get("b") is None and c.get("a") is not None and c.get("c") is not None
    assert c.bytes == 80 and len(c) == 2
    c.put("huge", entry(30))  # larger than the whole budget: not kept, nothing evicted
    assert c.get("huge") is None and len(c) == 2
    assert (c.hits, c.misses) == (3, 2)


def test_image_decoder_matches_against_the_exact_template(issued_v1, ctx_v1, monkeypatch):
    """A geser-v1 copy rendered exactly (no snapping in the evidence either): every shift bit read
    is right. (Under geser-v2 a few sign patterns of a row stay nearly ambiguous, with small LLRs.)"""
    issued, ctx = issued_v1, ctx_v1
    import tapak.decoder.image as image
    from tapak.decoder.image import collect_from_gray

    calls = []

    def spy(pdf, page, dpi, **kw):
        calls.append((pdf == ctx.master.pdf_bytes, page, dpi, kw.get("boxes")))
        return render_page_exact(pdf, page, dpi, **kw)

    monkeypatch.setattr(image, "render_page_exact", spy)
    out, manifest = issued
    img = render_page_exact((out / manifest.copies[8].file).read_bytes(), 0, 150, cache=False)
    obs = {sb.channel: sb for sb in collect_from_gray(img, ctx)}
    assert calls and calls[0][:2] == (True, 0)
    assert calls[0][3] == template_boxes(ctx.master, 0, calls[0][2])  # only the rows it reads
    sb = obs["shift"]
    x = ctx.codewords[8]
    assert len(sb) > 60 and np.mean((sb.llr > 0) == (x[sb.positions] == 1)) == 1.0
