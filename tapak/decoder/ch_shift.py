"""Decoder for channel 1 (word-group and line shifts).

The channel decoder works on *displacements*: for every master word, how far it sits from
its master position in the leaked copy (dx, dy in points). Where the displacements come
from depends on the input:

* a forwarded PDF: glyph origins read straight from the file (``measure_vector``);
* a photo or screenshot: sub-pixel template matching after rectification (M3).

From displacements, each data unit is compared with the line through its two control
neighbours (see ``marker/pdf_shift.py``), giving s = (2*bit - 1) * delta + noise. The noise
level sigma is estimated from the data with a two-component EM fit, then
LLR = 2 * delta * s / sigma^2.
"""

from __future__ import annotations

import difflib

import cv2
import numpy as np

from tapak.decoder.softbits import SoftBits, gaussian_llr
from tapak.marker.layout import DocumentLayout, RowId, WordId, extract_layout
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_shift import ShiftSettings, eligible_rows, relative_offset
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.plan import CHANNEL_SHIFT, EmbeddingPlan

Displacements = dict[WordId, tuple[float, float]]
OUTLIER_FACTOR = 3.0


def estimate_sigma(s: np.ndarray, delta: float, floor: float, iters: int = 30) -> float:
    """Noise std of s ~ 0.5 N(+delta, sigma^2) + 0.5 N(-delta, sigma^2), by EM."""
    s = np.asarray(s, dtype=np.float64)
    if s.size == 0:
        return max(delta, floor)
    sigma = max(delta, floor)
    for _ in range(iters):
        z = np.clip(2.0 * delta * s / (sigma * sigma), -50.0, 50.0)
        p1 = 1.0 / (1.0 + np.exp(-z))
        var = np.mean(p1 * (s - delta) ** 2 + (1.0 - p1) * (s + delta) ** 2)
        sigma = max(float(np.sqrt(var)), floor)
    return sigma


def _group_displacement(layout: DocumentLayout, disp: Displacements, page: int, row: int,
                        g: int) -> tuple[float, float] | None:
    r = layout.pages[page].rows[row]
    group = r.groups[g]
    vals = [disp[r.words[i].id][0] for i in group.word_indices if r.words[i].id in disp]
    if not vals:
        return None
    centre = 0.5 * (group.bbox[0] + group.bbox[2])
    return centre, float(np.mean(vals))


def row_slope(layout: DocumentLayout, disp: Displacements, page: int) -> float:
    """Shared slope of dy against x within rows (residual rotation or shear).

    Row offsets (including the +/-delta of data rows) are removed by centring each row, so
    only the common tilt remains: b = sum(xc * dyc) / sum(xc^2).
    """
    num = den = 0.0
    for r in layout.pages[page].rows:
        pts = [(w.glyphs[0].x, disp[w.id][1]) for w in r.words if w.id in disp]
        if len(pts) < 2:
            continue
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        xc, yc = xs - xs.mean(), ys - ys.mean()
        num += float(np.sum(xc * yc))
        den += float(np.sum(xc * xc))
    return num / den if den > 0 else 0.0


def _row_displacement(layout: DocumentLayout, disp: Displacements, rid: RowId,
                      slope: float, x_ref: float) -> tuple[float, float] | None:
    """Vertical displacement of a row evaluated at x_ref after removing the shared tilt."""
    r = layout.row(rid)
    vals = [disp[w.id][1] - slope * (w.glyphs[0].x - x_ref) for w in r.words if w.id in disp]
    if not vals:
        return None
    return r.baseline, float(np.median(vals))


