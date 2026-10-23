"""Contradiction check: a clear read that names nobody.

``tapak.tardos.detection`` proves, for the weights of one read, a bound B on the probability
that no member of a coalition of at most c recipients reaches the stage-1 threshold Z(p, w)
(``read_miss_ceiling``). The bound holds for every collusion strategy that obeys the marking
assumption, under two conditions on the channel: (C1) the read's noise acts after the coalition
chose its bits and does not depend on the code, and (C2) given the weights, read errors are
independent across positions with rates at most the ceilings used. When the read names nobody
although its own weights make B tiny, the read contradicts that premise: either the marks were
changed where the colluders' copies agree (reversed or randomized by someone who knows TAPAK,
which the erasure check of ``decoder/erasure.py`` cannot see because every mark still reads
clearly), or the coalition is larger than c, or the channel broke (C1) or (C2) (a reading
problem). This module raises a warning in that case. It never names anyone and never changes a
threshold, a score or the verdict.

Rule. After the accusation (all stages), and only when nobody is named, compute
B = max over c' = 1..c of ``read_miss_ceiling`` for the fused weights w and the rate ceilings
``tempered_error_rates(L, CONTRADICTION_TEMPERING)`` of the fused LLRs L, at the stage-1 eps1 the
accusation actually used. Warn when B <= CONTRADICTION_RATE. A name at a later stage needs a
name at stage 1, so "nobody named" is exactly "no copy reached the stage-1 threshold".

False alarms. For honest evidence (any coalition of at most c that obeys the marking
assumption, a single leaker included) under (C1) and (C2),

    P(warning) = E[ 1{B <= r} P(no member reaches Z | |L|) ] <= E[ 1{B <= r} B ] <= r,

with r = CONTRADICTION_RATE, because the bound holds conditionally on the fused |L| (which fixes
both the weights w = tanh(|L| / 2) and the ceilings, and is channel randomness alone under (C1);
the weights alone do not fix the ceilings where w rounds to 1) and B is a function of |L| alone.
The probability is over the code draw, the coalition's randomness and the channel, as for the
detection bound: for one document and one coalition the rate can be higher, while its average
over documents stays at most r. The rate is fixed before any measurement
(``research/kontradiksi``): 1e-3, the erasure check's rate. Whether the decoder's LLRs are calibrated is measured, not
assumed: the ceilings temper every fused LLR by CONTRADICTION_TEMPERING, a factor fixed on
development seeds only, so that the tempered rates cover the error rates measured per medium.
Measured on 30 honest copies of three development issuances through seven media
(``research/kontradiksi``, part ``kalibrasi``): forwarded PDFs make no error, photos and
screenshots are close to calibrated below |L| = 4 and overconfident above it (screenshots: 35
wrong of 51,154 positions at |L| >= 12, where a calibrated LLR predicts 0.3), and printed pages
are the worst (the shift channel alone: 26 wrong of 2,741 at |L| >= 12, about 1 %, mostly whole
rows read with the wrong offset). The largest factor whose tempered rates cover every medium
and |L| bin by the rule fixed before the run is 0.3, so a PDF mark read at |L| = 12 is treated as
wrong with probability 2.7 %.

Cost. The bound is evaluated on at most ``CONTRADICTION_BOXES`` weight boxes, for the largest
coalition first, and stops as soon as one coalition size is above the rate (that already rules
the warning out); a few tenths of a second per trace, and nothing when someone is named.

What it does not see. Anything that lowers the weights: an erasure (flagged by the erasure
check when it follows the colluders' agreement), a whole channel dropped (for example the
background pattern image removed from a PDF, or a background that the image decoder discards
because its bias pilot reads the reversed pattern as no pattern), or degradation that leaves too
few clear positions for a guarantee against c colluders. Then B is large and the check is
silent, and a reversal or randomization of what remains escapes this check (a reversal is
what the reversal check of ``decoder/reversal.py`` looks for, from the direction of the marks).
What the checks find is one merged warning (``decoder/manipulation.py``).

Measured on held-out seeds (``research/kontradiksi``, part ``sadar``: 36 coalitions of 2 and 3
copies per channel, geser-v1 and v2): reversing the agreeing marks of a forwarded PDF is flagged
36 of 36 times (bound at most 6e-7), and one copy reversing all its own marks 18 of 18 times.
Reversal through a screenshot, a photo or a print escapes 36 of 36 times: the image background
decoder reads a reversed pattern as no pattern, and some 220 shift positions are too few for a
guarantee against three colluders. Randomized marks (a random sign per cell), partial reversal
(an oracle-guided 40 to 45 % of the cells and units, just enough that nobody is named) and a
dropped background escape on every channel. No false accusation in 846 traces. Honest evidence
(part ``jujur``: single copies, standard coalitions of 2 and 3 and unmarked masters through seven
media) raised no warning in 678 traces; of the 177 that named nobody, mostly prints, none had a
bound below 1. Honest coalitions of 4 to 6 (part ``besar``, one of the causes the warning names)
raised it on 12 of the 41 traces that named nobody, all screenshots and photos. The check took a
median 0.25 s on the 1,408 held-out traces that named nobody.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from tapak.decoder.erasure import format_rate
from tapak.decoder.fuse import FusedEstimate
from tapak.tardos.detection import proven_read_miss_ceiling, tempered_error_rates
from tapak.tardos.params import TardosParams

CONTRADICTION_RATE = 1e-3
CONTRADICTION_TEMPERING = 0.3
CONTRADICTION_BOXES = 64
# The finding as the merged warning states it (``decoder/manipulation.py``).
CONTRADICTION_NOTE = "bukti terbaca jelas, tetapi tidak ada salinan yang mencapai ambang (bacaan jelas tanpa nama)"


@dataclass
class ContradictionCheck:
    """Outcome of the contradiction check of one trace (run only when nobody was named).

    Attributes:
        log10_bound: log10 of the proven bound B on P(no member of a coalition of at most
            ``coalition`` reaches the stage-1 threshold | the read's weights), at most 0. When
            ``complete`` is False the search stopped at the first coalition size whose bound was
            above ``rate``; the maximum is then at least this value.
        complete: True when every coalition size 1..c was evaluated.
        coalition: c, the largest coalition the bound covers.
        rate: warning when the bound is at most this (also the false-alarm bound).
        tempering: factor applied to every fused LLR for the error-rate ceilings.
        observed: positions with weight above 0.
        effective: sum of the squared weights.
        eps1: stage-1 per-recipient target that set the threshold.
        flagged: True when the warning is raised.
    """

    log10_bound: float
    complete: bool
    coalition: int
    rate: float
    tempering: float
    observed: int
    effective: float
    eps1: float
    flagged: bool

    @property
    def bound(self) -> float:
        """The bound B as a probability (0 when it underflows a float)."""
        return 10.0 ** self.log10_bound

    def text(self) -> str:
        """One line for reports: the bound, the warning level and the positions read."""
        n = f"{self.observed:,}".replace(",", ".")
        rate = format_rate(self.rate)
        if not self.complete:
            return (f"batas di atas {rate} (koalisi {self.coalition} orang: {format_bound(self.log10_bound)}; "
                    f"{n} posisi terbaca)")
        side = "tidak lebih dari" if self.flagged else "di atas"
        return (f"batas {format_bound(self.log10_bound)} untuk koalisi paling banyak {self.coalition} orang, {side} "
                f"{rate} ({n} posisi terbaca)")


def format_bound(log10_b: float) -> str:
    """An upper bound in Indonesian notation, mantissa rounded up: '1', '0,42', '2,1 x 10^-9'."""
    if log10_b >= 0:
        return "1"
    if log10_b == -math.inf:
        return "0"
    if log10_b > -2:
        value = math.ceil(10 ** log10_b * 100) / 100
        return "1" if value >= 1 else f"{value:.2f}".replace(".", ",")
    e = math.floor(log10_b)
    mant = math.ceil(10 ** (log10_b - e) * 10) / 10
    if mant >= 10:
        mant, e = mant / 10, e + 1
    return f"{mant:.1f}".replace(".", ",") + f" x 10^{e}"


def contradiction_check(fused: FusedEstimate, params: TardosParams, eps1: float, named: bool) -> ContradictionCheck | None:
    """Run the check on a trace's fused read (None when someone was named, at any stage).

    ``eps1`` is the stage-1 per-recipient target the accusation used (``ThresholdRecord.eps1``),
    so the bound refers to the threshold that decided "nobody named". Uses the bias law and the
    fused weights and LLRs only, never a codeword.
    """
    if named:
        return None
    w = np.asarray(fused.weights, dtype=np.float64)
    observed = int(np.count_nonzero(w > 0))
    effective = float(np.sum(w * w))
    if observed == 0:
        return ContradictionCheck(0.0, True, params.c, CONTRADICTION_RATE, CONTRADICTION_TEMPERING, 0, 0.0, eps1,
                                  False)
    ceilings = tempered_error_rates(fused.llr, CONTRADICTION_TEMPERING)
    bound = proven_read_miss_ceiling(params, w, ceilings, eps1=eps1, boxes=CONTRADICTION_BOXES,
                                     stop_above=CONTRADICTION_RATE)
    complete = bound <= CONTRADICTION_RATE
    log10_b = math.log10(bound) if bound > 0 else -math.inf
    return ContradictionCheck(log10_b, complete, params.c, CONTRADICTION_RATE, CONTRADICTION_TEMPERING, observed,
                              round(effective, 1), eps1, complete)


def contradiction_note(check: ContradictionCheck) -> str:
    """The warning shown next to the verdict for a flagged check alone: the merged warning of
    ``decoder/manipulation.py`` with this finding only (the bound, the possible causes, the rate
    and that nothing changes)."""
    from tapak.decoder.manipulation import manipulation_note

    note = manipulation_note(None, check, None)
    if note is None:
        raise ValueError("pemeriksaan bacaan jelas tanpa nama tidak berbunyi")
    return note


__all__ = [
    "CONTRADICTION_BOXES",
    "CONTRADICTION_NOTE",
    "CONTRADICTION_RATE",
    "CONTRADICTION_TEMPERING",
    "ContradictionCheck",
    "contradiction_check",
    "contradiction_note",
    "format_bound",
]
