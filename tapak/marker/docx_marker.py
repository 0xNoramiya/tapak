"""Channel 3 inside Word files: zero-width symbols and homoglyphs in DOCX text runs.

The marks are the ones of the PDF text layer (see ``pdf_zerowidth.py``), adapted to the
fact that Word, not TAPAK, draws the text on the reader's machine. Code positions come
from ``plan.assign_positions`` with the channels "zw" and "homoglyph", so fusion and
accusation work unchanged. Words containing digits never carry marks.

Zero-width symbols (DOCX variant: one bit per symbol). The PDF encoding (``encode_zw``)
uses four symbols per alphabet, two bits each. Half of them, U+2061..U+2064, are risky in
Word: every Windows font that maps them (Times New Roman, Tahoma, Cambria, Microsoft Sans
Serif, Segoe UI Symbol) draws them as visible dashed boxes 0.6 to 1.26 em wide, and Arial
or Calibri lack them, so Word would borrow one of those fonts. A DOCX copy therefore only
uses the symbols of value 0 and 1 of each alphabet:

    alphabet 0: U+200C ZWNJ (bit 0), U+200D ZWJ (bit 1)
    alphabet 1: U+200B ZWSP (bit 0), U+2060 WORD JOINER (bit 1)

That is exactly ``encode_zw`` with the high bit of every symbol fixed at 0, so the PDF
functions are reused unchanged (:func:`encode_docx_zw`, :func:`decode_docx_zw`). Symbol k
of a word still comes from alphabet k mod 2, at most two before and two after the word,
so a word carries at most 4 bits. Checked with fontTools on the Windows 11 font files:
these four code points are either unmapped or have zero advance in every font except the
monospaced Courier New, Consolas and MS Gothic (Courier New and Consolas are listed below
without zero-width symbols) and Sans Serif Collection, whose U+2060 is 0.6 em wide. A
font that lacks them (Arial and Calibri lack U+2060, Bookman Old Style lacks all four)
relies on Word borrowing them from another font.

Homoglyphs. An eligible all-lowercase word carries one bit: bit 1 swaps the first
swappable letter for its Cyrillic twin, bit 0 the second (the PDF rule). Swappable letters
are a, e, o, c, p, x, y, i, j, s, and only in fonts of :data:`VERIFIED_FONTS`, where the
twins U+0430, U+0435, U+043E, U+0441, U+0440, U+0445, U+0443, U+0456, U+0458, U+0455 have
the same outline and advance as the Latin letter in every style (regular, bold, italic,
bold italic), so a swap changes neither the look nor the line breaks. Words shown in
capitals by formatting (caps, small caps) get no homoglyph, because the capital of
Cyrillic U+0443 does not look like Y.

Fonts. The font of each run is resolved the way Word does it: direct formatting, the
character style, the paragraph style (each along its basedOn chain), the document defaults,
with theme fonts looked up in the theme part. Word draws a Latin letter with the ``ascii``
font slot and a Cyrillic letter with the ``hAnsi`` slot; when the two differ (or an East
Asian hint is set), the swapped letter gets its own run whose ``hAnsi`` slot names the
``ascii`` font. Text in a font that is not in the table gets no marks at all.

Where the marks go. A paragraph's visible text is the concatenation of its text runs (see
:func:`text_runs`); a run holds text in ``w:t`` elements next to tabs and breaks. Words are
split on whitespace, and each word records which ``w:t`` characters it occupies. Marks are
written into those ``w:t`` texts in place, so the inserted characters inherit the run
properties (``w:rPr``) of the letters around them. Every marked run also gets
``w:noProof``, so Word's spell checker does not underline mixed-script words on screen
(this does not change print or PDF output, and it is the same set of runs in every copy).

Coverage. Body paragraphs, tables (nested tables and merged cells once) and content
controls (``w:sdt``) are read in order. Field results (page numbers, dates, references,
tables of contents) are read for alignment but never marked, because Word regenerates them.
Headers, footers, text boxes, footnotes and comments are left untouched.

Not verified in Word itself: the font facts above come from the font files. Before a
demo, open a marked copy in Word on Windows and print it to PDF to confirm the symbols
stay invisible and the line breaks match the master.
"""

from __future__ import annotations

import copy
import io
import math
import re
import secrets
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.run import Run
from lxml import etree

from tapak.marker.layout import sha256_hex
from tapak.marker.master import HOMOGLYPHS
from tapak.marker.pdf_zerowidth import (
    MAX_ZW_SYMBOLS,
    MIN_HOMOGLYPH_WORD,
    ZW_ALPHABETS,
    ZW_CHARS,
    decode_zw,
    encode_zw,
)
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW, EmbeddingPlan, assign_positions, plan_key
from tapak.tardos.code import code_digest, derive_bias, derive_codeword
from tapak.tardos.params import TardosParams

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.xmlchemy import BaseOxmlElement
    from docx.text.paragraph import Paragraph

    from tapak.marker.issue import Recipient

