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
agreeing positions makes Z strongly negative. The warning is raised when Z <= -ERASURE_Z for
one of the two statistics below, with ERASURE_Z the normal quantile for ERASURE_ALARM_RATE / 2
(the rate, 1e-3, fixed before any measurement, split between the two) times the calibration
factor ERASURE_CALIBRATION, the standard deviation of Z on honest development evidence (single
copies through photo, screenshot, print and PDF; ``research/sepakat``), rounded up and at least
1 (measured: 1.00 over 232 evidence, so 1). Until ``research/balik`` there was one statistic,
with the quantile of the whole rate (z = -3.09). Fewer than ERASURE_MIN_POSITIONS measured
positions: that statistic is not computed.

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
cover a reversal either (the reversal check of ``decoder/reversal.py`` and, on a forwarded PDF,
the contradiction check of ``decoder/contradiction.py`` look for it instead; randomized marks
and a partial reversal stay outside all three). Flattening the whole background and erasing only the agreeing shift
units also passes: the strengths of the unmarked background (thousands of positions that
carry only noise) drowned the shift units. For the same reason the check was blind on prints,
where the default background never reaches the paper: under geser-v2 it flagged 1 of 36
erased prints, while the shift units alone would have flagged 19. Since
``research/kontradiksi`` the strengths of a background output count only when the background
decoder saw its pattern on that page (``SILENT_BACKGROUND_RULE``, "pola"). On held-out seeds (36
coalitions of 2 and 3 copies per channel, geser-v1 and v2) that rule flagged erased prints 16 of
36 times (before: 0), but erased PDFs 29 (36), screenshots 22 (36) and photos 19 (31): there
the background left by the attack is often not found (a random member per cell where the
copies differ leaves no coherent pattern, and flattened cells make the decoder's noise
estimate collapse), while its strengths showed the erased cells. Overall 86 of 144 erased
evidence was flagged, 103 under the old rule ("semua"). The geser-v2 shift strengths are also a
weaker detector than the geser-v1 ones: where most groups of a row are back at their master
positions, the row's offset makes them look like groups that all moved one way, so on their
own they flagged 32 of 36 erased PDFs but only 13 of 36 screenshots and 6 of 36 photos; the
warning there comes mostly from the background.

Two statistics (``research/balik``). Each rule sees what the other misses, so the check now
computes Z under both, "pola" and "semua" (``ERASURE_RULES``), and warns when either is at or
below its threshold. The alarm rate is split between them: each statistic has the threshold of
ERASURE_ALARM_RATE / 2 (5e-4, z = -3.29 times the calibration factor), so by the union bound the
check as a whole keeps the nominal rate ERASURE_ALARM_RATE on honest evidence, under the same
argument as before (each Z has mean 0 and variance 1 when the strengths do not depend on p).
Where no background output missed its pattern the two statistics are the same number and the
check is simply a little stricter. The split and the rules were fixed before any measurement
of ``research/balik``. A caller can still ask for one rule (``rules="semua"``), which then gets
the whole rate, as before.
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
ERASURE_MIN_POSITIONS = 100
# Background strengths enter the statistic only from pages on which the background decoder saw
# its pattern (``research/kontradiksi``, part 4: on a print the default pattern never reaches the
# paper, and thousands of noise-only background strengths drowned the shift units). Two readings
# of "saw" were fixed before any run; the one named here was chosen on development seeds by the
# rule written there (both flagged 24 of 48 erased development evidence with no honest alarm,
# so the tie went to "pola"), and ``"semua"`` keeps every background strength, as before:
#   "pola": the decoder's own decision (``pattern_found``: a presence test passed and, on images,
#           the pilot gave a positive gain);
#   "uji":  a presence test passed (``presence``), whatever the gain.
SILENT_BACKGROUND_RULE = "pola"
SILENT_BACKGROUND_RULES = ("pola", "uji", "semua")
# The shipped check computes both statistics and splits ERASURE_ALARM_RATE between them
# (``research/balik``, fixed before any of its runs): the first is ``ErasureCheck.z``, the
# second ``ErasureCheck.z_all``.
ERASURE_RULES = (SILENT_BACKGROUND_RULE, "semua")
# The finding as the merged warning states it (``decoder/manipulation.py``).
ERASURE_NOTE = "tanda hilang justru di posisi tempat salinan koalisi kemungkinan sama (pola penghapusan)"


def erasure_threshold(statistics: int = len(ERASURE_RULES)) -> float:
    """The magnitude of the threshold of each of ``statistics`` statistics that share
    ERASURE_ALARM_RATE: the normal quantile for ERASURE_ALARM_RATE / statistics times
    ERASURE_CALIBRATION (3.29 for two, 3.09 for one)."""
    if statistics < 1:
        raise ValueError("jumlah statistik minimal 1")
    return NormalDist().inv_cdf(1.0 - ERASURE_ALARM_RATE / statistics) * ERASURE_CALIBRATION


ERASURE_Z = erasure_threshold()


