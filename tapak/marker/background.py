"""Channel 2: low-amplitude background pattern (spread spectrum, blind decodable).

The page is divided into square cells (default 2 mm). Every code position carried on a
page owns ``cells_per_bit`` cells scattered over the whole page by a keyed permutation, and
every cell has a keyed pseudo-random sign pn_c in {-1, +1}. A copy draws, under all page
content, a light gray background whose level in cell c is

    base + amplitude * s_b * pn_c        with s_b = (2*bit - 1) * (1 - 2*whiten)

linearly interpolated between cell centres (a low-frequency pattern, no hard edges and no overshoot). With
the defaults the background varies between 251 and 255 gray levels (amplitude 2 around a
base of 253), invisible on screen and on paper.

Decoding never needs a candidate's codeword: the decoder correlates the measured cell
levels with pn_c over the cells of each position, which estimates s_b. Averaging or cutting
two copies together cancels exactly the positions where the copies differ (they read as
erased), which is the marking-assumption behaviour Tardos codes are built for.

Limitation (honest): printers render levels above about 250 as plain paper, so this channel
is meant for screens, screenshots and photos of screens; printed copies rely on channel 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import cv2
import numpy as np
import pymupdf

from tapak.marker.plan import CHANNEL_BACKGROUND, EmbeddingPlan, Slot, assign_positions
from tapak.tardos.code import uniform_stream

PT_PER_MM = 72.0 / 25.4


@dataclass(frozen=True)
class BackgroundSettings:
    """Pattern parameters."""

    cell_mm: float = 2.0
    cells_per_bit: int = 8
    amplitude: float = 2.0
    base: float = 253.0
    px_per_cell: int = 4

    def __post_init__(self) -> None:
        if self.base + self.amplitude > 255 or self.base - self.amplitude < 0:
            raise ValueError("base +/- amplitude must stay within 0..255")
        if self.cells_per_bit < 1 or self.cell_mm <= 0:
            raise ValueError("invalid cell settings")


@dataclass(frozen=True)
class PageGrid:
    """Cell grid of one page plus the keyed cell-to-bit map and signs."""

    page: int
    width_pt: float
    height_pt: float
    settings: BackgroundSettings
    key: bytes

    @property
    def cell_pt(self) -> float:
        """Cell size in points."""
        return self.settings.cell_mm * PT_PER_MM

    @property
    def nx(self) -> int:
        """Cells across."""
        return int(math.floor(self.width_pt / self.cell_pt))

    @property
    def ny(self) -> int:
        """Cells down."""
        return int(math.floor(self.height_pt / self.cell_pt))

    @property
    def n_cells(self) -> int:
        """Total cells."""
        return self.nx * self.ny

    @property
    def n_bits(self) -> int:
        """Code bits carried by this page."""
        return self.n_cells // self.settings.cells_per_bit

    @property
    def offset_pt(self) -> tuple[float, float]:
        """Top-left of the grid (the grid is centred on the page)."""
        return ((self.width_pt - self.nx * self.cell_pt) / 2.0, (self.height_pt - self.ny * self.cell_pt) / 2.0)

    @cached_property
    def cell_bit(self) -> np.ndarray:
        """Bit index (0..n_bits-1) of every cell, row-major (ny, nx); -1 for unused cells."""
        u = uniform_stream(self.key, f"bg-cells|{self.page}".encode(), self.n_cells)
        order = np.argsort(u, kind="stable")
        bit = np.full(self.n_cells, -1, dtype=np.int64)
        used = self.n_bits * self.settings.cells_per_bit
        bit[order[:used]] = np.arange(used) % self.n_bits
        return bit.reshape(self.ny, self.nx)

    @cached_property
    def pn(self) -> np.ndarray:
        """Keyed sign of every cell (ny, nx)."""
        u = uniform_stream(self.key, f"bg-pn|{self.page}".encode(), self.n_cells)
        return np.where(u < 0.5, -1.0, 1.0).reshape(self.ny, self.nx)

    def cell_centres_pt(self) -> tuple[np.ndarray, np.ndarray]:
        """x and y of cell centres in points (arrays of shape (nx,) and (ny,))."""
        ox, oy = self.offset_pt
        return ox + (np.arange(self.nx) + 0.5) * self.cell_pt, oy + (np.arange(self.ny) + 0.5) * self.cell_pt


def page_grids(page_sizes: list[tuple[float, float]], key: bytes,
               settings: BackgroundSettings) -> list[PageGrid]:
    """Grids for all pages of a document."""
    return [PageGrid(i, w, h, settings, key) for i, (w, h) in enumerate(page_sizes)]


def build_background_slots(grids: list[PageGrid], m: int, key: bytes) -> list[Slot]:
    """One slot per page bit; positions continue across pages so pages carry different slices."""
    refs = [(g.page, (b,), 1) for g in grids for b in range(g.n_bits)]
    return assign_positions(CHANNEL_BACKGROUND, refs, m, key)


def cell_levels(grid: PageGrid, slots: list[Slot], codeword: np.ndarray) -> np.ndarray:
    """Signed cell modulation in units of the amplitude: s_b(c) * pn_c, shape (ny, nx)."""
    signs = np.zeros(grid.n_bits)
    for s in slots:
        if s.page == grid.page:
            bit = int(codeword[s.positions[0]])
            signs[s.ref[0]] = (2 * bit - 1) * (1 - 2 * s.whiten[0])
    cb = grid.cell_bit
    level = np.where(cb >= 0, signs[np.clip(cb, 0, None)], 0.0) * grid.pn
    return level


def pattern_image(grid: PageGrid, level: np.ndarray) -> np.ndarray:
    """Smooth 8-bit gray image of the page background (linear interpolation of cell values)."""
    s = grid.settings
    k = s.px_per_cell
    up = cv2.resize(level.astype(np.float32), (grid.nx * k, grid.ny * k), interpolation=cv2.INTER_LINEAR)
    img = np.clip(np.rint(s.base + s.amplitude * up), 0, 255).astype(np.uint8)
    return img


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 4])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def background_hook(plan: EmbeddingPlan, codeword: np.ndarray, grids: list[PageGrid]):
    """A CopyMarks page hook that draws this copy's pattern under all page content."""
    slots = plan.channel(CHANNEL_BACKGROUND)
    by_page = {g.page: g for g in grids}

    def hook(doc: pymupdf.Document, page: pymupdf.Page) -> None:
        grid = by_page.get(page.number)
        if grid is None:
            return
        img = pattern_image(grid, cell_levels(grid, slots, codeword))
        ox, oy = grid.offset_pt
        rect = pymupdf.Rect(ox, oy, ox + grid.nx * grid.cell_pt, oy + grid.ny * grid.cell_pt)
        # Content inserted with overlay=False goes to the very front of the content stream, so
        # insert the pattern first and the plain base-level rectangle second: the rectangle
        # ends up at the bottom and fills the sub-cell margin around the grid, keeping the
        # page tone uniform.
        page.insert_image(rect, stream=_png(img), overlay=False)
        page.draw_rect(page.rect, color=None, fill=(grid.settings.base / 255.0,) * 3, overlay=False)

    return hook


def expected_page_image(grid: PageGrid, slots: list[Slot], codeword: np.ndarray) -> np.ndarray:
    """The pattern a given codeword produces (for tests and diagnostics)."""
    return pattern_image(grid, cell_levels(grid, slots, codeword))


def png_bytes(img: np.ndarray) -> bytes:
    """PNG encoding helper (exported for tests)."""
    return _png(img)


__all__ = [
    "BackgroundSettings",
    "PageGrid",
    "background_hook",
    "build_background_slots",
    "cell_levels",
    "expected_page_image",
    "page_grids",
    "pattern_image",
    "png_bytes",
]
