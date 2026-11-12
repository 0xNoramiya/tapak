"""Decoder for channel 1 (word-group and line shifts).

The channel decoder works on *displacements*: for every master word, how far it sits from
its master position in the leaked copy (dx, dy in points). Where the displacements come
from depends on the input:

* a forwarded PDF: glyph origins read straight from the file (``measure_vector``);
* a photo or screenshot: sub-pixel template matching after rectification (M3).

From displacements, each data unit is compared with the line through its two control
neighbours (see ``marker/pdf_shift.py``), giving s = (2*bit - 1) * delta + noise. The noise
level sigma is estimated from the data with a two-component EM fit, then
LLR = 2 * delta * s / sigma^2. Every measured unit also gets the code-blind strength |s| / sigma
(0 for an implausible offset) for the erasure check (``decoder/erasure.py``).

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
(:func:`joint_decode`), so on a clean copy it does not keep a trace of the marks. Sign patterns
that differ by an affine ramp, such as a row whose groups all moved the same way, look the same
and get LLR 0: the decoder never guesses. Every decoded group also gets a code-blind strength
with the meaning of the geser-v1 one (:func:`joint_strengths`): its offset from the row line
fitted to the other groups once their expected marks are taken off, in noise units, so a group
read clearly scores about delta / sigma and a group back at its master position about 0; a
slipped match dropped by :func:`screen_row` gets 0, and rows keep |s| / sigma. Like
every channel decoder here this uses only the evidence, the master layout and the code-blind
plan (positions and whitening), never a recipient's codeword.
"""

from __future__ import annotations

import difflib
import math
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from tapak.decoder.rectify import parabolic_peak
from tapak.decoder.softbits import SoftBits, Strengths, gaussian_llr
from tapak.marker.layout import DocumentLayout, RowId, WordId, extract_layout
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_shift import SCHEME_V2, ShiftSettings, eligible_rows, relative_offset
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.plan import CHANNEL_SHIFT, EmbeddingPlan

Displacements = dict[WordId, tuple[float, float]]
GroupKey = tuple[int, int, int]  # (page, row, group) of the shift layout
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


# Word groups of image evidence (research/geser). The Gaussian row model above holds on a forwarded
# PDF, but on photos and prints a few groups per page match far off (heavy tails: the kurtosis
# of the standardized residual was 7 to 9 on the development photos), and a group that slipped by
# more than delta reads as a confident mark the other way. Groups whose template matched poorly
# are the noisy ones, and below about 44 dpi effective resolution the measured shift is only
# 0.55 to 0.7 of the mark. So the word groups of image evidence are read with a Student t row
# likelihood (WORD_MODELS[IMAGE_WORD_MODEL]): nu degrees of freedom, a scale per group
# proportional to (1 - peak correlation of its match) relative to the evidence's median, clipped
# to QUALITY_CLIP and raised to ``quality``, and below ``low_res[0]`` dpi the mark taken as
# ``low_res[1]`` times its issued size. The row nuisance (offset and slope) is fitted per sign
# pattern by iteratively reweighted least squares (a profile likelihood), the 2^g patterns are
# enumerated as before, and the scale is fitted by EM over all rows. Sign patterns that differ by
# a ramp still get LLR 0. Only LLRs change: rows, the page field, dropped groups, sigma and
# strengths come from the Gaussian decode, so the erasure check sees the same units.
WORD_MODELS: dict[str, dict[str, object] | None] = {
    "gauss": None,  # the Gaussian row model above (every word group before research/geser)
    "t3_redam": {"nu": 3.0, "low_res": (44.0, 0.6), "quality": 0.0},
    "t3_redam_puncak": {"nu": 3.0, "low_res": (44.0, 0.6), "quality": 1.0},
    "t3_redam_puncak05": {"nu": 3.0, "low_res": (44.0, 0.6), "quality": 0.5},
    "t4_redam_puncak": {"nu": 4.0, "low_res": (44.0, 0.6), "quality": 1.0},
    "t2_redam_puncak": {"nu": 2.0, "low_res": (44.0, 0.6), "quality": 1.0},
}
IMAGE_WORD_MODEL = "t3_redam"  # chosen by research/geser/kandidat.py (hasil/pilihan.json)
QUALITY_CLIP = (0.25, 4.0)
T_EM_ROUNDS = 15
T_IRLS_FIRST, T_IRLS = 6, 3  # nuisance refits per pattern: first EM round, later rounds (warm start)
T_IRLS_FINAL = 8


def _t_logpdf(r: np.ndarray, sigma: float, nu: float) -> np.ndarray:
    return (math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi) - math.log(sigma)
            - (nu + 1) / 2 * np.log1p((r / sigma) ** 2 / nu))