@dataclass
class ErasureCheck:
    """Outcome of the erasure check of one trace.

    Attributes:
        z: the statistic under the first rule (``SILENT_BACKGROUND_RULE`` for the shipped check;
            None when fewer than ``ERASURE_MIN_POSITIONS`` positions were measured).
        positions: code positions with at least one strength under that rule.
        threshold: alarm when a statistic is at or below this (negative); every statistic of
            the check has the same threshold.
        alarm_rate: nominal false-alarm probability of the whole check on honest evidence.
        flagged: True when the warning is raised (either statistic at or below the threshold).
        units: measured units per physical channel under the first rule.
        z_all: the statistic under "semua", every background strength counted (None when it was
            not computed or too few positions were measured).
        positions_all: code positions with at least one strength under "semua" (0 when not
            computed).
    """

    z: float | None
    positions: int
    threshold: float
    alarm_rate: float
    flagged: bool
    units: dict[str, int] = field(default_factory=dict)
    z_all: float | None = None
    positions_all: int = 0

    @property
    def measured(self) -> bool:
        """True when at least one statistic was computed."""
        return self.z is not None or self.z_all is not None

    def text(self) -> str:
        """One line for reports: 'z = -12,30 dari 2.987 posisi terukur, ambang -3,29', both
        statistics when they differ, or why the check was not run."""
        thr = _num(self.threshold)
        single = self.z_all is None or (self.positions == self.positions_all and self.z == self.z_all)
        if single and self.z is not None:
            return f"z = {_num(self.z)} dari {_count(self.positions)} posisi terukur, ambang {thr}"
        if not self.measured:
            n = max(self.positions, self.positions_all)
            return f"tidak diperiksa: hanya {_count(n)} posisi terukur (minimal {ERASURE_MIN_POSITIONS})"
        first = (f"z = {_num(self.z)} dari halaman berpola ({_count(self.positions)} posisi)" if self.z is not None
                 else f"halaman berpola tidak diperiksa ({_count(self.positions)} posisi)")
        second = (f"z = {_num(self.z_all)} dengan semua kekuatan baca latar ({_count(self.positions_all)} posisi)"
                  if self.z_all is not None
                  else f"semua kekuatan baca latar tidak diperiksa ({_count(self.positions_all)} posisi)")
        return f"{first} dan {second}, ambang {thr} untuk masing-masing"


def _num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def erasure_note(check: ErasureCheck) -> str:
    """The warning shown next to the verdict for a flagged check alone: the merged warning of
    ``decoder/manipulation.py`` with this finding only."""
    from tapak.decoder.manipulation import manipulation_note

    note = manipulation_note(check, None, None)
    if note is None:
        raise ValueError("pemeriksaan pola penghapusan tidak berbunyi")
    return note


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


def erasure_statistic(observations: list[SoftBits], p: np.ndarray,
                      rule: str = SILENT_BACKGROUND_RULE) -> tuple[float | None, int, dict[str, int]]:
    """(Z, measured positions, units per physical channel) of one rule; Z is None when fewer
    than ``ERASURE_MIN_POSITIONS`` positions were measured. Uses the bias vector, no codeword."""
    p = np.asarray(p, dtype=np.float64)
    pos, scores, units = position_scores(observations, p.size, rule)
    if pos.size < ERASURE_MIN_POSITIONS:
        return None, int(pos.size), units
    return erasure_z(scores, agreement_score(p)[pos]), int(pos.size), units


def erasure_check(observations: list[SoftBits], p: np.ndarray,
                  rules: str | tuple[str, ...] = ERASURE_RULES) -> ErasureCheck:
    """Run the check on a trace's observations with the document's bias vector (no codeword).

    ``rules`` are the background rules of the statistics (:func:`background_pattern_seen`), one
    or two; they share ERASURE_ALARM_RATE (:func:`erasure_threshold`) and the warning is raised
    when either statistic is at or below the threshold. The shipped check uses ``ERASURE_RULES``
    ("pola" and "semua"); research passes one rule, for example ``"semua"``, to reproduce the
    check as it was before (``z_all`` is then None).
    """
    if isinstance(rules, str):
        rules = (rules,)
    if not 1 <= len(rules) <= 2:
        raise ValueError("pemeriksaan pola penghapusan memakai satu atau dua aturan latar")
    threshold = -erasure_threshold(len(rules))
    stats = [erasure_statistic(observations, p, rule) for rule in rules]
    flagged = any(z is not None and z <= threshold for z, _, _ in stats)
    z, positions, units = stats[0]
    z_all, positions_all = (stats[1][0], stats[1][1]) if len(stats) == 2 else (None, 0)
    return ErasureCheck(None if z is None else round(z, 4), positions, threshold, ERASURE_ALARM_RATE, flagged, units,
                        None if z_all is None else round(z_all, 4), positions_all)


__all__ = [
    "ERASURE_ALARM_RATE",
    "ERASURE_MIN_POSITIONS",
    "ERASURE_NOTE",
    "ERASURE_RULES",
    "ERASURE_Z",
    "ErasureCheck",
    "SILENT_BACKGROUND_RULE",
    "agreement_score",
    "background_pattern_seen",
    "erasure_check",
    "erasure_note",
    "erasure_statistic",
    "erasure_threshold",
    "erasure_z",
    "format_rate",
    "position_scores",
    "rank_scores",
]
