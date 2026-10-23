"""Evidence fusion: many channels' soft bits into one estimate of the leaked codeword.

Channels are treated as independent given the leaked word, so log-likelihood ratios add:
L_i = sum of all LLRs observed for position i. The estimate is y_i = 1 if L_i > 0 and the
reliability weight is w_i = tanh(|L_i| / 2) = 1 - 2 P(error), the classic soft-decision
weight. Positions with |L_i| below ``erase_below`` get weight 0 (erased).

Repeated reads of one slot. Every observation of a position is added, including several
evidence files of one leak that show the same slot: two photos of one page add their shift
and background LLRs (their camera noise is independent; the print is not), and a forwarded
PDF and a photo of it add the PDF's exact readout to the photo's. The visible-word channels
are the exception (``SAME_MARK_PHYSICAL``: sentence variants and word choice). Their marks are
words a reader can see, read from a text layer, pasted text or the OCR text of an image
(``decoder/ocr.py``), and the same printed phrase read twice is one mark, not two independent
pieces of evidence: OCR errors repeat on the same print, and the text layer and the OCR of the
same page agree by construction. So for these channels the reads of a position from different
observations (``SoftBits``) are combined by ``combine_repeated_reads``: their sum, clipped to
the largest single |LLR|. Agreeing reads keep the confidence of the best one; disagreeing reads
lower it, down to an erasure. Within one observation nothing changes (one read per position),
so a single text, PDF or image gives exactly the LLRs it gave before.

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

# Physical channels whose marks are visible words: repeated reads of one position are one mark.
SAME_MARK_PHYSICAL = frozenset({"semantik", "leksikal"})


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
        subchannels: sub-channels (``SoftBits.channel``) with at least one observation, for
            labels such as "read through OCR"; never used in any computation.
    """

    m: int
    llr: np.ndarray
    y: np.ndarray
    weights: np.ndarray
    observations: np.ndarray
    sources: list[str] = field(default_factory=list)
    conflicts: dict[str, tuple[int, int]] = field(default_factory=dict)
    subchannels: list[str] = field(default_factory=list)

    @property
    def n_observed(self) -> int:
        """Positions with non-zero weight."""
        return int(np.count_nonzero(self.weights > 0))


def combine_repeated_reads(reads: list[np.ndarray]) -> np.ndarray:
    """One LLR per position from several reads of the same visible marks (one array per
    observation, 0 where it read nothing): the sum, clipped to the largest single |LLR|.

    Reads that agree give the confidence of the best one, never more; reads that disagree
    reduce it (equal and opposite reads cancel to an erasure). A single read is returned
    unchanged. Uses only the LLRs, never a codeword.
    """
    if not reads:
        raise ValueError("tidak ada bacaan untuk digabung")
    stack = np.vstack([np.asarray(r, dtype=np.float64) for r in reads])
    cap = np.max(np.abs(stack), axis=0)
    return np.clip(stack.sum(axis=0), -cap, cap)


def _accumulate(parts: list[SoftBits], m: int) -> tuple[np.ndarray, np.ndarray]:
    llr = np.zeros(m)
    count = np.zeros(m, dtype=np.int64)
    visible: dict[str, list[np.ndarray]] = {}
    for sb in parts:
        if len(sb) == 0:
            continue
        if sb.positions.min() < 0 or sb.positions.max() >= m:
            raise ValueError(f"kanal {sb.channel}: posisi di luar [0, {m})")
        np.add.at(count, sb.positions, 1)
        phys = PHYSICAL_CHANNEL.get(sb.channel, sb.channel)
        if phys in SAME_MARK_PHYSICAL:
            one = np.zeros(m)
            np.add.at(one, sb.positions, sb.llr)
            visible.setdefault(phys, []).append(one)
        else:
            np.add.at(llr, sb.positions, sb.llr)
    for reads in visible.values():
        llr += reads[0] if len(reads) == 1 else combine_repeated_reads(reads)
    return llr, count


def fuse(observations: list[SoftBits], m: int, erase_below: float = 0.25,
         confident: float = 2.0) -> FusedEstimate:
    """Add LLRs per position (visible-word channels: ``combine_repeated_reads`` across
    observations) and turn them into (y, weights)."""
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
    subchannels = sorted({sb.channel for sb in observations if len(sb)})
    return FusedEstimate(m=m, llr=llr, y=y, weights=weights, observations=count,
                         sources=names, conflicts=conflicts, subchannels=subchannels)


def fuse_by_physical_channel(observations: list[SoftBits], m: int) -> dict[str, FusedEstimate]:
    """One fused estimate per physical channel (for independent agreement counting)."""
    groups: dict[str, list[SoftBits]] = {}
    for sb in observations:
        if len(sb):
            groups.setdefault(PHYSICAL_CHANNEL.get(sb.channel, sb.channel), []).append(sb)
    return {name: fuse(parts, m) for name, parts in groups.items()}