def _t_profile(x: np.ndarray, d: np.ndarray, v: np.ndarray, delta: float, sigma: float, nu: float,
               theta: np.ndarray | None, rounds: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """For every sign pattern s of one row (chunk): (patterns, log-likelihood, standardized
    residuals, t weights, nuisance) with the offset and slope fitted by IRLS, ``rounds`` times
    from ``theta`` (None: ordinary least squares)."""
    span = float(np.ptp(x)) or 1.0
    a = np.vander((x - x.mean()) / span, JOINT_DEGREE + 1)
    a0, a1 = a[:, 0], a[:, 1]
    s = _sign_patterns(len(d))
    r0 = d[None, :] - delta * s
    sg = sigma * np.sqrt(v)
    if theta is None:
        theta = r0 @ np.linalg.pinv(a).T
    for _ in range(rounds):
        res = r0 - theta @ a.T
        w = (nu + 1) / (nu + (res / sg) ** 2) / v
        m00, m01, m11 = w @ (a0 * a0), w @ (a0 * a1), w @ (a1 * a1)
        b0, b1 = (w * r0) @ a0, (w * r0) @ a1
        det = m00 * m11 - m01 * m01 + 1e-18
        theta = np.stack([(m11 * b0 - m01 * b1) / det, (m00 * b1 - m01 * b0) / det], axis=1)
    res = r0 - theta @ a.T
    w = (nu + 1) / (nu + (res / sg) ** 2)
    ll = (_t_logpdf(res / np.sqrt(v), sigma, nu) - 0.5 * np.log(v)).sum(axis=1)
    return s, ll, res / np.sqrt(v), w, theta


def robust_word_llrs(rows: list[tuple[np.ndarray, np.ndarray]], delta: float, floor: float, nu: float,
                     scales: list[np.ndarray] | None = None) -> tuple[list[np.ndarray], float]:
    """Sign LLRs of geser-v2 word groups under the Student t row model, and its fitted scale.

    ``rows`` holds (x, d) per row as for :func:`joint_word_llrs` (chunked the same way; a chunk
    with at most two groups gets LLR 0), ``delta`` is the mark (points), ``scales`` the relative
    noise variance of every group (None: all 1). The offset and slope of each chunk are fitted per
    sign pattern by IRLS; the t scale (at least ``floor``) by EM over all chunks: each round the
    posterior over the patterns weighs the t-weighted squared residuals, divided by the degrees
    of freedom left (g - 2 per chunk). Code-blind: only the evidence and the plan enter.
    """
    if nu <= 0:
        raise ValueError("derajat kebebasan harus positif")
    pieces = []
    for k, (x, d) in enumerate(rows):
        x = np.asarray(x, dtype=np.float64)
        d = np.asarray(d, dtype=np.float64)
        v = np.ones(x.size) if scales is None else np.asarray(scales[k], dtype=np.float64)
        for sl in _chunks(x.size) if x.size else []:
            if sl.stop - sl.start > JOINT_DEGREE + 1:
                pieces.append((k, sl, x[sl], d[sl], v[sl]))
    out = [np.zeros(len(x)) for x, _ in rows]
    dof = sum(len(pc[3]) - JOINT_DEGREE - 1 for pc in pieces)
    if not pieces or dof <= 0:
        return out, max(delta, floor)
    sigma = max(delta, floor)
    thetas: list[np.ndarray | None] = [None] * len(pieces)
    for it in range(T_EM_ROUNDS):
        energy = 0.0
        for i, (_, _, x, d, v) in enumerate(pieces):
            s, ll, res, w, thetas[i] = _t_profile(x, d, v, delta, sigma, nu, thetas[i], T_IRLS if it else T_IRLS_FIRST)
            post = np.exp(ll - ll.max())
            energy += float((post / post.sum()) @ (w * res * res).sum(axis=1))
        sigma = max(math.sqrt(energy / dof), floor)
    for i, (k, sl, x, d, v) in enumerate(pieces):
        s, ll, *_ = _t_profile(x, d, v, delta, sigma, nu, thetas[i], T_IRLS_FINAL)
        out[k][sl] = _marginals(s, ll)
    return out, sigma


@dataclass(frozen=True)
class ImageWords:
    """How the word groups of an image evidence are read: the model's name and settings
    (``WORD_MODELS``), the evidence's effective resolution and the peak correlation of every
    group's match by code position."""

    name: str
    model: dict[str, object] | None
    effective_dpi: float
    quality: dict[int, float] | None = None


def quality_scales(rows: list[list[tuple[int, int, float, float]]], quality: dict[int, float],
                   power: float) -> list[np.ndarray] | None:
    """Relative noise variance of every decoded word group from its match quality: (1 - peak)
    over the median of the evidence, clipped to QUALITY_CLIP, to the ``power``. ``quality`` maps
    code positions to peak correlations (groups without one get the median). None when
    ``power`` is 0 or nothing has a quality."""
    if power == 0 or not quality:
        return None
    bad = {q: 1.0 - min(max(float(v), 0.0), 0.999) for q, v in quality.items() if np.isfinite(v)}
    if not bad:
        return None
    med = float(np.median(list(bad.values())))
    if med <= 0:
        return None
    lo, hi = QUALITY_CLIP
    return [np.array([min(max(bad.get(u[0], med) / med, lo), hi) ** power for u in r]) for r in rows]


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


def _screened_rows(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    delta: float,
    degree: int,
    field: dict[int, float] | None,
) -> tuple[list[list[tuple[int, int, float, float]]], list[int]]:
    """Rows as in :func:`joint_measurements`, and the code positions of the dropped groups."""
    by_row = _word_units(master, plan, disp)
    if field:
        by_row = {k: [(q, w, xc, dx - field.get(q, 0.0)) for q, w, xc, dx in units] for k, units in by_row.items()}
    rows = []
    dropped: list[int] = []
    for units in by_row.values():
        if len(units) <= degree + 1:
            continue
        x = np.array([u[2] for u in units])
        d = np.array([u[3] for u in units])
        keep = screen_row(x, d, delta, degree)
        dropped += [u[0] for u, k in zip(units, keep) if not k]
        kept = [u for u, k in zip(units, keep) if k]
        if len(kept) > degree + 1:
            rows.append(kept)
    return rows, dropped


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
    rows, dropped = _screened_rows(master, plan, disp, delta, degree, field)
    return rows, len(dropped)


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
    rows, llrs, sigma, dropped = _joint_decode(master, plan, disp, delta, floor, degree, field_degree, rounds)
    return rows, llrs, sigma, len(dropped)


def _joint_decode(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    delta: float,
    floor: float,
    degree: int,
    field_degree: int | None,
    rounds: int,
) -> tuple[list[list[tuple[int, int, float, float]]], list[np.ndarray], float, list[int]]:
    """:func:`joint_decode` with the code positions of the dropped groups (last round)."""
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
        rows, dropped = _screened_rows(master, plan, disp, delta, degree, field)
        llrs, sigma = joint_word_llrs([(np.array([u[2] for u in r]), np.array([u[3] for u in r])) for r in rows],
                                      delta, floor=floor, degree=degree)
        # Posterior mean of each physical sign (direction of the move).
        means = {u[0]: float(np.tanh(v / 2.0)) for r, rl in zip(rows, llrs) for u, v in zip(r, rl)}
    return rows, llrs, sigma, dropped


def joint_strengths(
    rows: list[list[tuple[int, int, float, float]]],
    llrs: list[np.ndarray],
    sigma: float,
    delta: float,
    dropped: list[int] | tuple[int, ...] = (),
    degree: int = JOINT_DEGREE,
) -> Strengths:
    """Code-blind strength of every geser-v2 word group read by :func:`joint_decode`.

    ``rows`` and ``llrs`` are the decoded rows (units as in :func:`joint_measurements`) and
    their sign LLRs, ``sigma`` the fitted noise and ``delta`` the shift (same unit). Under
    geser-v1 a data unit's strength is its offset from the line through its two unmarked
    control neighbours, in noise units. Under geser-v2 every neighbour is marked, so each one's
    expected mark (delta times the posterior mean tanh(LLR / 2) of its sign) is taken off
    first; the strength of group g is then |d_g - L_g| / sigma, with L_g the row nuisance
    (polynomial of ``degree``, offset and slope) fitted to the other groups of its row, or of
    its chunk for rows split as in :func:`joint_word_llrs`. A clearly read group scores about
    delta / sigma whichever way it moved, a group put back at its master position about 0.
    Groups in ``dropped`` (slipped matches, see :func:`screen_row`) were measured but show no
    mark and get 0, like an implausible geser-v1 unit. Only the evidence enters: neither a
    codeword nor the bias vector.
    """
    if sigma <= 0 or delta <= 0:
        raise ValueError("sigma dan delta harus positif")
    if len(rows) != len(llrs) or any(len(r) != len(np.asarray(v).reshape(-1)) for r, v in zip(rows, llrs)):
        raise ValueError("satu LLR per kelompok")
    pos: list[int] = []
    val: list[float] = []
    for units, lam in zip(rows, llrs):
        x = np.array([u[2] for u in units], dtype=np.float64)
        d = np.array([u[3] for u in units], dtype=np.float64)
        mean = np.tanh(np.asarray(lam, dtype=np.float64).reshape(-1) / 2.0)
        offset = np.zeros(x.size)
        for sl in _chunks(x.size):
            if sl.stop - sl.start <= degree + 1:  # no line through the others: no strength
                offset[sl] = np.nan
                continue
            p = row_projector(x[sl], degree)
            resid = p @ (d[sl] - delta * mean[sl])
            # d_g minus the nuisance fitted to the other groups' marks-removed displacements
            offset[sl] = resid / np.maximum(np.diag(p), 1e-12) + delta * mean[sl]
        for u, v in zip(units, offset):
            if np.isfinite(v):
                pos.append(u[0])
                val.append(abs(float(v)) / sigma)
    return Strengths(np.array(pos + list(dropped), dtype=np.int64), np.array(val + [0.0] * len(dropped)))


def _decode_v2(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None,
    sigma_floor_ratio: float,
    degree: int,
    field_degree: int | None,
    image: ImageWords | None = None,
) -> SoftBits:
    """Channel 1 soft bits under geser-v2: word groups jointly per row, rows as in geser-v1.
    Strengths: :func:`joint_strengths` for the word groups, |s| / sigma for the rows (0 for an
    implausible offset), as under geser-v1. With ``image`` (image evidence) the word-group LLRs
    come from :func:`robust_word_llrs` under that model; everything else is unchanged."""
    delta = settings.word_pt
    rows, llrs, sigma_w, dropped = _joint_decode(master, plan, disp, delta, sigma_floor_ratio * delta, degree,
                                                 field_degree, FIELD_ROUNDS)
    word_meta: dict[str, object] = {}
    sign_llrs = llrs
    if image is not None and image.model is not None and rows:
        spec = image.model
        mark = delta
        lo_dpi, gain = spec["low_res"]  # type: ignore[misc]
        if image.effective_dpi < float(lo_dpi):  # the measured mark shrinks at low resolution
            mark = float(gain) * delta
        scales = quality_scales(rows, image.quality or {}, float(spec["quality"]))  # type: ignore[arg-type]
        sign_llrs, scale = robust_word_llrs([(np.array([u[2] for u in r]), np.array([u[3] for u in r])) for r in rows],
                                            mark, sigma_floor_ratio * delta, float(spec["nu"]), scales)  # type: ignore[arg-type]
        word_meta = {"word_model": image.name, "word_t_scale_pt": scale, "word_mark_pt": mark}
    pos: list[int] = []
    llr: list[float] = []
    for units, row_llr in zip(rows, sign_llrs):
        for (q, white, _, _), v in zip(units, row_llr):
            if abs(v) > AMBIGUOUS_LLR:  # patterns told apart only by rounding: unreadable
                pos.append(q)
                llr.append(float(v) * (1 - 2 * white))
    n_words = len(pos)
    sigmas: dict[str, float] = {"kata": sigma_w} if rows else {}
    parts = [joint_strengths(rows, llrs, sigma_w, delta, dropped, degree)]
    rpos, rvals, _ = signed_measurements(master, plan, disp, excluded, words=False)
    implausible = len(dropped)
    if rpos:
        s = np.array(rvals)
        sane = np.abs(s) <= OUTLIER_FACTOR * settings.row_pt
        implausible += int((~sane).sum())
        row_strength = np.zeros(s.size)  # an implausible offset: measured, no mark
        if sane.any():
            sigma = estimate_sigma(s[sane], settings.row_pt, floor=sigma_floor_ratio * settings.row_pt)
            sigmas["baris"] = sigma
            row_strength[sane] = np.abs(s[sane]) / sigma
            row_llr = gaussian_llr(s[sane], settings.row_pt, sigma)
            for q, v in zip(np.array(rpos)[sane], row_llr):
                if v != 0.0:
                    pos.append(int(q))
                    llr.append(float(v))
        parts.append(Strengths(np.array(rpos, dtype=np.int64), row_strength))
    strengths = Strengths(np.concatenate([p.positions for p in parts]), np.concatenate([p.values for p in parts]))
    total = len(plan.channel(CHANNEL_SHIFT))
    if not pos and not len(strengths):
        return SoftBits.empty(CHANNEL_SHIFT, slots_total=total, scheme=SCHEME_V2)
    clear = float(np.mean(np.abs(np.array(llr[:n_words])) >= 2.0)) if n_words else 0.0
    return SoftBits(
        CHANNEL_SHIFT,
        np.array(pos, dtype=np.int64),
        np.array(llr),
        {"slots_read": len(pos), "slots_total": total, "slots_implausible": implausible, "sigma_pt": sigmas,
         "fraction_clear": clear, "scheme": SCHEME_V2, "word_slots_read": n_words, **word_meta},
        strengths,
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
    grid: PixelGrid | None = None,
    quality: dict[GroupKey, float] | None = None,
    word_model: str | None = None,
) -> SoftBits:
    """Soft bits of channel 1 from per-word displacements, under the scheme of ``settings``
    (geser-v1: relative offsets; geser-v2: word groups read jointly per row after the page field
    of ``field_degree`` is subtracted, ``joint_degree`` being the degree of the row nuisance
    projected out).

    On image evidence (``grid`` given) the geser-v2 word groups are read with
    ``WORD_MODELS[word_model]`` (default ``IMAGE_WORD_MODEL``), using the match quality of every
    group (``quality``, from :func:`measure_image`) and the effective resolution of ``grid``.

    ``grid`` (image evidence only) says where the page lies in the image. When the rows of the
    page sit on the image's pixel grid (a renderer rounded the baselines, see
    :func:`rounded_rows`), the row slots of that page are decoded with the rounding model
    instead of the Gaussian one; everything else is unchanged, and without ``grid`` (a PDF) or
    on a page whose rows are not on the grid the result is exactly that of the Gaussian model."""
    image = None
    if grid is not None:
        name = IMAGE_WORD_MODEL if word_model is None else word_model
        by_pos = None
        if quality:
            by_pos = {sl.positions[0]: quality[(sl.page, *sl.ref)] for sl in plan.channel(CHANNEL_SHIFT)
                      if len(sl.ref) == 2 and (sl.page, *sl.ref) in quality}
        image = ImageWords(name, WORD_MODELS[name], grid.effective_dpi, by_pos)
    sb = _decode_gaussian(master, plan, disp, settings, excluded, sigma_floor_ratio, joint_degree, field_degree, image)
    return sb if grid is None else _with_rounded_rows(sb, master, plan, disp, settings, excluded, grid)


def _decode_gaussian(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None,
    sigma_floor_ratio: float,
    joint_degree: int,
    field_degree: int | None,
    image: ImageWords | None = None,
) -> SoftBits:
    """:func:`decode_displacements` without the rounding model (every row Gaussian)."""
    if settings.scheme == SCHEME_V2:
        return _decode_v2(master, plan, disp, settings, excluded, sigma_floor_ratio, joint_degree, field_degree,
                          image)
    pos, vals, kinds = signed_measurements(master, plan, disp, excluded)
    if not pos:
        return SoftBits.empty(CHANNEL_SHIFT, slots_total=len(plan.channel(CHANNEL_SHIFT)))
    s = np.array(vals)
    kinds_arr = np.array(kinds)
    llr = np.zeros_like(s)
    strength = np.full(s.shape, np.nan)
    sigmas = {}
    implausible = 0
    for kind, delta in (("kata", settings.word_pt), ("baris", settings.row_pt)):
        sel = kinds_arr == kind
        # A genuine mark moves a unit by +/-delta; a relative offset beyond 3 delta means the
        # matcher slipped (blur, a stain). Such units are unreadable, not evidence, and are
        # kept out of the noise estimate so they cannot silence the whole channel.
        sane = sel & (np.abs(s) <= OUTLIER_FACTOR * delta)
        implausible += int(sel.sum() - sane.sum())
        strength[sel & ~sane] = 0.0  # measured, but no mark: as erased for the erasure check
        if not sane.any():
            continue
        sigma = estimate_sigma(s[sane], delta, floor=sigma_floor_ratio * delta)
        sigmas[kind] = sigma
        llr[sane] = gaussian_llr(s[sane], delta, sigma)
        strength[sane] = np.abs(s[sane]) / sigma
    measured = ~np.isnan(strength)
    strengths = Strengths(np.array(pos, dtype=np.int64)[measured], strength[measured])
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
        strengths,
    )


