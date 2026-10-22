"""Decode a photo or screenshot of a copy: registration, then channels 1 and 2, and the
printed words of channels 4 and 6 through local OCR (``decoder/ocr.py``).

Registration and the background decoder use the supersampled master render
(``render_page``); the shift decoder matches word groups against the exact master template
(``render_page_exact``), which has no glyph snapping, so the template itself adds no per-group
offset of its own (10 to 30 um with the supersampled render). Only the text rows the shift
decoder reads are rendered exactly (``template_boxes``), which gives the same displacements
for about half to two thirds of the cost of a whole page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from tapak.decoder.ch_background import decode_background
from tapak.decoder.ch_shift import decode_displacements, measure_image, template_boxes
from tapak.decoder.rectify import load_gray, register, render_page, render_page_exact
from tapak.decoder.softbits import SoftBits
from tapak.marker.background import page_grids
from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

if TYPE_CHECKING:
    from tapak.decoder.trace import TraceContext


def collect_from_image(data: bytes, ctx: "TraceContext") -> list[SoftBits]:
    """Soft bits from an image file. Returns empty observations if the page is not found."""
    return collect_from_gray(load_gray(data), ctx)


def collect_from_gray(gray: np.ndarray, ctx: "TraceContext", read_text: bool = True) -> list[SoftBits]:
    """Soft bits from a grayscale page image (float32, 0..255): a photo, a screenshot or a
    rendered page of a scanned PDF. Returns empty observations if the page is not found.

    Besides the shift and background channels, a page whose master page carries semantic or
    word-choice marks is read with the local Tesseract and those marks are decoded from its
    text (``decoder/ocr.py``; ``read_text`` False skips it). OCR text never reaches the
    text-layer channel."""
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    reg = register(gray, ctx.master.pdf_bytes, sizes)
    if reg is None:
        return [SoftBits.empty(CHANNEL_SHIFT, registered=False),
                SoftBits.empty(CHANNEL_BACKGROUND, registered=False)]
    master_render = render_page(ctx.master.pdf_bytes, reg.page, reg.dpi)
    reg_meta = {"page": reg.page, "dpi": reg.dpi, "correlation": round(reg.correlation, 4),
                "method": reg.method, "effective_dpi": round(reg.effective_dpi, 1)}
    out: list[SoftBits] = []
    if ctx.plan.channel(CHANNEL_SHIFT):
        template = render_page_exact(ctx.master.pdf_bytes, reg.page, reg.dpi,
                                     boxes=template_boxes(ctx.master, reg.page, reg.dpi))
        disp = measure_image(reg.rectified, reg.valid, template, ctx.master, reg.page, reg.dpi)
        del template
        sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
        sb.meta.update(reg_meta)
        out.append(sb)
    if ctx.plan.channel(CHANNEL_BACKGROUND) and ctx.background is not None:
        grid = page_grids(sizes, ctx.key, ctx.background)[reg.page]
        sb = decode_background(reg.rectified, reg.valid, master_render, reg.dpi, grid,
                               ctx.plan.channel(CHANNEL_BACKGROUND), bias=ctx.p)
        sb.meta.update(reg_meta)
        out.append(sb)
    if read_text:
        from tapak.decoder.ocr import ocr_unavailable_reason, page_slots, read_visible_text

        if any(page_slots(ctx, reg.page)) and ocr_unavailable_reason() is not None:
            for sb in out:  # the page carries visible-text marks that could not be read (no Tesseract)
                sb.meta["ocr_unavailable"] = True
        for sb in read_visible_text(gray, reg, ctx):
            sb.meta.update(reg_meta)
            out.append(sb)
    return out
