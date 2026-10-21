"""Decode a photo or screenshot of a copy: registration, then channels 1 and 2."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from tapak.decoder.ch_background import decode_background
from tapak.decoder.ch_shift import decode_displacements, measure_image
from tapak.decoder.rectify import load_gray, register, render_page
from tapak.decoder.softbits import SoftBits
from tapak.marker.background import page_grids
from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

if TYPE_CHECKING:
    from tapak.decoder.trace import TraceContext


def collect_from_image(data: bytes, ctx: "TraceContext") -> list[SoftBits]:
    """Soft bits from an image file. Returns empty observations if the page is not found."""
    return collect_from_gray(load_gray(data), ctx)


def collect_from_gray(gray: np.ndarray, ctx: "TraceContext") -> list[SoftBits]:
    """Soft bits from a grayscale page image (float32, 0..255): a photo, a screenshot or a
    rendered page of a scanned PDF. Returns empty observations if the page is not found."""
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
        disp = measure_image(reg.rectified, reg.valid, master_render, ctx.master, reg.page, reg.dpi)
        sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
        sb.meta.update(reg_meta)
        out.append(sb)
    if ctx.plan.channel(CHANNEL_BACKGROUND) and ctx.background is not None:
        grid = page_grids(sizes, ctx.key, ctx.background)[reg.page]
        sb = decode_background(reg.rectified, reg.valid, master_render, reg.dpi, grid,
                               ctx.plan.channel(CHANNEL_BACKGROUND))
        sb.meta.update(reg_meta)
        out.append(sb)
    return out
