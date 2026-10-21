"""Decoder for channel 2 (background pattern) on a rectified page image.

Steps:
1. mask pixels that carry ink in the master (text, rules), pixels that carry ink in the
   evidence itself (text that differs from the master such as semantic variants, stamps,
   handwriting, stains) and pixels outside the evidence;
2. flatten illumination: divide by a smooth estimate of the paper level computed from the
   unmasked pixels only, so shadows and vignetting vanish and the pattern becomes a
   relative modulation of about +/- amplitude/base (0.8 % with the defaults);
3. average the modulation over every cell of the grid and despread it with the cell's keyed
   sign: u_c = pn_c * v_c is s_b times the cell's gain plus noise, b being the cell's bit;
4. decide whether a pattern is present. Two tests, each with its fixed threshold z = 3
   (p ~ 1.35e-3 on a page without pattern, so at most about 3e-3 for the pair):
   a. decoy test: per bit, t_b = sum_c pn_c v_c n_c / sum_c n_c, and its decoy with each
      cell's sign multiplied by an independent keyed random sign, so the pattern cancels and
      only noise remains. With no pattern, t and the decoy have the same energy in
      expectation (whatever the noise per cell); with a pattern of amplitude mu, t^2 exceeds
      the decoy by about mu^2 * 7/8. A paired z-test on the clipped per-bit energy difference
      decides. The energy difference comes from pairs of informative cells of the same bit,
      so the test fades when only scattered cells still carry the pattern;
   b. pilot test (images, where the trace passes the bias vector p): a code position whose
      Tardos bias p is near 0 or 1 carries nearly the same bit in every copy, so
      e_b = (2 p - 1) * (whitening sign) predicts s_b without looking at any codeword. With
      no pattern, Z = sum_c e_b u_c is a sum of terms with independent random keyed signs
      pn_c, so its spread is exactly sqrt(sum_c (e_b u_c)^2) whatever the noise. With a
      pattern it grows with every informative cell, paired or not.
   If neither test passes (a printed page, a photo clipped to white, another document), the
   channel reports nothing, so noise cannot dilute the other channels;
5. weigh the cells. An overexposed photo clips bright paper to 255: a clipped cell carries
   no pattern and almost no noise, a cell on the shoulder of the clipping an attenuated
   pattern. With the bias vector, cells are sorted into strata by the share of pixels at or
   near white around them (SAT_LEVEL, smoothed over about one cell on the grid, so the
   stratum follows the light rather than the cell's own pattern value). A cell mean over
   fewer usable pixels is noisier, so, as in t, a cell's noise variance is taken as
   v_j / n_c with n_c its valid-pixel fraction. Per stratum j the gain is the weighted
   regression of u_c on the pilot, g_j = sum n_c e_b u_c / sum n_c e_b^2, and
   v_j = E[n_c u_c^2] - g_j^2 E[n_c]; the LLR of bit b is the matched filter
   sum_c 2 g_j n_c u_c / v_j over its cells. Clipped cells get a weight near 0, so they
   neither dilute nor bias the statistic, and partly clipped cells count as much as their
   signal deserves. Without the bias vector (a page rendered from a PDF, which never clips),
   mu is fitted on t with sigma held at the decoy value and LLR = 2 mu t / sigma^2.

The tests are a detection aid only. The false-accusation bound never depends on them: the
weights use no codeword (only the evidence, the master, the keyed cell layout and the bias
vector, which is the same for every copy), so the bound holds for any input, noise included.

No codeword is consulted at any step.
"""

from __future__ import annotations

import cv2
import numpy as np

from tapak.decoder.softbits import SoftBits
from tapak.marker.background import PageGrid
from tapak.marker.plan import CHANNEL_BACKGROUND, Slot

