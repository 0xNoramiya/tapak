"""Document-level collusion attack aimed at the positions where the colluders' copies agree.

Research and test tool: it is never used by issuance or tracing. It plays a coalition that
knows TAPAK (the code is public; only the keys are secret) and holds two or more copies of a
text PDF. Everything the attack decides is computed from those copies alone:

* Background (channel 2). Every copy carries its pattern as one full-page image under the
  text (``marker.background.background_hook``): base + amplitude * level, upsampled from one
  value per cell. The coalition reads the sign of every cell's level from the centre of the
  cell (``image_cell_levels``) and compares copies. The eight cells of a code position always
  agree or disagree together, so a cell with the same level in every copy belongs to a
  position where the coalition's bits agree. No key is needed: the cell grid itself (2 mm,
  centred on the page) is public.
* Shifts (channel 1). Glyph origins are read from each copy PDF. Data units follow the public
  layout rule of the shift scheme: under geser-v1 odd word groups with a right neighbour and
  odd-ranked eligible rows; under geser-v2 every word group (at least 10 pt wide) of a row
  with at least three groups, and the same rows. A unit at the same place in every copy
  carries agreeing bits; one at two places 2 delta apart carries disagreeing bits, and its
  master position is the midpoint. For an agreeing unit the master position is estimated from
  typography. geser-v1 (``typographic_shift``): in a justified or ragged line the word gaps on
  both sides of a data group are equal in the master, so (left gap - right gap) / 2 is the
  shift; likewise (pitch above - pitch below) / 2 for a data row between two lines of the same
  paragraph. The estimate is rounded to +/- delta, or left undecided when it is not within
  delta / 2 of +/- delta (unequal gaps in the master). geser-v2 (``row_signs``): every group
  of a row moves, so the row is read as a whole. All word gaps of a justified or ragged line
  are equal in the master, and the gap between groups g and g + 1 of a copy is that gap plus
  delta (s[g+1] - s[g]); for every group the sign whose best explanation of the whole row
  (dynamic programming over the signs, every candidate common gap, the signs of disagreeing
  groups fixed) is clearly cheaper than that of the other sign. A gap that no pattern explains
  within delta / 2 (a label or a tab stop) splits the row; a group whose gaps are explained
  both ways (a piece whose groups all moved the same way, a single group after a tab) stays
  undecided unless a disagreeing group anchors it. Rows are read as under geser-v1, with
  their own delta. Under geser-v2 the coalition then anchors what is left on the document as
  a whole (``anchored_sign``): groups that share a column edge in the master (the left margin,
  a list indent, a tab stop, the right margin of justified text) and data rows whose pitches
  recur (lines of a paragraph, paragraph breaks) take the sign that puts them on the master
  edges and pitches of the units already known. The same row anchoring would work under
  geser-v1, whose rows are the same; it is applied under geser-v2 only, so the published
  geser-v1 measurements of ``research/sepakat`` stay reproducible.

The forged evidence (``forge_copy``) takes one copy's place for every unit: at an agreeing
unit the mark is neutralized with probability ``erase_fraction``, either erased (``hapus``:
background cell level 0, data unit moved to its estimated master position) or reversed
(``balik``: the cell's level negated, the data unit moved to the mirror of its position about
the master position, so it carries the other bit at full strength); at a disagreeing unit the
rule picks
the first copy (``salin``), a random member per unit or cell (``acak``) or the average of the
copies (``rata``, which erases the unit when two copies disagree, the classical averaging
attack). The forged PDF is drawn with TAPAK's own renderer from the master with these offsets
and cell levels: the coalition gets the same file by moving copy 1's glyphs and replacing its
background image, and its text layer carries no zero-width symbols or homoglyphs (stripped,
as anyone who knows the text channel would). The master is used only to draw the result,
never to decide anything.

Erasures and reversals that depend on agreement are outside the marking assumption, so the
proven miss bound (``tapak.tardos.detection``) does not cover them; ``research/sepakat``
measures them. A reversal leaves every unit as clearly marked as in an honest copy, so the
erasure check (``decoder/erasure.py``), which looks at how clearly units are read, cannot see
it (``research/sepakat/balik.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymupdf

from tapak.marker.background import BackgroundSettings, PageGrid, pattern_image, png_bytes
from tapak.marker.layout import DocumentLayout, Row, extract_layout, regroup
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_shift import (
    MIN_JOINT_GROUPS,
    MIN_ROW_GLYPHS,
    MM_TO_PT,
    SCHEME_GROUP_WIDTH,
    SCHEME_V1,
    SCHEME_V2,
    SHIFT_SCHEMES,
    V2_MAX_WORD_SHIFT_MM,
)
from tapak.marker.pdf_zerowidth import ZW_CHARS
from tapak.marker.render import CopyMarks, render_copy

RULES = ("salin", "acak", "rata")
CHANNELS = ("latar", "geser")
NEUTRALIZE = ("hapus", "balik")
POSITION_TOLERANCE_PT = 0.01  # glyph origins of copies closer than this count as the same place
ANCHOR_TOLERANCE = 0.25  # geser-v2 anchoring: a master value matches an anchor within this many deltas
MIN_ANCHORS = 2          # ... and needs at least this many anchors (a column edge or a line pitch)
ANCHOR_ROUNDS = 3        # anchoring passes; every decision adds anchors for the next pass
PUBLIC_DELTA_PT = 0.05 * MM_TO_PT  # TAPAK's default shift, used when no disagreeing unit shows it
PUBLIC_V2_WORD_DELTA_PT = V2_MAX_WORD_SHIFT_MM * MM_TO_PT  # geser-v2 word shift, likewise

UnitRef = tuple[int, ...]  # (page, row, group) for a word group, (page, row) for a row


@dataclass
class ShiftUnit:
    """One data unit of the shift channel as the coalition sees it.

    Attributes:
        ref: (page, row, group) for a word group, (page, row) for a row (the master's indices;
            a copy has the same rows and groups as the master).
        kind: "kata" (horizontal) or "baris" (vertical).
        positions: the unit's coordinate (points) in every copy, in copy order.
        typographic: the shift of copy 1 estimated from its own gaps (points), rounded to
            +/- delta, or None when the gaps do not allow it (under geser-v2 also from the
            column edges and line pitches of the units already known, ``anchored_sign``).
    """

    ref: UnitRef
    kind: str
    positions: np.ndarray
    typographic: float | None = None

    @property
    def agree(self) -> bool:
        """True when the unit sits at the same place in every copy."""
        return bool(np.ptp(self.positions) <= POSITION_TOLERANCE_PT)


@dataclass
class CoalitionView:
    """What a coalition extracts from its copies: background cell levels and shift units.

    ``levels[page]`` is an array (copies, ny, nx) of cell levels in amplitude units: exactly
    -1, 0 or +1 for TAPAK's pattern, continuous values for a masked pattern;
    ``agree_prob[page]`` is the probability that a cell's position has the same bit in every
    copy (0 or 1 for TAPAK's pattern, the posterior of ``agreement_posterior`` for a masked
    one); ``backgrounds[page]`` is (base, amplitude, px_per_cell) read from the images.
    ``delta_pt`` is the word shift the coalition uses, ``scheme`` the shift scheme it assumes.
    """

    copies: int
    levels: dict[int, np.ndarray] = field(default_factory=dict)
    agree_prob: dict[int, np.ndarray] = field(default_factory=dict)
    backgrounds: dict[int, tuple[float, float, int]] = field(default_factory=dict)
    units: list[ShiftUnit] = field(default_factory=list)
    delta_pt: float = PUBLIC_DELTA_PT
    scheme: str = SCHEME_V1


@dataclass
class ForgeryPlan:
    """The attack's decisions: forged cell levels per page and moves of copy 1's data units.

    ``moves`` maps a unit ref to the displacement (points) applied to copy 1's position;
    ``backgrounds`` is (base, amplitude, px_per_cell) per page as read from the copies;
    ``counts`` summarizes how many agreeing and disagreeing units and cells were touched.
    """

    levels: dict[int, np.ndarray]
    moves: dict[UnitRef, float]
    counts: dict[str, int]
    backgrounds: dict[int, tuple[float, float, int]] = field(default_factory=dict)


def copy_backgrounds(pdf_bytes: bytes) -> dict[int, np.ndarray]:
    """The background pattern image of every page of a copy (gray uint8), keyed by page.

    The pattern is the largest image drawn on the page; a page without an image (the channel
    was off) is left out.
    """
    out: dict[int, np.ndarray] = {}
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            best = None
            for info in page.get_images(full=True):
                xref = info[0]
                rects = page.get_image_rects(xref)
                area = max((r.width * r.height for r in rects), default=0.0)
                if best is None or area > best[0]:
                    best = (area, xref)
            if best is None:
                continue
            pix = pymupdf.Pixmap(doc, best[1])
            if pix.n - pix.alpha != 1:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0]
            out[page.number] = img.copy()
    return out


def image_cell_levels(img: np.ndarray, px_per_cell: int = 4) -> tuple[np.ndarray, float, float]:
    """(levels, base, amplitude) of a background image: the sign of every cell's level.

    The image is base + amplitude * level, linearly upsampled ``px_per_cell`` times. The mean
    of the central 2 x 2 pixels of a cell weighs the cell itself at least 0.53 of the
    amplitude above its neighbours, so its sign against the base (the image median) is the
    cell's sign exactly; a cell within half a gray level of the base has level 0 (unused).
    """
    k = int(px_per_cell)
    ny, nx = img.shape[0] // k, img.shape[1] // k
    blocks = img[:ny * k, :nx * k].astype(np.float64).reshape(ny, k, nx, k)
    lo, hi = k // 2 - 1, k // 2 + 1
    centre = blocks[:, lo:hi, :, lo:hi].mean(axis=(1, 3))
    base = float(np.median(img))
    dev = centre - base
    levels = np.where(dev > 0.5, 1, np.where(dev < -0.5, -1, 0)).astype(np.int8)
    amplitude = float(np.round(np.percentile(np.abs(img.astype(np.float64) - base), 99.5)))
    return levels, base, max(amplitude, 1.0)


def _upsampling_matrix(n: int, k: int) -> np.ndarray:
    """The (k n, n) matrix of OpenCV's linear upsampling by k (borders replicated)."""
    r = np.zeros((k * n, n))
    for i in range(k * n):
        x = (i + 0.5) / k - 0.5
        x0 = int(np.floor(x))
        f = x - x0
        if x0 < 0:
            x0, f = 0, 0.0
        x1 = min(x0 + 1, n - 1)
        x0 = min(x0, n - 1)
        r[i, x0] += 1.0 - f
        r[i, x1] += f
    return r


