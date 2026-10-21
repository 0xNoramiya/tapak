"""Collusion strategies for simulation.

Every strategy respects the marking assumption: where all colluders hold the same bit
they cannot detect the position, so the leaked bit equals theirs. Strategies only differ
at "detectable" positions where colluders disagree.

Each strategy returns (y, weights): y is the forged word, weights is 1 for an observed
position and 0 for an erased one (only the ``erase`` strategy erases).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

Strategy = Callable[[np.ndarray, np.random.Generator], tuple[np.ndarray, np.ndarray]]


def _split(xc: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    xc = np.asarray(xc, dtype=np.int64)
    if xc.ndim != 2:
        raise ValueError("kata kode koalisi harus larik 2 dimensi (c x m)")
    ones = xc.sum(axis=0)
    c = xc.shape[0]
    detectable = (ones > 0) & (ones < c)
    return ones, c, detectable


def majority(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Leak the bit held by most colluders (ties broken at random)."""
    ones, c, _ = _split(xc)
    y = (2 * ones > c).astype(np.uint8)
    tie = 2 * ones == c
    y[tie] = rng.integers(0, 2, int(tie.sum()))
    return y, np.ones(xc.shape[1])


def minority(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Where colluders disagree, leak the bit held by fewer of them (ties at random)."""
    ones, c, detectable = _split(xc)
    y = (ones == c).astype(np.uint8)
    y[detectable] = (2 * ones[detectable] < c).astype(np.uint8)
    tie = detectable & (2 * ones == c)
    y[tie] = rng.integers(0, 2, int(tie.sum()))
    return y, np.ones(xc.shape[1])


def random_mix(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Interleaving: each position copied from a colluder chosen uniformly at random."""
    xc = np.asarray(xc)
    pick = rng.integers(0, xc.shape[0], xc.shape[1])
    return xc[pick, np.arange(xc.shape[1])].astype(np.uint8), np.ones(xc.shape[1])


def coin_flip(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Where colluders disagree, leak a fair coin flip."""
    ones, c, detectable = _split(xc)
    y = (ones == c).astype(np.uint8)
    y[detectable] = rng.integers(0, 2, int(detectable.sum()))
    return y, np.ones(xc.shape[1])


def all_ones(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Where colluders disagree, always leak 1."""
    ones, _, _ = _split(xc)
    return (ones > 0).astype(np.uint8), np.ones(xc.shape[1])


def all_zeros(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Where colluders disagree, always leak 0."""
    ones, c, _ = _split(xc)
    return (ones == c).astype(np.uint8), np.ones(xc.shape[1])


def erase(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Where colluders disagree, destroy the mark (models averaging two copies)."""
    ones, c, detectable = _split(xc)
    y = (ones == c).astype(np.uint8)
    w = np.where(detectable, 0.0, 1.0)
    return y, w


STRATEGIES: dict[str, Strategy] = {
    "majority": majority,
    "minority": minority,
    "random-mix": random_mix,
    "coin": coin_flip,
    "all-1": all_ones,
    "all-0": all_zeros,
    "erase": erase,
}

# Indonesian names for reports; the keys above stay the command-line identifiers.
STRATEGY_LABELS: dict[str, str] = {
    "majority": "mayoritas",
    "minority": "minoritas",
    "random-mix": "campur acak",
    "coin": "lempar koin",
    "all-1": "semua 1",
    "all-0": "semua 0",
    "erase": "hapus",
}


def add_channel_noise(
    y: np.ndarray,
    weights: np.ndarray,
    rng: np.random.Generator,
    ber: float = 0.0,
    erasure: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Flip each observed bit with probability ``ber`` and erase it with probability ``erasure``."""
    if not (0.0 <= ber <= 0.5 and 0.0 <= erasure <= 1.0):
        raise ValueError("ber harus di antara 0 dan 0,5 dan erasure di antara 0 dan 1")
    y = np.asarray(y, dtype=np.uint8).copy()
    w = np.asarray(weights, dtype=np.float64).copy()
    if ber > 0:
        flip = rng.random(len(y)) < ber
        y[flip] ^= 1
    if erasure > 0:
        w[rng.random(len(y)) < erasure] = 0.0
    return y, w
