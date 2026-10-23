"""Decoder for channel 6 (word choice) on pasted, extracted or retyped text.

Alignment-based reader:

1. the master text (every point in its master form) and the leaked text are normalized with
   ``semantic.match_key`` (invisible marks removed, look-alike letters mapped back,
   lowercase, punctuation dropped, whitespace collapsed);
2. one global character alignment (Levenshtein opcodes, rapidfuzz) maps every position of
   the master text into the leaked text, so each point gets a window of the leaked text even
   when words were dropped, merged or mistyped;
3. inside the window every form of the point is matched together with up to ``CONTEXT``
   characters of master context on each side (never crossing another point): pattern =
   left context + form + right context, cost = semi-global edit distance
   (``ch_semantic.semiglobal_distance``). Typos in the shared context cost every form the
   same and cancel;
4. the point is absent when the closest pattern needs more than ``MAX_EDIT_FRACTION`` of its
   length in edits, or when its alignment has ``CUT_EDITS`` or more edits within
   ``EDIT_WINDOW`` steps at the phrase itself (``phrase_ops``: the form plus
   ``FORM_MARGIN`` characters; the phrase was reworded or cut there). With
   ``CLUSTER_EDITS`` or more such edits the read is kept with a low confidence
   (``CLUSTER_MAX_LLR``). Dense edits in the shared context cancel and are ignored;
5. per carried bit, LLR = LLR_PER_EDIT * (closest form with bit 0 - closest form with bit 1),
   clipped to +/- MAX_LLR (or the cluster cap); a bit whose two sides differ by less than
   MIN_MARGIN edits is not read. Forms differ by at least 3 characters, so a clean read
   gives +/- 6.

Text missing from an excerpt maps onto a collapsed stretch of the leaked text, where no
pattern with its context fits: missing text gives erasures, not confident wrong reads.

Code-blind: only the master text, the points and the slots (positions and whitening) are
used, never a recipient's codeword, so the Chernoff threshold stays valid. Diagnostics hold
point ids, form indices and counts, never text.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

import numpy as np
from rapidfuzz.distance import Levenshtein

from tapak.decoder.ch_semantic import alignment_ops, densest_edits, semiglobal_distance
from tapak.decoder.softbits import SoftBits
from tapak.marker.lexical import LexPoint
from tapak.marker.master import MasterDocument
from tapak.marker.plan import CHANNEL_LEXICAL, Slot
from tapak.marker.semantic import match_key

CONTEXT = 16              # characters of master context on each side of a point
MAX_EDIT_FRACTION = 0.3   # closest pattern with more edits than this share of its length: absent
FORM_MARGIN = 3           # pattern characters on each side of the form checked for dense edits
EDIT_WINDOW = 10          # alignment steps over which edits are counted
CUT_EDITS = 5             # this many edits in one window: reworded or cut off, absent
CLUSTER_EDITS = 3         # this many edits in one window: low confidence
MIN_MARGIN = 1            # edits between the closest bit-0 and bit-1 forms, else the bit is skipped
LLR_PER_EDIT = 2.0
MAX_LLR = 6.0
CLUSTER_MAX_LLR = 2.0


class LexReference:
    """Normalized master text with the character span of every point (master forms).

    ``pages`` (optional) keeps only the rows of those master pages: the reference for the OCR
    text of one photographed page, whose contexts then end where the page ends, as they do
    in the image. Points on other pages get no span (the reader counts them inconsistent).
    """

    def __init__(self, master: MasterDocument, points: Sequence[LexPoint],
                 pages: Collection[int] | None = None) -> None:
        start_of = {(p.page, p.row, p.start): p for p in points}
        parts: list[str] = []
        pos = 0
        self.spans: dict[str, tuple[int, int]] = {}
        open_point: tuple[LexPoint, int] | None = None
        for row in master.layout.rows():
            if pages is not None and row.page not in pages:
                continue
            for k, w in enumerate(row.words):
                key = match_key(w.text)
                pt = start_of.get((row.page, row.index, k))
                if pt is not None:
                    open_point = (pt, pos)
                if key:
                    parts.append(key)
                    pos += len(key) + 1
                if open_point is not None and row.index == open_point[0].row and k == open_point[0].end - 1:
                    self.spans[open_point[0].point_id] = (open_point[1], max(open_point[1], pos - 1))
                    open_point = None
        self.text = " ".join(parts)
        bounds = sorted(self.spans.values())
        self._starts = np.array([b[0] for b in bounds], dtype=np.int64)
        self._ends = np.array([b[1] for b in bounds], dtype=np.int64)

    def context(self, point_id: str) -> tuple[str, str, int, int]:
        """(left context, right context, start of left, end of right) in the reference text."""
        s, e = self.spans[point_id]
        prev_end = self._ends[self._ends <= s]
        next_start = self._starts[self._starts >= e]
        lo = max(s - CONTEXT, int(prev_end.max()) if prev_end.size else 0)
        hi = min(e + CONTEXT, int(next_start.min()) if next_start.size else len(self.text))
        return self.text[lo:s], self.text[e:hi], lo, hi


def phrase_ops(ops: str, start: int, end: int, margin: int = FORM_MARGIN) -> str:
    """Alignment steps (``ch_semantic.alignment_ops``, pattern order) that touch pattern
    characters [start - margin, end + margin), with insertions kept at their position.

    Edits in the shared context cost every form the same and cancel; only edits at the phrase
    itself can say that the phrase was reworded or cut.
    """
    out = []
    i = 0  # index of the next pattern character
    for op in ops:
        if start - margin <= i < end + margin:
            out.append(op)
        if op != "I":
            i += 1
    return "".join(out)


def position_map(ref: str, leaked: str) -> np.ndarray:
    """f[i] = position in ``leaked`` aligned with position i of ``ref`` (length len(ref) + 1)."""
    f = np.zeros(len(ref) + 1, dtype=np.int64)
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(ref, leaked):
        if tag == "insert":
            continue
        for k in range(i2 - i1):
            f[i1 + k] = j1 if tag == "delete" else j1 + min(k, max(j2 - j1 - 1, 0))
    f[len(ref)] = len(leaked)
    return f


def decode_lexical(text: str, ref: LexReference, points: Sequence[LexPoint], slots: Iterable[Slot]) -> SoftBits:
    """Soft bits of the lexical channel found in ``text``.

    Diagnostics (``meta``): points_total, points_read (at least one bit read), points_absent
    (not found, reworded or cut off), points_ambiguous (found, no bit decided),
    points_inconsistent (slot and point disagree), points_low_confidence (read with
    clustered edits), bits_skipped, and per read point its id, form index and edit counts.
    """
    leaked = match_key(text)
    fmap = position_map(ref.text, leaked) if leaked else None
    positions: list[int] = []
    llrs: list[float] = []
    reads: list[dict[str, object]] = []
    total = absent = ambiguous = inconsistent = skipped = clustered = 0
    for slot in slots:
        if slot.channel != CHANNEL_LEXICAL:
            continue
        total += 1
        pt = points[slot.ref[0]] if 0 <= slot.ref[0] < len(points) else None
        n = len(slot.positions)
        if pt is None or len(pt.forms) != 1 << n or pt.point_id not in ref.spans:
            inconsistent += 1
            continue
        if fmap is None:
            absent += 1
            continue
        left, right, lo, hi = ref.context(pt.point_id)
        keys = [match_key(f) for f in pt.forms]
        slack = 8 + max(len(k) for k in keys)
        window = leaked[max(0, int(fmap[lo]) - slack): int(fmap[hi]) + slack]
        pats = [left + k + right for k in keys]
        dist = np.array([semiglobal_distance(pat, window) for pat in pats])
        best = int(np.argmin(dist))
        dense = 0
        if dist[best]:
            ops = phrase_ops(alignment_ops(pats[best], window), len(left), len(left) + len(keys[best]))
            dense = densest_edits(ops, EDIT_WINDOW)
        if dist[best] > MAX_EDIT_FRACTION * len(pats[best]) or dense >= CUT_EDITS:
            absent += 1
            continue
        cap = CLUSTER_MAX_LLR if dense >= CLUSTER_EDITS else MAX_LLR
        ks = np.arange(len(keys))
        got = 0
        for j, (pos, white) in enumerate(zip(slot.positions, slot.whiten)):
            code_bit = ((ks >> (n - 1 - j)) & 1) ^ white
            d1, d0 = dist[code_bit == 1].min(), dist[code_bit == 0].min()
            if abs(d0 - d1) < MIN_MARGIN:
                skipped += 1
                continue
            positions.append(int(pos))
            llrs.append(float(np.clip(LLR_PER_EDIT * (d0 - d1), -cap, cap)))
            got += 1
        if got == 0:
            ambiguous += 1
            continue
        clustered += dense >= CLUSTER_EDITS
        reads.append({"point": pt.point_id, "form": best, "edits": int(dist[best]), "densest_edits": dense,
                      "bits": got})
    return SoftBits(CHANNEL_LEXICAL, np.array(positions, dtype=np.int64), np.array(llrs, dtype=np.float64),
                    {"points_total": total, "points_read": len(reads), "points_absent": absent,
                     "points_ambiguous": ambiguous, "points_inconsistent": inconsistent,
                     "points_low_confidence": clustered, "bits_skipped": skipped, "reads": reads,
                     "slots_total": total, "slots_read": len(reads)})