# Baselines on the evidence's pixel grid (screenshots, rasterized PDF pages). PDF renderers put
# every baseline on a grid of device pixels: MuPDF and Poppler's Splash on whole pixels, Cairo on
# quarter pixels (measured in research/layar/kuantisasi.py; MuPDF uses uneven half pixels for glyphs
# below about 8 pixels per em, 11 pt text below 56 dpi, which is no clean grid and is not tested).
# In a capture that was not rescaled every text row then sits at the same offset from that grid,
# and a row shift of 0.05 mm (0.08 to 0.3 pixel at 40 to 150 dpi) is either rounded away or moves
# the row by one grid step. The Gaussian row model reads the rounding of the neighbouring rows as a
# mark, with a confident sign now and then, and drops rows that moved a whole pixel as implausible
# (beyond 3 delta). The gate, the grid steps and the model were chosen on the development set of
# research/layar (kandidat.py, candidate kisi_baris3) before its held-out run.
GRID_MIN_CONTROLS = 8          # measured control rows a page needs before its pixel grid is tested
GRID_MIN_CONCENTRATION = 0.7   # mean resultant length of the control rows' positions modulo one grid step
GRID_PITCHES_PX = (1.0, 0.25)  # grid steps tested, in image pixels, coarsest first
LATTICE_OFF_GRID_PX = 0.25     # a row further than this (in grid steps) is not a clean lattice point
LATTICE_SPAN = 0.01            # relative range of pixel scales searched around the control rows' fit
LATTICE_STEPS = 4001
LATTICE_FLOOR = 0.01           # chance that a row lands on a pixel the model does not predict (|LLR| <= 4.6)