def signed_measurements(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    excluded: set[RowId] | None = None,
) -> tuple[list[int], list[float], list[str]]:
    """(positions, s values, unit kind) for every readable shift slot.

    s is the relative offset multiplied by the whitening sign, so s > 0 means bit 1.
    """
    layout = master.layout
    excluded = excluded or set()
    eligible = {p.index: eligible_rows(layout, p.index, excluded) for p in layout.pages}
    row_rank = {(p, r.index): k for p, rows in eligible.items() for k, r in enumerate(rows)}
    slopes = {p.index: row_slope(layout, disp, p.index) for p in layout.pages}
    pos: list[int] = []
    vals: list[float] = []
    kinds: list[str] = []
    for slot in plan.channel(CHANNEL_SHIFT):
        if len(slot.ref) == 2:
            row, g = slot.ref
            trip = [_group_displacement(layout, disp, slot.page, row, k) for k in (g - 1, g, g + 1)]
            kind = "kata"
        else:
            k = row_rank.get((slot.page, slot.ref[0]))
            if k is None or k == 0 or k + 1 >= len(eligible[slot.page]):
                continue
            rows = eligible[slot.page]
            x_ref = 0.5 * layout.pages[slot.page].width
            trip = [_row_displacement(layout, disp, rows[j].id, slopes[slot.page], x_ref)
                    for j in (k - 1, k, k + 1)]
            kind = "baris"
        if any(t is None for t in trip):
            continue
        (pl, dl), (pd, dd), (pr, dr) = trip  # type: ignore[misc]
        r = relative_offset(pl, dl, pd, dd, pr, dr)
        pos.append(slot.positions[0])
        vals.append(r * (1 - 2 * slot.whiten[0]))
        kinds.append(kind)
    return pos, vals, kinds


def decode_displacements(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None = None,
    sigma_floor_ratio: float = 0.05,
) -> SoftBits:
    """Soft bits of channel 1 from per-word displacements."""
    pos, vals, kinds = signed_measurements(master, plan, disp, excluded)
    if not pos:
        return SoftBits.empty(CHANNEL_SHIFT, slots_total=len(plan.channel(CHANNEL_SHIFT)))
    s = np.array(vals)
    kinds_arr = np.array(kinds)
    llr = np.zeros_like(s)
    sigmas = {}
    implausible = 0
    for kind, delta in (("kata", settings.word_pt), ("baris", settings.row_pt)):
        sel = kinds_arr == kind
        # A genuine mark moves a unit by +/-delta; a relative offset beyond 3 delta means the
        # matcher slipped (blur, a stain). Such units are unreadable, not evidence, and are
        # kept out of the noise estimate so they cannot silence the whole channel.
        sane = sel & (np.abs(s) <= OUTLIER_FACTOR * delta)
        implausible += int(sel.sum() - sane.sum())
        if not sane.any():
            continue
        sigma = estimate_sigma(s[sane], delta, floor=sigma_floor_ratio * delta)
        sigmas[kind] = sigma
        llr[sane] = gaussian_llr(s[sane], delta, sigma)
    keep = llr != 0
    s, llr, kinds_arr = s[keep], llr[keep], kinds_arr[keep]
    pos = [q for q, k in zip(pos, keep) if k]
    agree = float(np.mean(np.abs(s) > 0.5 * min(settings.word_pt, settings.row_pt))) if len(s) else 0.0
    return SoftBits(
        CHANNEL_SHIFT,
        np.array(pos, dtype=np.int64),
        llr,
        {"slots_read": len(pos), "slots_total": len(plan.channel(CHANNEL_SHIFT)),
         "slots_implausible": implausible, "sigma_pt": sigmas, "fraction_clear": agree},
    )


def match_words(master_layout: DocumentLayout, leaked_layout: DocumentLayout) -> Displacements:
    """Displacement of every master word found in a leaked *PDF* layout (same page order)."""
    disp: Displacements = {}
    for mp, lp in zip(master_layout.pages, leaked_layout.pages):
        mw = [w for r in mp.rows for w in r.words]
        lw = [w for r in lp.rows for w in r.words]
        sm = difflib.SequenceMatcher(None, [w.text for w in mw],
                                     [normalize_text(w.text) for w in lw], autojunk=False)
        for b in sm.get_matching_blocks():
            for k in range(b.size):
                a, c = mw[b.a + k], lw[b.b + k]
                disp[a.id] = (c.glyphs[0].x - a.glyphs[0].x, c.glyphs[0].y - a.glyphs[0].y)
    return disp


def measure_vector(pdf_bytes: bytes, master: MasterDocument) -> Displacements:
    """Displacements read from the glyph origins of a leaked PDF file."""
    return match_words(master.layout, extract_layout(pdf_bytes))


