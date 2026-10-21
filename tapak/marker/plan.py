"""Embedding plan: which code position is carried by which slot of which channel.

Each channel lists its slots in reading order (page by page). Code positions are handed out
from a keyed pseudo-random permutation of [0, m), sequentially across the document, so each
page of a physical channel carries its own slice of the codeword and a photo of one page
still yields a random subset of positions. If a channel has more capacity than m, the
permutation wraps around and positions repeat (extra redundancy).

Every carried bit is also XORed with a keyed whitening bit so that the physical pattern
(shift directions, which zero-width symbol) looks random even where the code bias p_i is
close to 0 or 1.

The plan is a pure function of (master layout, m, plan key, settings); issuer and decoder
compute it independently and get the same result.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from tapak.tardos.code import uniform_stream

CHANNEL_SHIFT = "shift"
CHANNEL_ZW = "zw"
CHANNEL_HOMOGLYPH = "homoglyph"
CHANNEL_BACKGROUND = "background"
CHANNEL_SEMANTIC = "semantic"

# Physical channel each sub-channel belongs to (used to count independent agreement).
PHYSICAL_CHANNEL = {
    CHANNEL_SHIFT: "geser",
    CHANNEL_ZW: "teks",
    CHANNEL_HOMOGLYPH: "teks",
    CHANNEL_BACKGROUND: "latar",
    CHANNEL_SEMANTIC: "semantik",
}


@dataclass(frozen=True)
class Slot:
    """A place in the document that carries ``len(positions)`` code bits.

    Attributes:
        channel: sub-channel name (see CHANNEL_* constants).
        page: page index.
        ref: channel-specific location, e.g. (row, group) for a shifted word group.
        positions: code positions carried, in order.
        whiten: keyed whitening bit per position (0 or 1).
    """

    channel: str
    page: int
    ref: tuple[int, ...]
    positions: tuple[int, ...]
    whiten: tuple[int, ...]


@dataclass
class EmbeddingPlan:
    """All slots of all channels for one document."""

    m: int
    slots: list[Slot] = field(default_factory=list)

    def channel(self, name: str) -> list[Slot]:
        """Slots of one sub-channel, in reading order."""
        return [s for s in self.slots if s.channel == name]

    def coverage(self, name: str | None = None) -> int:
        """Number of distinct code positions carried (by one channel or all)."""
        pos: set[int] = set()
        for s in self.slots:
            if name is None or s.channel == name:
                pos.update(s.positions)
        return len(pos)

    def summary(self) -> dict[str, dict[str, int]]:
        """Per channel: number of slots, bits, distinct positions, pages used."""
        out: dict[str, dict[str, int]] = {}
        for name in sorted({s.channel for s in self.slots}):
            ss = self.channel(name)
            out[name] = {
                "slots": len(ss),
                "bits": sum(len(s.positions) for s in ss),
                "positions": self.coverage(name),
                "pages": len({s.page for s in ss}),
            }
        return out


def plan_key(secret: bytes, doc_hash: str) -> bytes:
    """Per-document key for permutations and whitening (HMAC-SHA256 of the code secret)."""
    return hmac.new(secret, b"TAPAK-plan-v1|" + doc_hash.encode(), hashlib.sha256).digest()


def assign_positions(
    channel: str,
    refs: Iterable[tuple[int, tuple[int, ...], int]],
    m: int,
    key: bytes,
) -> list[Slot]:
    """Turn (page, ref, n_bits) entries into slots with positions and whitening bits."""
    refs = list(refs)
    total = sum(n for _, _, n in refs)
    if total == 0:
        return []
    perm = np.argsort(uniform_stream(key, f"perm|{channel}".encode(), m), kind="stable")
    white = (uniform_stream(key, f"white|{channel}".encode(), total) < 0.5).astype(int)
    slots: list[Slot] = []
    cursor = 0
    for page, ref, n in refs:
        idx = [(cursor + k) % m for k in range(n)]
        slots.append(
            Slot(
                channel=channel,
                page=page,
                ref=tuple(ref),
                positions=tuple(int(perm[i]) for i in idx),
                whiten=tuple(int(white[cursor + k]) for k in range(n)),
            )
        )
        cursor += n
    return slots