MIN_VALID_FRACTION = 0.3
SIGNAL_Z = 3.0  # z needed by either presence test to call the pattern present (p ~ 1e-3 by chance)
CLIP_SIGMAS = 4.0  # per-bit statistics are clipped here before the energy test (stains, folds)
SAT_LEVEL = 254.5  # rectified gray level counted as clipped white
SAT_EDGES = (0.0, 0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98)  # lower edges of the saturation strata
SAT_SMOOTH_CELLS = 1.0  # Gaussian sigma (in cells) of the saturated share that picks the stratum
MIN_STRATUM_CELLS = 40  # a stratum with fewer cells gets weight 0 (its gain cannot be estimated)
CELL_CLIP = 5.0  # despread cell values beyond this many robust deviations are clipped


def pattern_z(t: np.ndarray, t_decoy: np.ndarray, sigma: float) -> float:
    """z statistic of E[t^2] > E[t_decoy^2] from paired per-bit values, both clipped at
    CLIP_SIGMAS * sigma. Near 0 without a pattern, grows with mu^2 * sqrt(n) with one."""
    if t.size < 8 or sigma <= 0:
        return 0.0
    c = CLIP_SIGMAS * sigma
    d = np.clip(t, -c, c) ** 2 - np.clip(t_decoy, -c, c) ** 2
    se = float(np.std(d, ddof=1)) / np.sqrt(d.size)
    return float(np.mean(d)) / se if se > 0 else 0.0


def pilot_z(u: np.ndarray, e: np.ndarray) -> float:
    """z of sum_c e_c u_c against its exact spread without a pattern.

    Without a pattern u_c = pn_c * m_c with independent random keyed signs pn_c, so the sum
    is a Rademacher sum of variance sum_c (e_c u_c)^2, whatever the noise m_c. Positive and
    growing with sqrt(sum of per-cell SNR^2) when u_c carries s_b and e_c predicts it."""
    a = np.asarray(e, dtype=np.float64) * np.asarray(u, dtype=np.float64)
    var = float(np.sum(a * a))
    return float(np.sum(a) / np.sqrt(var)) if var > 0 else 0.0


def robust_bound(t: np.ndarray, k: float = CELL_CLIP) -> float:
    """Median magnitude of t plus k robust (MAD) deviations of the magnitude: a clipping bound
    for a two-sided mixture 0.5 N(+mu, s^2) + 0.5 N(-mu, s^2) that a few outliers cannot move.
    It depends on |t| only, so it never sees a keyed sign."""
    t = np.asarray(t, dtype=np.float64)
    if t.size == 0:
        return 0.0
    mag = np.abs(t)
    centre = float(np.median(mag))
    spread = 1.4826 * float(np.median(np.abs(mag - centre))) or float(np.std(t)) or 1e-9
    return centre + k * spread


def estimate_mixture(t: np.ndarray, iters: int = 50) -> tuple[float, float]:
    """(mu, sigma) of t ~ 0.5 N(+mu, s^2) + 0.5 N(-mu, s^2) by EM.

    Values further than 5 robust deviations from the median magnitude are clipped first, so
    a few damaged cells (a stain, a fold) cannot inflate sigma and silence the channel.
    """
    t = np.asarray(t, dtype=np.float64)
    if t.size < 4:
        return 0.0, 1.0
    bound = robust_bound(t, 5.0)
    t = np.clip(t, -bound, bound)
    mu = float(np.median(np.abs(t)))
    sigma = float(np.std(t)) or 1e-9
    for _ in range(iters):
        z = np.clip(2.0 * mu * t / (sigma * sigma), -50, 50)
        w = np.tanh(z / 2.0)                # E[sign | t]
        mu = max(float(np.mean(w * t)), 0.0)
        var = float(np.mean(t * t)) - mu * mu
        sigma = max(np.sqrt(max(var, 1e-18)), 1e-9)
    return mu, sigma


