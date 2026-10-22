"""Channel 1: sub-visible word-group and line shifts.

Encoding uses *relative* offsets. In every row the shift groups alternate
control / data / control / ...; a data group moves horizontally by +delta or -delta and its
two control neighbours stay put. Likewise rows alternate control / data and data rows move
vertically. A decoder measures the displacement d of every unit relative to the master and
compares a data unit with the straight line through its two control neighbours:

    r = d_data - interp(d_left, d_right)      (interpolated at the data unit's position)

Any affine distortion left over after perspective correction (translation, scale, shear,
slight rotation) is linear along a row, so it cancels in r and only +/-delta remains.

The sign carried is (2*bit - 1) * (1 - 2*whiten), so shift directions look random.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tapak.marker.layout import DocumentLayout, GroupId, Row, RowId
from tapak.marker.plan import CHANNEL_SHIFT, EmbeddingPlan, Slot, assign_positions

MM_TO_PT = 72.0 / 25.4
DEFAULT_WORD_SHIFT_MM = 0.05
DEFAULT_ROW_SHIFT_MM = 0.05
# Sub-visibility bound: between ANY two copies no glyph moves more than 0.10 mm along
# either axis. 0.10 mm is 1 arcminute at a 35 cm reading distance (the resolution limit of
# 20/20 vision) and well below the natural variation of word spacing in justified text.
# Two copies can carry opposite signs, so the per-copy shift is at most half the bound.
VISIBILITY_BOUND_MM = 0.10
MAX_SHIFT_MM = VISIBILITY_BOUND_MM / 2
MIN_ROW_GLYPHS = 3


@dataclass(frozen=True)
class ShiftSettings:
    """Shift magnitudes in millimetres."""

    word_mm: float = DEFAULT_WORD_SHIFT_MM
    row_mm: float = DEFAULT_ROW_SHIFT_MM

    def __post_init__(self) -> None:
        if not (0 < self.word_mm <= MAX_SHIFT_MM and 0 < self.row_mm <= MAX_SHIFT_MM):
            raise ValueError(f"besar geser harus di antara 0 dan {MAX_SHIFT_MM} mm")

    @property
    def word_pt(self) -> float:
        """Horizontal shift in points."""
        return self.word_mm * MM_TO_PT

    @property
    def row_pt(self) -> float:
        """Vertical shift in points."""
        return self.row_mm * MM_TO_PT


def eligible_rows(layout: DocumentLayout, page: int, excluded: set[RowId]) -> list[Row]:
    """Rows of a page that take part in row alternation (enough glyphs, not excluded)."""
    rows = []
    for row in layout.pages[page].rows:
        if row.id in excluded:
            continue
        if sum(len(w.glyphs) for w in row.words) < MIN_ROW_GLYPHS:
            continue
        rows.append(row)
    return rows


def data_groups(row: Row) -> list[int]:
    """Indices of data groups in a row: odd indices that have a right neighbour."""
    return [g for g in range(1, len(row.groups) - 1, 2)]


def shift_slot_refs(
    layout: DocumentLayout, excluded: set[RowId], late_pages: frozenset[int] | set[int] = frozenset()
) -> list[tuple[int, tuple[int, ...], int]]:
    """(page, ref, n_bits) for every data unit, in reading order.

    Word slots have ref (row, group); row slots have ref (row,). One bit each. Pages in
    ``late_pages`` (scanned pages, whose rows come from OCR word boxes) follow all other
    pages, so the code positions of text pages never depend on the boxes; without them the
    order is the original reading order.
    """
    refs: list[tuple[int, tuple[int, ...], int]] = []
    order = [p for p in layout.pages if p.index not in late_pages] + [p for p in layout.pages if p.index in late_pages]
    for page in order:
        rows = eligible_rows(layout, page.index, excluded)
        for row in rows:
            for g in data_groups(row):
                refs.append((page.index, (row.index, g), 1))
        for k in range(1, len(rows) - 1, 2):
            refs.append((page.index, (rows[k].index,), 1))
    return refs


def build_shift_slots(
    layout: DocumentLayout, m: int, key: bytes, excluded: set[RowId] | None = None,
    late_pages: frozenset[int] | set[int] = frozenset(),
) -> list[Slot]:
    """Slots of channel 1 with their code positions (``late_pages``: see shift_slot_refs)."""
    return assign_positions(CHANNEL_SHIFT, shift_slot_refs(layout, excluded or set(), late_pages), m, key)


def carried_sign(bit: int, whiten: int) -> int:
    """Physical direction (+1 or -1) that encodes ``bit`` under whitening bit ``whiten``."""
    return (2 * int(bit) - 1) * (1 - 2 * int(whiten))


def shift_marks(
    plan: EmbeddingPlan, codeword: np.ndarray, settings: ShiftSettings
) -> tuple[dict[GroupId, float], dict[RowId, float]]:
    """Per-copy offsets: horizontal for data groups, vertical for data rows (points)."""
    group_dx: dict[GroupId, float] = {}
    row_dy: dict[RowId, float] = {}
    for slot in plan.channel(CHANNEL_SHIFT):
        sign = carried_sign(codeword[slot.positions[0]], slot.whiten[0])
        if len(slot.ref) == 2:
            group_dx[(slot.page, slot.ref[0], slot.ref[1])] = sign * settings.word_pt
        else:
            row_dy[(slot.page, slot.ref[0])] = sign * settings.row_pt
    return group_dx, row_dy


def relative_offset(
    pos_left: float, d_left: float, pos_data: float, d_data: float, pos_right: float, d_right: float
) -> float:
    """r = d_data minus the line through the two control neighbours, at the data position."""
    if pos_right == pos_left:
        ref = 0.5 * (d_left + d_right)
    else:
        t = (pos_data - pos_left) / (pos_right - pos_left)
        ref = d_left + t * (d_right - d_left)
    return d_data - ref