def image_cell_values(img: np.ndarray, base: float, amplitude: float, px_per_cell: int = 4) -> np.ndarray:
    """Continuous cell levels (amplitude units) of a background image, by inverting the linear
    upsampling exactly (least squares); the image's rounding to whole gray levels remains as
    an error of at most 0.5 / amplitude per pixel."""
    k = int(px_per_cell)
    ny, nx = img.shape[0] // k, img.shape[1] // k
    m = (img[:ny * k, :nx * k].astype(np.float64) - base) / amplitude
    ry, rx = np.linalg.pinv(_upsampling_matrix(ny, k)), np.linalg.pinv(_upsampling_matrix(nx, k))
    return ry @ m @ rx.T


def agreement_posterior(values: np.ndarray, ratio: float, quant: float = 0.15) -> np.ndarray:
    """P(every copy carries the same bit | the copies' values of one cell), per cell.

    Model of a masked pattern: copy j shows pn (s_j + e_j) with s_j = +/-1 and e_j uniform on
    [-ratio, ratio], independent across copies; ``quant`` is the spread of the reading error
    (image rounding). The keyed sign pn is unknown, so both signs are averaged. Prior over the
    bit patterns: the code's arcsine bias law, E[p^z (1-p)^(k-z)] for a pattern with z ones.
    ``values`` is (copies, ...); the result has the shape of one copy.
    """
    from itertools import product
    from math import lgamma, pi

    from scipy.special import ndtr

    k = values.shape[0]

    def dens(e: np.ndarray) -> np.ndarray:
        return (ndtr((ratio - e) / quant) - ndtr((-ratio - e) / quant)) / (2.0 * ratio)

    def prior(z: int) -> float:  # E[p^z (1-p)^(k-z)] = B(z + 1/2, k - z + 1/2) / B(1/2, 1/2)
        return float(np.exp(lgamma(z + 0.5) + lgamma(k - z + 0.5) - lgamma(k + 1.0)) / pi)

    same = np.zeros(values.shape[1:])
    total = np.zeros(values.shape[1:])
    for signs in product((-1.0, 1.0), repeat=k):
        s = np.array(signs).reshape((k,) + (1,) * (values.ndim - 1))
        like = 0.5 * (np.prod(dens(values - s), axis=0) + np.prod(dens(values + s), axis=0))
        w = prior(int(np.sum(np.array(signs) > 0))) * like
        total += w
        if len(set(signs)) == 1:
            same += w
    return np.where(total > 0, same / np.maximum(total, 1e-300), 1.0)