@dataclass(frozen=True)
class PixelGrid:
    """Where a page lies in an evidence image.

    Attributes:
        h_page_to_img: homography from page pixel coordinates at ``dpi`` to image pixels (the
            registration's ``h_page_to_img``).
        dpi: analysis resolution of those page pixels.
        effective_dpi: image pixels per inch of page at the page centre.
    """

    h_page_to_img: np.ndarray
    dpi: float
    effective_dpi: float

    def __post_init__(self) -> None:
        if np.asarray(self.h_page_to_img).shape != (3, 3) or self.dpi <= 0 or self.effective_dpi <= 0:
            raise ValueError("kisi piksel memerlukan homografi 3x3 dan resolusi positif")

    @property
    def pixel_pt(self) -> float:
        """One image pixel in page points (at the page centre)."""
        return 72.0 / self.effective_dpi

    def image_y(self, x_pt: np.ndarray, y_pt: np.ndarray) -> np.ndarray:
        """Image row coordinate (pixels) of page points (x_pt, y_pt)."""
        s = self.dpi / 72.0
        x = np.asarray(x_pt, dtype=np.float64).reshape(-1) * s
        y = np.asarray(y_pt, dtype=np.float64).reshape(-1) * s
        hom = np.c_[x, y, np.ones_like(x)] @ np.asarray(self.h_page_to_img, dtype=np.float64).T
        return hom[:, 1] / hom[:, 2]