def fit_mu(t: np.ndarray, sigma: float, iters: int = 50) -> float:
    """Pattern amplitude mu of t ~ 0.5 N(+mu, sigma^2) + 0.5 N(-mu, sigma^2) with sigma fixed."""
    t = np.asarray(t, dtype=np.float64)
    if t.size == 0 or sigma <= 0:
        return 0.0
    mu = float(np.sqrt(max(np.mean(t * t) - sigma * sigma, 0.0)))
    for _ in range(iters):
        w = np.tanh(np.clip(mu * t / (sigma * sigma), -50, 50))
        mu = max(float(np.mean(w * t)), 0.0)
    return mu


def ink_mask(master_render: np.ndarray, dilate_px: int = 2) -> np.ndarray:
    """True where the master has ink (anything clearly darker than paper), dilated."""
    ink = (master_render < 235).astype(np.uint8)
    if dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        ink = cv2.dilate(ink, k)
    return ink.astype(bool)


def relative_modulation(rectified: np.ndarray, usable: np.ndarray, sigma_px: float) -> np.ndarray:
    """I / paper - 1, with the paper level from a normalized (masked) Gaussian blur."""
    img = rectified.astype(np.float64)
    w = usable.astype(np.float64)
    num = cv2.GaussianBlur(img * w, (0, 0), sigma_px)
    den = cv2.GaussianBlur(w, (0, 0), sigma_px)
    paper = num / np.maximum(den, 1e-6)
    return np.where(usable, img / np.maximum(paper, 1.0) - 1.0, 0.0)


def cell_means(mod: np.ndarray, usable: np.ndarray, grid: PageGrid, dpi: float) -> tuple[np.ndarray, np.ndarray]:
    """Mean modulation and valid-pixel fraction of every cell, both shaped (ny, nx).

    The grid region is resampled with area averaging to 4 x 4 samples per cell and only the
    central 2 x 2 samples are used, which keeps away from the blur shared with neighbours.
    """
    s = dpi / 72.0
    ox, oy = grid.offset_pt
    x0, y0 = int(round(ox * s)), int(round(oy * s))
    x1 = int(round((ox + grid.nx * grid.cell_pt) * s))
    y1 = int(round((oy + grid.ny * grid.cell_pt) * s))
    k = 4
    size = (grid.nx * k, grid.ny * k)
    m_w = cv2.resize((mod * usable)[y0:y1, x0:x1], size, interpolation=cv2.INTER_AREA)
    v_w = cv2.resize(usable[y0:y1, x0:x1].astype(np.float64), size, interpolation=cv2.INTER_AREA)
    m_c = m_w.reshape(grid.ny, k, grid.nx, k)[:, 1:3, :, 1:3].sum(axis=(1, 3))
    v_c = v_w.reshape(grid.ny, k, grid.nx, k)[:, 1:3, :, 1:3].sum(axis=(1, 3))
    frac = v_c / 4.0
    means = np.where(v_c > 0, m_c / np.maximum(v_c, 1e-9), 0.0)
    return means, frac


def saturated_share(rectified: np.ndarray, usable: np.ndarray, grid: PageGrid, dpi: float,
                    frac: np.ndarray) -> np.ndarray:
    """Share of usable pixels at or above SAT_LEVEL around every cell, shaped (ny, nx).

    The per-cell share is smoothed over the grid with a Gaussian of SAT_SMOOTH_CELLS cells
    (cells below MIN_VALID_FRACTION do not count), so it follows the exposure of the region:
    in a screenshot the brightest pattern cells touch 255 themselves, and their own share
    alone would sort them by the sign they carry.
    """
    own, _ = cell_means((rectified >= SAT_LEVEL).astype(np.float64), usable, grid, dpi)
    w = (frac >= MIN_VALID_FRACTION).astype(np.float64)
    num = cv2.GaussianBlur(own * w, (0, 0), SAT_SMOOTH_CELLS)
    den = cv2.GaussianBlur(w, (0, 0), SAT_SMOOTH_CELLS)
    return np.where(den > 1e-9, num / np.maximum(den, 1e-9), own)