# Lowercase Latin letters that may ever be swapped in Word files (every key of HOMOGLYPHS);
# which of them a given font allows is in VERIFIED_FONTS.
DOCX_HOMOGLYPH_LETTERS: frozenset[str] = frozenset("aeocpxyijs")

# The four zero-width symbols a DOCX copy uses: values 0 and 1 of each PDF alphabet.
DOCX_ZW_ALPHABETS: tuple[tuple[str, str], tuple[str, str]] = (
    (ZW_ALPHABETS[0][0], ZW_ALPHABETS[0][1]),  # U+200C, U+200D
    (ZW_ALPHABETS[1][0], ZW_ALPHABETS[1][1]),  # U+200B, U+2060
)
DOCX_ZW_CHARS: frozenset[str] = frozenset(DOCX_ZW_ALPHABETS[0] + DOCX_ZW_ALPHABETS[1])
DOCX_MAX_ZW_BITS = MAX_ZW_SYMBOLS  # one bit per symbol, two symbols before and two after


@dataclass(frozen=True)
class FontSupport:
    """What a font allows.

    Attributes:
        homoglyphs: letters whose Cyrillic twin has the same outline and advance width as
            the Latin letter in every style of the family.
        zero_width: U+200B, U+200C, U+200D and U+2060 are unmapped or have zero advance.
    """

    homoglyphs: frozenset[str]
    zero_width: bool


def _support(letters: str, zero_width: bool = True) -> FontSupport:
    return FontSupport(frozenset(letters), zero_width)


_ALL = "aceijopsxy"
# Font families (Word's names) checked with fontTools on the Windows 11 font files: for each
# letter, both code points mapped, equal advance width and equal outline in every style file
# of the family (Times New Roman Italic c, j, y differ only in point order and render
# pixel-identical). tests/test_docx.py re-checks this table when C:/Windows/Fonts is mounted.
# Families without Cyrillic (Gill Sans MT, Trebuchet MS, Lucida Sans, ...) are absent on
# purpose: Word would draw the twins with a fallback font.
VERIFIED_FONTS: dict[str, FontSupport] = {
    "Arial": _support(_ALL),
    "Arial Black": _support(_ALL),
    "Arial Narrow": _support(_ALL),
    "Book Antiqua": _support("aeosx"),
    "Bookman Old Style": _support(_ALL),
    "Calibri": _support(_ALL),
    "Calibri Light": _support(_ALL),
    "Cambria": _support(_ALL),
    "Candara": _support(_ALL),
    "Century Gothic": _support("aceiopsx"),
    "Century Schoolbook": _support(_ALL),
    "Consolas": _support(_ALL, zero_width=False),        # U+200B is 0.55 em wide
    "Constantia": _support("aceijopsx"),
    "Corbel": _support("aceijops"),
    "Courier New": _support("aceijopsx", zero_width=False),  # U+200C, U+200D are 0.6 em
    "Garamond": _support("aceijopsy"),
    "Georgia": _support(_ALL),
    "Lucida Console": _support(_ALL),
    "Lucida Sans Unicode": _support("aceijopsx"),
    "Microsoft Sans Serif": _support("aceijopsx"),
    "Palatino Linotype": _support("ijs"),
    "Segoe UI": _support(_ALL),
    "Segoe UI Light": _support(_ALL),
    "Segoe UI Semibold": _support(_ALL),
    "Segoe UI Semilight": _support(_ALL),
    "Tahoma": _support(_ALL),
    "Times New Roman": _support(_ALL),
    "Verdana": _support("aeijopsxy"),  # Cyrillic c is wider than Latin c
}
UNVERIFIED_FONT = FontSupport(frozenset(), False)
WORD_DEFAULT_FONT = "Times New Roman"  # what Word uses when no level names a font

# Run properties that disqualify a word from a sub-channel when in effect.
NO_HOMOGLYPH_PROPS = ("w:caps", "w:smallCaps")
NO_ZW_PROPS = ("w:spacing", "w:fitText")

SAMPLE_TEMPLATE = Path(__file__).resolve().parents[2] / "samples" / "templates" / "nota_dinas.json"
SAMPLE_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)  # fixed, so the sample's hash is stable
RECIPIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")  # recipient_id is part of the file name

# Compiled with an explicit namespace map, because some wrappers (w:sdt, w:sdtContent) are
# plain lxml elements without python-docx's namespace-aware xpath().
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_BLOCKS = etree.XPath("./w:p | ./w:tbl | ./w:sdt/w:sdtContent", namespaces=_NS)
_CELLS = etree.XPath("./w:tr/w:tc | ./w:tr/w:sdt/w:sdtContent/w:tc | ./w:sdt/w:sdtContent/w:tr/w:tc",
                     namespaces=_NS)
