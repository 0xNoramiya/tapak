"""Decoder for channel 3 inside Word files: zero-width symbols and homoglyphs.

Input is any text that came out of a marked DOCX copy: the body text of a forwarded
file (``extract_docx_text``), a paragraph pasted from Word into a chat, or the text layer
of a PDF exported from the copy. The decoder

1. tokenizes the text with the PDF channel's ``tokenize`` (invisible symbols before a
   word become its prefix, those after it its suffix);
2. aligns the tokens with the master's words, both normalized back to plain Latin, so an
   excerpt or text with extra lines still maps to the right slots;
3. reads the symbols (one bit each, see ``docx_marker.decode_docx_zw``) and look-alike
   letters of every aligned word that carries a slot.

It never consults any recipient's codeword.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence

import numpy as np

from tapak.decoder.ch_zerowidth import DIGITAL_LLR, tokenize
from tapak.decoder.softbits import SoftBits
from tapak.marker.docx_marker import DocxMaster, decode_docx_zw, iter_paragraphs, open_docx, paragraph_text
from tapak.marker.master import REVERSE_HOMOGLYPHS
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW, EmbeddingPlan


def extract_docx_text(data: bytes) -> str:
    """Body text of a DOCX (paragraphs, tables and content controls in reading order).

    One line per paragraph, built from the same runs the marker splits into words.
    Raises ValueError (Indonesian message) if ``data`` is not a Word file.
    """
    doc = open_docx(data)
    return "\n".join(paragraph_text(p) for p in iter_paragraphs(doc.element.body))


def align_docx_tokens(leaked_words: Sequence[str], master: DocxMaster) -> list[tuple[int, int]]:
    """Pairs (leaked word index, master word index) of equal words after normalization.

    ``leaked_words`` are the tokens' visible characters (``token.raw``), homoglyphs kept.
    """
    leaked = [normalize_text(w) for w in leaked_words]
    words = [normalize_text(w.text) for w in master.words]
    sm = difflib.SequenceMatcher(None, leaked, words, autojunk=False)
    pairs = []
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            pairs.append((block.a + k, block.b + k))
    return pairs


def decode_docx(
    text: str, master: DocxMaster, plan: EmbeddingPlan, llr: float = DIGITAL_LLR
) -> list[SoftBits]:
    """Soft bits of the "zw" and "homoglyph" sub-channels found in ``text``."""
    tokens = tokenize(text)
    matched = {wi: ti for ti, wi in align_docx_tokens([t.raw for t in tokens], master)}

    zw_pos: list[int] = []
    zw_llr: list[float] = []
    zw_read = zw_broken = 0
    for slot in plan.channel(CHANNEL_ZW):
        ti = matched.get(slot.ref[0])
        if ti is None:
            continue
        tok = tokens[ti]
        bits = None if tok.broken else decode_docx_zw(tok.prefix, tok.suffix, len(slot.positions))
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
        ti = matched.get(slot.ref[0])
        if ti is None:
            continue
        word = master.words[slot.ref[0]]
        raw = tokens[ti].raw
        if len(raw) != len(word.text):
            continue
        cands = word.hg_candidates
        first, second = raw[cands[0]] in REVERSE_HOMOGLYPHS, raw[cands[1]] in REVERSE_HOMOGLYPHS
        if first == second:
            continue  # none swapped (normalized text) or both: unreadable
        hg_read += 1
        bit = (1 if first else 0) ^ slot.whiten[0]
        hg_pos.append(slot.positions[0])
        hg_llr.append(llr if bit == 1 else -llr)

    meta_common = {"format": "docx", "tokens": len(tokens), "aligned_words": len(matched)}
    return [
        SoftBits(CHANNEL_ZW, np.array(zw_pos), np.array(zw_llr),
                 {**meta_common, "slots_read": zw_read, "slots_broken": zw_broken,
                  "slots_total": len(plan.channel(CHANNEL_ZW))}),
        SoftBits(CHANNEL_HOMOGLYPH, np.array(hg_pos), np.array(hg_llr),
                 {**meta_common, "slots_read": hg_read, "slots_total": len(plan.channel(CHANNEL_HOMOGLYPH))}),
    ]