def grid_concentration(y_img: np.ndarray) -> float:
    """Mean resultant length of image positions modulo one pixel: 1 when every position sits at
    the same offset from the pixel grid, about 1/sqrt(n) for n positions unrelated to it, 0 for
    no positions."""
    y = np.asarray(y_img, dtype=np.float64).reshape(-1)
    return float(np.abs(np.mean(np.exp(2j * np.pi * y)))) if y.size else 0.0


def lattice_row_llrs(
    control_pt: np.ndarray,
    control_px: np.ndarray,
    data_pt: np.ndarray,
    data_px: np.ndarray,
    delta: float,
    span: float = LATTICE_SPAN,
    steps: int = LATTICE_STEPS,
    floor: float = LATTICE_FLOOR,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]] | None:
    """Sign LLRs of data rows whose baselines a renderer rounded to whole pixels, and the mask of
    rows the model explains; None when the control rows admit no rounding.

    ``control_pt`` and ``data_pt`` are master baselines (points), ``control_px`` and ``data_px``
    the measured image positions of those rows (pixels), ``delta`` the row shift (points). The
    renderer drew row j at pixel n_j = round(k * y_j + phi), y_j the copy's baseline (the master's,
    plus or minus delta on a data row), k pixels per point and phi an offset, both unknown. Every
    control row (unmarked) confines (k, phi) to a strip; with a flat prior on the intersection of
    the strips (k within ``span`` of the least-squares scale of the controls, ``steps`` values) a
    data row's sign has the likelihood of the part of the region where k (y + s delta) + phi rounds
    to the row's measured pixel. A shift rounded away leaves both signs equally likely (LLR 0); a
    shift that moved the row a whole pixel is read, with ``floor`` the chance of a pixel the model
    does not predict. Rows (controls or data) further than LATTICE_OFF_GRID_PX from the common
    pixel offset are not clean lattice points: controls are left out, data rows get mask False.
    Only the evidence, the master baselines and which rows carry no mark enter: no codeword. For a
    grid finer than one pixel, pass the positions divided by the grid step (then "pixel" above means
    one grid step).
    """
    cy = np.asarray(control_pt, dtype=np.float64).reshape(-1)
    cz = np.asarray(control_px, dtype=np.float64).reshape(-1)
    dy = np.asarray(data_pt, dtype=np.float64).reshape(-1)
    dz = np.asarray(data_px, dtype=np.float64).reshape(-1)
    if cy.shape != cz.shape or dy.shape != dz.shape or delta <= 0 or steps < 2 or span <= 0:
        raise ValueError("baris dan posisinya harus sama panjang; delta, rentang, dan langkah positif")
    offset = float(np.angle(np.mean(np.exp(2j * np.pi * cz))) / (2.0 * np.pi)) if cz.size else 0.0

    def off_grid(z: np.ndarray) -> np.ndarray:
        return np.abs((z - offset + 0.5) % 1.0 - 0.5)

    clean = off_grid(cz) <= LATTICE_OFF_GRID_PX
    cy, cz = cy[clean], cz[clean]
    if cy.size < 2 or float(np.ptp(cy)) <= 0:
        return None
    k0 = float(np.polyfit(cy, cz, 1)[0])
    if k0 <= 0:
        return None
    ks = k0 * (1.0 + np.linspace(-span, span, steps))
    n_c = np.round(cz - offset)
    lo = np.max(n_c[None, :] - 0.5 - cy[None, :] * ks[:, None], axis=1)
    hi = np.min(n_c[None, :] + 0.5 - cy[None, :] * ks[:, None], axis=1)
    total = float(np.clip(hi - lo, 0.0, None).sum())
    if total <= 0.0:
        return None
    n_d = np.round(dz - offset)
    areas = []
    for sign in (1.0, -1.0):
        y = dy + sign * delta
        a = n_d[None, :] - 0.5 - y[None, :] * ks[:, None]
        b = n_d[None, :] + 0.5 - y[None, :] * ks[:, None]
        areas.append(np.clip(np.minimum(hi[:, None], b) - np.maximum(lo[:, None], a), 0.0, None).sum(axis=0))
    plus, minus = areas
    explained = (off_grid(dz) <= LATTICE_OFF_GRID_PX) & ((plus + minus) > 0)
    llr = np.log((plus + floor * total) / (minus + floor * total))
    feasible = ks[hi > lo]
    info: dict[str, object] = {"controls_used": int(cy.size),
                               "pixel_per_pt": [round(float(feasible.min()), 6), round(float(feasible.max()), 6)]}
    return np.where(explained, llr, 0.0), explained, info


