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

Scheme geser-v2 moves every group of a row. A row of g groups is then read as one vector,
d = A theta + delta * s + noise, where A spans the row's nuisance (offset and slope along the
row: whatever affine distortion is left after rectification), s in {-1, +1}^g are the physical
signs and the noise is Gaussian with one sigma per evidence file. Projecting out A (projector
P) removes the nuisance exactly; the likelihood of a sign pattern is then
exp(-|P d - delta P s|^2 / (2 sigma^2)), and the marginal LLR of each sign is computed exactly
by enumerating all 2^g patterns (:func:`row_sign_llrs`; g is at most 11 on the samples and rows
beyond MAX_JOINT_GROUPS are split). Sigma comes from an EM fit over all rows
(:func:`joint_word_llrs`). Before that, a smooth displacement field over the whole page (a
polynomial in the page coordinates, :func:`fit_page_field`) is subtracted from every group: a
photo leaves a bow along the rows after rectification that a per-row line cannot take out, and
one field for the page costs far fewer degrees of freedom than a curvature term in every row.
The field is fitted to the displacements minus the marks the decoder itself expects (the
posterior mean of each sign, zero at first), and refitted FIELD_ROUNDS times
(:func:`joint_decode`), so on a clean copy it does not keep a trace of the marks. Sign patterns that differ by an affine ramp, such as a row whose
groups all moved the same way, look the same and get LLR 0: the decoder never guesses. Like
every channel decoder here this uses only the evidence, the master layout and the code-blind
plan (positions and whitening), never a recipient's codeword.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from tapak.decoder.softbits import SoftBits, gaussian_llr
from tapak.marker.layout import DocumentLayout, RowId, WordId, extract_layout
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_shift import SCHEME_V2, ShiftSettings, eligible_rows, relative_offset
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.plan import CHANNEL_SHIFT, EmbeddingPlan

Displacements = dict[WordId, tuple[float, float]]
OUTLIER_FACTOR = 3.0
JOINT_DEGREE = 1          # geser-v2 row nuisance: polynomial of this degree along the row (offset, slope)
FIELD_DEGREE = 3          # geser-v2 page field: polynomial of this total degree in (x, y), None for none
FIELD_ROUNDS = 3          # fits of the page field, each to the displacements minus the expected marks
MAX_JOINT_GROUPS = 12     # longer rows are decoded in consecutive chunks of at most this many groups
AMBIGUOUS_LLR = 1e-6      # a geser-v2 sign LLR this close to 0 comes from indistinguishable patterns


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
    words: bool = True,
) -> tuple[list[int], list[float], list[str]]:
    """(positions, s values, unit kind) for every readable shift slot of scheme geser-v1.

    s is the relative offset multiplied by the whitening sign, so s > 0 means bit 1. Rows are
    those of ``master.shift_layout``: the text layer, plus the word boxes of scanned pages.
    ``words=False`` leaves the word slots out (geser-v2 reads them jointly, rows the same way).
    """
    layout = master.shift_layout
    excluded = excluded or set()
    eligible = {p.index: eligible_rows(layout, p.index, excluded) for p in layout.pages}
    row_rank = {(p, r.index): k for p, rows in eligible.items() for k, r in enumerate(rows)}
    slopes = {p.index: row_slope(layout, disp, p.index) for p in layout.pages}
    pos: list[int] = []
    vals: list[float] = []
    kinds: list[str] = []
    for slot in plan.channel(CHANNEL_SHIFT):
        if len(slot.ref) == 2:
            if not words:
                continue
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


@lru_cache(maxsize=MAX_JOINT_GROUPS + 1)
def _sign_patterns(g: int) -> np.ndarray:
    """All 2^g sign patterns as a (2^g, g) array of +/-1 (read only)."""
    idx = np.arange(2 ** g)[:, None] >> np.arange(g)[None, :]
    out = np.where(idx & 1, 1.0, -1.0)
    out.setflags(write=False)
    return out


