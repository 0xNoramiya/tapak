"""Soft bit estimates produced by channel decoders.

A channel decoder never looks at any recipient's codeword. It only reports, for code
positions it could read, a log-likelihood ratio LLR = log P(bit=1 | evidence) / P(bit=0 |
evidence). Positive means "probably 1". The same position may appear several times
(repetition); fusion adds the LLRs.

The shift and background decoders also report a code-blind *strength* for every unit they
measured (``Strengths``): the magnitude of the raw measurement in noise units, also where the
channel reports no LLR (no pattern found). Fusion never uses it; only the erasure check
(``decoder/erasure.py``) does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

LLR_CLIP = 12.0


@dataclass
class Strengths:
    """Magnitude of every measured unit of a channel, in noise units, by code position.

    ``values`` has one row per unit and one column per measure (a 1-D array is one measure);
    the background decoder reports two (|despread mean| and cell energy). A value never
    depends on the bit carried (only on how clearly the unit was marked and read), so it never
    reveals a codeword; 0 means "measured, no mark found".
    """

    positions: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=np.int64).reshape(-1)
        v = np.asarray(self.values, dtype=np.float64)
        self.values = v[:, None] if v.ndim == 1 else v
        if self.values.ndim != 2 or self.values.shape[0] != self.positions.shape[0]:
            raise ValueError("posisi dan kekuatan harus sama panjang")

    def __len__(self) -> int:
        return int(self.positions.size)


@dataclass
class SoftBits:
    """LLR observations of one sub-channel.

    Attributes:
        channel: sub-channel name (``shift``, ``zw``, ``homoglyph``, ``background``, ...).
        positions: code positions observed (int array).
        llr: one LLR per observation (float array, clipped to +/- LLR_CLIP).
        meta: diagnostics for the report (slots read, noise estimate, page, ...).
        strengths: code-blind strength of every measured unit (shift and background
            decoders only; None for the other channels). Never used by fusion.
    """

    channel: str
    positions: np.ndarray
    llr: np.ndarray
    meta: dict[str, object] = field(default_factory=dict)
    strengths: Strengths | None = None

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=np.int64).reshape(-1)
        self.llr = np.clip(np.asarray(self.llr, dtype=np.float64).reshape(-1), -LLR_CLIP, LLR_CLIP)
        if self.positions.shape != self.llr.shape:
            raise ValueError("posisi dan llr harus sama panjang")

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
        measured = [p.strengths for p in parts if p.strengths is not None]
        strengths = (Strengths(np.concatenate([s.positions for s in measured]),
                               np.concatenate([s.values for s in measured], axis=0)) if measured else None)
        return SoftBits(channel, pos, llr, dict(meta), strengths)


def gaussian_llr(signed_measure: np.ndarray, amplitude: float, sigma: float) -> np.ndarray:
    """LLR for a measurement s = (2b-1) * amplitude + N(0, sigma^2): 2 * amplitude * s / sigma^2."""
    if sigma <= 0:
        raise ValueError("sigma harus positif")
    return 2.0 * amplitude * np.asarray(signed_measure, dtype=np.float64) / (sigma * sigma)
