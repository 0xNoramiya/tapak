"""Check for erasure aimed at the positions where the colluders' copies agree.

A coalition that knows TAPAK can compare its copies and neutralize the marks exactly where
they are identical (flatten the background cells; put data groups back on the line through
their control neighbours under geser-v1, or every agreeing word group back at its master
position estimated from the word gaps under geser-v2), keeping the rest. That is outside the
marking assumption and the proven miss bound does not cover it (``tapak.tardos.detection``,
``research/sepakat``). This module lets the decoder notice it without ever looking at a
codeword.

Idea. At code position i the coalition's copies agree with probability p_i^c + (1 - p_i)^c,
which rises with q_i = (2 p_i - 1)^2 for every coalition size (for c = 2 and 3 it is exactly
linear in q_i). An erasure that follows agreement therefore removes the marks of high-q
positions more often than those of low-q positions. Channel noise cannot do that: the bias
vector p is secret, the slots are matched to positions by a keyed permutation and the
whitened marks look the same for every bit, so how clearly a unit is read (its strength,
``softbits.Strengths``) does not depend on p. The shift strength is a unit's offset in noise
units: under geser-v1 from the line through its two control neighbours (|s| / sigma), under
geser-v2 from the row line fitted to the other groups of its row once their expected marks are
taken off (``ch_shift.joint_strengths``); rows keep |s| / sigma in both. The statistic is the
correlation between the strengths and q over the positions measured:

* every channel output (one ``SoftBits``) turns each of its strength measures into
  standardized rank scores ((rank - 1/2) / n - 1/2) * sqrt(12), ties sharing their mean rank,
  so channels with very different noise scales count alike and outliers cannot dominate (the
  background reports two measures: |despread mean|, which drops when an agreeing position is
  flattened or its cells get random signs, and cell energy, which drops when it is flattened
  even if the coalition gives the cells of its disagreeing positions random signs);
* the scores of all units on the same position are added: C_i;
* Z = r(C, q) * sqrt(n - 1), r the Pearson correlation over the n measured positions.

Under honest evidence (strengths independent of p) the q values at the measured positions are
independent draws from the code's bias law, independent of the scores; then r has mean 0 and
variance exactly 1 / (n - 1) whatever the strengths, so Z has mean 0 and variance 1, close to a
standard normal for the hundreds to thousands of positions of a page. A deliberate erasure of
agreeing positions makes Z strongly negative. The warning is raised when Z <= -ERASURE_Z, with
ERASURE_Z the normal quantile for ERASURE_ALARM_RATE (1e-3, fixed before any measurement)
times the calibration factor ERASURE_CALIBRATION, the standard deviation of Z on honest
development evidence (single copies through photo, screenshot, print and PDF;
``research/sepakat``), rounded up and at least 1 (measured: 1.00 over 232 evidence, so 1).
Fewer than ERASURE_MIN_POSITIONS measured positions: no check.

The rate holds on average over the draw of the code. For one document it does not: part of
the strength pattern is the same in every copy of that document (how well each slot can be
read, and at near-certain positions the same whitened sign in every copy), so honest Z of one
document is centred on an offset rather than on 0. Measured offsets per issuance and channel
ranged from -1.4 to +1.7 over 14 issuances, most spread out on forwarded PDFs (between-issuance
standard deviation about 0.75), so for an unlucky document the rate is a few percent; 2 of
856 honest evidence raised the warning (``research/sepakat``, ``balik.py``). Under geser-v2,
with the shift strengths of ``ch_shift.joint_strengths`` and the same threshold, fresh seeds
gave no warning on 644 honest evidence (480 copies of 12 issuances through PDF, screenshot,
photo and print, 36 unmarked masters, 128 README benchmark traces): standard deviation of Z
0.96, per-issuance means -0.93 to +0.69 (``research/sepakat/geser2.py``, parts ``jujur`` and
``jujur-tinjauan``).

What it does not do. It never changes a threshold, a score or the verdict and never names
anyone. It only sees erasures that follow agreement; a coalition that erases at random (or
everything) is not flagged, and then the proven bound applies to the positions still read. It
does not see marks that were removed so thoroughly that the unit was not measured at all
(for example a word group cut out of the page).

It does not stop a coalition that knows it (``research/sepakat/balik.py``). Reversing the
agreeing marks instead of erasing them (background cells negated, data units mirrored about
their master position) leaves every unit as clearly marked as in an honest copy, so Z stays
near 0 or turns positive, and the coalition escapes all the same; the proven bound does not
cover a reversal either. Flattening the whole background and erasing only the agreeing shift
units also passes: the strengths of the unmarked background (thousands of positions that
carry only noise) drown the shift units. For the same reason the check is blind on prints,
where the default background never reaches the paper: also under geser-v2, whose prints now
carry enough shift positions to name a copy, it flagged 1 of 36 erased prints, while the
shift units alone would have flagged 19. The geser-v2 shift strengths are also a weaker
detector than the geser-v1 ones: where most groups of a row are back at their master
positions, the row's offset makes them look like groups that all moved one way, so on their
own they flagged 32 of 36 erased PDFs but only 13 of 36 screenshots and 6 of 36 photos; the
warning there comes mostly from the background.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np

from tapak.decoder.softbits import SoftBits
from tapak.marker.plan import CHANNEL_BACKGROUND, PHYSICAL_CHANNEL

ERASURE_ALARM_RATE = 1e-3
ERASURE_CALIBRATION = 1.0
ERASURE_Z = NormalDist().inv_cdf(1.0 - ERASURE_ALARM_RATE) * ERASURE_CALIBRATION
ERASURE_MIN_POSITIONS = 100
# Background strengths enter the statistic only from pages on which the background decoder saw
# its pattern (``research/kontradiksi``, part 4: on a print the default pattern never reaches the
# paper, and thousands of noise-only background strengths drowned the shift units). Two readings
# of "saw" were fixed before any run; the one named here was chosen on development seeds by the
# rule written there, and ``"semua"`` keeps every background strength, as before:
#   "pola": the decoder's own decision (``pattern_found``: a presence test passed and, on images,
#           the pilot gave a positive gain);
#   "uji":  a presence test passed (``presence``), whatever the gain.
SILENT_BACKGROUND_RULE = "pola"
SILENT_BACKGROUND_RULES = ("pola", "uji", "semua")
ERASURE_NOTE = ("pola penghapusan disengaja terdeteksi: kemungkinan koalisi yang memahami TAPAK; bukti di posisi "
                "tempat salinan koalisi sama dihapus")


@dataclass
class ErasureCheck:
    """Outcome of the erasure check of one trace.

    Attributes:
        z: the statistic (None when fewer than ``ERASURE_MIN_POSITIONS`` positions were measured).
        positions: code positions with at least one strength.
        threshold: alarm when z <= threshold (negative).
        alarm_rate: nominal false-alarm probability on honest evidence.
        flagged: True when the warning is raised.
        units: measured units per physical channel.
    """

    z: float | None
    positions: int
    threshold: float
    alarm_rate: float
    flagged: bool
    units: dict[str, int] = field(default_factory=dict)

    def text(self) -> str:
        """One line for reports: 'z = -12,3 (ambang -3,09; 2.987 posisi)' or why it was not run."""
        if self.z is None:
            return f"tidak diperiksa: hanya {self.positions} posisi terukur (minimal {ERASURE_MIN_POSITIONS})"
        z = f"{self.z:.2f}".replace(".", ",")
        thr = f"{self.threshold:.2f}".replace(".", ",")
        n = f"{self.positions:,}".replace(",", ".")
        return f"z = {z} (ambang {thr}; {n} posisi terukur)"


def erasure_note(check: ErasureCheck) -> str:
    """The warning shown next to the verdict for a flagged check: ``ERASURE_NOTE`` and the numbers."""
    return (f"{ERASURE_NOTE}. Ini hanya peringatan: putusan, ambang, dan skor tidak berubah, dan pemeriksaan ini "
            f"tidak menunjuk siapa pun ({check.text()}; peluang alarm palsu pada bukti jujur rata-rata sekitar "
            f"{format_rate(check.alarm_rate)}, untuk dokumen tertentu dapat sampai beberapa persen)")


def format_rate(rate: float) -> str:
    """'10^-3' for a power of ten, otherwise the number with a decimal comma."""
    e = math.log10(rate)
    return f"10^{int(round(e))}" if abs(e - round(e)) < 1e-9 else f"{rate:.2g}".replace(".", ",")


def agreement_score(p: np.ndarray) -> np.ndarray:
    """q = (2 p - 1)^2 per code position: the direction in which the chance that a coalition's
    copies agree grows (p^2 + (1 - p)^2 = (1 + q) / 2, p^3 + (1 - p)^3 = (1 + 3 q) / 4)."""
    p = np.asarray(p, dtype=np.float64)
    return (2.0 * p - 1.0) ** 2


def rank_scores(values: np.ndarray) -> np.ndarray:
    """Standardized rank scores ((rank - 1/2) / n - 1/2) * sqrt(12), ties at their mean rank;
    mean 0 and variance close to 1 for distinct values."""
    from scipy.stats import rankdata

    v = np.asarray(values, dtype=np.float64)
    if v.size == 0:
        return v
    u = (rankdata(v, method="average") - 0.5) / v.size
    return (u - 0.5) * math.sqrt(12.0)


def background_pattern_seen(meta: Mapping[str, object], rule: str = SILENT_BACKGROUND_RULE) -> bool:
    """Whether a background channel output saw its pattern, by ``rule`` (``SILENT_BACKGROUND_RULES``).

    A decision the background decoder has already made without any codeword; an output that
    does not record it (older observations, other channels) counts as seen.
    """
    if rule not in SILENT_BACKGROUND_RULES:
        raise ValueError(f"aturan latar tidak dikenal: {rule!r}")
    if rule == "semua":
        return True
    key = "pattern_found" if rule == "pola" else "presence"
    return bool(meta.get(key, True))


def position_scores(observations: list[SoftBits], m: int,
                    rule: str = SILENT_BACKGROUND_RULE) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """(positions, summed rank score per position, units per physical channel) of all strengths.

    Every measure (column) of a channel output is ranked on its own. A measure whose values
    are all equal (an exact digital read) carries no information about erasure and is left out,
    and so are the strengths of a background output that did not see its pattern
    (:func:`background_pattern_seen` with ``rule``).
    """
    total = np.zeros(m)
    seen = np.zeros(m, dtype=bool)
    units: dict[str, int] = {}
    for sb in observations:
        st = sb.strengths
        if st is None or len(st) < 2:
            continue
        if sb.channel == CHANNEL_BACKGROUND and not background_pattern_seen(sb.meta, rule):
            continue
        if st.positions.min() < 0 or st.positions.max() >= m:
            raise ValueError(f"kanal {sb.channel}: posisi kekuatan di luar [0, {m})")
        used = False
        for column in st.values.T:
            if float(np.ptp(column)) <= 0.0:
                continue
            np.add.at(total, st.positions, rank_scores(column))
            used = True
        if used:
            seen[st.positions] = True
            name = PHYSICAL_CHANNEL.get(sb.channel, sb.channel)
            units[name] = units.get(name, 0) + len(st)
    pos = np.flatnonzero(seen)
    return pos, total[pos], units


def erasure_z(scores: np.ndarray, q: np.ndarray) -> float:
    """Z = r(scores, q) * sqrt(n - 1); 0 when either side has no spread."""
    a = np.asarray(scores, dtype=np.float64)
    b = np.asarray(q, dtype=np.float64)
    n = a.size
    if n < 3:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
    if den <= 0.0:
        return 0.0
    return float(np.sum(a * b) / den) * math.sqrt(n - 1)


def erasure_check(observations: list[SoftBits], p: np.ndarray, rule: str = SILENT_BACKGROUND_RULE) -> ErasureCheck:
    """Run the check on a trace's observations with the document's bias vector (no codeword).

    ``rule`` decides which background outputs count (:func:`background_pattern_seen`); research
    passes ``"semua"`` to reproduce the check as it was before.
    """
    p = np.asarray(p, dtype=np.float64)
    pos, scores, units = position_scores(observations, p.size, rule)
    threshold = -ERASURE_Z
    if pos.size < ERASURE_MIN_POSITIONS:
        return ErasureCheck(None, int(pos.size), threshold, ERASURE_ALARM_RATE, False, units)
    z = erasure_z(scores, agreement_score(p)[pos])
    return ErasureCheck(round(z, 4), int(pos.size), threshold, ERASURE_ALARM_RATE, z <= threshold, units)


__all__ = [
    "ERASURE_ALARM_RATE",
    "ERASURE_MIN_POSITIONS",
    "ERASURE_NOTE",
    "ERASURE_Z",
    "ErasureCheck",
    "SILENT_BACKGROUND_RULE",
    "agreement_score",
    "background_pattern_seen",
    "erasure_check",
    "erasure_note",
    "erasure_z",
    "format_rate",
    "position_scores",
    "rank_scores",
]