@dataclass(frozen=True)
class _PageRows:
    """Row units of one page at x = x_ref: data rows (position, whitening, master baseline,
    baseline plus measured displacement) and control rows (master baseline, baseline plus
    displacement), in points."""

    x_ref: float
    data: list[tuple[int, int, float, float]]
    controls: list[tuple[float, float]]


def _page_rows(master: MasterDocument, plan: EmbeddingPlan, disp: Displacements,
               excluded: set[RowId] | None) -> dict[int, _PageRows]:
    """Row units of every page; a data row needs its two control neighbours measured, as in
    :func:`signed_measurements`."""
    layout = master.shift_layout
    slot_of = {(s.page, s.ref[0]): s for s in plan.channel(CHANNEL_SHIFT) if len(s.ref) == 1}
    out: dict[int, _PageRows] = {}
    for pg in layout.pages:
        rows = eligible_rows(layout, pg.index, excluded or set())
        slope = row_slope(layout, disp, pg.index)
        x_ref = 0.5 * pg.width
        meas = [_row_displacement(layout, disp, r.id, slope, x_ref) for r in rows]
        data_k = set(range(1, len(rows) - 1, 2))  # the data rows of shift_slot_refs
        data = []
        for k in sorted(data_k):
            slot = slot_of.get((pg.index, rows[k].index))
            if slot is None or any(m is None for m in meas[k - 1:k + 2]):
                continue
            base, d = meas[k]  # type: ignore[misc]
            data.append((slot.positions[0], slot.whiten[0], base, base + d))
        controls = [(m[0], m[0] + m[1]) for k, m in enumerate(meas) if k not in data_k and m is not None]
        out[pg.index] = _PageRows(x_ref, data, controls)
    return out


