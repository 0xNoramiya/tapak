"""Evidence fusion: many channels' soft bits into one estimate of the leaked codeword.

Channels are treated as independent given the leaked word, so log-likelihood ratios add:
L_i = sum of all LLRs observed for position i. The estimate is y_i = 1 if L_i > 0 and the
reliability weight is w_i = tanh(|L_i| / 2) = 1 - 2 P(error), the classic soft-decision
weight. Positions with |L_i| below ``erase_below`` get weight 0 (erased).

Fusion also checks consistency: if two physical channels confidently disagree on many
shared positions, someone may have tampered with one channel (for example rewritten the
zero-width symbols); that is reported, and the per-channel accusations in
``decoder/accuse.py`` let an analyst see which channel is out of line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tapak.decoder.softbits import SoftBits
from tapak.marker.plan import PHYSICAL_CHANNEL


@dataclass
class FusedEstimate:
    """Fused estimate of the leaked word y.

    Attributes:
        m: code length.
        llr: summed LLR per position (0 where nothing was observed).
        y: hard decision per position.
        weights: reliability in [0, 1]; 0 means erased.
        observations: number of observations per position.
        sources: physical channels that contributed at least one readable position.
        conflicts: per pair of physical channels, (shared positions, confident disagreements).
    """

    m: int
    llr: np.ndarray
    y: np.ndarray
    weights: np.ndarray
    observations: np.ndarray
    sources: list[str] = field(default_factory=list)
    conflicts: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def n_observed(self) -> int:
        """Positions with non-zero weight."""
        return int(np.count_nonzero(self.weights > 0))


def _accumulate(parts: list[SoftBits], m: int) -> tuple[np.ndarray, np.ndarray]:
    llr = np.zeros(m)
    count = np.zeros(m, dtype=np.int64)
    for sb in parts:
        if len(sb) == 0:
            continue
        if sb.positions.min() < 0 or sb.positions.max() >= m:
            raise ValueError(f"kanal {sb.channel}: posisi di luar [0, {m})")
        np.add.at(llr, sb.positions, sb.llr)
        np.add.at(count, sb.positions, 1)
    return llr, count


def fuse(observations: list[SoftBits], m: int, erase_below: float = 0.25,
         confident: float = 2.0) -> FusedEstimate:
    """Add LLRs per position and turn them into (y, weights)."""
    llr, count = _accumulate(observations, m)
    y = (llr > 0).astype(np.uint8)
    weights = np.tanh(np.abs(llr) / 2.0)
    weights[np.abs(llr) < erase_below] = 0.0

    by_phys: dict[str, list[SoftBits]] = {}
    for sb in observations:
        if len(sb):
            by_phys.setdefault(PHYSICAL_CHANNEL.get(sb.channel, sb.channel), []).append(sb)
    per_phys = {k: _accumulate(v, m)[0] for k, v in by_phys.items()}
    conflicts: dict[str, tuple[int, int]] = {}
    names = sorted(per_phys)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            la, lb = per_phys[a], per_phys[b]
            shared = (np.abs(la) >= confident) & (np.abs(lb) >= confident)
            disagree = shared & (np.sign(la) != np.sign(lb))
            conflicts[f"{a}|{b}"] = (int(shared.sum()), int(disagree.sum()))
    return FusedEstimate(m=m, llr=llr, y=y, weights=weights, observations=count,
                         sources=names, conflicts=conflicts)


def fuse_by_physical_channel(observations: list[SoftBits], m: int) -> dict[str, FusedEstimate]:
    """One fused estimate per physical channel (for independent agreement counting)."""
    groups: dict[str, list[SoftBits]] = {}
    for sb in observations:
        if len(sb):
            groups.setdefault(PHYSICAL_CHANNEL.get(sb.channel, sb.channel), []).append(sb)
    return {name: fuse(parts, m) for name, parts in groups.items()}
