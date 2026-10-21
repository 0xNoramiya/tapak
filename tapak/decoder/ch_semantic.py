"""Decoder for channel 4 (semantic variants) on pasted, extracted or retyped text.

For every semantic slot the decoder asks which usable variant of the unit appears in the
leaked text:

1. both sides are normalized (invisible marks removed, look-alike letters mapped back,
   lowercase, punctuation dropped, whitespace collapsed), so typing style does not matter;
2. the unit is located with rapidfuzz ``partial_ratio_alignment`` (best sliding window over
   all variants); it counts as present only if that window scores at least MIN_SCORE;
3. inside the window (plus some slack) every variant gets its semi-global edit distance:
   the fewest single-character inserts, deletes and substitutions that turn the variant into
   some stretch of the leaked text. Unlike a fixed-length window, this charges a typo the
   same whether it adds or removes a character, so short and long variants compete fairly;
4. the alignment of the closest variant is checked for dense edits: typos are scattered
   single-character edits, while a cut-off excerpt or a word left out, added or replaced
   puts many edits close together. Over every EDIT_WINDOW consecutive alignment steps:
   CUT_EDITS or more edits (or more than MAX_EDIT_FRACTION of the variant edited) means
   the sentence is not whole in the text, and the slot is skipped as partial. A variant
   whose own version of the missing part is shorter would otherwise win with a confident
   wrong read. CLUSTER_EDITS or more edits means a word may have been changed, and the
   read is kept with a low confidence (at most CLUSTER_MAX_LLR);
5. per carried bit, LLR = LLR_PER_EDIT * ((closest variant with bit 0) - (closest variant
   with bit 1)), clipped to +/- MAX_LLR (or CLUSTER_MAX_LLR); a bit whose two sides differ
   by less than MIN_MARGIN edits is not read. Variants differ by at least 3 characters, so
   a clean read gives +/-6 and a read with typos in the differing words gives less.

Typos in the part of the sentence that all variants share cost every variant the same and
cancel in step 5; only typos inside the few differing words can move the decision.

The decoder never consults any recipient's codeword. Its diagnostics hold unit ids,
variant indices and scores, never text. A slot whose VariantSet does not belong to its
unit (another sentence or document) is counted as inconsistent and never read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
from rapidfuzz import fuzz

from tapak.decoder.softbits import SoftBits
from tapak.marker.plan import CHANNEL_SEMANTIC, Slot
from tapak.marker.semantic import SemanticUnit, SetsLike, index_sets, match_key, set_matches_unit, usable_indices

MIN_SCORE = 75.0          # rapidfuzz partial_ratio (0..100) below this: the unit is not in the text
MAX_EDIT_FRACTION = 0.2   # closest variant with more edits than this share of its length: garbled
EDIT_WINDOW = 10          # alignment steps (characters) over which edits are counted
CUT_EDITS = 5             # this many edits in one window: sentence cut off or words missing, skip
CLUSTER_EDITS = 3         # this many edits in one window: a word may have changed, low confidence
MIN_MARGIN = 1            # edits between the closest bit-0 and bit-1 variants, else the bit is skipped
LLR_PER_EDIT = 2.0        # LLR per edit of difference
MAX_LLR = 6.0
CLUSTER_MAX_LLR = 2.0


def semiglobal_distance(pattern: str, text: str) -> int:
    """Fewest edits (insert, delete, substitute) turning ``pattern`` into a substring of ``text``.

    Classic edit-distance table with a free start and a free end in ``text``, computed one
    pattern character at a time over all text positions with numpy.
    """
    if not pattern:
        return 0
    t = np.frombuffer(text.encode("utf-32-le"), dtype="<u4")
    cols = np.arange(len(t) + 1)
    prev = np.zeros(len(t) + 1, dtype=np.int64)  # free start: empty prefix matches anywhere
    for i, ch in enumerate(pattern, start=1):
        cur = np.empty_like(prev)
        cur[0] = i
        cur[1:] = np.minimum(prev[:-1] + (t != ord(ch)), prev[1:] + 1)  # match/substitute, delete
        prev = cols + np.minimum.accumulate(cur - cols)  # insert: min over k <= j of cur[k] + (j - k)
    return int(prev.min())  # free end


def locate(keys: Sequence[str], text_key: str) -> tuple[float, str]:
    """(best partial_ratio score, window of ``text_key`` with slack) for a set of variant keys."""
    best = max((fuzz.partial_ratio_alignment(k, text_key) for k in keys), key=lambda a: a.score)
    slack = max(len(k) for k in keys) // 4 + 10
    return float(best.score), text_key[max(0, best.dest_start - slack): best.dest_end + slack]


def alignment_ops(pattern: str, text: str) -> str:
    """Steps of the best semi-global alignment of ``pattern`` in ``text``, pattern order.

    "M" match, "S" substitute, "D" pattern character missing from the text, "I" extra text
    character. Same table as :func:`semiglobal_distance`, kept in full and traced back from
    the best end column; ties prefer match or substitution, then deletion, then insertion.
    The number of letters other than "M" equals the distance.
    """
    t = np.frombuffer(text.encode("utf-32-le"), dtype="<u4")
    cols = np.arange(len(t) + 1)
    table = np.zeros((len(pattern) + 1, len(t) + 1), dtype=np.int64)
    for i, ch in enumerate(pattern, start=1):
        cur = np.empty(len(t) + 1, dtype=np.int64)
        cur[0] = i
        cur[1:] = np.minimum(table[i - 1, :-1] + (t != ord(ch)), table[i - 1, 1:] + 1)
        table[i] = cols + np.minimum.accumulate(cur - cols)
    i, j = len(pattern), int(np.argmin(table[-1]))
    ops: list[str] = []
    while i > 0:
        if j > 0 and table[i, j] == table[i - 1, j - 1] + (pattern[i - 1] != text[j - 1]):
            ops.append("S" if pattern[i - 1] != text[j - 1] else "M")
            i, j = i - 1, j - 1
        elif table[i, j] == table[i - 1, j] + 1:
            ops.append("D")
            i -= 1
        else:
            ops.append("I")
            j -= 1
    return "".join(reversed(ops))


def densest_edits(ops: str, window: int = EDIT_WINDOW) -> int:
    """Largest number of edits (non-"M" steps) in any ``window`` consecutive alignment steps."""
    edits = np.array([op != "M" for op in ops], dtype=np.int64)
    if len(edits) <= window:
        return int(edits.sum())
    sums = np.convolve(edits, np.ones(window, dtype=np.int64), mode="valid")
    return int(sums.max())


def decode_semantic(
    text: str,
    units: Sequence[SemanticUnit],
    sets: SetsLike,
    slots: Iterable[Slot],
) -> SoftBits:
    """Soft bits of the semantic channel found in ``text``.

    Diagnostics (``meta``): slots_total, slots_read (at least one bit read), slots_absent
    (unit not found), slots_partial (unit cut off, changed or garbled), slots_ambiguous
    (found but no bit decided), slots_inconsistent (variant sets differ from the ones used
    at issuance), slots_low_confidence (read with clustered edits), bits_skipped, and per
    read slot the unit id, variant index and scores.
    """
    text_key = match_key(text)
    idx = index_sets(sets)
    positions: list[int] = []
    llrs: list[float] = []
    reads: list[dict[str, object]] = []
    total = absent = partial = ambiguous = inconsistent = skipped_bits = clustered = 0
    for slot in slots:
        if slot.channel != CHANNEL_SEMANTIC:
            continue
        total += 1
        unit = units[slot.ref[0]] if 0 <= slot.ref[0] < len(units) else None
        vs = idx.get(unit.unit_id) if unit is not None else None
        n = len(slot.positions)
        if unit is None or vs is None or not set_matches_unit(vs, unit) or len(usable_indices(vs)) != 1 << n:
            inconsistent += 1  # variant sets differ from the ones used at issuance
            continue
        usable = usable_indices(vs)
        keys = [match_key(vs.variants[i]) for i in usable]
        if len(text_key) < 0.8 * min(len(k) for k in keys):
            absent += 1
            continue
        score, window = locate(keys, text_key)
        if score < MIN_SCORE:
            absent += 1
            continue
        dist = np.array([semiglobal_distance(k, window) for k in keys])
        best = int(np.argmin(dist))
        dense = densest_edits(alignment_ops(keys[best], window))
        if dist[best] > MAX_EDIT_FRACTION * len(keys[best]) or dense >= CUT_EDITS:
            partial += 1
            continue
        cap = CLUSTER_MAX_LLR if dense >= CLUSTER_EDITS else MAX_LLR
        ks = np.arange(len(keys))
        bits_read = 0
        for j, (pos, white) in enumerate(zip(slot.positions, slot.whiten)):
            code_bit = ((ks >> (n - 1 - j)) & 1) ^ white
            d1, d0 = dist[code_bit == 1].min(), dist[code_bit == 0].min()
            if abs(d0 - d1) < MIN_MARGIN:
                skipped_bits += 1
                continue
            positions.append(pos)
            llrs.append(float(np.clip(LLR_PER_EDIT * (d0 - d1), -cap, cap)))
            bits_read += 1
        if bits_read == 0:
            ambiguous += 1
            continue
        clustered += dense >= CLUSTER_EDITS
        second = int(np.partition(dist, 1)[1])
        reads.append({"unit_id": unit.unit_id, "variant": int(usable[best]), "score": round(score, 1),
                      "edits": int(dist[best]), "densest_edits": dense, "margin": second - int(dist[best]),
                      "bits": bits_read})
    return SoftBits(
        CHANNEL_SEMANTIC, np.array(positions, dtype=np.int64), np.array(llrs),
        {"slots_total": total, "slots_read": len(reads), "slots_absent": absent, "slots_partial": partial,
         "slots_ambiguous": ambiguous, "slots_inconsistent": inconsistent, "slots_low_confidence": clustered,
         "bits_skipped": skipped_bits, "reads": reads},
    )
