"""Embedding plan: which code position is carried by which slot of which channel.

Each channel lists its slots in reading order (page by page). Code positions are handed out
from a keyed pseudo-random permutation of [0, m), sequentially across the document, so each
page of a physical channel carries its own slice of the codeword and a photo of one page
still yields a random subset of positions. If a channel has more capacity than m, the
permutation wraps around and positions repeat (extra redundancy).

Every carried bit is also XORed with a keyed whitening bit so that the physical pattern
(shift directions, which zero-width symbol) looks random even where the code bias p_i is
close to 0 or 1.

Channels that survive retyping (semantic variants, lexical word choice) carry only a few
dozen bits. A document that opts into the lexical channel records ``retype_positions =
"band-0.3-0.7"``: both channels then take their positions only from code positions whose bias
lies in [0.3, 0.7] (``retype_pool``), from one shared keyed permutation (stream "ketik"),
semantic from the front and lexical from the back, so neither depends on the other's size
and they never collide while the band has room. The choice uses only the bias vector, never
a codeword, so innocent bits there are still independent Bernoulli(p_i) and the Chernoff
threshold holds. Near p = 1/2 a lone leaker scores up to 1 per bit (2/pi on average over the
arcsine law), but a coalition voting for the minority bit scores about zero there, so band
positions are a lone-leaker tool only. Documents without the record keep the uniform rule.

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
CHANNEL_LEXICAL = "lexical"

# Position rule of the retype-surviving channels (semantic, lexical) of a new document that
# opts into the lexical channel. Documents without this record keep the uniform rule.
RETYPE_BAND = "band-0.3-0.7"
RETYPE_RULES = {RETYPE_BAND: (0.3, 0.7)}
RETYPE_STREAM = "ketik"

# Physical channel each sub-channel belongs to (used to count independent agreement).
PHYSICAL_CHANNEL = {
    CHANNEL_SHIFT: "geser",
    CHANNEL_ZW: "teks",
    CHANNEL_HOMOGLYPH: "teks",
    CHANNEL_BACKGROUND: "latar",
    CHANNEL_SEMANTIC: "semantik",
    CHANNEL_LEXICAL: "leksikal",
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


def retype_pool(p: np.ndarray, rule: str) -> np.ndarray:
    """Boolean mask of the code positions a retype rule allows (from the bias vector only)."""
    if rule not in RETYPE_RULES:
        raise ValueError(f"aturan posisi ketik ulang tidak dikenal: {rule!r}")
    lo, hi = RETYPE_RULES[rule]
    p = np.asarray(p, dtype=np.float64)
    return (p >= lo) & (p <= hi)


def assign_positions(
    channel: str,
    refs: Iterable[tuple[int, tuple[int, ...], int]],
    m: int,
    key: bytes,
    pool: np.ndarray | None = None,
    stream: str | None = None,
    from_end: bool = False,
) -> list[Slot]:
    """Turn (page, ref, n_bits) entries into slots with positions and whitening bits.

    By default positions follow the channel's own keyed permutation of [0, m). ``pool`` (a
    boolean mask of length m) keeps only the allowed positions, in permutation order;
    ``stream`` names a permutation shared by several channels; ``from_end`` walks that
    sequence from its last element backwards, so two channels sharing a stream (one from the
    front, one from the back) never collide while the pool has room. Whitening always comes
    from the channel's own stream. Without these options the result is the original rule.
    """
    refs = list(refs)
    total = sum(n for _, _, n in refs)
    if total == 0:
        return []
    perm = np.argsort(uniform_stream(key, f"perm|{stream or channel}".encode(), m), kind="stable")
    if pool is not None:
        pool = np.asarray(pool, dtype=bool)
        if pool.shape != (m,):
            raise ValueError("kumpulan posisi harus sepanjang kode")
        perm = perm[pool[perm]]
        if perm.size == 0:
            raise ValueError("tidak ada posisi kode yang memenuhi aturan posisi")
    if from_end:
        perm = perm[::-1]
    white = (uniform_stream(key, f"white|{channel}".encode(), total) < 0.5).astype(int)
    slots: list[Slot] = []
    cursor = 0
    size = int(perm.size)
    for page, ref, n in refs:
        idx = [(cursor + k) % size for k in range(n)]
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
