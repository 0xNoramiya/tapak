"""Layout model of a text PDF: pages, rows, words, shift groups, glyph origins.

The same function runs at issuance (to know what to mark) and at decoding (to know where
every word *should* be in the unmarked master). Everything is derived from the PDF
itself, so issuer and decoder agree as long as they read the same master file.

Coordinates are PDF points with the origin at the top-left of the page (PyMuPDF
convention); ``y`` of a glyph is its baseline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field

import pymupdf

from tapak.fonts import strip_subset_tag

ROW_TOLERANCE = 0.6          # pt: glyphs whose baselines differ by less share a row
WORD_GAP_FACTOR = 0.15       # gap > factor * font size starts a new word
MIN_GROUP_WIDTH = 20.0       # pt (about 7 mm): shift groups are at least this wide

_EXTRACT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE
    | pymupdf.TEXT_INHIBIT_SPACES
    | pymupdf.TEXT_PRESERVE_LIGATURES
    | pymupdf.TEXT_MEDIABOX_CLIP
)

WordId = tuple[int, int, int]   # (page, row, word)
GroupId = tuple[int, int, int]  # (page, row, group)
RowId = tuple[int, int]         # (page, row)


@dataclass(frozen=True)
class Glyph:
    """One drawn character: its Unicode value, baseline origin and drawing state."""

    char: str
    x: float
    y: float
    advance: float
    size: float
    font: str
    color: int
    bbox: tuple[float, float, float, float]


@dataclass
class Word:
    """A maximal run of glyphs on a row without a word gap."""

    id: WordId
    glyphs: list[Glyph]

    @property
    def text(self) -> str:
        """The word's characters."""
        return "".join(g.char for g in self.glyphs)

    @property
    def x0(self) -> float:
        """Left edge (origin of the first glyph)."""
        return self.glyphs[0].x

    @property
    def x1(self) -> float:
        """Right edge (end of the last glyph's advance)."""
        last = self.glyphs[-1]
        return last.x + last.advance

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Union of glyph boxes."""
        return (
            min(g.bbox[0] for g in self.glyphs),
            min(g.bbox[1] for g in self.glyphs),
            max(g.bbox[2] for g in self.glyphs),
            max(g.bbox[3] for g in self.glyphs),
        )


@dataclass
class Group:
    """A rigid unit for horizontal shifts: one or more consecutive words of a row."""

    id: GroupId
    word_indices: list[int]
    bbox: tuple[float, float, float, float]


@dataclass
class Row:
    """All glyphs sharing a baseline, ordered left to right."""

    page: int
    index: int
    baseline: float
    words: list[Word]
    groups: list[Group] = field(default_factory=list)

    @property
    def id(self) -> RowId:
        """(page, row) identifier."""
        return (self.page, self.index)

    @property
    def text(self) -> str:
        """Words joined by single spaces."""
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Union of word boxes."""
        boxes = [w.bbox for w in self.words]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


@dataclass
class PageLayout:
    """Rows of one page, top to bottom."""

    index: int
    width: float
    height: float
    rows: list[Row]


@dataclass
class DocumentLayout:
    """Layout of a whole document plus the SHA-256 of the exact PDF bytes it came from."""

    doc_hash: str
    pages: list[PageLayout]
    fonts: dict[str, str]  # normalized font key -> name as found in the PDF

    def words(self) -> Iterator[Word]:
        """All words in reading order (page, row, left to right)."""
        for page in self.pages:
            for row in page.rows:
                yield from row.words

    def rows(self) -> Iterator[Row]:
        """All rows in reading order."""
        for page in self.pages:
            yield from page.rows

    def word(self, wid: WordId) -> Word:
        """Look up a word by id."""
        return self.pages[wid[0]].rows[wid[1]].words[wid[2]]

    def row(self, rid: RowId) -> Row:
        """Look up a row by id."""
        return self.pages[rid[0]].rows[rid[1]]

    @property
    def glyph_count(self) -> int:
        """Total number of glyphs."""
        return sum(len(w.glyphs) for w in self.words())