def _clean_words(row: Row) -> list[tuple[float, float]]:
    """(x0, x1) of every word of a row without zero-width glyphs (the coalition strips them)."""
    out = []
    for w in row.words:
        gs = [g for g in w.glyphs if g.char not in ZW_CHARS]
        if not gs:
            gs = w.glyphs
        out.append((gs[0].x, gs[-1].x + gs[-1].advance))
    return out


def _eligible(layout: DocumentLayout, page: int) -> list[Row]:
    """Rows of a page that the public rule makes eligible for row shifts (zero-width glyphs
    stripped; rows excluded at issuance, such as semantic rows, are unknown to the coalition)."""
    return [r for r in layout.pages[page].rows
            if sum(1 for w in r.words for g in w.glyphs if g.char not in ZW_CHARS) >= MIN_ROW_GLYPHS]


def typographic_shift(gap_before: float, gap_after: float, delta: float) -> float | None:
    """Shift of a data unit read from its two gaps: (before - after) / 2 rounded to +/- delta,
    or None unless it lies within delta / 2 of +/- delta (the master's gaps were not equal)."""
    s = 0.5 * (gap_before - gap_after)
    if abs(abs(s) - delta) <= 0.5 * delta:
        return float(np.sign(s) * delta)
    return None


def row_signs(gaps: np.ndarray, delta: float, known: list[int | None] | None = None,
              tol: float = 0.5) -> list[int | None]:
    """Shift sign (+1 or -1) of every group of a geser-v2 row read from its word gaps, or None.

    ``gaps`` holds the n - 1 gaps (points) between consecutive groups of one copy. In the
    master all gaps of the row are equal (G0), so gap g is G0 + delta (s[g+1] - s[g]). The cost
    of signs s and a common gap G0 is the sum over the gaps of the squared residual, at most
    (``tol`` * delta)^2 per gap: a gap no pattern explains (a label, a tab stop) costs that
    whatever the signs, so it splits the row. For every candidate G0 (a gap plus -2, 0 or +2
    delta) a forward and a backward dynamic programme give, for every group and sign, the
    lowest cost of the whole row with that group at that sign; the ``known`` signs
    (disagreeing groups; None where unknown) are fixed. A group is decided when one sign costs
    at least half a capped gap less than the other over all G0; otherwise (the same gaps
    explained both ways, such as a piece whose groups all moved the same way, which cannot be
    told from the same piece moved the other way) it is None.
    """
    gaps = np.asarray(gaps, dtype=np.float64).reshape(-1)
    n = gaps.size + 1
    known = list(known) if known is not None else [None] * n
    if len(known) != n:
        raise ValueError("satu tanda diketahui (atau None) per kelompok")
    signs = (-1, 1)
    allowed = [np.array([k is None or k == sg for sg in signs]) for k in known]
    cap = (tol * delta) ** 2
    best = np.where(np.array(allowed), 0.0, np.inf) if n == 1 else np.full((n, 2), np.inf)
    for g0 in sorted({float(g + 2.0 * delta * k) for g in gaps for k in (-1, 0, 1)}):
        # step[i][t, s]: cost of gap i between group i at sign t and group i + 1 at sign s
        step = [np.minimum((gap - g0 - delta * (np.array(signs)[None, :] - np.array(signs)[:, None])) ** 2, cap)
                for gap in gaps]
        fwd = np.full((n, 2), np.inf)
        fwd[0] = np.where(allowed[0], 0.0, np.inf)
        for i in range(1, n):
            fwd[i] = np.where(allowed[i], np.min(fwd[i - 1][:, None] + step[i - 1], axis=0), np.inf)
        bwd = np.full((n, 2), np.inf)
        bwd[n - 1] = np.where(allowed[n - 1], 0.0, np.inf)
        for i in range(n - 2, -1, -1):
            bwd[i] = np.where(allowed[i], np.min(step[i] + bwd[i + 1][None, :], axis=1), np.inf)
        best = np.minimum(best, fwd + bwd)
    out: list[int | None] = []
    for lo, hi in best:
        if np.isfinite(min(lo, hi)) and abs(lo - hi) > 0.5 * cap:
            out.append(-1 if lo < hi else 1)
        else:
            out.append(None)
    return out