# Runs whose text is visible in a paragraph, in document order: plain runs, hyperlinks,
# tracked insertions, inline content controls and simple fields.
_TEXT_RUNS = etree.XPath(
    "./w:r | ./w:hyperlink/w:r | ./w:ins/w:r | ./w:sdt/w:sdtContent/w:r"
    " | ./w:sdt/w:sdtContent/w:hyperlink/w:r | ./w:fldSimple/w:r",
    namespaces=_NS,
)
_RUN_TEXT_TAGS = "w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab"  # same as python-docx Run.text
_RUN_TEXT = etree.XPath(_RUN_TEXT_TAGS, namespaces=_NS)
_RUN_CHILDREN = etree.XPath(_RUN_TEXT_TAGS + " | w:fldChar", namespaces=_NS)
_W_P = qn("w:p")
_W_TBL = qn("w:tbl")
_W_T = qn("w:t")
_W_RPR = qn("w:rPr")
_W_RFONTS = qn("w:rFonts")
_W_FLDCHAR = qn("w:fldChar")
_W_FLDSIMPLE = qn("w:fldSimple")
_XML_SPACE = qn("xml:space")
_OFF_VALUES = {"0", "false", "off"}
_DRAWINGML = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _font_key(name: str) -> str:
    return " ".join(name.split()).casefold()


_SUPPORT_BY_KEY = {_font_key(name): s for name, s in VERIFIED_FONTS.items()}


def font_support(name: str) -> FontSupport:
    """What the font family ``name`` allows; nothing if it is not in VERIFIED_FONTS."""
    return _SUPPORT_BY_KEY.get(_font_key(name), UNVERIFIED_FONT)


@dataclass(frozen=True)
class TextSpan:
    """Characters ``[start, end)`` of one ``w:t`` element.

    Attributes:
        run: index of the run in :func:`text_runs` of the paragraph.
        node: index of the ``w:t`` among that run's ``w:t`` children.
        start: first character offset inside the ``w:t`` text.
        end: offset one past the last character.
    """

    run: int
    node: int
    start: int
    end: int


@dataclass(frozen=True)
class DocxWord:
    """One whitespace-delimited word of the body text and where its letters are stored.

    Attributes:
        index: position in reading order (the slot reference of the plan).
        text: the word as it is displayed.
        paragraph: index of its paragraph in :func:`iter_paragraphs` order.
        spans: the ``w:t`` character ranges holding the word, in order (empty if some
            character is not stored in a markable ``w:t``: a non-breaking hyphen element
            or a field result).
        zw_ok: the word carries invisible symbols (text rule, formatting and fonts allow).
        hg_candidates: indices of the letters that may be swapped (text rule, formatting
            and font allow); the word carries a homoglyph bit if there are at least two.
    """

    index: int
    text: str
    paragraph: int
    spans: tuple[TextSpan, ...]
    zw_ok: bool
    hg_candidates: tuple[int, ...]

    @property
    def hg_ok(self) -> bool:
        """True if the word carries a homoglyph bit."""
        return len(self.hg_candidates) >= 2


@dataclass
class DocxMaster:
    """Master (unmarked) Word file: its bytes, hash and words in reading order.

    ``unverified_fonts`` lists body font names outside VERIFIED_FONTS (text in them is
    not marked); it holds font names only, never document text.
    """

    docx_bytes: bytes
    doc_hash: str
    words: list[DocxWord] = field(default_factory=list)
    unverified_fonts: list[str] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        """The words' texts in reading order."""
        return [w.text for w in self.words]


# --- eligibility on plain strings ----------------------------------------------------


def docx_zw_eligible(text: str) -> bool:
    """A word can carry invisible symbols if it has no digit and no invisible character."""
    return bool(text) and not any(ch.isdigit() or ch in ZW_CHARS for ch in text)


def docx_homoglyph_candidates(text: str) -> list[int]:
    """Indices of swappable letters in ``text``; empty if the word is not eligible.

    Eligible: no digit, no invisible character, at least MIN_HOMOGLYPH_WORD letters, all
    letters lowercase (skips names, acronyms and sentence starts). The font may allow only
    some of these letters (see :class:`DocxWord`); a word carries a bit only if at least
    two remain.
    """
    if any(ch.isdigit() or ch in ZW_CHARS for ch in text):
        return []
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < MIN_HOMOGLYPH_WORD or any(not ch.islower() for ch in letters):
        return []
    return [i for i, ch in enumerate(text) if ch in DOCX_HOMOGLYPH_LETTERS]


# --- zero-width encoding (one bit per symbol) ----------------------------------------


def docx_zw_bits_per_word(m: int, n_words: int) -> int:
    """Bits per word (1 to 4) so the sub-channel covers the codeword if it can."""
    if n_words == 0:
        return 0
    return max(1, min(DOCX_MAX_ZW_BITS, math.ceil(m / n_words)))


def encode_docx_zw(bits: Sequence[int]) -> tuple[str, str]:
    """Bits (at most 4) to the (prefix, suffix) invisible strings of a word.

    Each bit becomes one symbol: ``encode_zw`` with the symbol's high bit fixed at 0, so
    only U+200C, U+200D, U+200B and U+2060 are written.
    """
    if len(bits) > DOCX_MAX_ZW_BITS:
        raise ValueError("at most 4 bits per word")
    return encode_zw([v for b in bits for v in (0, int(b))])


