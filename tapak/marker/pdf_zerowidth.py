"""Channel 3: invisible marks in the text layer (zero-width characters and homoglyphs).

Zero-width sub-channel. Every eligible word carries up to four invisible symbols, two
bits each: a pair directly *before* the word and a pair directly *after* it, so the word
itself stays contiguous and single-word search keeps working. Symbol k of a word is
taken from alphabet k mod 2:

    alphabet 0: U+200C ZWNJ, U+200D ZWJ, U+2061 FUNCTION APPLICATION, U+2062 INVISIBLE TIMES
    alphabet 1: U+200B ZWSP, U+2060 WORD JOINER, U+2063 INVISIBLE SEPARATOR, U+2064 INVISIBLE PLUS

Why this layout: text extractors treat identical glyphs drawn at the same position as
"fake bold" duplicates and drop them (MuPDF drops an adjacent repeat, poppler drops repeats
anywhere in a stack). With at most two symbols per position, always from different
alphabets, no extractor sees a duplicate; the alternation also reveals a lost symbol.

Homoglyph sub-channel. An eligible word (lowercase letters only, no digits, at least two
letters whose Cyrillic look-alike is pixel-identical in its font) carries one bit: bit 1
replaces the first such letter with its Cyrillic twin, bit 0 replaces the second. Exactly
one letter per word changes, so text normalized back to Latin is detected as "erased"
rather than read as a run of zeros.

Words containing digits never carry marks, so numbers copied out of a document stay clean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from tapak.marker.layout import DocumentLayout, RowId, Word, WordId
from tapak.marker.master import HOMOGLYPHS, REVERSE_HOMOGLYPHS, MasterDocument
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW, EmbeddingPlan, Slot, assign_positions

ZW_ALPHABETS: tuple[tuple[str, ...], tuple[str, ...]] = (
    ("\u200c", "\u200d", "\u2061", "\u2062"),
    ("\u200b", "\u2060", "\u2063", "\u2064"),
)
ZW_CHARS = frozenset(c for alpha in ZW_ALPHABETS for c in alpha) | {"\ufeff", "\u200e", "\u200f", "\u034f"}
ZW_SYMBOL_INFO = {c: (k, v) for k, alpha in enumerate(ZW_ALPHABETS) for v, c in enumerate(alpha)}
MAX_ZW_SYMBOLS = 4           # two before and two after the word
BITS_PER_SYMBOL = 2
MIN_HOMOGLYPH_WORD = 4


@dataclass
class TextMarks:
    """Per-copy text-layer marks.

    Attributes:
        zw: (prefix, suffix) invisible strings drawn before and after a word.
        homoglyph: (glyph index in the word, replacement character) for a word.
    """

    zw: dict[WordId, tuple[str, str]]
    homoglyph: dict[WordId, tuple[int, str]]


def zw_eligible(word: Word) -> bool:
    """A word can carry zero-width symbols if it contains no digit."""
    return not any(ch.isdigit() for ch in word.text)


def homoglyph_candidates(word: Word, safe: frozenset[str]) -> list[int]:
    """Glyph indices in ``word`` that may be swapped; empty if the word is not eligible."""
    text = word.text
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < MIN_HOMOGLYPH_WORD or any(ch.isdigit() for ch in text):
        return []
    if any(not ch.islower() for ch in letters):
        return []  # skip names, acronyms and sentence starts
    if len({g.font for g in word.glyphs}) != 1:
        return []
    return [i for i, ch in enumerate(text) if ch in safe]


def zw_bits_per_word(m: int, n_words: int) -> int:
    """Bits per word (2 per symbol) so the sub-channel covers the codeword if it can."""
    if n_words == 0:
        return 0
    symbols = max(1, min(MAX_ZW_SYMBOLS, math.ceil(m / n_words / BITS_PER_SYMBOL)))
    return BITS_PER_SYMBOL * symbols


def build_text_slots(
    master: MasterDocument, m: int, key: bytes, excluded: set[RowId] | None = None
) -> list[Slot]:
    """Slots of both text sub-channels."""
    excluded = excluded or set()
    layout: DocumentLayout = master.layout
    zw_words: list[Word] = []
    hg_refs: list[tuple[int, tuple[int, ...], int]] = []
    for w in layout.words():
        if (w.id[0], w.id[1]) in excluded:
            continue
        font = master.fonts[w.glyphs[0].font]
        if zw_eligible(w) and font.supports_zero_width():
            zw_words.append(w)
        if len(homoglyph_candidates(w, font.homoglyph_safe)) >= 2:
            hg_refs.append((w.id[0], (w.id[1], w.id[2]), 1))
    per_word = zw_bits_per_word(m, len(zw_words))
    zw_refs = [(w.id[0], (w.id[1], w.id[2]), per_word) for w in zw_words]
    return assign_positions(CHANNEL_ZW, zw_refs, m, key) + assign_positions(
        CHANNEL_HOMOGLYPH, hg_refs, m, key
    )


def encode_zw(bits: list[int]) -> tuple[str, str]:
    """Bits (even count, at most 8) to the (prefix, suffix) invisible strings of a word."""
    if len(bits) % BITS_PER_SYMBOL or len(bits) > BITS_PER_SYMBOL * MAX_ZW_SYMBOLS:
        raise ValueError("jumlah bit harus genap, paling banyak 8")
    symbols = [
        ZW_ALPHABETS[k % 2][2 * int(bits[2 * k]) + int(bits[2 * k + 1])] for k in range(len(bits) // 2)
    ]
    return "".join(symbols[:2]), "".join(symbols[2:])


def decode_zw(prefix: str, suffix: str, n_bits: int) -> list[int] | None:
    """Inverse of :func:`encode_zw`; None if a symbol is missing, extra or out of order."""
    n_sym = n_bits // BITS_PER_SYMBOL
    if len(prefix) != min(n_sym, 2) or len(suffix) != max(n_sym - 2, 0):
        return None
    bits: list[int] = []
    for k, ch in enumerate(prefix + suffix):
        info = ZW_SYMBOL_INFO.get(ch)
        if info is None or info[0] != k % 2:
            return None
        bits += [info[1] >> 1, info[1] & 1]
    return bits


def text_marks(plan: EmbeddingPlan, master: MasterDocument, codeword: np.ndarray) -> TextMarks:
    """Per-copy zero-width suffixes and homoglyph swaps."""
    zw: dict[WordId, tuple[str, str]] = {}
    hg: dict[WordId, tuple[int, str]] = {}
    for slot in plan.channel(CHANNEL_ZW):
        bits = [int(codeword[p]) ^ w for p, w in zip(slot.positions, slot.whiten)]
        zw[(slot.page, slot.ref[0], slot.ref[1])] = encode_zw(bits)
    for slot in plan.channel(CHANNEL_HOMOGLYPH):
        wid = (slot.page, slot.ref[0], slot.ref[1])
        word = master.layout.word(wid)
        cands = homoglyph_candidates(word, master.fonts[word.glyphs[0].font].homoglyph_safe)
        bit = int(codeword[slot.positions[0]]) ^ slot.whiten[0]
        idx = cands[0] if bit == 1 else cands[1]
        hg[wid] = (idx, HOMOGLYPHS[word.text[idx]])
    return TextMarks(zw=zw, homoglyph=hg)


def normalize_text(text: str) -> str:
    """Remove zero-width symbols and map Cyrillic look-alikes back to Latin."""
    return "".join(REVERSE_HOMOGLYPHS.get(ch, ch) for ch in text if ch not in ZW_CHARS)