def shift_units(layouts: list[DocumentLayout], delta: float | None = None,
                scheme: str = SCHEME_V1) -> tuple[list[ShiftUnit], float]:
    """Data units of the shift channel seen in the copies, and the word delta the coalition uses.

    Units come from the public layout rule of ``scheme`` on the first copy's rows and groups
    (copies have the master's rows and groups; under geser-v2 the layouts are first regrouped
    in place to the scheme's group width). Under geser-v1 delta is half the median spread of
    the disagreeing units (TAPAK's default when no unit disagrees) unless given, for words and
    rows alike. Under geser-v2 words and rows each get half the median spread of their own
    disagreeing units (the public 0.025 mm and 0.05 mm when none disagrees), and ``delta``
    overrides the word delta only; agreeing units the row-wise estimate leaves undecided are
    then anchored on column edges and line pitches (``anchored_sign``).
    """
    if scheme not in SHIFT_SCHEMES:
        raise ValueError(f"skema geser tidak dikenal: {scheme!r}")
    v2 = scheme == SCHEME_V2
    if v2:
        for lay in layouts:
            regroup(lay, SCHEME_GROUP_WIDTH[SCHEME_V2])
    first = layouts[0]
    units: list[ShiftUnit] = []
    for page in first.pages:
        pi = page.index
        for row in page.rows:
            if v2:
                groups = range(len(row.groups)) if len(row.groups) >= MIN_JOINT_GROUPS else range(0)
            else:
                groups = range(1, len(row.groups) - 1, 2)
            for g in groups:
                xs = []
                for lay in layouts:
                    r = lay.pages[pi].rows[row.index]
                    words = _clean_words(r)
                    xs.append(float(np.mean([words[i][0] for i in r.groups[g].word_indices])))
                units.append(ShiftUnit((pi, row.index, g), "kata", np.array(xs)))
        rows = _eligible(first, pi)
        for k in range(1, len(rows) - 1, 2):
            ys = [lay.pages[pi].rows[rows[k].index].baseline for lay in layouts]
            units.append(ShiftUnit((pi, rows[k].index), "baris", np.array(ys, dtype=np.float64)))
    if not v2:
        spreads = [float(np.ptp(u.positions)) for u in units if not u.agree]
        if delta is None:
            delta = 0.5 * float(np.median(spreads)) if spreads else PUBLIC_DELTA_PT
        for u in units:
            u.typographic = _typography(first, u, delta)
        return units, delta
    word_delta = delta if delta is not None else _kind_delta(units, "kata", PUBLIC_V2_WORD_DELTA_PT)
    row_delta = _kind_delta(units, "baris", PUBLIC_DELTA_PT)
    for u in units:
        if u.kind == "baris":
            u.typographic = _typography(first, u, row_delta)
    word_units = [u for u in units if u.kind == "kata"]
    _v2_typography(first, word_units, word_delta)
    _anchor_words(first, word_units, word_delta)
    _anchor_rows(first, [u for u in units if u.kind == "baris"], row_delta)
    return units, word_delta