def font_key(name: str) -> str:
    """Normalize a PDF font name: drop subset tag, spaces, dashes and case."""
    base = strip_subset_tag(name)
    return "".join(ch for ch in base.lower() if ch.isalnum())


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _page_glyphs(page: pymupdf.Page, fonts: dict[str, str]) -> list[Glyph]:
    raw = page.get_text("rawdict", flags=_EXTRACT_FLAGS)
    glyphs: list[Glyph] = []
    for block in raw["blocks"]:
        if block.get("type", 0) != 0:
            continue
        for line in block["lines"]:
            if abs(line["dir"][1]) > 1e-3 or line["dir"][0] <= 0:
                continue  # only horizontal left-to-right text is marked
            for span in line["spans"]:
                key = font_key(span["font"])
                fonts.setdefault(key, span["font"])
                for ch in span["chars"]:
                    if ch["c"].isspace() or ch.get("synthetic"):
                        continue
                    x0, y0, x1, y1 = ch["bbox"]
                    glyphs.append(
                        Glyph(
                            char=ch["c"],
                            x=float(ch["origin"][0]),
                            y=float(ch["origin"][1]),
                            advance=float(x1 - x0),
                            size=float(span["size"]),
                            font=key,
                            color=int(span["color"]),
                            bbox=(float(x0), float(y0), float(x1), float(y1)),
                        )
                    )
    return glyphs


def _rows_from_glyphs(glyphs: list[Glyph], page_index: int) -> list[Row]:
    ordered = sorted(glyphs, key=lambda g: (g.y, g.x))
    clusters: list[list[Glyph]] = []
    for g in ordered:
        if clusters and abs(g.y - clusters[-1][0].y) < ROW_TOLERANCE:
            clusters[-1].append(g)
        else:
            clusters.append([g])
    rows: list[Row] = []
    for r_idx, cluster in enumerate(clusters):
        cluster.sort(key=lambda g: g.x)
        words_glyphs: list[list[Glyph]] = []
        for g in cluster:
            if words_glyphs:
                prev = words_glyphs[-1][-1]
                gap = g.x - (prev.x + prev.advance)
                if gap <= WORD_GAP_FACTOR * max(g.size, prev.size):
                    words_glyphs[-1].append(g)
                    continue
            words_glyphs.append([g])
        words = [Word(id=(page_index, r_idx, i), glyphs=gs) for i, gs in enumerate(words_glyphs)]
        baseline = sum(g.y for g in cluster) / len(cluster)
        row = Row(page=page_index, index=r_idx, baseline=baseline, words=words)
        row.groups = _make_groups(row)
        rows.append(row)
    return rows


def _make_groups(row: Row) -> list[Group]:
    """Merge consecutive words until each group is at least MIN_GROUP_WIDTH wide."""
    groups: list[list[int]] = []
    for i, w in enumerate(row.words):
        if groups:
            first = row.words[groups[-1][0]]
            last = row.words[groups[-1][-1]]
            if last.x1 - first.x0 < MIN_GROUP_WIDTH:
                groups[-1].append(i)
                continue
        groups.append([i])
    # A narrow trailing group is merged into its left neighbour.
    if len(groups) > 1:
        tail = groups[-1]
        if row.words[tail[-1]].x1 - row.words[tail[0]].x0 < MIN_GROUP_WIDTH:
            groups[-2].extend(groups.pop())
    out = []
    for g_idx, idxs in enumerate(groups):
        boxes = [row.words[i].bbox for i in idxs]
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        out.append(Group(id=(row.page, row.index, g_idx), word_indices=idxs, bbox=bbox))
    return out


def extract_layout(pdf_bytes: bytes) -> DocumentLayout:
    """Build the layout model of a PDF given as bytes."""
    fonts: dict[str, str] = {}
    pages: list[PageLayout] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for p_idx, page in enumerate(doc):
            glyphs = _page_glyphs(page, fonts)
            pages.append(
                PageLayout(
                    index=p_idx,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    rows=_rows_from_glyphs(glyphs, p_idx),
                )
            )
    return DocumentLayout(doc_hash=sha256_hex(pdf_bytes), pages=pages, fonts=fonts)