def decode_vector(
    pdf_bytes: bytes,
    master: MasterDocument,
    plan: EmbeddingPlan,
    settings: ShiftSettings,
    excluded: set[RowId] | None = None,
) -> SoftBits:
    """Channel 1 soft bits from a forwarded PDF (exact digital readout)."""
    return decode_displacements(master, plan, measure_vector(pdf_bytes, master), settings, excluded)


ECC_TRANSLATION = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)


def _parabolic(c_m: float, c_0: float, c_p: float) -> float:
    """Sub-sample offset of a peak from three samples around it."""
    den = c_m - 2.0 * c_0 + c_p
    return 0.0 if den >= 0 else 0.5 * (c_m - c_p) / den


def match_offset(tmpl: np.ndarray, win: np.ndarray, m: int) -> tuple[float, float, float] | None:
    """(dx, dy, peak correlation) of ``tmpl`` inside ``win`` (``win`` is larger by m on each side).

    An exhaustive normalized cross-correlation over every integer offset finds the right
    peak even on blurry, repetitive text, where a local optimizer can lock onto a wrong
    character; a parabola through the neighbours gives the sub-pixel part, and ECC then
    polishes from there (kept only if it stays within half a pixel).
    """
    res = cv2.matchTemplate(win, tmpl, cv2.TM_CCOEFF_NORMED)
    _, peak, _, (ix, iy) = cv2.minMaxLoc(res)
    if not (0 < ix < res.shape[1] - 1 and 0 < iy < res.shape[0] - 1):
        return None
    fx = ix + _parabolic(res[iy, ix - 1], res[iy, ix], res[iy, ix + 1])
    fy = iy + _parabolic(res[iy - 1, ix], res[iy, ix], res[iy + 1, ix])
    warp = np.array([[1, 0, fx], [0, 1, fy]], dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(tmpl, win, warp, cv2.MOTION_TRANSLATION, ECC_TRANSLATION, None, 1)
        if abs(warp[0, 2] - fx) <= 0.5 and abs(warp[1, 2] - fy) <= 0.5:
            fx, fy = float(warp[0, 2]), float(warp[1, 2])
    except cv2.error:
        pass
    return fx - m, fy - m, float(peak)


def measure_image(
    rectified: np.ndarray,
    valid: np.ndarray,
    master_render: np.ndarray,
    master: MasterDocument,
    page: int,
    dpi: float,
    search_px: int = 5,
    pad_px: int = 3,
    min_peak: float = 0.6,
) -> Displacements:
    """Displacement of every shift group on a rectified page image.

    For each group the template is the master render around the group's box and the search
    window is the same box in the evidence, enlarged by ``search_px``; see
    :func:`match_offset`. Matches with a weak correlation peak are discarded. All words of a
    group get the group's displacement (in points).
    """
    s = dpi / 72.0
    disp: Displacements = {}
    h, w = rectified.shape
    tmpl_all = cv2.GaussianBlur(master_render.astype(np.float32), (0, 0), 0.7)
    img_all = cv2.GaussianBlur(rectified.astype(np.float32), (0, 0), 0.7)
    for row in master.layout.pages[page].rows:
        for g in row.groups:
            x0, y0, x1, y1 = g.bbox
            X0, Y0 = int(np.floor(x0 * s)) - pad_px, int(np.floor(y0 * s)) - pad_px
            X1, Y1 = int(np.ceil(x1 * s)) + pad_px, int(np.ceil(y1 * s)) + pad_px
            m = search_px
            if X0 - m < 0 or Y0 - m < 0 or X1 + m > w or Y1 + m > h:
                continue
            if not valid[Y0 - m:Y1 + m, X0 - m:X1 + m].all():
                continue
            tmpl = tmpl_all[Y0:Y1, X0:X1]
            if float(tmpl.std()) < 10.0:
                continue
            found = match_offset(tmpl, img_all[Y0 - m:Y1 + m, X0 - m:X1 + m], m)
            if found is None or found[2] < min_peak:
                continue
            dx, dy = found[0] / s, found[1] / s
            for wi in g.word_indices:
                disp[row.words[wi].id] = (dx, dy)
    return disp
