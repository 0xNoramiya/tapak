"""Exact master templates (rectify.render_page_exact): rendered without glyph snapping and used
by the shift decoder for images."""

from __future__ import annotations

import numpy as np

from tapak.decoder.ch_shift import measure_image
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
    a = render_page_exact(sample_pdf, 0, 150)  # rendered by the test above (same page and dpi)
    a[:] = 0  # callers get a copy: the cached template stays intact
    b = render_page_exact(sample_pdf, 0, 150)
    assert b.min() < 128 < b.max() == 255.0
    from tapak.decoder.rectify import _render_exact_cached

    hits = _render_exact_cached.cache_info().hits
    render_page_exact(sample_pdf, 0, 150)
    assert _render_exact_cached.cache_info().hits == hits + 1


def test_image_decoder_matches_against_the_exact_template(issued, ctx, monkeypatch):
    """A copy rendered exactly (no snapping in the evidence either): every shift bit read is right."""
    import tapak.decoder.image as image
    from tapak.decoder.image import collect_from_gray

    calls = []

    def spy(pdf, page, dpi):
        calls.append((pdf == ctx.master.pdf_bytes, page, dpi))
        return render_page_exact(pdf, page, dpi)

    monkeypatch.setattr(image, "render_page_exact", spy)
    out, manifest = issued
    img = render_page_exact((out / manifest.copies[8].file).read_bytes(), 0, 150, cache=False)
    obs = {sb.channel: sb for sb in collect_from_gray(img, ctx)}
    assert calls and calls[0][:2] == (True, 0)
    sb = obs["shift"]
    x = ctx.codewords[8]
    assert len(sb) > 60 and np.mean((sb.llr > 0) == (x[sb.positions] == 1)) == 1.0