def row_projector(x: np.ndarray, degree: int = JOINT_DEGREE) -> np.ndarray:
    """Projector onto the complement of the polynomials of ``degree`` in ``x`` (positions along a
    row): P d keeps what an offset (degree 0), slope (1) or curvature (2) along the row cannot
    explain. Needs more groups than ``degree + 1``."""
    x = np.asarray(x, dtype=np.float64)
    if x.size <= degree + 1:
        raise ValueError("kelompok terlalu sedikit untuk derajat gangguan ini")
    span = float(np.ptp(x)) or 1.0
    a = np.vander((x - x.mean()) / span, degree + 1)
    q, _ = np.linalg.qr(a)
    return np.eye(x.size) - q @ q.T


def _pattern_residuals(x: np.ndarray, d: np.ndarray, delta: float, degree: int) -> tuple[np.ndarray, np.ndarray]:
    """(patterns, |P d - delta P s|^2 for every pattern s) of one row."""
    p = row_projector(x, degree)
    y = p @ np.asarray(d, dtype=np.float64)
    s = _sign_patterns(len(d))
    quad = np.einsum("ij,jk,ik->i", s, p, s)
    return s, float(y @ y) - 2.0 * delta * (s @ y) + delta * delta * quad


def _logsumexp(v: np.ndarray) -> float:
    top = float(v.max())
    return top + float(np.log(np.exp(v - top).sum()))


def _marginals(s: np.ndarray, ll: np.ndarray) -> np.ndarray:
    """log P(s_g = +1) - log P(s_g = -1) for every column g, from pattern log-likelihoods."""
    return np.array([_logsumexp(ll[s[:, g] > 0]) - _logsumexp(ll[s[:, g] < 0]) for g in range(s.shape[1])])


def row_sign_llrs(x: np.ndarray, d: np.ndarray, delta: float, sigma: float,
                  degree: int = JOINT_DEGREE) -> np.ndarray:
    """Exact marginal LLR log P(s_g = +1 | d) / P(s_g = -1 | d) of every group of one row.

    Model: d = (polynomial of ``degree`` in x) + delta * s + N(0, sigma^2) per group, all sign
    patterns equally likely a priori. The polynomial (the row's nuisance) is projected out and
    the 2^g patterns are enumerated (at most MAX_JOINT_GROUPS groups). Positive means the group
    moved in the + direction; patterns that differ by a polynomial (for example all groups
    moved the same way) cannot be told apart and their signs get LLR 0.
    """
    if sigma <= 0:
        raise ValueError("sigma harus positif")
    if len(d) > MAX_JOINT_GROUPS:
        raise ValueError(f"paling banyak {MAX_JOINT_GROUPS} kelompok per baris")
    s, resid = _pattern_residuals(x, d, delta, degree)
    return _marginals(s, -resid / (2.0 * sigma * sigma))