def decode_docx_zw(prefix: str, suffix: str, n_bits: int) -> list[int] | None:
    """Inverse of :func:`encode_docx_zw`; None if a symbol is missing, extra or foreign."""
    pairs = decode_zw(prefix, suffix, 2 * n_bits)
    if pairs is None or any(pairs[0::2]):
        return None  # a high bit of 1 means U+2061..U+2064: not written by this encoder
    return pairs[1::2]


# --- reading the document ------------------------------------------------------------


def iter_paragraphs(container: BaseOxmlElement) -> Iterator[CT_P]:
    """``w:p`` elements of a body (or table cell) in reading order.

    Tables are read row by row, cell by cell, descending into nested tables; each ``w:tc``
    is visited once, so merged cells are not repeated. Content controls (``w:sdt``) around
    paragraphs, tables, rows or cells are read like their content.
    """
    for child in _BLOCKS(container):
        if child.tag == _W_P:
            yield child
        elif child.tag == _W_TBL:
            for cell in _CELLS(child):
                yield from iter_paragraphs(cell)
        else:
            yield from iter_paragraphs(child)


def text_runs(paragraph: CT_P) -> list[BaseOxmlElement]:
    """The paragraph's runs whose text is displayed, in document order."""
    return _TEXT_RUNS(paragraph)


def paragraph_text(paragraph: CT_P) -> str:
    """Displayed text of a paragraph (tabs as "\\t", breaks as "\\n"), the view words come from."""
    return "".join(str(child) for r in text_runs(paragraph) for child in _RUN_TEXT(r))


def _child_val(parent: BaseOxmlElement | None, tag: str) -> str | None:
    el = parent.find(qn(tag)) if parent is not None else None
    return el.get(qn("w:val")) if el is not None else None


def _theme_fonts(doc: DocxDocument) -> dict[str, str]:
    """Latin typefaces of the theme: {"major": ..., "minor": ...} (empty if no theme)."""
    try:
        root = parse_xml(doc.part.part_related_by(RT.THEME).blob)
    except (KeyError, etree.XMLSyntaxError):
        return {}  # no theme: theme fonts stay unknown, so text in them is not marked
    fonts = {}
    for kind in ("major", "minor"):
        latin = root.find(f".//{_DRAWINGML}{kind}Font/{_DRAWINGML}latin")
        if latin is not None and latin.get("typeface"):
            fonts[kind] = latin.get("typeface")
    return fonts


@dataclass(frozen=True)
class _RunInfo:
    """Effective formatting of one run that matters for marking."""

    ascii_font: str       # draws Latin letters
    hansi_font: str       # draws Cyrillic letters and the zero-width symbols
    east_asia_hint: bool  # Word may draw Cyrillic with the East Asian font instead
    caps: bool            # caps or small caps in effect
    spaced: bool          # character spacing or fit-text in effect

    @property
    def needs_own_font(self) -> bool:
        """True if a Cyrillic letter in this run would be drawn with another font."""
        return self.east_asia_hint or _font_key(self.ascii_font) != _font_key(self.hansi_font)

    @property
    def zw_ok(self) -> bool:
        """True if invisible symbols in this run stay invisible and change no spacing."""
        return (not self.spaced and not self.east_asia_hint
                and font_support(self.ascii_font).zero_width and font_support(self.hansi_font).zero_width)

    def homoglyph_ok(self, letter: str) -> bool:
        """True if ``letter`` in this run may be swapped for its Cyrillic twin."""
        return not self.caps and letter in font_support(self.ascii_font).homoglyphs