def rounded_rows(
    master: MasterDocument,
    plan: EmbeddingPlan,
    disp: Displacements,
    settings: ShiftSettings,
    excluded: set[RowId] | None,
    grid: PixelGrid,
) -> tuple[set[int], np.ndarray, np.ndarray, dict[str, object]] | None:
    """Row slots of the pages whose rows sit on the image's pixel grid, decoded with
    :func:`lattice_row_llrs`: (those pages, code positions, LLRs, model), or None when no page
    qualifies.

    The gate is code-blind: the control rows (unmarked) of a page are mapped into the image with
    ``grid``; with at least GRID_MIN_CONTROLS of them, the first grid step of GRID_PITCHES_PX (whole
    or quarter pixel) at which their positions have a :func:`grid_concentration` of at least
    GRID_MIN_CONCENTRATION is the step the renderer rounded the baselines to (a capture that was not
    rescaled), and the page's rows are read with the rounding model on that grid. A rescaled
    capture, a photo or a scan does not pass and keeps the Gaussian model, as does a page whose
    control rows admit no rounding.
    """
    delta = settings.row_pt
    pages: set[int] = set()
    pos: list[int] = []
    llr: list[float] = []
    tested: list[dict[str, object]] = []
    for page, units in _page_rows(master, plan, disp, excluded).items():
        if len(units.controls) < GRID_MIN_CONTROLS:
            continue
        c_pt = np.array([c[0] for c in units.controls])
        c_px = grid.image_y(np.full(c_pt.size, units.x_ref), np.array([c[1] for c in units.controls]))
        pitch, conc = GRID_PITCHES_PX[0], 0.0
        for pitch in GRID_PITCHES_PX:
            conc = grid_concentration(c_px / pitch)
            if conc >= GRID_MIN_CONCENTRATION:
                break
        entry: dict[str, object] = {"page": page, "concentration": round(conc, 4), "control_rows": len(units.controls)}
        tested.append(entry)
        if conc < GRID_MIN_CONCENTRATION or not units.data:
            continue
        d_pt = np.array([u[2] for u in units.data])
        d_px = grid.image_y(np.full(d_pt.size, units.x_ref), np.array([u[3] for u in units.data]))
        found = lattice_row_llrs(c_pt, c_px / pitch, d_pt, d_px / pitch, delta)
        entry["pitch_px"] = pitch
        if found is None:
            entry["feasible"] = False
            continue
        values, explained, info = found
        pages.add(page)
        for (position, white, _, _), v, ok in zip(units.data, values, explained):
            if ok and v != 0.0:
                pos.append(position)
                llr.append(float(v) * (1 - 2 * white))
        entry.update(info, feasible=True, q_pt=round(pitch * grid.pixel_pt, 5), rows_explained=int(explained.sum()))
    if not pages:
        return None
    return pages, np.array(pos, dtype=np.int64), np.array(llr), {"pages": tested}


