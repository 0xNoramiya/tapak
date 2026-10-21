"""The master (unmarked) document: PDF bytes, layout model and usable fonts.

Re-rendering a copy needs a real font for every font used in the master. Resolution order:

1. a bundled font with the same name (exact reproduction, full glyph set);
2. the font program embedded in the PDF, if it maps every character the master uses;
3. the bundled DejaVu Sans as a fallback (the visual gate will then usually refuse).

Homoglyph substitution is only allowed for character pairs whose glyph outlines and
advance widths are identical in the resolved font, checked with fontTools.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from functools import cached_property

import pymupdf
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from tapak.fonts import BUNDLED, font_path
from tapak.marker.layout import DocumentLayout, extract_layout, font_key

# Latin letter -> Cyrillic look-alike (lowercase only are used for embedding).
HOMOGLYPHS: dict[str, str] = {
    "a": "\u0430", "e": "\u0435", "o": "\u043e", "c": "\u0441", "p": "\u0440",
    "x": "\u0445", "y": "\u0443", "i": "\u0456", "j": "\u0458", "s": "\u0455",
}
# Used only to normalize leaked text back to Latin.
HOMOGLYPHS_UPPER: dict[str, str] = {
    "A": "\u0410", "B": "\u0412", "C": "\u0421", "E": "\u0415", "H": "\u041d", "K": "\u041a",
    "M": "\u041c", "O": "\u041e", "P": "\u0420", "T": "\u0422", "X": "\u0425", "I": "\u0406",
    "J": "\u0408", "S": "\u0405",
}
REVERSE_HOMOGLYPHS: dict[str, str] = {
    v: k for k, v in {**HOMOGLYPHS, **HOMOGLYPHS_UPPER}.items()
}

_BUNDLED_KEYS = {font_key(name): name for name in BUNDLED}
# PDF producers often report "Family Style" names; map common style suffixes.
_ALIASES = {"dejavusansbook": "DejaVuSans", "dejavusansregular": "DejaVuSans",
            "dejavusans": "DejaVuSans", "dejavusansbold": "DejaVuSans-Bold"}


@dataclass
class ResolvedFont:
    """A font usable for drawing, and where it came from."""

    key: str
    font: pymupdf.Font
    source: str            # "bundled" | "embedded" | "fallback"
    program: bytes | None  # raw font file when available (for homoglyph checks)

    @cached_property
    def homoglyph_safe(self) -> frozenset[str]:
        """Lowercase Latin letters whose Cyrillic look-alike renders identically."""
        if self.program is None:
            return frozenset()
        try:
            tt = TTFont(io.BytesIO(self.program), lazy=True)
            cmap = tt.getBestCmap()
            glyph_set = tt.getGlyphSet()
            hmtx = tt["hmtx"]
        except Exception:  # noqa: BLE001 - unreadable font program: no homoglyphs
            return frozenset()
        safe = set()
        for latin, cyr in HOMOGLYPHS.items():
            gl, gc = cmap.get(ord(latin)), cmap.get(ord(cyr))
            if gl is None or gc is None or hmtx[gl] != hmtx[gc]:
                continue
            p1, p2 = DecomposingRecordingPen(glyph_set), DecomposingRecordingPen(glyph_set)
            glyph_set[gl].draw(p1)
            glyph_set[gc].draw(p2)
            if p1.value == p2.value:
                safe.add(latin)
        return frozenset(safe)

    def supports_zero_width(self) -> bool:
        """True if the font maps the eight invisible code points used by channel 3."""
        return all(
            self.font.has_glyph(cp) and self.font.glyph_advance(cp) == 0
            for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064)
        )


@dataclass
class MasterDocument:
    """Master PDF plus derived layout and fonts."""

    pdf_bytes: bytes
    layout: DocumentLayout
    fonts: dict[str, ResolvedFont] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def doc_hash(self) -> str:
        """SHA-256 of the master PDF bytes."""
        return self.layout.doc_hash


def _embedded_programs(doc: pymupdf.Document) -> dict[str, bytes]:
    progs: dict[str, bytes] = {}
    for page in doc:
        for xref, _ext, _type, basefont, *_ in page.get_fonts(full=True):
            key = font_key(basefont)
            if key in progs:
                continue
            try:
                _name, ext, _t, buf = doc.extract_font(xref)
            except Exception:  # noqa: BLE001 - some fonts cannot be extracted
                continue
            if buf and ext not in ("", "n/a"):
                progs[key] = buf
    return progs


def load_master(pdf_bytes: bytes) -> MasterDocument:
    """Parse a master PDF and resolve a drawable font for every font it uses."""
    layout = extract_layout(pdf_bytes)
    master = MasterDocument(pdf_bytes=pdf_bytes, layout=layout)
    chars_by_font: dict[str, set[str]] = {}
    for w in layout.words():
        for g in w.glyphs:
            chars_by_font.setdefault(g.font, set()).add(g.char)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        embedded = _embedded_programs(doc)
    for key, chars in chars_by_font.items():
        bundled_name = _BUNDLED_KEYS.get(key) or _ALIASES.get(key)
        if bundled_name:
            prog = font_path(bundled_name).read_bytes()
            master.fonts[key] = ResolvedFont(key, pymupdf.Font(fontbuffer=prog), "bundled", prog)
            continue
        prog = embedded.get(key)
        if prog is not None:
            try:
                f = pymupdf.Font(fontbuffer=prog)
                if all(f.has_glyph(ord(c)) for c in chars):
                    master.fonts[key] = ResolvedFont(key, f, "embedded", prog)
                    continue
            except Exception:  # noqa: BLE001 - broken embedded font: fall back
                pass
        prog = font_path("DejaVuSans").read_bytes()
        master.fonts[key] = ResolvedFont(key, pymupdf.Font(fontbuffer=prog), "fallback", prog)
        master.warnings.append(
            f"font {layout.fonts.get(key, key)!r} tidak dapat dipakai ulang; memakai DejaVu Sans"
        )
    return master
