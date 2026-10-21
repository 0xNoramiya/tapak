"""Soft bit estimates produced by channel decoders.

A channel decoder never looks at any recipient's codeword. It only reports, for code
positions it could read, a log-likelihood ratio LLR = log P(bit=1 | evidence) / P(bit=0 |
evidence). Positive means "probably 1". The same position may appear several times
(repetition); fusion adds the LLRs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

LLR_CLIP = 12.0


@dataclass
class SoftBits:
    """LLR observations of one sub-channel.

    Attributes:
        channel: sub-channel name (``shift``, ``zw``, ``homoglyph``, ``background``, ...).
        positions: code positions observed (int array).
        llr: one LLR per observation (float array, clipped to +/- LLR_CLIP).
        meta: diagnostics for the report (slots read, noise estimate, page, ...).
    """

    channel: str
    positions: np.ndarray
    llr: np.ndarray
    meta: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=np.int64).reshape(-1)
        self.llr = np.clip(np.asarray(self.llr, dtype=np.float64).reshape(-1), -LLR_CLIP, LLR_CLIP)
        if self.positions.shape != self.llr.shape:
            raise ValueError("positions and llr must have the same length")

    @classmethod
    def empty(cls, channel: str, **meta: object) -> "SoftBits":
        """No observation (channel absent or unreadable)."""
        return cls(channel, np.zeros(0, dtype=np.int64), np.zeros(0), dict(meta))

    def __len__(self) -> int:
        return int(self.positions.size)

    @staticmethod
    def concat(channel: str, parts: list["SoftBits"], **meta: object) -> "SoftBits":
        """Merge several observation sets into one."""
        if not parts:
            return SoftBits.empty(channel, **meta)
        pos = np.concatenate([p.positions for p in parts])
        llr = np.concatenate([p.llr for p in parts])
        return SoftBits(channel, pos, llr, dict(meta))


def gaussian_llr(signed_measure: np.ndarray, amplitude: float, sigma: float) -> np.ndarray:
    """LLR for a measurement s = (2b-1) * amplitude + N(0, sigma^2): 2 * amplitude * s / sigma^2."""
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    return 2.0 * amplitude * np.asarray(signed_measure, dtype=np.float64) / (sigma * sigma)