def _kind_delta(units: list[ShiftUnit], kind: str, default: float) -> float:
    """Half the median spread of the disagreeing units of one kind (``default`` without any)."""
    spreads = [float(np.ptp(u.positions)) for u in units if u.kind == kind and not u.agree]
    return 0.5 * float(np.median(spreads)) if spreads else default


def _v2_typography(layout: DocumentLayout, units: list[ShiftUnit], delta: float) -> None:
    """Typographic estimates of geser-v2 word units, row by row (``row_signs``): copy 1's shift
    of every decided group, +/- delta. Disagreeing groups enter with copy 1's known sign."""
    by_row: dict[tuple[int, int], list[ShiftUnit]] = {}
    for u in units:
        by_row.setdefault((u.ref[0], u.ref[1]), []).append(u)
    for (pi, ri), row_units in by_row.items():
        row = layout.pages[pi].rows[ri]
        words = _clean_words(row)
        row_units.sort(key=lambda u: u.ref[2])
        gaps = np.array([words[row.groups[g + 1].word_indices[0]][0] - words[row.groups[g].word_indices[-1]][1]
                         for g in range(len(row.groups) - 1)])
        known: list[int | None] = []
        for u in row_units:
            if u.agree:
                known.append(None)
            else:
                mid = 0.5 * (float(u.positions.min()) + float(u.positions.max()))
                known.append(1 if u.positions[0] > mid else -1)
        for u, sign in zip(row_units, row_signs(gaps, delta, known)):
            u.typographic = None if sign is None else float(sign * delta)


def anchored_sign(readings: list[tuple[float, int, np.ndarray]], delta: float,
                  tol: float = ANCHOR_TOLERANCE, min_anchors: int = MIN_ANCHORS) -> int | None:
    """Shift sign (+1 or -1) of one unit from master values it shares with other units, or None.

    Each reading is (value in copy 1, direction, anchors): moving the unit by s * delta changes
    the value by direction * s * delta, so its master value is value - direction * s * delta,
    and ``anchors`` are master values of units whose shift is known (the left edges of the
    groups of one text column, a line pitch). A sign scores one point per reading whose master
    value lies within ``tol`` * delta of at least ``min_anchors`` anchors; the sign with more
    points is returned, None on a tie (no anchor, or both signs fit).
    """
    if delta <= 0:
        raise ValueError("delta harus positif")
    score = {}
    for sign in (-1, 1):
        score[sign] = 0
        for value, direction, anchors in readings:
            master = value - direction * sign * delta
            score[sign] += int(np.count_nonzero(np.abs(np.asarray(anchors, dtype=np.float64) - master)
                                                <= tol * delta) >= min_anchors)
    if score[1] == score[-1]:
        return None
    return 1 if score[1] > score[-1] else -1


def _known_shift(u: ShiftUnit) -> float | None:
    """Copy 1's shift of a unit as the coalition knows it: from the spread of a disagreeing
    unit, the typographic estimate of an agreeing one (None while undecided)."""
    if u.agree:
        return u.typographic
    mid = 0.5 * (float(u.positions.min()) + float(u.positions.max()))
    return float(u.positions[0]) - mid


def _group_edges(layout: DocumentLayout, ref: UnitRef) -> tuple[float, float]:
    row = layout.pages[ref[0]].rows[ref[1]]
    words = _clean_words(row)
    group = row.groups[ref[2]]
    return words[group.word_indices[0]][0], words[group.word_indices[-1]][1]


