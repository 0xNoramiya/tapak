"""Decoder for channel 3 (text layer): zero-width symbols and homoglyphs.

Input is any text that came out of a copy: the full text layer of a forwarded PDF, a
pasted paragraph, a chat message. The decoder

1. tokenizes the leaked text, attaching zero-width symbols to the word they follow;
2. aligns the tokens (normalized back to plain Latin) with the master's words, so a
   partial excerpt still maps to the right slots;
3. reads the symbols and look-alike letters of every aligned word that carries a slot.

It never consults any recipient's codeword.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

import numpy as np
import pymupdf

from tapak.decoder.softbits import SoftBits
from tapak.marker.master import REVERSE_HOMOGLYPHS, MasterDocument
from tapak.marker.pdf_zerowidth import ZW_CHARS, decode_zw, homoglyph_candidates, normalize_text
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW, EmbeddingPlan

DIGITAL_LLR = 8.0  # error probability about 3e-4 per symbol


@dataclass
class _Token:
    raw: str = ""      # characters without zero-width symbols (homoglyphs kept)
    prefix: str = ""   # invisible symbols directly before the word
    suffix: str = ""   # invisible symbols directly after the word
    broken: bool = False  # invisible symbols found inside the word


def tokenize(text: str) -> list[_Token]:
    """Split on whitespace; separate leading and trailing invisible symbols of each token."""
    tokens: list[_Token] = []
    cur = _Token()
    for ch in text:
        if ch in ZW_CHARS:
            if cur.raw:
                cur.suffix += ch
            else:
                cur.prefix += ch
        elif ch.isspace():
            if cur.raw:
                tokens.append(cur)
            cur = _Token()
        else:
            if cur.suffix:  # symbols in the middle of a word: not our layout
                cur.broken = True
                cur.suffix = ""
            cur.raw += ch
    if cur.raw:
        tokens.append(cur)
    return tokens


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Text layer of a PDF as a viewer's copy-paste would give it (MuPDF)."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def align_tokens(tokens: list[_Token], master_words: list[str]) -> list[tuple[int, int]]:
    """Pairs (token index, master word index) of exactly matching normalized words."""
    leaked = [normalize_text(t.raw) for t in tokens]
    sm = difflib.SequenceMatcher(None, leaked, master_words, autojunk=False)
    pairs = []
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            pairs.append((block.a + k, block.b + k))
    return pairs


def decode_text(
    text: str, master: MasterDocument, plan: EmbeddingPlan, llr: float = DIGITAL_LLR
) -> list[SoftBits]:
    """Soft bits of the zero-width and homoglyph sub-channels found in ``text``."""
    words = list(master.layout.words())
    word_index = {w.id: i for i, w in enumerate(words)}
    tokens = tokenize(text)
    matched = {mi: ti for ti, mi in align_tokens(tokens, [w.text for w in words])}

    zw_pos: list[int] = []
    zw_llr: list[float] = []
    zw_read = zw_broken = 0
    for slot in plan.channel(CHANNEL_ZW):
        ti = matched.get(word_index[(slot.page, slot.ref[0], slot.ref[1])])
        if ti is None:
            continue
        tok = tokens[ti]
        bits = None if tok.broken else decode_zw(tok.prefix, tok.suffix, len(slot.positions))
        if bits is None:
            zw_broken += 1
            continue
        zw_read += 1
        for pos, white, b in zip(slot.positions, slot.whiten, bits):
            zw_pos.append(pos)
            zw_llr.append(llr if (b ^ white) == 1 else -llr)

    hg_pos: list[int] = []
    hg_llr: list[float] = []
    hg_read = 0
    for slot in plan.channel(CHANNEL_HOMOGLYPH):
        wid = (slot.page, slot.ref[0], slot.ref[1])
        ti = matched.get(word_index[wid])
        if ti is None:
            continue
        word = master.layout.word(wid)
        raw = tokens[ti].raw
        if len(raw) != len(word.text):
            continue
        cands = homoglyph_candidates(word, master.fonts[word.glyphs[0].font].homoglyph_safe)
        first, second = raw[cands[0]] in REVERSE_HOMOGLYPHS, raw[cands[1]] in REVERSE_HOMOGLYPHS
        if first == second:
            continue  # none swapped (normalized text) or both: unreadable
        hg_read += 1
        bit = (1 if first else 0) ^ slot.whiten[0]
        hg_pos.append(slot.positions[0])
        hg_llr.append(llr if bit == 1 else -llr)

    meta_common = {"tokens": len(tokens), "aligned_words": len(matched)}
    return [
        SoftBits(CHANNEL_ZW, np.array(zw_pos), np.array(zw_llr),
                 {**meta_common, "slots_read": zw_read, "slots_broken": zw_broken,
                  "slots_total": len(plan.channel(CHANNEL_ZW))}),
        SoftBits(CHANNEL_HOMOGLYPH, np.array(hg_pos), np.array(hg_llr),
                 {**meta_common, "slots_read": hg_read, "slots_total": len(plan.channel(CHANNEL_HOMOGLYPH))}),
    ]