def _with_rounded_rows(sb: SoftBits, master: MasterDocument, plan: EmbeddingPlan, disp: Displacements,
                       settings: ShiftSettings, excluded: set[RowId] | None, grid: PixelGrid) -> SoftBits:
    """``sb`` with the row observations of the pages on the pixel grid replaced by :func:`rounded_rows`
    (strengths unchanged: the erasure check sees the same units)."""
    found = rounded_rows(master, plan, disp, settings, excluded, grid)
    if found is None:
        return sb
    pages, pos, llr, model = found
    slots = plan.channel(CHANNEL_SHIFT)
    rows_out = {s.positions[0] for s in slots if len(s.ref) == 1 and s.page in pages}
    words = {s.positions[0] for s in slots if len(s.ref) == 2}
    if rows_out & words:  # a position shared by a word and a row slot cannot be split: keep the Gaussian rows
        return sb
    keep = np.array([int(p) not in rows_out for p in sb.positions], dtype=bool)
    meta = dict(sb.meta, row_model=model)
    meta["slots_read"] = int(keep.sum()) + len(pos)
    sigmas = dict(meta.get("sigma_pt") or {})  # type: ignore[call-overload]
    sigmas.pop("baris", None)  # the rows are not Gaussian any more; row_model holds their step and noise
    meta["sigma_pt"] = sigmas
    return SoftBits(sb.channel, np.concatenate([sb.positions[keep], pos]), np.concatenate([sb.llr[keep], llr]), meta,
                    sb.strengths)


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
    fx = ix + parabolic_peak(res[iy, ix - 1], res[iy, ix], res[iy, ix + 1])
    fy = iy + parabolic_peak(res[iy - 1, ix], res[iy, ix], res[iy + 1, ix])
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
    quality: dict[GroupKey, float] | None = None,
) -> Displacements:
    """Displacement of every shift group on a rectified page image.

    For each group the template is the master render around the group's box and the search
    window is the same box in the evidence, enlarged by ``search_px``; see
    :func:`match_offset`. Matches with a weak correlation peak are discarded. All words of a
    group get the group's displacement (in points). Only the master render inside
    :func:`template_boxes` (same ``pad_px``) is read. On a scanned page the groups come from
    its word boxes (``master.shift_layout``) and the template is the master page image itself.
    ``quality``, when given, receives the peak correlation of every group measured, by (page,
    row, group): how well its template matched, which the word model of image evidence reads.
    """
    s = dpi / 72.0
    disp: Displacements = {}
    h, w = rectified.shape
    tmpl_all = cv2.GaussianBlur(master_render.astype(np.float32), (0, 0), MATCH_BLUR_SIGMA)
    img_all = cv2.GaussianBlur(rectified.astype(np.float32), (0, 0), MATCH_BLUR_SIGMA)
    for row in master.shift_layout.pages[page].rows:
        for gi, g in enumerate(row.groups):
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
            if quality is not None:
                quality[(page, row.index, gi)] = found[2]
    return disp