def _anchor_words(layout: DocumentLayout, units: list[ShiftUnit], delta: float) -> None:
    """Decide undecided geser-v2 word groups from the text's columns (``anchored_sign``).

    In the master many groups share a left edge (the left margin, a list indent, the tab stop
    after a label) or a right edge (the right margin of justified text). The master edges of
    every group whose shift is known are the anchors; an undecided group whose edges fit them
    for one sign only gets that sign, and ``row_signs`` carries it through its piece of the row
    (the groups its gaps tie to it). Repeated, since every decision adds anchors.
    """
    by_row: dict[tuple[int, int], list[ShiftUnit]] = {}
    for u in units:
        by_row.setdefault((u.ref[0], u.ref[1]), []).append(u)
    for _ in range(ANCHOR_ROUNDS):
        lefts, rights = [], []
        for u in units:
            shift = _known_shift(u)
            if shift is not None:
                left, right = _group_edges(layout, u.ref)
                lefts.append(left - shift)
                rights.append(right - shift)
        anchors = (np.array(lefts), np.array(rights))
        changed = False
        for (pi, ri), row_units in by_row.items():
            if not any(u.agree and u.typographic is None for u in row_units):
                continue
            row_units.sort(key=lambda u: u.ref[2])
            known: list[int | None] = []
            for u in row_units:
                shift = _known_shift(u)
                if shift is not None:
                    known.append(1 if shift > 0 else -1)
                    continue
                left, right = _group_edges(layout, u.ref)
                known.append(anchored_sign([(left, 1, anchors[0]), (right, 1, anchors[1])], delta))
            if all(k is None for k, u in zip(known, row_units) if u.agree and u.typographic is None):
                continue
            row = layout.pages[pi].rows[ri]
            words = _clean_words(row)
            gaps = np.array([words[row.groups[g + 1].word_indices[0]][0] - words[row.groups[g].word_indices[-1]][1]
                             for g in range(len(row.groups) - 1)])
            for u, sign in zip(row_units, row_signs(gaps, delta, known)):
                if u.agree and u.typographic is None and sign is not None:
                    u.typographic = float(sign * delta)
                    changed = True
        if not changed:
            return


def _anchor_rows(layout: DocumentLayout, units: list[ShiftUnit], delta: float) -> None:
    """Decide undecided data rows from the document's line pitches (``anchored_sign``).

    A data row sits between two rows that do not move, so its pitch above is the master pitch
    plus its shift and its pitch below the master pitch minus it. The few pitches of a
    document (lines of a paragraph, paragraph breaks, headings) recur, so the master pitches of
    the rows whose shift is known are the anchors; a row whose two pitches fit them for one
    sign only gets that sign. Repeated, since every decision adds anchors.
    """
    pitches_of: dict[UnitRef, tuple[float, float]] = {}
    for u in units:
        rows = _eligible(layout, u.ref[0])
        k = next(i for i, r in enumerate(rows) if r.index == u.ref[1])
        pitches_of[u.ref] = (rows[k].baseline - rows[k - 1].baseline, rows[k + 1].baseline - rows[k].baseline)
    for _ in range(ANCHOR_ROUNDS):
        anchors = []
        for u in units:
            shift = _known_shift(u)
            if shift is not None:
                above, below = pitches_of[u.ref]
                anchors += [above - shift, below + shift]
        pitches = np.array(anchors)
        changed = False
        for u in units:
            if u.agree and u.typographic is None:
                above, below = pitches_of[u.ref]
                sign = anchored_sign([(above, 1, pitches), (below, -1, pitches)], delta)
                if sign is not None:
                    u.typographic = float(sign * delta)
                    changed = True
        if not changed:
            return


def _typography(layout: DocumentLayout, unit: ShiftUnit, delta: float) -> float | None:
    pi = unit.ref[0]
    if unit.kind == "kata":
        row = layout.pages[pi].rows[unit.ref[1]]
        g = unit.ref[2]
        words = _clean_words(row)
        left = words[row.groups[g].word_indices[0]][0] - words[row.groups[g - 1].word_indices[-1]][1]
        right = words[row.groups[g + 1].word_indices[0]][0] - words[row.groups[g].word_indices[-1]][1]
        return typographic_shift(left, right, delta)
    rows = _eligible(layout, pi)
    k = next(i for i, r in enumerate(rows) if r.index == unit.ref[1])
    above = rows[k].baseline - rows[k - 1].baseline
    below = rows[k + 1].baseline - rows[k].baseline
    return typographic_shift(above, below, delta)