def _chunks(n: int) -> list[slice]:
    """Consecutive pieces of at most MAX_JOINT_GROUPS of a row of n groups, as equal as possible."""
    k = -(-n // MAX_JOINT_GROUPS)
    edges = np.linspace(0, n, k + 1).round().astype(int)
    return [slice(int(a), int(b)) for a, b in zip(edges, edges[1:])]


def screen_row(x: np.ndarray, d: np.ndarray, delta: float, degree: int = JOINT_DEGREE,
               factor: float = OUTLIER_FACTOR) -> np.ndarray:
    """Mask of the groups of a row kept as readable.

    The best fitting sign pattern and nuisance of the row give a residual per group; divided
    by the group's diagonal entry of the projector this is the group's deleted residual (how
    far it lies from what the other groups predict). A group whose deleted residual exceeds
    ``factor`` * delta is a slipped match and is dropped, one at a time, worst first: a genuine
    mark moves a group by delta, so such a group is unreadable, not evidence. Rows longer than
    MAX_JOINT_GROUPS are screened chunk by chunk.
    """
    x = np.asarray(x, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    keep = np.ones(x.size, dtype=bool)
    for sl in _chunks(x.size) if x.size else []:
        part = np.arange(sl.start, sl.stop)
        while keep[part].sum() > degree + 1:
            idx = part[keep[part]]
            s, resid = _pattern_residuals(x[idx], d[idx], delta, degree)
            best = s[int(np.argmin(resid))]
            p = row_projector(x[idx], degree)
            r = p @ (d[idx] - delta * best)
            deleted = np.abs(r) / np.maximum(np.diag(p), 1e-9)
            worst = int(np.argmax(deleted))
            if deleted[worst] <= factor * delta:
                break
            keep[idx[worst]] = False
    return keep


def joint_word_llrs(rows: list[tuple[np.ndarray, np.ndarray]], delta: float, floor: float,
                    degree: int = JOINT_DEGREE, iters: int = 30) -> tuple[list[np.ndarray], float]:
    """Sign LLRs of geser-v2 word groups, row by row, and the noise sigma fitted by EM.

    ``rows`` holds (x, d) per row: group positions along the row and measured horizontal
    displacements (same unit as ``delta``). Rows longer than MAX_JOINT_GROUPS are split into
    consecutive chunks with their own nuisance; a row or chunk with at most ``degree + 1``
    groups carries no information and gets all-zero LLRs. Sigma (at least ``floor``)
    maximizes the likelihood of all rows together: each EM step averages |P d - delta P s|^2
    over the posterior of the sign patterns and divides by the degrees of freedom left
    (g - degree - 1 per row or chunk).
    """
    pieces: list[tuple[int, slice, np.ndarray, np.ndarray]] = []
    for k, (x, d) in enumerate(rows):
        x = np.asarray(x, dtype=np.float64)
        d = np.asarray(d, dtype=np.float64)
        for sl in _chunks(x.size) if x.size else []:
            if sl.stop - sl.start > degree + 1:
                s, resid = _pattern_residuals(x[sl], d[sl], delta, degree)
                pieces.append((k, sl, s, resid))
    out = [np.zeros(len(x)) for x, _ in rows]
    dof = sum(piece[2].shape[1] - degree - 1 for piece in pieces)
    if not pieces or dof <= 0:
        return out, max(delta, floor)
    sigma = max(delta, floor)
    for _ in range(iters):
        energy = 0.0
        for _, _, _, resid in pieces:
            ll = -resid / (2.0 * sigma * sigma)
            w = np.exp(ll - ll.max())
            energy += float((w * resid).sum() / w.sum())
        sigma = max(float(np.sqrt(max(energy, 0.0) / dof)), floor)
    for k, sl, s, resid in pieces:
        out[k][sl] = _marginals(s, -resid / (2.0 * sigma * sigma))
    return out, sigma


def fit_page_field(x: np.ndarray, y: np.ndarray, d: np.ndarray, degree: int = 3,
                   rounds: int = 3, factor: float = 3.0) -> np.ndarray:
    """Values at (x, y) of a polynomial of total ``degree`` in the page coordinates fitted to the
    displacements ``d`` by least squares, refitted ``rounds`` times without the points beyond
    ``factor`` robust standard deviations (median absolute deviation) of the residual. With
    fewer than four points per coefficient nothing is fitted (zeros)."""
    x, y, d = (np.asarray(v, dtype=np.float64) for v in (x, y, d))
    terms = (degree + 1) * (degree + 2) // 2
    if d.size < 4 * terms:
        return np.zeros(d.size)
    xn = (x - x.mean()) / (float(np.ptp(x)) or 1.0)
    yn = (y - y.mean()) / (float(np.ptp(y)) or 1.0)
    a = np.stack([xn**i * yn**j for i in range(degree + 1) for j in range(degree + 1 - i)], axis=1)
    keep = np.ones(d.size, dtype=bool)
    coef = np.zeros(a.shape[1])
    for _ in range(rounds):
        if keep.sum() < a.shape[1]:
            break
        coef, *_ = np.linalg.lstsq(a[keep], d[keep], rcond=None)
        r = d - a @ coef
        mad = 1.4826 * float(np.median(np.abs(r[keep] - np.median(r[keep]))))
        if mad <= 0:
            break
        keep = np.abs(r) <= factor * mad
    return a @ coef


def _word_units(master: MasterDocument, plan: EmbeddingPlan,
                disp: Displacements) -> dict[tuple[int, int], list[tuple[int, int, float, float]]]:
    """Measured geser-v2 word slots by (page, row): (position, whitening, group centre, dx)."""
    layout = master.shift_layout
    by_row: dict[tuple[int, int], list[tuple[int, int, float, float]]] = {}
    for slot in plan.channel(CHANNEL_SHIFT):
        if len(slot.ref) != 2:
            continue
        row, g = slot.ref
        found = _group_displacement(layout, disp, slot.page, row, g)
        if found is None:
            continue
        by_row.setdefault((slot.page, row), []).append((slot.positions[0], slot.whiten[0], found[0], found[1]))
    return by_row


def joint_measurements(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    delta: float,
    degree: int = JOINT_DEGREE,
    field: dict[int, float] | None = None,
) -> tuple[list[list[tuple[int, int, float, float]]], int]:
    """Readable geser-v2 word slots grouped by row: per row a list of (position, whitening,
    group centre, measured dx minus ``field`` at that position), after :func:`screen_row`; plus
    the number of groups dropped as slipped matches. ``field`` maps code positions to the page
    field to subtract (see :func:`joint_decode`); None subtracts nothing."""
    by_row = _word_units(master, plan, disp)
    if field:
        by_row = {k: [(q, w, xc, dx - field.get(q, 0.0)) for q, w, xc, dx in units] for k, units in by_row.items()}
    rows = []
    dropped = 0
    for units in by_row.values():
        if len(units) <= degree + 1:
            continue
        x = np.array([u[2] for u in units])
        d = np.array([u[3] for u in units])
        keep = screen_row(x, d, delta, degree)
        dropped += int((~keep).sum())
        kept = [u for u, k in zip(units, keep) if k]
        if len(kept) > degree + 1:
            rows.append(kept)
    return rows, dropped


def joint_decode(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    delta: float,
    floor: float,
    degree: int = JOINT_DEGREE,
    field_degree: int | None = FIELD_DEGREE,
    rounds: int = FIELD_ROUNDS,
) -> tuple[list[list[tuple[int, int, float, float]]], list[np.ndarray], float, int]:
    """geser-v2 word groups of an evidence file: (rows of units as in :func:`joint_measurements`,
    their sign LLRs, the fitted noise sigma, groups dropped as slipped matches).

    With ``field_degree`` a page field (:func:`fit_page_field`) is fitted ``rounds`` times, each
    time to the measured displacements minus delta times the posterior mean of every sign from
    the previous decode (zero before the first), and subtracted before decoding. Without it, one
    decode with the per-row nuisance only.
    """
    layout = master.shift_layout
    units = _word_units(master, plan, disp)
    means: dict[int, float] = {}
    field: dict[int, float] | None = None
    for _ in range(max(rounds, 1) if field_degree is not None else 1):
        if field_degree is not None:
            field = {}
            for page in sorted({k[0] for k in units}):
                pts = [(q, xc, layout.pages[page].rows[k[1]].baseline, dx - delta * means.get(q, 0.0))
                       for k, row in units.items() if k[0] == page for q, _, xc, dx in row]
                fit = fit_page_field(np.array([p[1] for p in pts]), np.array([p[2] for p in pts]),
                                     np.array([p[3] for p in pts]), degree=field_degree)
                field.update({p[0]: float(v) for p, v in zip(pts, fit)})
        rows, dropped = joint_measurements(master, plan, disp, delta, degree, field)
        llrs, sigma = joint_word_llrs([(np.array([u[2] for u in r]), np.array([u[3] for u in r])) for r in rows],
                                      delta, floor=floor, degree=degree)
        # Posterior mean of each physical sign (direction of the move).
        means = {u[0]: float(np.tanh(v / 2.0)) for r, rl in zip(rows, llrs) for u, v in zip(r, rl)}
    return rows, llrs, sigma, dropped


def _decode_v2(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None,
    sigma_floor_ratio: float,
    degree: int,
    field_degree: int | None,
) -> SoftBits:
    """Channel 1 soft bits under geser-v2: word groups jointly per row, rows as in geser-v1."""
    delta = settings.word_pt
    rows, llrs, sigma_w, dropped = joint_decode(master, plan, disp, delta, sigma_floor_ratio * delta, degree,
                                                field_degree)
    pos: list[int] = []
    llr: list[float] = []
    for units, row_llr in zip(rows, llrs):
        for (q, white, _, _), v in zip(units, row_llr):
            if abs(v) > AMBIGUOUS_LLR:  # patterns told apart only by rounding: unreadable
                pos.append(q)
                llr.append(float(v) * (1 - 2 * white))
    n_words = len(pos)
    sigmas: dict[str, float] = {"kata": sigma_w} if rows else {}
    rpos, rvals, _ = signed_measurements(master, plan, disp, excluded, words=False)
    implausible = dropped
    if rpos:
        s = np.array(rvals)
        sane = np.abs(s) <= OUTLIER_FACTOR * settings.row_pt
        implausible += int((~sane).sum())
        if sane.any():
            sigma = estimate_sigma(s[sane], settings.row_pt, floor=sigma_floor_ratio * settings.row_pt)
            sigmas["baris"] = sigma
            row_llr = gaussian_llr(s[sane], settings.row_pt, sigma)
            for q, v in zip(np.array(rpos)[sane], row_llr):
                if v != 0.0:
                    pos.append(int(q))
                    llr.append(float(v))
    total = len(plan.channel(CHANNEL_SHIFT))
    if not pos:
        return SoftBits.empty(CHANNEL_SHIFT, slots_total=total, scheme=SCHEME_V2)
    clear = float(np.mean(np.abs(np.array(llr[:n_words])) >= 2.0)) if n_words else 0.0
    return SoftBits(
        CHANNEL_SHIFT,
        np.array(pos, dtype=np.int64),
        np.array(llr),
        {"slots_read": len(pos), "slots_total": total, "slots_implausible": implausible, "sigma_pt": sigmas,
         "fraction_clear": clear, "scheme": SCHEME_V2, "word_slots_read": n_words},
    )


def decode_displacements(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None = None,
    sigma_floor_ratio: float = 0.05,
    joint_degree: int = JOINT_DEGREE,
    field_degree: int | None = FIELD_DEGREE,
) -> SoftBits:
    """Soft bits of channel 1 from per-word displacements, under the scheme of ``settings``
    (geser-v1: relative offsets; geser-v2: word groups read jointly per row after the page field
    of ``field_degree`` is subtracted, ``joint_degree`` being the degree of the row nuisance
    projected out)."""
    if settings.scheme == SCHEME_V2:
        return _decode_v2(master, plan, disp, settings, excluded, sigma_floor_ratio, joint_degree, field_degree)
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


def map_pages(master_layout: DocumentLayout, leaked_layout: DocumentLayout,
              min_ratio: float = 0.5) -> dict[int, int]:
    """Evidence page index -> master page index, by word-sequence similarity.

    A leaked PDF may drop pages, add a cover page or reorder them; pairing by position would
    compare the wrong pages. The pairing is one-to-one (two evidence pages never claim the same
    master page) and maximizes the total similarity; between equally similar pages (for example
    two pages of identical boilerplate) the pairing that keeps the page order wins. Pages that
    match no master page well enough are left out.
    """
    from scipy.optimize import linear_sum_assignment

    master_words = [[w.text for r in p.rows for w in r.words] for p in master_layout.pages]
    leaked = [(lp.index, [normalize_text(w.text) for r in lp.rows for w in r.words]) for lp in leaked_layout.pages]
    leaked = [(i, words) for i, words in leaked if words]
    if not leaked or not master_words:
        return {}
    sim = np.array([[difflib.SequenceMatcher(None, words, mw, autojunk=False).ratio() for mw in master_words]
                    for _, words in leaked])
    # A tie-break far below any real similarity difference: prefer pairs in page order.
    rank_l = np.arange(len(leaked))[:, None] / max(len(leaked) - 1, 1)
    rank_m = np.arange(len(master_words))[None, :] / max(len(master_words) - 1, 1)
    rows, cols = linear_sum_assignment(-(sim - 1e-6 * np.abs(rank_l - rank_m)))
    return {leaked[r][0]: int(c) for r, c in zip(rows, cols) if sim[r, c] >= min_ratio}


# A page counts as being in the master's frame when the fitted transform is within these.
FRAME_SCALE_TOL = 0.0005   # 0.3 pt across an A4 page
FRAME_OFFSET_TOL_PT = 0.25


@dataclass(frozen=True)
class PageFrame:
    """Where an evidence PDF page's text lies relative to its master page:
    x' = sx * x + ox and y' = sy * y + oy (points), fitted over the matched words.

    ``invisible`` marks a page whose text is mostly invisible (render mode 3): an OCR layer
    over a scanned image, whose positions are estimates rather than the printed geometry.
    """

    master_page: int
    sx: float = 1.0
    ox: float = 0.0
    sy: float = 1.0
    oy: float = 0.0
    invisible: bool = False

    @property
    def in_master_frame(self) -> bool:
        """True when the page is neither scaled nor moved (a direct copy of the master page)."""
        return (abs(self.sx - 1) <= FRAME_SCALE_TOL and abs(self.sy - 1) <= FRAME_SCALE_TOL
                and abs(self.ox) <= FRAME_OFFSET_TOL_PT and abs(self.oy) <= FRAME_OFFSET_TOL_PT)


def invisible_text_pages(pdf_bytes: bytes) -> set[int]:
    """Pages whose text is mostly invisible (render mode 3), as OCR software writes it."""
    import pymupdf

    out = set()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            seen = hidden = 0
            for span in page.get_texttrace():
                n = len(span["chars"])
                seen += n
                hidden += n if span["type"] == 3 or span.get("opacity", 1.0) == 0 else 0
            if seen and hidden > 0.5 * seen:
                out.add(page.number)
    return out


def _fit_axis(m: np.ndarray, v: np.ndarray) -> tuple[float, float]:
    """Robust v = a * m + b: least squares, refitted twice without outliers. With too little
    spread to fit a scale, only the offset (median difference) is estimated."""
    if len(m) < 8 or float(np.ptp(m)) < 50.0:
        return 1.0, float(np.median(v - m)) if len(m) else 0.0
    a, b = np.polyfit(m, v, 1)
    for _ in range(2):
        r = v - (a * m + b)
        spread = 1.4826 * float(np.median(np.abs(r - np.median(r)))) or 1e-6
        keep = np.abs(r) <= max(5.0 * spread, 0.5)
        if keep.sum() >= 8:
            a, b = np.polyfit(m[keep], v[keep], 1)
    # An exact copy fits the identity up to rounding; report it exactly.
    return (1.0 if abs(a - 1) < 1e-9 else float(a)), (0.0 if abs(b) < 1e-6 else float(b))


def _word_pairs(master_layout: DocumentLayout, leaked_layout: DocumentLayout, li: int, mi: int):
    """(master word, leaked word) pairs of one page pair, matched by text sequence."""
    mp, lp = master_layout.pages[mi], leaked_layout.pages[li]
    mw = [w for r in mp.rows for w in r.words]
    lw = [w for r in lp.rows for w in r.words]
    sm = difflib.SequenceMatcher(None, [w.text for w in mw], [normalize_text(w.text) for w in lw], autojunk=False)
    return [(mw[b.a + k], lw[b.b + k]) for b in sm.get_matching_blocks() for k in range(b.size)]


def page_frames(master_layout: DocumentLayout, leaked_layout: DocumentLayout,
                invisible: set[int] | frozenset[int] = frozenset()) -> dict[int, PageFrame]:
    """Evidence page index -> its master page and fitted frame (see :class:`PageFrame`)."""
    frames: dict[int, PageFrame] = {}
    for li, mi in map_pages(master_layout, leaked_layout).items():
        pairs = _word_pairs(master_layout, leaked_layout, li, mi)
        mx = np.array([a.glyphs[0].x for a, _ in pairs])
        my = np.array([a.glyphs[0].y for a, _ in pairs])
        lx = np.array([c.glyphs[0].x for _, c in pairs])
        ly = np.array([c.glyphs[0].y for _, c in pairs])
        sx, ox = _fit_axis(mx, lx)
        sy, oy = _fit_axis(my, ly)
        frames[li] = PageFrame(mi, sx, ox, sy, oy, li in invisible)
    return frames


def match_words(master_layout: DocumentLayout, leaked_layout: DocumentLayout,
                frames: dict[int, PageFrame] | None = None) -> Displacements:
    """Displacement of every master word found in a leaked *PDF* layout, in the master's frame.

    Pages are matched by text, and each page's scale and offset (a print scaled to fit, or to
    another paper size) is removed first, so only the per-word marks remain. Pages with an
    invisible text layer (OCR over a scan) are skipped: they are decoded as images.
    """
    if frames is None:
        frames = page_frames(master_layout, leaked_layout)
    disp: Displacements = {}
    for li, f in frames.items():
        if f.invisible:
            continue
        for a, c in _word_pairs(master_layout, leaked_layout, li, f.master_page):
            disp[a.id] = ((c.glyphs[0].x - f.ox) / f.sx - a.glyphs[0].x,
                          (c.glyphs[0].y - f.oy) / f.sy - a.glyphs[0].y)
    return disp


def measure_vector(pdf_bytes: bytes, master: MasterDocument) -> Displacements:
    """Displacements read from the glyph origins of a leaked PDF file."""
    layout = extract_layout(pdf_bytes)
    return match_words(master.layout, layout, page_frames(master.layout, layout, invisible_text_pages(pdf_bytes)))


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


# Gaussian blur applied to template and evidence before matching (measure_image); OpenCV's
# kernel for sigma 0.7 on float images reaches 3 px from its centre.
MATCH_BLUR_SIGMA = 0.7
TEMPLATE_MARGIN_PX = 8  # beyond each group window: more than the blur reaches


def template_boxes(master: MasterDocument, page: int, dpi: float, pad_px: int = 3,
                   margin_px: int = TEMPLATE_MARGIN_PX) -> tuple[tuple[int, int, int, int], ...]:
    """Output pixel rectangles (x0, y0, x1, y1) of ``page`` at ``dpi`` that hold every template
    pixel :func:`measure_image` reads: per text row the union of its group windows (padded by
    ``pad_px`` as in measure_image) plus ``margin_px`` for the blur, with rectangles that touch
    merged. A master template that is exact inside these rectangles gives the same displacements
    as one exact everywhere (``render_page_exact(..., boxes=...)``)."""
    s = dpi / 72.0
    m = pad_px + margin_px
    rects = []
    for row in master.shift_layout.pages[page].rows:
        if not row.groups:
            continue
        x0 = min(g.bbox[0] for g in row.groups)
        y0 = min(g.bbox[1] for g in row.groups)
        x1 = max(g.bbox[2] for g in row.groups)
        y1 = max(g.bbox[3] for g in row.groups)
        rects.append([int(np.floor(x0 * s)) - m, int(np.floor(y0 * s)) - m,
                      int(np.ceil(x1 * s)) + m, int(np.ceil(y1 * s)) + m])
    rects.sort(key=lambda r: r[1])
    merged: list[list[int]] = []
    for r in rects:
        if merged and r[1] <= merged[-1][3]:
            last = merged[-1]
            last[:] = [min(last[0], r[0]), last[1], max(last[2], r[2]), max(last[3], r[3])]
        else:
            merged.append(r)
    return tuple((max(r[0], 0), max(r[1], 0), r[2], r[3]) for r in merged)


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
    group get the group's displacement (in points). Only the master render inside
    :func:`template_boxes` (same ``pad_px``) is read. On a scanned page the groups come from
    its word boxes (``master.shift_layout``) and the template is the master page image itself.
    """
    s = dpi / 72.0
    disp: Displacements = {}
    h, w = rectified.shape
    tmpl_all = cv2.GaussianBlur(master_render.astype(np.float32), (0, 0), MATCH_BLUR_SIGMA)
    img_all = cv2.GaussianBlur(rectified.astype(np.float32), (0, 0), MATCH_BLUR_SIGMA)
    for row in master.shift_layout.pages[page].rows:
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
