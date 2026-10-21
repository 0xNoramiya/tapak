"""Channel 4: meaning-preserving variants of sentences the issuer marks as safe.

Workflow:

1. ``find_candidate_units`` suggests sentences that may be rephrased: paragraphs that start
   with "Dengan hormat", "Bersama ini" or "Demikian", and tembusan lines. A suggestion is
   offered only if it is a whole sentence on whole rows (``unit_problems``) and passes
   ``safety_check`` (no digits, times, coordinates, capitalized words such as names and
   units, order, deadline or negation words). Unsafe units are never offered.
2. ``generate_variant_set`` asks a local LLM provider for paraphrases, runs automatic
   checks (protected tokens identical, safety_check passes, punctuation unchanged, no
   near-duplicates, the variant wraps into exactly the same rows) and has the provider
   judge equivalence.
3. A human approves or rejects every variant in the review UI. ``require_approved`` blocks
   issuance while any variant of a selected unit is still pending, and
   ``validate_selection`` re-checks every approved variant before any copy is drawn.
4. A unit with 2^b usable variants carries b code bits: the copy shows the variant whose
   index is the unit's (whitened) bits read as a binary number, most significant first.

A unit occupies whole consecutive rows of one page with one font, size and colour, so a
variant is drawn into the same rows (``CopyMarks.row_words``): same left and right edge,
full rows justified if they were justified, last row left aligned.

A VariantSet remembers the unit it was generated for (``unit_key``, a fingerprint of the
unit), so a set can never be applied to another sentence or another document, and
``variant_sets_digest`` (kept in the issuance record) covers the units as well.

Data minimization: the variant texts (and the candidates in ``VariantSet.dropped``) are
document content. Store VariantSet JSON with the same protection as the master PDF, never
in the registry or in logs. Refusal reasons name only a category, never document words.
The variant ids returned by ``semantic_marks`` are derived from the copy's codeword: do
not store them in clear (see that function).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz.distance import Levenshtein

from tapak.llm.provider import LLMProvider, is_capitalized, protected_tokens, split_words
from tapak.marker.layout import PageLayout, Row, RowId
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.plan import CHANNEL_SEMANTIC, Slot

TRIGGERS = ("Dengan hormat", "Bersama ini", "Demikian")
TEMBUSAN_HEADER = re.compile(r"^Tembusan\s*:?$")
SENTENCE_END = (".", "!", "?", ":", ";")   # a row ending like this may end a paragraph
TERMINATORS = (".", "!", "?")              # a unit must end like this (a whole sentence)
_CLOSERS = "\"')]\u201d\u2019"             # closing quotes and brackets after a terminator

MAX_UNIT_ROWS = 6
LEADING_MAX = 1.6           # rows of one paragraph are at most 1.6 font sizes apart
X_TOL = 0.5                 # pt: rows start at the same left edge
FULL_TOL = 1.5              # pt: a row ending this close to the column edge is full
WRAP_TOL = 0.5              # pt: overshoot tolerated when re-wrapping a variant
MAX_GAP_FACTOR = 3.0        # justified gaps up to 3 spaces (or the original's widest gap)
MIN_WORDS = 4
MIN_VARIANT_DISTANCE = 3    # characters between any two variants (normalized)

STATUS_PENDING = "menunggu"
STATUS_APPROVED = "disetujui"
STATUS_REJECTED = "ditolak"
STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)

# Order, prohibition and deadline words, matched as substrings of a lowercased token so
# that affixed forms are caught too (diwajibkan, melarang, kewajiban, selambat-lambatnya).
# Indonesian nasal prefixes drop the first letter of some roots (serang -> menyerang,
# tembak -> menembak), so those stems are listed in both forms.
ORDER_STEMS = (
    "wajib", "larang", "rintah", "laksana", "harus", "segera", "nyegera", "serang", "nyerang",
    "serbu", "nyerbu", "tembak", "nembak", "gerak", "siaga", "nyiaga", "berangkat", "henti",
    "tangkap", "nangkap", "hancur", "kepung", "ngepung", "rebut", "sergap", "nyergap",
    "kerjakan", "ngerjakan", "siapkan", "nyiapkan", "cepat", "lekas", "lambat", "tenggat",
)
# Passive and noun forms of the standard closing formula ("Demikian untuk dilaksanakan dan
# dilaporkan pelaksanaannya"). They contain the stem "laksana" but give no order of their
# own; they are protected tokens, so every variant must keep them unchanged.
FORMULA_WORDS = frozenset({"dilaksanakan", "pelaksanaan", "pelaksanaannya"})
# Whole-word patterns, applied to each hyphen-separated part of a lowercased token.
_NEGATION_RE = re.compile(r"^(?:tidak|tak|bukan|belum|tanpa|tiada|jangan)(?:lah|kah|pun|nya|kan)?$")
_TIME_WORD_RE = re.compile(
    r"^(?:pukul|jam|tanggal|hari|besok|esok|lusa|kemarin|pagi|siang|sore|petang|malam|dini|fajar"
    r"|subuh|senja|pekan|minggu|bulan|tahun|detik|menit|waktu|sekarang|nanti|kini|wib|wita|wit"
    r"|senin|selasa|rabu|kamis|jumat|sabtu|januari|februari|maret|april|mei|juni|juli|agustus"
    r"|september|oktober|november|desember)(?:an|nya|lah)?$"
)
_NUMBER_WORD_RE = re.compile(
    r"^(?:nol|setengah|separuh|seperempat|sepertiga|pertama|kesatu|ganda"
    r"|(?:ke|ber)?(?:satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|sebelas|seratus"
    r"|seribu)(?:nya)?"
    r"|(?:se|ber|ke)?(?:puluh|belas|ratus|ribu|juta|miliar)(?:an)?(?:nya)?)$"
)
COORD_WORDS = frozenset({"koordinat", "lintang", "bujur", "derajat", "grid"})
_TIME_RE = re.compile(r"\b\d{1,2}[.:]\d{2}\b")
_COORD_RE = re.compile(r"\u00b0|\d+\s*['\u2032\u2033]|\b(?:LS|LU|BT|BB)\b")
_NON_WORD = re.compile(r"[^\w\s]|_")
_PUNCT = re.compile(r"[^\w\s-]|_")

SetsLike = Mapping[str, "VariantSet"] | Iterable["VariantSet"]


class IssuanceBlocked(RuntimeError):
    """Issuance refused: semantic variants await human review or fail a re-check."""


# ---------------------------------------------------------------------------------------
# Units


@dataclass(frozen=True)
class SemanticUnit:
    """A whole sentence occupying whole consecutive rows of one page.

    Attributes:
        unit_id: identifier, e.g. "u0".
        page: page index.
        rows: row indices on that page, consecutive.
        text: original text, rows joined by single spaces.
        left_x: common left edge of the rows (pt).
        right_x: right edge for re-wrapping (pt): the justified rows' edge, else the column edge.
        justified: per row, True if the row was stretched to the right edge.
    """

    unit_id: str
    page: int
    rows: tuple[int, ...]
    text: str
    left_x: float
    right_x: float
    justified: tuple[bool, ...]

    @property
    def row_ids(self) -> list[RowId]:
        """(page, row) of every row of the unit."""
        return [(self.page, r) for r in self.rows]

    @property
    def fingerprint(self) -> str:
        """SHA-256 over every field: ties a VariantSet to exactly this unit."""
        blob = json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("ascii")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return {"unit_id": self.unit_id, "page": self.page, "rows": list(self.rows), "text": self.text,
                "left_x": self.left_x, "right_x": self.right_x, "justified": list(self.justified)}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "SemanticUnit":
        """Inverse of :meth:`to_dict`."""
        return cls(str(d["unit_id"]), int(d["page"]), tuple(int(r) for r in d["rows"]),  # type: ignore[union-attr]
                   str(d["text"]), float(d["left_x"]), float(d["right_x"]),  # type: ignore[arg-type]
                   tuple(bool(j) for j in d["justified"]))  # type: ignore[union-attr]


def _column_edge(page: PageLayout, left: float) -> float:
    """Rightmost row end among rows of the page that start at ``left``."""
    return max(r.words[-1].x1 for r in page.rows if abs(r.words[0].x0 - left) <= X_TOL)


def _size(row: Row) -> float:
    return row.words[0].glyphs[0].size


def _same_block(upper: Row, lower: Row) -> bool:
    """True if ``lower`` follows ``upper`` at normal line spacing in the same font size."""
    size = _size(lower)
    return _size(upper) == size and 0 < lower.baseline - upper.baseline <= LEADING_MAX * size


def _ends_with(text: str, endings: tuple[str, ...]) -> bool:
    return text.rstrip().rstrip(_CLOSERS).endswith(endings)


def make_unit(master: MasterDocument, unit_id: str, page: int, rows: Sequence[int]) -> SemanticUnit:
    """Build a unit from consecutive rows; ValueError if the rows cannot be re-flowed as one block.

    Only the geometry is checked here. Whether the rows hold one whole sentence is checked
    by :func:`unit_problems`, which ``generate_variant_set`` and ``validate_selection``
    enforce, so a custom unit that cuts a sentence can never be issued.
    """
    idx = tuple(int(r) for r in rows)
    if not idx or idx != tuple(range(idx[0], idx[0] + len(idx))):
        raise ValueError("baris unit harus berurutan")
    page_layout = master.layout.pages[page]
    if idx[0] < 0 or idx[-1] >= len(page_layout.rows):
        raise ValueError("baris unit berada di luar halaman")
    objs = [page_layout.rows[r] for r in idx]
    states = {(g.font, g.size, g.color) for row in objs for w in row.words for g in w.glyphs}
    if len(states) != 1:
        raise ValueError("unit harus memakai satu jenis huruf, ukuran, dan warna")
    left = objs[0].words[0].x0
    if any(abs(r.words[0].x0 - left) > X_TOL for r in objs):
        raise ValueError("semua baris unit harus dimulai pada posisi kiri yang sama")
    edge = _column_edge(page_layout, left)
    last = len(objs) - 1
    justified = tuple(
        k < last and len(r.words) > 1 and edge - r.words[-1].x1 <= FULL_TOL for k, r in enumerate(objs)
    )
    right = max((r.words[-1].x1 for r, j in zip(objs, justified) if j), default=edge)
    text = " ".join(r.text for r in objs)
    return SemanticUnit(unit_id, page, idx, text, float(left), float(right), justified)


def _paragraph_rows(page: PageLayout, start: int) -> list[int]:
    """Rows of the paragraph starting at ``start``: continue while a row is full or unfinished."""
    rows = page.rows
    left = rows[start].words[0].x0
    edge = _column_edge(page, left)
    out = [start]
    while len(out) < MAX_UNIT_ROWS and out[-1] + 1 < len(rows):
        cur, nxt = rows[out[-1]], rows[out[-1] + 1]
        full = edge - cur.words[-1].x1 <= FULL_TOL
        if _ends_with(cur.text, SENTENCE_END) and not full:
            break
        if abs(nxt.words[0].x0 - left) > X_TOL or not _same_block(cur, nxt):
            break
        out.append(out[-1] + 1)
    return out


def _tembusan_items(page: PageLayout) -> list[int]:
    """Rows of the lists that follow a "Tembusan:" header (one cc line per row)."""
    rows = page.rows
    out: list[int] = []
    for header, row in enumerate(rows):
        if TEMBUSAN_HEADER.match(row.text):
            j = header + 1
            while j < len(rows) and _same_block(rows[j - 1], rows[j]):
                out.append(j)
                j += 1
    return out


def unit_problems(master: MasterDocument, unit: SemanticUnit) -> list[str]:
    """Reasons (Indonesian) why the unit is not one whole sentence on whole rows; empty = fine.

    A paragraph unit must (1) start where a sentence starts: no row above it in the same
    block, or that row ends with . ! ? : or ;  (2) end with . ! or ? (closing quotes
    allowed), and (3) have a last row shorter than the column, so neither the sentence nor
    the paragraph continues on the next row or page. This rejects the fragments of long
    paragraphs, of paragraphs split by a page break and of first-line indents.
    A single cc line under "Tembusan:" is a whole list item by construction.
    """
    page = master.layout.pages[unit.page]
    rows = page.rows
    if len(unit.rows) == 1 and unit.rows[0] in _tembusan_items(page):
        return []
    reasons: list[str] = []
    first, last = rows[unit.rows[0]], rows[unit.rows[-1]]
    if unit.rows[0] > 0:
        prev = rows[unit.rows[0] - 1]
        if _same_block(prev, first) and not _ends_with(prev.text, SENTENCE_END):
            reasons.append("unit bukan kalimat utuh: baris sebelumnya belum mengakhiri kalimat")
    if not _ends_with(unit.text, TERMINATORS):
        reasons.append("unit bukan kalimat utuh: tidak diakhiri titik, tanda seru, atau tanda tanya")
    elif _column_edge(page, unit.left_x) - last.words[-1].x1 <= FULL_TOL:
        reasons.append("unit bukan kalimat utuh: baris terakhir penuh sehingga paragraf dapat berlanjut")
    return reasons


def scan_candidates(master: MasterDocument) -> list[tuple[SemanticUnit, list[str]]]:
    """Every suggested unit in reading order with the reasons it is refused (empty = allowed).

    The reasons name categories only (never document words), so the UI can show them.
    """
    found: list[tuple[int, list[int]]] = []
    for page in master.layout.pages:
        tembusan = set(_tembusan_items(page))
        i = 0
        while i < len(page.rows):
            if i in tembusan:
                found.append((page.index, [i]))
                i += 1
            elif page.rows[i].text.startswith(TRIGGERS):
                rows = _paragraph_rows(page, i)
                found.append((page.index, rows))
                i = rows[-1] + 1
            else:
                i += 1
    out: list[tuple[SemanticUnit, list[str]]] = []
    for n, (page_index, rows) in enumerate(found):
        try:
            unit = make_unit(master, f"u{n}", page_index, rows)
        except ValueError:
            continue
        reasons = unit_problems(master, unit) + safety_check(unit.text)
        if not reasons and fit_variant(master, unit, unit.text) is None:
            reasons.append("kalimat asli tidak dapat ditata ulang pada baris yang sama")
        out.append((unit, reasons))
    return out


def find_candidate_units(master: MasterDocument) -> list[SemanticUnit]:
    """Suggested units that are whole sentences and pass ``safety_check`` (unsafe ones are never offered)."""
    return [unit for unit, reasons in scan_candidates(master) if not reasons]


def _parts(token: str) -> list[str]:
    return [p for p in token.lower().split("-") if p]


def safety_check(text: str) -> list[str]:
    """Reasons (Indonesian) why ``text`` must NOT be rephrased; an empty list means allowed.

    Refused: fewer than MIN_WORDS words, digits, times and time words (pukul, pagi, minggu,
    month and day names, ...), coordinates, capitalized words other than the first (names,
    units, ranks), order, prohibition and deadline words in any affixed form (see
    ORDER_STEMS), negations (tidak, tak, bukan, belum, tanpa, tiada, jangan) and number or
    quantity words (dua, kedua, puluhan, setengah, ...). The reasons are categories only.
    """
    toks = split_words(text)
    lower = [t.lower() for t in toks]
    parts = [p for t in toks for p in _parts(t)]
    reasons: list[str] = []
    if len(toks) < MIN_WORDS:
        reasons.append("kalimat terlalu pendek untuk diparafrasekan")
    if any(ch.isdigit() for ch in text):
        reasons.append("mengandung angka")
    if _TIME_RE.search(text) or any(_TIME_WORD_RE.match(p) for p in parts):
        reasons.append("menyebut waktu atau tanggal")
    if _COORD_RE.search(text) or any(p in COORD_WORDS for p in parts):
        reasons.append("menyebut koordinat atau posisi")
    if any(is_capitalized(t) for t in toks[1:]):
        reasons.append("mengandung kata berhuruf kapital selain kata pertama (nama, satuan, atau jabatan)")
    if any(t not in FORMULA_WORDS and any(stem in t for stem in ORDER_STEMS) for t in lower):
        reasons.append("mengandung kata perintah, larangan, atau tenggat")
    if any(_NEGATION_RE.match(p) for p in parts):
        reasons.append("mengandung kata ingkar")
    if any(_NUMBER_WORD_RE.match(p) for p in parts):
        reasons.append("menyebut bilangan")
    return reasons


# ---------------------------------------------------------------------------------------
# Layout fit


def fit_variant(master: MasterDocument, unit: SemanticUnit, text: str) -> dict[RowId, list[tuple[float, str]]] | None:
    """Word positions of ``text`` wrapped into exactly the unit's rows, or None if it does not fit.

    Same font, size, left and right edge as the original rows; rows that were justified are
    justified again, the last row is left aligned. A justified gap may be at most
    MAX_GAP_FACTOR spaces or the widest gap of the original rows, whichever is larger, so a
    variant never looks sparser than the document already does.
    """
    rows_obj = [master.layout.row((unit.page, r)) for r in unit.rows]
    g0 = rows_obj[0].words[0].glyphs[0]
    font, size = master.fonts[g0.font].font, g0.size
    words = text.split()
    if not words or any(not font.has_glyph(ord(ch)) for w in words for ch in w):
        return None
    space = font.text_length(" ", size)
    widest = max((b.x0 - a.x1 for row, j in zip(rows_obj, unit.justified) if j
                  for a, b in zip(row.words, row.words[1:])), default=0.0)
    max_gap = max(MAX_GAP_FACTOR * space, widest + 0.01)
    widths = [font.text_length(w, size) for w in words]
    avail = unit.right_x - unit.left_x
    lines: list[list[int]] = [[]]
    line_width = 0.0
    for i, w in enumerate(widths):
        if w > avail + WRAP_TOL:
            return None  # a single word wider than the column
        trial = w if not lines[-1] else line_width + space + w
        if lines[-1] and trial > avail + WRAP_TOL:
            lines.append([i])
            line_width = w
        else:
            lines[-1].append(i)
            line_width = trial
    if len(lines) != len(unit.rows):
        return None
    out: dict[RowId, list[tuple[float, str]]] = {}
    for k, (row, line) in enumerate(zip(unit.rows, lines)):
        gap = space
        if unit.justified[k] and k < len(lines) - 1 and len(line) > 1:
            gap = (avail - sum(widths[i] for i in line)) / (len(line) - 1)
            if gap > max_gap:
                return None
        x = unit.left_x
        placed = []
        for i in line:
            placed.append((round(x, 3), words[i]))
            x += widths[i] + gap
        out[(unit.page, row)] = placed
    return out


# ---------------------------------------------------------------------------------------
# Variant sets and review state


@dataclass
class VariantSet:
    """Variants of one unit with their review state.

    Attributes:
        unit_id: the unit these variants belong to.
        variants: variants[0] is the original sentence.
        equivalence: per variant, (equivalent, reason) from the provider's judge.
        status: per variant "menunggu" | "disetujui" | "ditolak"; the original is "disetujui".
        dropped: candidates removed by the automatic checks or the judge, with the reason.
            The candidate texts are document content (same protection as the master).
        provider: name of the provider that proposed the variants.
        unit_key: ``SemanticUnit.fingerprint`` of the unit the set was generated for.
    """

    unit_id: str
    variants: list[str]
    equivalence: list[tuple[bool, str]]
    status: list[str]
    dropped: list[tuple[str, str]] = field(default_factory=list)
    provider: str = ""
    unit_key: str = ""

    def __post_init__(self) -> None:
        if not self.variants or not (len(self.variants) == len(self.equivalence) == len(self.status)):
            raise ValueError("varian, hasil kesetaraan, dan status harus sama panjang")
        if any(s not in STATUSES for s in self.status):
            raise ValueError("status varian tidak dikenal")
        if self.status[0] != STATUS_APPROVED:
            raise ValueError("kalimat asli (varian 0) harus berstatus disetujui")

    def set_status(self, index: int, status: str) -> None:
        """Record a reviewer decision for variant ``index`` (1 .. len-1; the original cannot change)."""
        if status not in STATUSES:
            raise ValueError(f"status tidak dikenal: {status!r}")
        if index == 0:
            raise ValueError("status kalimat asli tidak dapat diubah")
        if not 1 <= index < len(self.status):
            raise ValueError("indeks varian tidak valid")
        self.status[index] = status

    def pending(self) -> list[int]:
        """Indices of variants still awaiting review."""
        return [i for i, s in enumerate(self.status) if s == STATUS_PENDING]

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form (for the review UI)."""
        return {
            "unit_id": self.unit_id,
            "unit_key": self.unit_key,
            "variants": list(self.variants),
            "equivalence": [{"equivalent": ok, "reason": why} for ok, why in self.equivalence],
            "status": list(self.status),
            "dropped": [{"text": t, "reason": r} for t, r in self.dropped],
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "VariantSet":
        """Inverse of :meth:`to_dict`."""
        return cls(
            unit_id=str(d["unit_id"]),
            variants=[str(v) for v in d["variants"]],  # type: ignore[union-attr]
            equivalence=[(bool(e["equivalent"]), str(e["reason"])) for e in d["equivalence"]],  # type: ignore[union-attr,index]
            status=[str(s) for s in d["status"]],  # type: ignore[union-attr]
            dropped=[(str(x["text"]), str(x["reason"])) for x in d.get("dropped", [])],  # type: ignore[union-attr,index,attr-defined]
            provider=str(d.get("provider", "")),  # type: ignore[attr-defined]
            unit_key=str(d.get("unit_key", "")),  # type: ignore[attr-defined]
        )


def match_key(text: str) -> str:
    """Normalized form for comparing sentences: no invisible marks, lowercase, no punctuation."""
    return " ".join(_NON_WORD.sub(" ", normalize_text(text).lower()).split())


def _punctuation_problem(original: str, candidate: str) -> str | None:
    """Reason if ``candidate`` adds punctuation or markup, or changes the final terminator."""
    if not set(_PUNCT.findall(candidate)) <= set(_PUNCT.findall(original)):
        return "memuat tanda baca atau karakter yang tidak ada pada kalimat asli"
    if original.rstrip()[-1:] in TERMINATORS and candidate.rstrip()[-1:] != original.rstrip()[-1:]:
        return "tanda akhir kalimat berubah"
    return None


def _variant_problem(master: MasterDocument, unit: SemanticUnit, candidate: str) -> str | None:
    """Reason (Indonesian) a variant of ``unit`` is not acceptable, or None (checks run in order)."""
    if protected_tokens(candidate) != protected_tokens(unit.text):
        return "token terlindungi berubah (angka, nama, atau kata kunci)"
    unsafe = safety_check(candidate)
    if unsafe:
        return "tidak lolos pemeriksaan keamanan: " + "; ".join(unsafe)
    punct = _punctuation_problem(unit.text, candidate)
    if punct:
        return punct
    if fit_variant(master, unit, candidate) is None:
        return "tidak muat tepat pada baris yang sama"
    return None


def _automatic_check(master: MasterDocument, unit: SemanticUnit, candidate: str,
                     kept_keys: list[str]) -> str | None:
    """Reason (Indonesian) to drop ``candidate``, or None if it passes every automatic check."""
    key = match_key(candidate)
    if not key:
        return "kandidat kosong"
    if key == kept_keys[0]:
        return "sama dengan kalimat asli"
    if any(Levenshtein.distance(key, k) < MIN_VARIANT_DISTANCE for k in kept_keys):
        return "duplikat atau terlalu mirip dengan varian lain"
    return _variant_problem(master, unit, candidate)


def _check_unit(master: MasterDocument, unit: SemanticUnit) -> None:
    rows = master.layout.pages[unit.page].rows if 0 <= unit.page < len(master.layout.pages) else []
    if (not unit.rows or unit.rows[-1] >= len(rows)
            or " ".join(rows[r].text for r in unit.rows) != unit.text):
        raise ValueError(f"unit {unit.unit_id} tidak cocok dengan dokumen induk")


def generate_variant_set(master: MasterDocument, unit: SemanticUnit, provider: LLMProvider,
                         n_candidates: int = 6) -> VariantSet:
    """Ask ``provider`` for paraphrases, keep those passing all checks; new ones await review.

    Raises ValueError (Indonesian) if the unit does not match the master, is not a whole
    sentence on whole rows, or fails ``safety_check``.
    """
    _check_unit(master, unit)
    problems = unit_problems(master, unit) + safety_check(unit.text)
    if problems:
        raise ValueError(f"unit {unit.unit_id} tidak boleh diparafrasekan: " + "; ".join(problems))
    if fit_variant(master, unit, unit.text) is None:
        raise ValueError(f"kalimat asli unit {unit.unit_id} tidak dapat ditata ulang pada baris yang sama")
    vs = VariantSet(unit.unit_id, [unit.text], [(True, "kalimat asli")], [STATUS_APPROVED],
                    provider=getattr(provider, "name", type(provider).__name__), unit_key=unit.fingerprint)
    kept_keys = [match_key(unit.text)]
    for raw in provider.paraphrase(unit.text, n_candidates):
        candidate = " ".join(raw.split())
        reason = _automatic_check(master, unit, candidate, kept_keys)
        why = ""
        if reason is None:  # the (possibly slow) model judge runs only on candidates that pass
            ok, why = provider.judge_equivalent(unit.text, candidate)
            if not ok:
                reason = f"tidak setara menurut pemeriksa: {why}"
        if reason is not None:
            vs.dropped.append((candidate, reason))
            continue
        vs.variants.append(candidate)
        vs.equivalence.append((True, why))
        vs.status.append(STATUS_PENDING)
        kept_keys.append(match_key(candidate))
    return vs


def index_sets(sets: SetsLike) -> dict[str, VariantSet]:
    """Variant sets keyed by unit id (accepts a mapping or an iterable of sets)."""
    items = list(sets.values()) if isinstance(sets, Mapping) else list(sets)
    out: dict[str, VariantSet] = {}
    for vs in items:
        if vs.unit_id in out:
            raise ValueError(f"unit ganda dalam himpunan varian: {vs.unit_id}")
        out[vs.unit_id] = vs
    return out


def set_matches_unit(vs: VariantSet | None, unit: SemanticUnit) -> bool:
    """True if ``vs`` was generated for exactly ``unit`` (same fingerprint, same original text)."""
    return (vs is not None and vs.unit_id == unit.unit_id and vs.unit_key == unit.fingerprint
            and vs.variants[0] == unit.text)


def usable_indices(vs: VariantSet) -> list[int]:
    """Indices of approved variants (original first), truncated to the largest power of two."""
    approved = [i for i, s in enumerate(vs.status) if s == STATUS_APPROVED]
    if not approved:
        return []
    return approved[: 1 << (len(approved).bit_length() - 1)]


def usable_variants(vs: VariantSet) -> list[str]:
    """Approved variant texts, truncated to a power of two (one variant means zero bits)."""
    return [vs.variants[i] for i in usable_indices(vs)]


def bits_per_unit(vs: VariantSet) -> int:
    """Code bits carried by a unit: log2 of the number of usable variants."""
    n = len(usable_indices(vs))
    return n.bit_length() - 1 if n else 0


def require_approved(sets: SetsLike) -> None:
    """Raise IssuanceBlocked if any selected unit still has variants awaiting review."""
    waiting = [uid for uid, vs in index_sets(sets).items() if vs.pending()]
    if waiting:
        raise IssuanceBlocked(
            "penerbitan diblokir: varian semantik untuk unit " + ", ".join(waiting)
            + " masih menunggu persetujuan; setujui atau tolak setiap varian terlebih dahulu"
        )


def check_structure(units: Sequence[SemanticUnit], sets: SetsLike) -> dict[str, VariantSet]:
    """Check that units and sets belong together; return the sets keyed by unit id.

    Units must be in reading order without overlap (so the code positions of each unit
    follow from the document alone), every unit needs its own VariantSet (same
    fingerprint and original text) and every set needs its unit. Raises ValueError
    (Indonesian) otherwise. These are structural checks, independent of the safety rules,
    so they hold at trace time for any selection that was valid at issuance.
    """
    idx = index_sets(sets)
    ids = [u.unit_id for u in units]
    if len(set(ids)) != len(ids):
        raise ValueError("id unit semantik ganda")
    for a, b in zip(units, units[1:]):
        if (b.page, b.rows[0]) <= (a.page, a.rows[-1]):
            raise ValueError("unit semantik harus berurutan sesuai urutan baca dan tidak bertumpang tindih")
    for u in units:
        if u.unit_id not in idx:
            raise ValueError(f"unit {u.unit_id} tidak memiliki himpunan varian")
        if not set_matches_unit(idx[u.unit_id], u):
            raise ValueError(f"himpunan varian tidak cocok dengan unit {u.unit_id} (dibuat untuk kalimat lain)")
    extra = sorted(set(idx) - set(ids))
    if extra:
        raise ValueError("himpunan varian tanpa unit: " + ", ".join(extra))
    return idx


def validate_selection(master: MasterDocument, units: Sequence[SemanticUnit], sets: SetsLike) -> None:
    """Re-check a selection right before issuance; IssuanceBlocked (Indonesian) on any problem.

    Runs ``require_approved`` and ``check_structure``, then checks every unit against the
    master (same text, whole sentence, safety_check) and every usable variant again
    (protected tokens, safety_check, punctuation, layout fit). This catches a hand-edited
    varian.json or a custom unit that was never reviewed by the automatic checks.
    """
    require_approved(sets)
    try:
        idx = check_structure(units, sets)
    except ValueError as exc:
        raise IssuanceBlocked(f"penerbitan diblokir: {exc}") from exc
    problems: list[str] = []
    for unit in units:
        try:
            _check_unit(master, unit)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        for reason in unit_problems(master, unit) + safety_check(unit.text):
            problems.append(f"unit {unit.unit_id}: {reason}")
        vs = idx[unit.unit_id]
        for i in usable_indices(vs):
            reason = None
            if i == 0:
                if fit_variant(master, unit, unit.text) is None:
                    reason = "kalimat asli tidak dapat ditata ulang pada baris yang sama"
            else:
                reason = _variant_problem(master, unit, vs.variants[i])
            if reason:
                problems.append(f"varian {unit.unit_id}:v{i}: {reason}")
    if problems:
        raise IssuanceBlocked("penerbitan diblokir: " + "; ".join(problems))


def variant_sets_digest(sets: SetsLike) -> str:
    """SHA-256 over unit ids, unit fingerprints, variants and statuses (kept instead of the text).

    Through ``unit_key`` the digest also covers the units (page, rows, text, edges,
    justification), and ``check_structure`` fixes their order, so a changed selection
    never matches the issuance record.
    """
    idx = index_sets(sets)
    payload = [{"unit_id": k, "unit_key": idx[k].unit_key, "variants": idx[k].variants, "status": idx[k].status}
               for k in sorted(idx)]
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------------------
# Embedding


def bits_to_index(bits: Sequence[int]) -> int:
    """Bits read as a binary number, most significant first."""
    k = 0
    for b in bits:
        k = (k << 1) | int(b)
    return k


def semantic_slot_refs(units: Sequence[SemanticUnit], sets: SetsLike) -> list[tuple[int, tuple[int, ...], int]]:
    """(page, (unit_index,), n_bits) per unit carrying at least one bit, for ``assign_positions``.

    Raises IssuanceBlocked while variants are pending and ValueError (``check_structure``)
    if units and sets do not belong together.
    """
    require_approved(sets)
    idx = check_structure(units, sets)
    refs = []
    for i, unit in enumerate(units):
        n_bits = bits_per_unit(idx[unit.unit_id])
        if n_bits > 0:
            refs.append((unit.page, (i,), n_bits))
    return refs


def semantic_marks(
    slots: Iterable[Slot],
    codeword: np.ndarray,
    master: MasterDocument,
    units: Sequence[SemanticUnit],
    sets: SetsLike,
) -> tuple[dict[RowId, list[tuple[float, str]]], list[str]]:
    """Row replacements for CopyMarks.row_words and the chosen variant ids ("u0:v2", ...).

    Runs ``validate_selection`` first, so nothing is drawn from an unreviewed or edited
    selection. The ids reveal codeword bits (index = bits XOR whitening): show them to the
    issuer if useful, but never store them in clear in the manifest or the registry,
    which outside auditors read. Anyone holding a recipient's ids and the variant texts
    could retype a leak that points at that recipient. They can always be recomputed at
    trace time from the code secret and copy_id (derive_codeword, then this function), and
    ``code_digest`` already commits to the whole codeword.
    """
    validate_selection(master, units, sets)
    idx = index_sets(sets)
    row_words: dict[RowId, list[tuple[float, str]]] = {}
    ids: list[str] = []
    for slot in slots:
        if slot.channel != CHANNEL_SEMANTIC:
            continue
        unit = units[slot.ref[0]]
        usable = usable_indices(idx[unit.unit_id])
        if len(usable) != 1 << len(slot.positions):
            raise ValueError(f"jumlah varian unit {unit.unit_id} tidak sesuai dengan rencana penyematan")
        bits = [int(codeword[p]) ^ w for p, w in zip(slot.positions, slot.whiten)]
        vi = usable[bits_to_index(bits)]
        fitted = fit_variant(master, unit, idx[unit.unit_id].variants[vi])
        if fitted is None:
            raise ValueError(f"varian {unit.unit_id}:v{vi} tidak muat pada baris aslinya")
        row_words.update(fitted)
        ids.append(f"{unit.unit_id}:v{vi}")
    return row_words, ids