def coalition_view(copy_pdfs: list[bytes], delta: float | None = None,
                   mask: tuple[float, float, float] | None = None, scheme: str = SCHEME_V1) -> CoalitionView:
    """Background cell levels and shift units of a coalition's copies (at least two).

    ``mask`` = (base, amplitude, ratio) are the public parameters of a masked pattern
    (``research/sepakat/samaran.py``): the cell values are then read continuously and the
    agreement of every cell is the posterior of ``agreement_posterior``. Without it the cells
    are read exactly as -1, 0, +1 and agree when equal in every copy. ``scheme`` is the shift
    scheme the coalition assumes (``shift_units``).
    """
    if len(copy_pdfs) < 2:
        raise ValueError("koalisi memerlukan sedikitnya dua salinan")
    view = CoalitionView(copies=len(copy_pdfs), scheme=scheme)
    images = [copy_backgrounds(pdf) for pdf in copy_pdfs]
    for page in sorted(set.intersection(*(set(i) for i in images))):
        if mask is None:
            parsed = [image_cell_levels(i[page]) for i in images]
            stack = np.stack([p[0] for p in parsed]).astype(np.float64)
            view.levels[page] = stack
            view.agree_prob[page] = np.all(stack == stack[:1], axis=0).astype(np.float64)
            view.backgrounds[page] = (parsed[0][1], parsed[0][2], 4)
        else:
            base, amplitude, ratio = mask
            stack = np.stack([image_cell_values(i[page], base, amplitude) for i in images])
            view.levels[page] = stack
            view.agree_prob[page] = agreement_posterior(stack, ratio, quant=0.3 / amplitude)
            view.backgrounds[page] = (base, amplitude, 4)
    view.units, view.delta_pt = shift_units([extract_layout(pdf) for pdf in copy_pdfs], delta, scheme)
    return view


def plan_forgery(view: CoalitionView, rule: str = "acak", erase_fraction: float = 1.0,
                 channels: tuple[str, ...] = CHANNELS, rng: np.random.Generator | None = None,
                 agree_threshold: float = 0.5, neutralize: str = "hapus") -> ForgeryPlan:
    """Decide the forged evidence: neutralize agreeing units, apply ``rule`` at disagreeing ones.

    ``channels`` names the channels whose agreeing units are neutralized ("latar", "geser");
    in the others agreeing units keep copy 1's marks. Each agreeing unit (background cell,
    shift unit with a typographic estimate) is neutralized with probability
    ``erase_fraction``: erased (``neutralize="hapus"``) or reversed (``"balik"``: level
    negated, data unit mirrored about its master position). A background cell counts as
    agreeing when its agreement probability is at least ``agree_threshold`` (always 0 or 1
    for TAPAK's pattern).
    """
    if rule not in RULES:
        raise ValueError(f"aturan tidak dikenal: {rule!r}")
    if not set(channels) <= set(CHANNELS):
        raise ValueError(f"kanal serangan tidak dikenal: {channels!r}")
    if neutralize not in NEUTRALIZE:
        raise ValueError(f"cara menetralkan tidak dikenal: {neutralize!r}")
    reverse = neutralize == "balik"
    rng = rng or np.random.default_rng()
    counts = {k: 0 for k in ("sel_sama", "sel_sama_dihapus", "sel_beda", "unit_sama", "unit_sama_dinetralkan",
                             "unit_sama_tanpa_taksiran", "unit_beda")}
    levels: dict[int, np.ndarray] = {}
    for page, stack in view.levels.items():
        agree = view.agree_prob[page] >= agree_threshold
        out = stack[0].astype(np.float64).copy()
        k = stack.shape[0]
        if rule == "acak":
            pick = rng.integers(0, k, size=out.shape)
            chosen = np.take_along_axis(stack, pick[None], axis=0)[0]
            out = np.where(agree, out, chosen)
        elif rule == "rata":
            out = np.where(agree, out, stack.mean(axis=0))
        used = agree & (stack[0] != 0)
        counts["sel_sama"] += int(used.sum())
        counts["sel_beda"] += int((~agree).sum())
        if "latar" in channels:
            erase = used & (rng.random(out.shape) < erase_fraction)
            out[erase] = -stack[0][erase] if reverse else 0.0
            counts["sel_sama_dihapus"] += int(erase.sum())
        levels[page] = out
    moves: dict[UnitRef, float] = {}
    for u in view.units:
        base = float(u.positions[0])
        if u.agree:
            counts["unit_sama"] += 1
            if u.typographic is None:
                counts["unit_sama_tanpa_taksiran"] += 1
                continue
            if "geser" in channels and rng.random() < erase_fraction:
                moves[u.ref] = (-2.0 if reverse else -1.0) * u.typographic
                counts["unit_sama_dinetralkan"] += 1
            continue
        counts["unit_beda"] += 1
        if rule == "acak":
            moves[u.ref] = float(u.positions[rng.integers(0, len(u.positions))]) - base
        elif rule == "rata":
            moves[u.ref] = float(np.mean(u.positions)) - base
    return ForgeryPlan(levels, moves, counts, dict(view.backgrounds))