class _RunProps:
    """Effective run properties, resolved as Word does.

    Order, most specific first: direct run formatting, the run's character style, the
    paragraph style (each followed along its basedOn chain), then the document defaults.
    The first level that sets a property decides; font slots are resolved one by one, and
    a theme font attribute wins over a font name on the same level. Table styles and
    Word's toggle combination across style levels are not modelled.
    """

    def __init__(self, doc: DocxDocument) -> None:
        root = doc.styles.element
        self.styles = {s.get(qn("w:styleId")): s for s in root.findall(qn("w:style"))}
        self.default_paragraph_style = next(
            (sid for sid, s in self.styles.items()
             if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) in ("1", "true", "on")),
            None,
        )
        self.defaults = root.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{_W_RPR}")
        self.theme = _theme_fonts(doc)

    def _style_chain(self, style_id: str | None) -> list[BaseOxmlElement]:
        out: list[BaseOxmlElement] = []
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            style = self.styles.get(style_id)
            if style is None:
                break
            rpr = style.find(_W_RPR)
            if rpr is not None:
                out.append(rpr)
            style_id = _child_val(style, "w:basedOn")
        return out

    def chain(self, run: BaseOxmlElement, paragraph: BaseOxmlElement) -> list[BaseOxmlElement]:
        """The ``w:rPr`` elements that apply to ``run``, most specific first."""
        rpr = run.find(_W_RPR)
        char_style = _child_val(rpr, "w:rStyle")
        para_style = _child_val(paragraph.find(qn("w:pPr")), "w:pStyle") or self.default_paragraph_style
        levels = [rpr, *self._style_chain(char_style), *self._style_chain(para_style), self.defaults]
        return [level for level in levels if level is not None]

    @staticmethod
    def _active(chain: list[BaseOxmlElement], tag: str) -> bool:
        for rpr in chain:
            el = rpr.find(qn(tag))
            if el is not None:
                return el.get(qn("w:val"), "1") not in _OFF_VALUES
        return False

    def _font(self, chain: list[BaseOxmlElement], slot: str) -> str:
        for rpr in chain:
            rfonts = rpr.find(_W_RFONTS)
            if rfonts is None:
                continue
            theme = rfonts.get(qn(f"w:{slot}Theme"))
            if theme:
                return self.theme.get("major" if theme.startswith("major") else "minor", "")
            name = rfonts.get(qn(f"w:{slot}"))
            if name:
                return name
        return WORD_DEFAULT_FONT

    @staticmethod
    def _hint(chain: list[BaseOxmlElement]) -> bool:
        for rpr in chain:
            rfonts = rpr.find(_W_RFONTS)
            if rfonts is not None and rfonts.get(qn("w:hint")) is not None:
                return rfonts.get(qn("w:hint")) == "eastAsia"
        return False

    def info(self, run: BaseOxmlElement, paragraph: BaseOxmlElement) -> _RunInfo:
        """Effective fonts and flags of ``run`` in ``paragraph``."""
        chain = self.chain(run, paragraph)
        return _RunInfo(
            ascii_font=self._font(chain, "ascii"),
            hansi_font=self._font(chain, "hAnsi"),
            east_asia_hint=self._hint(chain),
            caps=any(self._active(chain, t) for t in NO_HOMOGLYPH_PROPS),
            spaced=any(self._active(chain, t) for t in NO_ZW_PROPS),
        )


_CharLoc = tuple[int, int, int]  # (run index, w:t index in the run, offset in the w:t)


def _locate(spans: Sequence[TextSpan], char_index: int) -> tuple[TextSpan, int]:
    """The span holding character ``char_index`` of a word and its offset in the w:t."""
    k = char_index
    for span in spans:
        n = span.end - span.start
        if k < n:
            return span, span.start + k
        k -= n
    raise IndexError("character index outside the word")


def _make_word(index: int, para_index: int, chars: list[tuple[str, _CharLoc | None]],
               infos: list[_RunInfo]) -> DocxWord:
    text = "".join(ch for ch, _ in chars)
    spans: list[TextSpan] = []
    if all(loc is not None for _, loc in chars):
        for _, (ri, node, k) in chars:  # type: ignore[misc]
            last = spans[-1] if spans else None
            if last is not None and (last.run, last.node, last.end) == (ri, node, k):
                spans[-1] = TextSpan(ri, node, last.start, k + 1)
            else:
                spans.append(TextSpan(ri, node, k, k + 1))
    if not spans:
        return DocxWord(index, text, para_index, (), False, ())
    zw_ok = docx_zw_eligible(text) and all(infos[s.run].zw_ok for s in spans)
    hg = tuple(i for i in docx_homoglyph_candidates(text)
               if infos[_locate(spans, i)[0].run].homoglyph_ok(text[i]))
    return DocxWord(index, text, para_index, tuple(spans), zw_ok, hg)


def _collect_words(doc: DocxDocument) -> tuple[list[DocxWord], list[str]]:
    """All body words in reading order, and the body fonts missing from VERIFIED_FONTS."""
    props = _RunProps(doc)
    words: list[DocxWord] = []
    unverified: set[str] = set()
    field_depth = 0  # complex fields may span paragraphs
    for pi, p in enumerate(iter_paragraphs(doc.element.body)):
        runs = text_runs(p)
        infos = [props.info(r, p) for r in runs]
        chars: list[tuple[str, _CharLoc | None]] = []
        for ri, r in enumerate(runs):
            in_simple_field = r.getparent().tag == _W_FLDSIMPLE
            node = 0
            for child in _RUN_CHILDREN(r):
                if child.tag == _W_FLDCHAR:
                    kind = child.get(qn("w:fldCharType"))
                    if kind == "begin":
                        field_depth += 1
                    elif kind == "end" and field_depth > 0:
                        field_depth -= 1
                    continue
                s = str(child)  # python-docx's text equivalent ("\t" for a tab, ...)
                if child.tag != _W_T:
                    chars.extend((ch, None) for ch in s)
                    continue
                if field_depth or in_simple_field:  # field result: shown, never marked
                    chars.extend((ch, None) for ch in s)
                else:
                    chars.extend((ch, (ri, node, k)) for k, ch in enumerate(s))
                node += 1
                if s.strip():
                    unverified.update(f for f in (infos[ri].ascii_font, infos[ri].hansi_font)
                                      if font_support(f) is UNVERIFIED_FONT)
        current: list[tuple[str, _CharLoc | None]] = []
        for ch, loc in chars + [(" ", None)]:
            if not ch.isspace():
                current.append((ch, loc))
            elif current:
                words.append(_make_word(len(words), pi, current, infos))
                current = []
    return words, sorted(unverified)


