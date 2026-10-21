"""Re-render a master PDF into one marked copy.

Steps per page:
1. remove the original text with a redaction that keeps images and vector graphics;
2. redraw every glyph of the layout model at its original origin plus the copy's offset,
   with homoglyph swaps and zero-width suffixes applied;
3. subset the fonts and save.

A word whose glyph origins match the font's advance widths is drawn as one string (fast);
otherwise each glyph is placed individually, which reproduces kerning and letter spacing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pymupdf

from tapak.marker.layout import GroupId, RowId, Word, WordId
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_zerowidth import TextMarks

ADVANCE_TOLERANCE = 0.005  # pt


@dataclass
class CopyMarks:
    """Everything that differs between copies.

    Attributes:
        group_dx: horizontal offset (pt) per shift group.
        row_dy: vertical offset (pt) per row.
        text: zero-width suffixes and homoglyph swaps.
        row_text: replacement text for whole rows, drawn from the row's first glyph origin
            with the row's first font (simple left-aligned replacement).
        row_words: replacement words for whole rows with explicit x positions (points),
            drawn on the row's baseline with the row's first font and size; used by the
            semantic channel to re-justify a variant sentence into the original rows. An
            entry (x, text, word_id) with a master word id redraws that master word at x
            with its own glyphs and its text marks (zero-width symbols, homoglyph); the
            lexical channel uses it so that unchanged words of a re-justified row keep
            their marks. (x, text) and (x, text, None) draw plain text.
        page_hooks: callables run on each page after the text is drawn (background
            pattern, canary actions); they receive (document, page).
    """

    group_dx: dict[GroupId, float] = field(default_factory=dict)
    row_dy: dict[RowId, float] = field(default_factory=dict)
    text: TextMarks | None = None
    row_text: dict[RowId, str] = field(default_factory=dict)
    row_words: dict[RowId, list[tuple[float, str] | tuple[float, str, WordId | None]]] = field(
        default_factory=dict)
    page_hooks: list[Callable[[pymupdf.Document, pymupdf.Page], None]] = field(default_factory=list)
    doc_hooks: list[Callable[[pymupdf.Document], None]] = field(default_factory=list)


def _rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0


class _AdvanceCache:
    """Remembers which master words can be drawn as a single string."""

    def __init__(self, master: MasterDocument) -> None:
        self.master = master
        self.cache: dict[WordId, bool] = {}

    def simple(self, word: Word) -> bool:
        hit = self.cache.get(word.id)
        if hit is not None:
            return hit
        # Compare with the advances recorded in the PDF itself (its /W widths), not with
        # the font program: producers round widths, and a re-rendered copy gets the same
        # rounding, so only kerning or letter spacing forces glyph-by-glyph placement.
        ok = True
        g0 = word.glyphs[0]
        for prev, g in zip(word.glyphs, word.glyphs[1:]):
            same_state = g.font == g0.font and g.size == g0.size and g.color == g0.color
            if not same_state or abs(g.y - g0.y) > 1e-3 or abs(g.x - (prev.x + prev.advance)) > ADVANCE_TOLERANCE:
                ok = False
                break
        self.cache[word.id] = ok
        return ok


def strip_text(doc: pymupdf.Document) -> None:
    """Remove all text from every page, keeping images and line art untouched."""
    for page in doc:
        page.add_redact_annot(page.rect, fill=False, cross_out=False)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )


def _draw_word(
    page: pymupdf.Page,
    master: MasterDocument,
    cache: _AdvanceCache,
    word: Word,
    dx: float,
    dy: float,
    text_marks: TextMarks,
) -> None:
    """Draw one word in its own text object.

    One TextWriter per word keeps an absolute text matrix for every word. A shared writer
    would merge words on the same baseline into one TJ array with integer kerning, which
    quantizes positions to about 0.01 pt per glyph and drifts along the row, comparable to
    the shift being embedded.
    """
    chars = [g.char for g in word.glyphs]
    swap = text_marks.homoglyph.get(word.id)
    if swap is not None:
        chars[swap[0]] = swap[1]
    prefix, suffix = text_marks.zw.get(word.id, ("", ""))
    g0 = word.glyphs[0]
    tw = pymupdf.TextWriter(page.rect)
    if cache.simple(word):
        tw.append((g0.x + dx, g0.y + dy), prefix + "".join(chars) + suffix,
                  font=master.fonts[g0.font].font, fontsize=g0.size)
    else:
        last = len(word.glyphs) - 1
        for k, (g, ch) in enumerate(zip(word.glyphs, chars)):
            txt = (prefix if k == 0 else "") + ch + (suffix if k == last else "")
            tw.append((g.x + dx, g.y + dy), txt, font=master.fonts[g.font].font, fontsize=g.size)
    tw.write_text(page, color=_rgb(g0.color))


def render_copy(master: MasterDocument, marks: CopyMarks, cache: _AdvanceCache | None = None) -> bytes:
    """Produce the PDF bytes of one copy with the given marks."""
    cache = cache or _AdvanceCache(master)
    text_marks = marks.text or TextMarks({}, {})
    doc = pymupdf.open(stream=master.pdf_bytes, filetype="pdf")
    strip_text(doc)
    for page_layout, page in zip(master.layout.pages, doc):
        for row in page_layout.rows:
            dy = marks.row_dy.get(row.id, 0.0)
            words_override = marks.row_words.get(row.id)
            if words_override is not None:
                g0 = row.words[0].glyphs[0]
                font = master.fonts[g0.font].font
                for entry in words_override:
                    x, text = entry[0], entry[1]
                    wid = entry[2] if len(entry) > 2 else None
                    if wid is not None:
                        word = master.layout.word(wid)
                        _draw_word(page, master, cache, word, x - word.x0, dy, text_marks)
                        continue
                    tw = pymupdf.TextWriter(page.rect)
                    tw.append((x, g0.y + dy), text, font=font, fontsize=g0.size)
                    tw.write_text(page, color=_rgb(g0.color))
                continue
            override = marks.row_text.get(row.id)
            if override is not None:
                g0 = row.words[0].glyphs[0]
                tw = pymupdf.TextWriter(page.rect)
                tw.append((g0.x, g0.y + dy), override, font=master.fonts[g0.font].font, fontsize=g0.size)
                tw.write_text(page, color=_rgb(g0.color))
                continue
            for group in row.groups:
                dx = marks.group_dx.get(group.id, 0.0)
                for wi in group.word_indices:
                    _draw_word(page, master, cache, row.words[wi], dx, dy, text_marks)
        for hook in marks.page_hooks:
            hook(doc, page)
    for hook in marks.doc_hooks:
        hook(doc)
    doc.subset_fonts()
    data = doc.tobytes(garbage=3, deflate=True, no_new_id=False)
    doc.close()
    return data


def render_pages(pdf_bytes: bytes, dpi: int, pages: list[int] | None = None) -> list[np.ndarray]:
    """Grayscale renders (uint8 arrays) of the given pages at ``dpi``."""
    out = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if pages is not None and i not in pages:
                continue
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            out.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy())
    return out


@dataclass
class GateResult:
    """Outcome of the visual gate (unmarked re-render vs. original)."""

    passed: bool
    max_diff: int
    mean_diff: float
    dpi: int


def visual_gate(master: MasterDocument, dpi: int = 100, max_allowed: int = 24,
                mean_allowed: float = 0.05) -> GateResult:
    """Refuse to issue if re-rendering *without* marks visibly changes the document.

    This catches unusable fonts or content the renderer cannot reproduce. Thresholds are
    in gray levels at ``dpi``: a few anti-aliasing differences are tolerated, a changed
    font or a missing element is not.
    """
    original = render_pages(master.pdf_bytes, dpi)
    rerendered = render_pages(render_copy(master, CopyMarks()), dpi)
    max_d, total, count = 0, 0.0, 0
    for a, b in zip(original, rerendered):
        if a.shape != b.shape:
            return GateResult(False, 255, 255.0, dpi)
        d = np.abs(a.astype(np.int16) - b.astype(np.int16))
        max_d = max(max_d, int(d.max()))
        total += float(d.sum())
        count += d.size
    mean_d = total / max(count, 1)
    passed = len(original) == len(rerendered) and max_d <= max_allowed and mean_d <= mean_allowed
    return GateResult(passed, max_d, mean_d, dpi)