def saturation_strata(share: np.ndarray) -> np.ndarray:
    """Stratum index (0 .. len(SAT_EDGES) - 1) of every cell from its saturated share."""
    return np.searchsorted(np.asarray(SAT_EDGES), np.asarray(share, dtype=np.float64), side="right") - 1


def stratum_gains(u: np.ndarray, e: np.ndarray, stratum: np.ndarray, n_strata: int,
                  w: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Gain g_j and noise variance v_j per stratum for despread cells u_c = g_j s_b + noise,
    the noise of cell c having variance v_j / w_c (w_c: its valid-pixel fraction, 1 if None).

    g_j = sum w_c e_c u_c / sum w_c e_c^2 is the weighted regression of the cells on the
    pilot e_c (the bit predicted by the bias vector, the same for every copy): linear, so it
    cannot reinforce itself on noise the way a decision-directed fit does.
    v_j = E[w_c u_c^2] - g_j^2 E[w_c] (at least 1 % of E[w_c u_c^2]). Strata with fewer than
    MIN_STRATUM_CELLS cells and negative gains get g_j = 0. No codeword is used.
    """
    u = np.asarray(u, dtype=np.float64)
    e = np.asarray(e, dtype=np.float64)
    w = np.ones_like(u) if w is None else np.asarray(w, dtype=np.float64)
    n = np.bincount(stratum, minlength=n_strata)
    mean_w = np.bincount(stratum, weights=w, minlength=n_strata) / np.maximum(n, 1)
    power = np.bincount(stratum, weights=w * u * u, minlength=n_strata) / np.maximum(n, 1)
    num = np.bincount(stratum, weights=w * e * u, minlength=n_strata)
    den = np.bincount(stratum, weights=w * e * e, minlength=n_strata)
    ok = (n >= MIN_STRATUM_CELLS) & (den > 0) & (power > 0)
    gain = np.where(ok, np.maximum(num / np.maximum(den, 1e-300), 0.0), 0.0)
    var = np.maximum(power - gain ** 2 * mean_w, np.maximum(0.01 * power, 1e-300))
    return gain, var


def _clip_by_stratum(u: np.ndarray, stratum: np.ndarray, n_strata: int) -> np.ndarray:
    out = u.copy()
    for j in range(n_strata):
        m = stratum == j
        if m.any():
            b = robust_bound(u[m])
            out[m] = np.clip(u[m], -b, b)
    return out


def decode_background(
    rectified: np.ndarray,
    valid: np.ndarray,
    master_render: np.ndarray,
    dpi: float,
    grid: PageGrid,
    slots: list[Slot],
    bias: np.ndarray | None = None,
) -> SoftBits:
    """Soft bits of the background channel for one page.

    ``bias`` is the document's Tardos bias vector p (one value per code position, the same
    for every copy). With it the pilot test and the saturation strata are used (photos and
    screenshots); without it the decoder keeps a single amplitude for the whole page.
    """
    page_slots = [s for s in slots if s.page == grid.page and s.channel == CHANNEL_BACKGROUND]
    if not page_slots:
        return SoftBits.empty(CHANNEL_BACKGROUND)
    usable = valid & ~ink_mask(master_render) & (rectified > 20)
    sigma_px = 3.0 * grid.cell_pt * dpi / 72.0
    mod = relative_modulation(rectified, usable, sigma_px)
    # Second pass: drop ink present in the evidence but not in the master (the pattern
    # itself is below 1 %, ink is tens of percent darker than paper).
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    extra_ink = cv2.dilate((usable & (mod < -0.08)).astype(np.uint8), k).astype(bool)
    usable &= ~extra_ink
    mod = relative_modulation(rectified, usable, sigma_px)
    means, frac = cell_means(mod, usable, grid, dpi)
    ok = frac >= MIN_VALID_FRACTION
    cb = grid.cell_bit
    sel = ok & (cb >= 0)
    bits = cb[sel]
    contrib = (grid.pn * means)[sel]
    weight = frac[sel]
    num = np.bincount(bits, weights=contrib * weight, minlength=grid.n_bits)
    den = np.bincount(bits, weights=weight, minlength=grid.n_bits)
    seen = den > 0
    t = np.where(seen, num / np.maximum(den, 1e-12), 0.0)
    # Decoy: same cells, independent keyed signs. The pattern cancels; the noise does not.
    from tapak.tardos.code import uniform_stream

    decoy_sign = np.where(uniform_stream(grid.key, f"bg-decoy|{grid.page}".encode(), grid.n_cells) < 0.5,
                          -1.0, 1.0).reshape(grid.ny, grid.nx)
    num_d = np.bincount(bits, weights=(decoy_sign * grid.pn * means)[sel] * weight, minlength=grid.n_bits)
    t_decoy = np.where(seen, num_d / np.maximum(den, 1e-12), 0.0)
    noise2 = float(np.median(t_decoy[seen] ** 2)) if seen.any() else 0.0
    sigma = float(np.sqrt(noise2 / 0.4549)) if noise2 > 0 else 1.0  # median of chi2(1) is 0.4549
    z_decoy = pattern_z(t[seen], t_decoy[seen], sigma) if noise2 > 0 else 0.0
    share = saturated_share(rectified, usable, grid, dpi, frac)
    meta: dict[str, object] = {"page": grid.page, "bits_total": len(page_slots), "decoy_z": round(z_decoy, 2),
                               "clipped_share": round(float(np.mean(share[sel] >= 0.5)) if sel.any() else 0.0, 3)}

    if bias is None:
        mu = fit_mu(t[seen], sigma) if z_decoy >= SIGNAL_Z else 0.0
        llr = 2.0 * mu * t / (sigma * sigma) if mu > 0 else np.zeros_like(t)
        reported = seen
        meta.update(mu=mu, sigma=sigma, snr=mu / sigma if sigma > 0 else 0.0, signal_z=round(z_decoy, 2),
                    cells_used=int(sel.sum()))
        found = mu > 0
    else:
        n_strata = len(SAT_EDGES)
        stratum = saturation_strata(share[sel])
        u = _clip_by_stratum(contrib, stratum, n_strata)
        e_bit = np.zeros(grid.n_bits)
        for s in page_slots:
            e_bit[s.ref[0]] = (2.0 * float(bias[s.positions[0]]) - 1.0) * (1 - 2 * s.whiten[0])
        e = e_bit[bits]
        z_pilot = pilot_z(u, e)
        gain, var = stratum_gains(u, e, stratum, n_strata, weight)
        found = (z_decoy >= SIGNAL_Z or z_pilot >= SIGNAL_Z) and bool(np.any(gain > 0))
        info = np.bincount(bits, weights=(gain ** 2 / var)[stratum] * weight, minlength=grid.n_bits)  # per-bit SNR^2
        llr = np.bincount(bits, weights=(2.0 * gain / var)[stratum] * weight * u, minlength=grid.n_bits)
        reported = info > 0
        best = int(np.argmax(gain / np.sqrt(var)))
        meta.update(mu=float(gain[best]) if found else 0.0, sigma=float(np.sqrt(var[best])),
                    snr=float(np.sqrt(np.mean(info[reported]))) if found and reported.any() else 0.0,
                    signal_z=round(max(z_decoy, z_pilot), 2), pilot_z=round(z_pilot, 2),
                    cells_used=int(np.count_nonzero(gain[stratum] > 0)) if found else 0)
    pos, val = [], []
    if found:  # no pattern detected: report nothing rather than noise
        for s in page_slots:
            b = s.ref[0]
            if not reported[b]:
                continue
            pos.append(s.positions[0])
            val.append(llr[b] * (1 - 2 * s.whiten[0]))
    meta.update(bits_read=len(pos), pattern_found=bool(found))
    return SoftBits(CHANNEL_BACKGROUND, np.array(pos, dtype=np.int64), np.array(val), meta)