def open_docx(data: bytes) -> DocxDocument:
    """Open DOCX bytes with python-docx; ValueError (Indonesian message) if not a Word file."""
    try:
        return Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - zip, XML or package errors all mean "not a DOCX"
        raise ValueError("berkas bukan dokumen Word (DOCX) yang valid") from exc


def load_docx_master(data: bytes) -> DocxMaster:
    """Parse a master DOCX; ``doc_hash`` is the SHA-256 of these exact bytes."""
    words, unverified = _collect_words(open_docx(data))
    return DocxMaster(docx_bytes=data, doc_hash=sha256_hex(data), words=words, unverified_fonts=unverified)


# --- plan ----------------------------------------------------------------------------


def build_docx_plan(master: DocxMaster, m: int, key: bytes) -> EmbeddingPlan:
    """Slots of the "zw" and "homoglyph" sub-channels for a Word file.

    A slot's ``ref`` is ``(word index,)``. DOCX has no fixed pagination, so every slot is
    on page 0. Same inputs give the same plan at issuance and at decoding. A zero-width
    slot carries 1 to 4 bits, so a document with fewer than m / 4 eligible words covers
    only part of the codeword (the sample nota dinas: 1568 of 2987 positions, plus 247
    homoglyph bits), which is still enough to identify a full copy among 20.
    """
    zw_words = [w for w in master.words if w.zw_ok]
    per_word = docx_zw_bits_per_word(m, len(zw_words))
    zw_refs = [(0, (w.index,), per_word) for w in zw_words]
    hg_refs = [(0, (w.index,), 1) for w in master.words if w.hg_ok]
    slots = assign_positions(CHANNEL_ZW, zw_refs, m, key) + assign_positions(CHANNEL_HOMOGLYPH, hg_refs, m, key)
    return EmbeddingPlan(m=m, slots=slots)


# --- marking -------------------------------------------------------------------------


@dataclass
class _NodeEdit:
    """Pending changes to one ``w:t`` element, offsets relative to its original text.

    ``own_font`` is set when a swapped letter must get its own run drawn with this font.
    """

    t: BaseOxmlElement
    own_font: str | None = None
    inserts: dict[int, str] = field(default_factory=dict)
    swaps: dict[int, str] = field(default_factory=dict)


def _new_run(template: BaseOxmlElement, children: list[BaseOxmlElement],
             own_font: str | None = None) -> BaseOxmlElement:
    """A run with the template's attributes and a copy of its rPr, holding ``children``.

    With ``own_font``, the run's ``hAnsi`` slot is set to that font (and the East Asian
    hint reset), so a Cyrillic letter is drawn with the font of the Latin letters.
    """
    run = OxmlElement("w:r", attrs=dict(template.attrib))
    rpr = template.find(_W_RPR)
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    if own_font is not None:
        rfonts = run.get_or_add_rPr().get_or_add_rFonts()
        rfonts.set(qn("w:hAnsi"), own_font)
        rfonts.attrib.pop(qn("w:hAnsiTheme"), None)
        rfonts.set(qn("w:hint"), "default")
    for child in children:
        run.append(child)  # moves the element (identity kept for later edits)
    return run


def _new_t(text: str) -> BaseOxmlElement:
    t = OxmlElement("w:t")
    t.text = text
    t.set(_XML_SPACE, "preserve")
    return t


def _apply_edit(edit: _NodeEdit) -> None:
    """Rewrite one ``w:t``; split its run only to isolate a letter needing its own font."""
    t = edit.t
    run = t.getparent()
    Run(run, None).font.no_proof = True  # before any split, so every piece inherits it
    text = t.text or ""
    isolate = bool(edit.swaps) and edit.own_font is not None
    # New text with inserted symbols and swapped letters, cut around isolated letters.
    segments: list[tuple[str, bool]] = []  # (text, needs its own run with the own font)
    current = ""
    for k in range(len(text) + 1):
        current += edit.inserts.get(k, "")
        if k == len(text):
            break
        swap = edit.swaps.get(k)
        if swap is not None and isolate:
            segments += [(current, False), (swap, True)]
            current = ""
        else:
            current += swap or text[k]
    segments = [seg for seg in segments + [(current, False)] if seg[0]]
    if not isolate:
        t.text = "".join(s for s, _ in segments)
        return
    content = [c for c in run if c.tag != _W_RPR]
    i = content.index(t)
    new_runs = []
    if content[:i]:
        new_runs.append(_new_run(run, content[:i]))
    new_runs += [_new_run(run, [_new_t(s)], edit.own_font if own else None) for s, own in segments]
    if content[i + 1:]:
        new_runs.append(_new_run(run, content[i + 1:]))
    parent = run.getparent()
    pos = parent.index(run)
    parent.remove(run)
    for k, new in enumerate(new_runs):
        parent.insert(pos + k, new)


