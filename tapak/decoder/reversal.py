"""Reversal check: marks read against the direction every copy almost surely carries.

A coalition that knows TAPAK can reverse the marks where its copies agree instead of erasing
them (background cells negated, data units mirrored about their master position), or one copy
can reverse every mark it can read. Every unit then reads as clearly as in an honest copy, so
the erasure check (``decoder/erasure.py``) cannot see it, and on images the background decoder
reads a reversed pattern as no pattern (its pilot gain is negative), so the contradiction check
(``decoder/contradiction.py``) has too few clear positions left (``research/kontradiksi``). This
module notices the reversal itself, without ever looking at a codeword.

Idea. At code position i every copy carries bit 1 with probability p_i (the secret bias vector,
the same for every copy). Where p_i is near 0 or 1 the copies almost surely agree, and the
agreed bit is the one 2 p_i - 1 points to. An honest copy, and any coalition of at most three
copies that obeys the marking assumption, leaves bits that follow that direction on average; a
reversal of the agreeing marks turns them against it. Two statistics measure this, each from
the bias vector and the evidence alone.

* Pilot (images). The background decoder already computes, per page, the pilot sum
  S = sum_c e_c u_c over its despread cells u_c with e_c = (2 p - 1) times the cell's whitening
  sign (``ch_background.pilot_parts``). Without a pattern u_c = pn_c m_c with independent keyed
  random signs pn_c, so S is a Rademacher sum: given |e_c u_c| its sign pattern is symmetric,
  and by Hoeffding P(S <= -t sqrt(V)) <= exp(-t^2 / 2) with V = sum_c (e_c u_c)^2, whatever the
  noise. Pages are independent (their cell signs come from different keyed streams), so their
  sums add; two reads of the same page share the signs, and their variances are combined as
  (sum of sqrt(V))^2, which bounds the variance of their sum (Minkowski). The statistic is
  z_pilot = sum S / sqrt(sum over pages of (sum of sqrt(V))^2). With an honest pattern S has a
  positive mean (the decoder's presence test); with the agreeing cells reversed it is strongly
  negative.
* Signs (every channel). Over the fused read (weights w_i, decisions y_i) and d_i = |2 p_i - 1|,
  sigma_i = sign(2 p_i - 1): A = sum_i w_i d_i sigma_i (2 y_i - 1), B = sum_i (w_i d_i)^2, and
  z_signs = A / sqrt(B).

The bound for the signs. Condition on d (all |2 p_i - 1|); the bias law is symmetric, so every
sigma_i is a fair sign. For a coalition of c copies holding k ones at position i, an output
y = 1 with probability (1 + g(k)) / 2, g(0) = -1 and g(c) = 1 (marking assumption), gives
E[sigma (2 y - 1) | d] = (1/2) sum_k P(k | p+) (g(k) - g(c - k)) with p+ = (1 + d) / 2. For one
copy this is d, for two copies d (k = 1 pairs with itself), for three at least
P(3) - P(0) - P(2) + P(1) = d^3, so it is never negative for c <= 3, whatever g. Read errors
that do not depend on the code and flip each read with probability at most 1/2, independently
across positions, multiply it by 1 - 2 e >= 0. A strategy that looks at other positions does
not help: given the coalition's copies the signs sigma_i are independent with posteriors that
depend only on the coalition's bits at i, so the moment generating function of -A is at most
the product of the per-position maxima, which is that of a position-wise strategy. Every term
lies in [-w_i d_i, w_i d_i] and has a non-negative mean, so Hoeffding's lemma gives
P(z_signs <= -t) <= exp(-t^2 / 2), with no assumption on how well the weights are calibrated.
On unmarked evidence the read does not depend on the code at all and A is an exact Rademacher
sum in sigma, so the same bound holds for any read errors. For a coalition of four or more the
mean can turn negative where p is near 1/2 (four copies voting for the minority bit), so the
bound is stated for at most three.

Rule. Each statistic has the threshold -REVERSAL_Z with REVERSAL_Z = sqrt(2 ln(2 / r)),
r = REVERSAL_ALARM_RATE = 1e-3 split equally between them (5e-4 each, z = -3.90), so on honest
evidence the warning comes with probability at most about r. What is proven: the bound of
z_signs for unmarked evidence and, under the stated conditions on the read, for honest marked
evidence (a single copy or a coalition of at most three that obeys the marking assumption); the
bound of z_pilot for every page without a pattern. With an honest pattern on the page the pilot
sum has a positive mean (it is the decoder's presence test) but its self-normalized lower tail
is not proven, only measured (938 honest image pages never went below -2.8 in
``research/kontradiksi``; ``research/balik`` measures it again). As for the other checks the
probability is over the code draw and the reading noise, averaged over documents. The rate, the
split and the threshold were fixed before any measurement (``research/balik``). A missing
statistic (no image page, nothing read) is not computed and its share is unused.

What it does not see. A partial reversal that leaves fewer than half of the agreeing marks
reversed, or a randomization, keeps both statistics positive or near 0: the marks are weakened,
not reversed (the erasure check is the one that can see that). A coalition that drops the
background and reverses only half of the shift units at random keeps A near 0. Neither changes a
score, a threshold or the verdict, and neither names anyone; the warning never names anyone
either.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from tapak.decoder.fuse import FusedEstimate
from tapak.decoder.softbits import SoftBits
from tapak.marker.plan import CHANNEL_BACKGROUND

REVERSAL_ALARM_RATE = 1e-3
REVERSAL_STATISTICS = ("pilot", "tanda")
REVERSAL_Z = math.sqrt(2.0 * math.log(len(REVERSAL_STATISTICS) / REVERSAL_ALARM_RATE))
REVERSAL_MAX_COALITION = 3  # the largest honest coalition the bound covers, whatever the code's c
# The finding as the merged warning states it (``decoder/manipulation.py``).
REVERSAL_NOTE = "tanda di posisi yang hampir pasti sama di semua salinan terbaca terbalik (pola tanda terbalik)"


@dataclass
class ReversalCheck:
    """Outcome of the reversal check of one trace.

    Attributes:
        z_pilot: the joint pilot statistic over the image pages (None without an image page).
        pilot_pages: background outputs (image pages) that went into ``z_pilot``.
        z_signs: A / sqrt(B) over the fused read (None when nothing was read).
        positions: code positions with weight above 0 in the fused read.
        threshold: alarm when a statistic is at or below this (negative).
        alarm_rate: false-alarm bound of the whole check on honest evidence.
        flagged: True when the warning is raised.
    """

    z_pilot: float | None
    pilot_pages: int
    z_signs: float | None
    positions: int
    threshold: float
    alarm_rate: float
    flagged: bool

    def text(self) -> str:
        """One line for reports: both statistics with what they rest on, and the threshold."""
        thr = _num(self.threshold)
        parts = []
        if self.z_pilot is not None:
            parts.append(f"z pilot = {_num(self.z_pilot)} dari {self.pilot_pages} halaman gambar")
        if self.z_signs is not None:
            parts.append(f"z tanda = {_num(self.z_signs)} dari {_count(self.positions)} posisi terbaca")
        if not parts:
            return "tidak diperiksa: tidak ada tanda yang terbaca"
        if len(parts) == 2:
            return f"{parts[0]} dan {parts[1]}, ambang {thr} untuk masing-masing"
        return f"{parts[0]}, ambang {thr}"


def _num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def pilot_statistic(observations: list[SoftBits]) -> tuple[float | None, int]:
    """(z_pilot, outputs used) from the pilot sums the background decoder reports on images
    (``pilot_sum``, ``pilot_var``); None when no output carries one or every variance is 0.

    Outputs of the same master page share their keyed cell signs, so their sums are added and
    their spreads combined as the sum of sqrt(V) (a bound on the spread of the sum); pages are
    independent and their variances add."""
    sums: dict[object, float] = defaultdict(float)
    spreads: dict[object, float] = defaultdict(float)
    used = 0
    for sb in observations:
        if sb.channel != CHANNEL_BACKGROUND or "pilot_sum" not in sb.meta:
            continue
        var = float(sb.meta["pilot_var"])
        if not math.isfinite(var) or var < 0:
            raise ValueError("varians pilot tidak sah")
        page = sb.meta.get("page")
        sums[page] += float(sb.meta["pilot_sum"])
        spreads[page] += math.sqrt(var)
        used += 1
    total = sum(s * s for s in spreads.values())
    if used == 0 or total <= 0:
        return None, used
    return sum(sums.values()) / math.sqrt(total), used


def sign_statistic(fused: FusedEstimate, p: np.ndarray) -> tuple[float | None, int]:
    """(z_signs, positions read): A / sqrt(B) with A = sum w d sigma (2 y - 1) and
    B = sum (w d)^2 over the fused read, d = |2 p - 1|, sigma = sign(2 p - 1); None when B is 0."""
    p = np.asarray(p, dtype=np.float64)
    w = np.asarray(fused.weights, dtype=np.float64)
    if w.shape != p.shape:
        raise ValueError("bobot dan p harus berukuran sama")
    a = w * (2.0 * p - 1.0)
    signs = 2.0 * np.asarray(fused.y, dtype=np.float64) - 1.0
    b = float(np.sum(a * a))
    observed = int(np.count_nonzero(w > 0))
    if b <= 0:
        return None, observed
    return float(np.sum(a * signs)) / math.sqrt(b), observed


def reversal_check(observations: list[SoftBits], fused: FusedEstimate, p: np.ndarray) -> ReversalCheck:
    """Run the check on a trace's observations and fused read with the document's bias vector
    (no codeword). Warns when either statistic is at or below -REVERSAL_Z."""
    z_pilot, pages = pilot_statistic(observations)
    z_signs, positions = sign_statistic(fused, p)
    threshold = -REVERSAL_Z
    flagged = any(z is not None and z <= threshold for z in (z_pilot, z_signs))
    return ReversalCheck(None if z_pilot is None else round(z_pilot, 4), pages,
                         None if z_signs is None else round(z_signs, 4), positions, threshold,
                         REVERSAL_ALARM_RATE, flagged)


def reversal_note(check: ReversalCheck) -> str:
    """The warning shown next to the verdict for a flagged check alone: the merged warning of
    ``decoder/manipulation.py`` with this finding only."""
    from tapak.decoder.manipulation import manipulation_note

    note = manipulation_note(None, None, check)
    if note is None:
        raise ValueError("pemeriksaan pola tanda terbalik tidak berbunyi")
    return note


__all__ = [
    "REVERSAL_ALARM_RATE",
    "REVERSAL_MAX_COALITION",
    "REVERSAL_NOTE",
    "REVERSAL_STATISTICS",
    "REVERSAL_Z",
    "ReversalCheck",
    "pilot_statistic",
    "reversal_check",
    "reversal_note",
    "sign_statistic",
]
