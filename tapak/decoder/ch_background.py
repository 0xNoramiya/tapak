"""Decoder for channel 2 (background pattern) on a rectified page image.

Steps:
1. mask pixels that carry ink in the master (text, rules), pixels that carry ink in the
   evidence itself (text that differs from the master such as semantic variants, stamps,
   handwriting, stains) and pixels outside the evidence;
2. flatten illumination: divide by a smooth estimate of the paper level computed from the
   unmasked pixels only, so shadows and vignetting vanish and the pattern becomes a
   relative modulation of about +/- amplitude/base (0.8 % with the defaults);
3. average the modulation over every cell of the grid;
4. for every code position, correlate its cells with their keyed signs pn_c:
   t_b = sum_c pn_c * v_c * n_c / sum_c n_c, which estimates s_b times an unknown gain;
5. fit the symmetric two-component mixture t ~ +/-mu + N(0, sigma^2) (EM, after clipping
   gross outliers) and output LLR = 2 mu t / sigma^2.

No codeword is consulted at any step.
"""

from __future__ import annotations

import cv2
import numpy as np

from tapak.decoder.softbits import SoftBits
from tapak.marker.background import PageGrid
from tapak.marker.plan import CHANNEL_BACKGROUND, Slot

MIN_VALID_FRACTION = 0.3


def estimate_mixture(t: np.ndarray, iters: int = 50) -> tuple[float, float]:
    """(mu, sigma) of t ~ 0.5 N(+mu, s^2) + 0.5 N(-mu, s^2) by EM.

    Values further than 5 robust deviations from the median magnitude are clipped first, so
    a few damaged cells (a stain, a fold) cannot inflate sigma and silence the channel.
    """
    t = np.asarray(t, dtype=np.float64)
    if t.size < 4:
        return 0.0, 1.0
    mag = np.abs(t)
    centre = float(np.median(mag))
    spread = 1.4826 * float(np.median(np.abs(mag - centre))) or float(np.std(t)) or 1e-9
    t = np.clip(t, -(centre + 5 * spread), centre + 5 * spread)
    mu = float(np.median(np.abs(t)))
    sigma = float(np.std(t)) or 1e-9
    for _ in range(iters):
        z = np.clip(2.0 * mu * t / (sigma * sigma), -50, 50)
        w = np.tanh(z / 2.0)                # E[sign | t]
        mu = max(float(np.mean(w * t)), 0.0)
        var = float(np.mean(t * t)) - mu * mu
        sigma = max(np.sqrt(max(var, 1e-18)), 1e-9)
    return mu, sigma


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


def decode_background(
    rectified: np.ndarray,
    valid: np.ndarray,
    master_render: np.ndarray,
    dpi: float,
    grid: PageGrid,
    slots: list[Slot],
) -> SoftBits:
    """Soft bits of the background channel for one page."""
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
    mu, sigma = estimate_mixture(t[seen])
    llr = 2.0 * mu * t / (sigma * sigma) if mu > 0 else np.zeros_like(t)
    pos, val = [], []
    for s in page_slots:
        b = s.ref[0]
        if not seen[b]:
            continue
        pos.append(s.positions[0])
        val.append(llr[b] * (1 - 2 * s.whiten[0]))
    snr = mu / sigma if sigma > 0 else 0.0
    return SoftBits(CHANNEL_BACKGROUND, np.array(pos), np.array(val),
                    {"page": grid.page, "bits_read": len(pos), "bits_total": len(page_slots),
                     "mu": mu, "sigma": sigma, "snr": snr, "cells_used": int(sel.sum())})