def mark_docx(master_bytes: bytes, plan: EmbeddingPlan, codeword: np.ndarray) -> bytes:
    """Bytes of one marked copy: invisible symbols around words and homoglyph swaps."""
    x = np.asarray(codeword, dtype=np.uint8)
    if x.shape != (plan.m,):
        raise ValueError("panjang codeword tidak sama dengan m pada rencana penandaan")
    doc = open_docx(master_bytes)
    words, _ = _collect_words(doc)
    props = _RunProps(doc)
    paragraphs = list(iter_paragraphs(doc.element.body))
    runs_of: dict[int, list[BaseOxmlElement]] = {}
    edits: dict[tuple[int, int, int], _NodeEdit] = {}

    def word_of(index: int, ok: Callable[[DocxWord], bool]) -> DocxWord:
        if index >= len(words) or not ok(words[index]):
            raise ValueError("rencana penandaan tidak cocok dengan dokumen ini")
        return words[index]

    def edit_for(word: DocxWord, span: TextSpan) -> _NodeEdit:
        key = (word.paragraph, span.run, span.node)
        if key not in edits:
            p = paragraphs[word.paragraph]
            run = runs_of.setdefault(word.paragraph, text_runs(p))[span.run]
            info = props.info(run, p)
            edits[key] = _NodeEdit(run.findall(_W_T)[span.node], info.ascii_font if info.needs_own_font else None)
        return edits[key]

    # Resolve every change to its w:t element first; nothing is modified until all are known.
    for slot in plan.channel(CHANNEL_ZW):
        word = word_of(slot.ref[0], lambda w: w.zw_ok)
        prefix, suffix = encode_docx_zw([int(x[p]) ^ w for p, w in zip(slot.positions, slot.whiten)])
        first, last = word.spans[0], word.spans[-1]
        e = edit_for(word, first)
        e.inserts[first.start] = e.inserts.get(first.start, "") + prefix
        e = edit_for(word, last)
        e.inserts[last.end] = e.inserts.get(last.end, "") + suffix
    for slot in plan.channel(CHANNEL_HOMOGLYPH):
        word = word_of(slot.ref[0], lambda w: w.hg_ok)
        bit = int(x[slot.positions[0]]) ^ slot.whiten[0]
        idx = word.hg_candidates[0] if bit == 1 else word.hg_candidates[1]
        span, offset = _locate(word.spans, idx)
        edit_for(word, span).swaps[offset] = HOMOGLYPHS[word.text[idx]]
    for e in edits.values():
        _apply_edit(e)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# --- issuance ------------------------------------------------------------------------


def issue_docx(
    docx_path: Path,
    recipients: Sequence["Recipient"],
    out_dir: Path,
    secret: bytes,
    params: TardosParams,
    post_process: Callable[[bytes], bytes] | None = None,
    *,
    post_process_copy: Callable[[bytes, str], bytes] | None = None,
) -> list[tuple[int, str, Path, str]]:
    """Write one marked DOCX per recipient; return (seq, copy_id, path, code_digest) rows.

    Mirrors ``issue.py``: the bias vector and every codeword come from the code secret,
    only the commitment ``code_digest`` is returned (never the codeword), and no document
    text is stored. ``post_process(bytes) -> bytes`` runs on every copy and must not depend
    on the copy. ``post_process_copy(bytes, copy_id) -> bytes`` runs after it and is the
    entry point for per-copy canaries, for example
    ``lambda b, cid: add_docx_canary(b, canary_url(canary_token(secret, doc_hash, cid), domain))``.

    Every recipient_id must match RECIPIENT_ID_PATTERN (it is part of the file name). If
    any copy fails, the files already written are deleted, so no untraceable copy is left.
    """
    if len(recipients) > params.n_max:
        raise ValueError("jumlah penerima melebihi n_max kode")
    for rec in recipients:
        if not RECIPIENT_ID_PATTERN.fullmatch(rec.recipient_id):
            raise ValueError(
                f"recipient_id tidak valid untuk nama berkas: {rec.recipient_id!r} "
                "(hanya huruf, angka, titik, garis bawah, dan tanda hubung)"
            )
    data = Path(docx_path).read_bytes()
    master = load_docx_master(data)
    plan = build_docx_plan(master, params.length, plan_key(secret, master.doc_hash))
    if not plan.slots:
        message = "dokumen tidak memiliki teks yang dapat ditandai"
        if master.unverified_fonts:
            message += " (font belum terverifikasi: " + ", ".join(master.unverified_fonts) + ")"
        raise ValueError(message)
    p = derive_bias(secret, master.doc_hash, params)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(docx_path).stem
    issued: list[tuple[int, str, Path, str]] = []
    written: list[Path] = []
    try:
        for seq, rec in enumerate(recipients, start=1):
            copy_id = secrets.token_hex(8)
            x = derive_codeword(secret, master.doc_hash, copy_id, p)
            marked = mark_docx(data, plan, x)
            if post_process is not None:
                marked = post_process(marked)
            if post_process_copy is not None:
                marked = post_process_copy(marked, copy_id)
            path = out_dir / f"{stem}__salinan{seq:03d}_{rec.recipient_id}.docx"
            written.append(path)
            path.write_bytes(marked)
            issued.append((seq, copy_id, path, code_digest(master.doc_hash, copy_id, x)))
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return issued