def _forged_hook(grids: dict[int, PageGrid], levels: dict[int, np.ndarray]):
    """A page hook that draws the forged background exactly as ``background_hook`` draws a copy's."""

    def hook(doc: pymupdf.Document, page: pymupdf.Page) -> None:
        grid = grids.get(page.number)
        if grid is None or page.number not in levels:
            return
        img = pattern_image(grid, levels[page.number])
        ox, oy = grid.offset_pt
        rect = pymupdf.Rect(ox, oy, ox + grid.nx * grid.cell_pt, oy + grid.ny * grid.cell_pt)
        page.insert_image(rect, stream=png_bytes(img), overlay=False)
        page.draw_rect(page.rect, color=None, fill=(grid.settings.base / 255.0,) * 3, overlay=False)

    return hook


def copy_displacements(pdf_bytes: bytes, master: MasterDocument) -> dict[tuple[int, int, int], tuple[float, float]]:
    """Exact (dx, dy) of every master word in a copy PDF, page by page in the master's frame
    (no fitted scale or offset: a copy is drawn on the master's own coordinates)."""
    from tapak.decoder.ch_shift import PageFrame, match_words

    layout = extract_layout(pdf_bytes)
    frames = {p.index: PageFrame(p.index) for p in layout.pages if p.index < len(master.layout.pages)}
    return match_words(master.layout, layout, frames)


def forge_copy(master: MasterDocument, copy_pdfs: list[bytes], plan: ForgeryPlan,
               cell_mm: float = 2.0) -> bytes:
    """The forged PDF: copy 1 with ``plan`` applied (moves and background), text marks stripped.

    It is drawn from the master with offsets equal to copy 1's own (read exactly from its
    glyph origins) plus the planned moves; the background uses the copies' base, amplitude and
    the public cell grid with the forged levels.
    """
    disp = copy_displacements(copy_pdfs[0], master)
    marks = CopyMarks()
    layout = master.layout
    for page in layout.pages:
        for row in page.rows:
            for group in row.groups:
                dxs = [disp[row.words[i].id][0] for i in group.word_indices if row.words[i].id in disp]
                dx = float(np.median(dxs)) if dxs else 0.0
                dx += plan.moves.get(group.id, 0.0)
                if abs(dx) > 1e-6:
                    marks.group_dx[group.id] = dx
            dys = [disp[w.id][1] for w in row.words if w.id in disp]
            dy = float(np.median(dys)) if dys else 0.0
            dy += plan.moves.get(row.id, 0.0)
            if abs(dy) > 1e-6:
                marks.row_dy[row.id] = dy
    grids: dict[int, PageGrid] = {}
    for page_no, lv in plan.levels.items():
        base, amp, px = plan.backgrounds.get(page_no, (253.0, 2.0, 4))
        p = layout.pages[page_no]
        settings = BackgroundSettings(cell_mm=cell_mm, base=base, amplitude=amp, px_per_cell=px)
        grid = PageGrid(page_no, p.width, p.height, settings, b"")  # geometry only: no key is used
        if (grid.ny, grid.nx) != lv.shape:
            raise ValueError("kisi sel latar salinan tidak cocok dengan halaman induk")
        grids[page_no] = grid
    marks.page_hooks.append(_forged_hook(grids, plan.levels))
    return render_copy(master, marks)


def attack(master: MasterDocument, copy_pdfs: list[bytes], rule: str = "acak", erase_fraction: float = 1.0,
           channels: tuple[str, ...] = CHANNELS, rng: np.random.Generator | None = None,
           mask: tuple[float, float, float] | None = None, agree_threshold: float = 0.5,
           neutralize: str = "hapus", scheme: str | None = None) -> tuple[bytes, CoalitionView, ForgeryPlan]:
    """Coalition view, forgery plan and forged PDF in one call (see the module docstring).

    ``scheme`` is the shift scheme the coalition assumes; None takes the scheme ``master`` is
    grouped for (``issue.apply_shift_scheme``), whose groups ``forge_copy`` draws in any case.
    """
    if scheme is None:
        scheme = SCHEME_V2 if master.group_width == SCHEME_GROUP_WIDTH[SCHEME_V2] else SCHEME_V1
    view = coalition_view(copy_pdfs, mask=mask, scheme=scheme)
    plan = plan_forgery(view, rule, erase_fraction, channels, rng, agree_threshold, neutralize)
    return forge_copy(master, copy_pdfs, plan), view, plan


__all__ = [
    "CHANNELS",
    "NEUTRALIZE",
    "RULES",
    "CoalitionView",
    "ForgeryPlan",
    "ShiftUnit",
    "agreement_posterior",
    "anchored_sign",
    "attack",
    "coalition_view",
    "copy_backgrounds",
    "copy_displacements",
    "forge_copy",
    "image_cell_levels",
    "image_cell_values",
    "plan_forgery",
    "row_signs",
    "shift_units",
    "typographic_shift",
]