# --- synthetic sample ----------------------------------------------------------------


def _paragraph(doc: DocxDocument, text: str = "", *, bold: bool = False, size: float | None = None,
               align: WD_ALIGN_PARAGRAPH | None = None, indent_cm: float = 0.0,
               hanging_cm: float = 0.0) -> Paragraph:
    p = doc.add_paragraph()
    if text:
        run = p.add_run(text)
        run.bold = bold or None
        if size:
            run.font.size = Pt(size)
    fmt = p.paragraph_format
    if align is not None:
        fmt.alignment = align
    if indent_cm:
        fmt.left_indent = Cm(indent_cm)
    if hanging_cm:
        fmt.first_line_indent = Cm(-hanging_cm)
        fmt.tab_stops.add_tab_stop(Cm(indent_cm))
    return p


def _numbered(doc: DocxDocument, label: str, text: str, indent_cm: float, bold_head: bool) -> None:
    """Hanging-indent item "label<TAB>text"; optionally the first sentence in bold."""
    p = _paragraph(doc, indent_cm=indent_cm, hanging_cm=0.75, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    p.add_run(label).add_tab()
    head, sep, rest = text.partition(". ")
    if bold_head and sep:
        p.add_run(head + ".").bold = True
        p.add_run(" " + rest)
    else:
        p.add_run(text)


def _fixed_zip_times(data: bytes) -> bytes:
    """Rewrite a DOCX zip with a fixed timestamp on every entry (same order, same content)."""
    stamp = SAMPLE_TIMESTAMP.timetuple()[:6]
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=stamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 0
            dst.writestr(entry, src.read(info.filename))
    return out.getvalue()


def make_sample_docx(path: Path, template: Path | None = None) -> Path:
    """Write a fictional nota dinas DOCX built from ``samples/templates/nota_dinas.json``.

    Everything in it is synthetic (units, names, numbers); the footer of every page says
    "CONTOH SINTETIS - BUKAN DOKUMEN ASLI". The output is byte-for-byte reproducible
    (fixed document properties and zip timestamps), so its doc_hash stays the same when
    the sample is regenerated.
    """
    from tapak.samplegen import FOOTER_TEXT, load_template

    tpl = load_template(template or SAMPLE_TEMPLATE)
    klasifikasi = tpl.get("klasifikasi", "RAHASIA")
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(3)
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin, section.right_margin = Cm(2.5), Cm(2.2)
    section.top_margin, section.bottom_margin = Cm(2.0), Cm(2.5)

    head = section.header.paragraphs[0]
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    head.add_run(klasifikasi).bold = True
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    foot.add_run(klasifikasi).bold = True
    note = section.footer.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.add_run(FOOTER_TEXT).font.size = Pt(7)

    for line in tpl["kop"]:
        _paragraph(doc, line, bold=True, size=10.5)
    _paragraph(doc)
    title = _paragraph(doc, tpl["judul"], bold=True, size=12.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    title.runs[0].underline = True
    _paragraph(doc, tpl["nomor"], align=WD_ALIGN_PARAGRAPH.CENTER)
    _paragraph(doc)

    table = doc.add_table(rows=len(tpl["kepala"]), cols=3)
    for row, (label, value) in zip(table.rows, tpl["kepala"]):
        for cell, text, width in zip(row.cells, (label, ":", value), (Cm(3.0), Cm(0.5), Cm(12.5))):
            cell.text = text
            cell.width = width
    _paragraph(doc)

    if tpl.get("pembuka"):
        _paragraph(doc, tpl["pembuka"], align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    for i, item in enumerate(tpl["isi"], start=1):
        text = item if isinstance(item, str) else item["teks"]
        _numbered(doc, f"{i}.", text, 0.75, bold_head=True)
        for j, sub in enumerate([] if isinstance(item, str) else item.get("sub", [])):
            _numbered(doc, f"{chr(97 + j)}.", sub, 1.5, bold_head=False)
    if tpl.get("penutup"):
        _paragraph(doc, tpl["penutup"], align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    _paragraph(doc)
    for k, line in enumerate(tpl["ttd"]):
        _paragraph(doc, line, indent_cm=9.0)
        if k == len(tpl["ttd"]) // 2 - 1:
            _paragraph(doc)
            _paragraph(doc)
    if tpl.get("tembusan"):
        _paragraph(doc)
        _paragraph(doc, "Tembusan:")
        for i, line in enumerate(tpl["tembusan"], start=1):
            _numbered(doc, f"{i}.", line, 0.75, bold_head=False)

    props = doc.core_properties
    props.author = "TAPAK samplegen"
    props.last_modified_by = "TAPAK samplegen"
    props.title = "Contoh sintetis"
    props.comments = FOOTER_TEXT
    props.created = props.modified = SAMPLE_TIMESTAMP
    props.revision = 1
    out = io.BytesIO()
    doc.save(out)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fixed_zip_times(out.getvalue()))
    return path
