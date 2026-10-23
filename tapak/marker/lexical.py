"""Channel 6 (opt-in): word choice in the body text, reviewed by a person point by point.

Retyping a document removes every mark except what the words themselves say. This channel
gives each copy its own choice among forms of a short phrase that mean exactly the same in
Indonesian official letters ("sehubungan dengan" / "berkenaan dengan", "terdiri atas" /
"terdiri dari", "dan" / "serta" between two ordinary words, ...). The forms come from a
versioned lexicon file (``tapak/assets/leksikon/naskah_dinas_v1.json``), which is a DRAFT
until a Tata Naskah Dinas language reviewer signs it off.

Workflow:

1. ``scan_candidates`` finds every *point*: a lexicon phrase in a row of a justified body
   paragraph that passes the guards below and whose every combination of forms re-justifies
   into the same row. It returns a ``LexicalSelection`` with every point awaiting review and
   refusal counts per category (never document words).
2. A person approves or rejects every point (``set_status``, CLI ``tapak leksikal review``).
   ``require_reviewed`` blocks issuance while any point is undecided, and
   ``validate_selection`` re-checks the file before any copy is drawn: the scan digest (points
   or forms edited by hand are refused), the lexicon digest, a fresh scan of the master that
   must give exactly the same points, and the layout fit. The review decisions themselves are
   not authenticated: a status edited by hand is accepted, so the file is kept like the master.
3. An approved point with 2^b forms carries b code bits: the copy shows the form whose index
   is the point's whitened bits read as a binary number, most significant first, as in the
   semantic channel. Positions come from the shared retype band (``plan.RETYPE_BAND``).

What is never changed:

* the phrase is a lexicon entry, never a number, name, unit, rank, time, coordinate,
  quantity, order or negation;
* guard window: no word within ``GUARD_WINDOW`` words of the phrase in the same sentence
  (and no word of the phrase) may hold a digit, a capitalized word other than a sentence
  start, a time, coordinate, number or quantity word, an order, prohibition or deadline
  word, or a negation (the ``semantic.safety_check`` categories plus a few function words
  such as "agar", "harap", "paling", "sampai");
* policy "kalimat" (stricter): the whole sentence must pass ``semantic.safety_check``;
* paragraph headings ("14. Maksud dan tujuan."), header fields, the signature block,
  tembusan lists, page headers and footers, rows of suggested semantic units and rows that
  mix fonts are never touched (``body_rows``), and a phrase never spans two rows;
* forms of one rule differ by at least ``MIN_FORM_DISTANCE`` characters and no form is
  another form minus a word, so a dropped word or a typo cannot turn one form into another.

Layout: a row holding points is redrawn word by word (``CopyMarks.row_words``). Unchanged
words keep their master glyphs, kerning, zero-width marks and homoglyph; only the point
words are new text. Every combination of forms must keep the left and right edge, any
hanging label ("1.", "14.", "a.", see ``label_count``) and the first word after it in place,
with gaps between ``MIN_GAP_FACTOR`` and
``MAX_GAP_FACTOR`` spaces (or the row's widest original gap); otherwise the point with the
largest width change is dropped. Rows that hold a carrying point leave the shift channel.

Data minimization: forms and row context are document content. The selection file
(``leksikal.json``) is stored next to the master, never in the registry or in logs; the
registry and the manifest keep only its digest. Form choices of a copy are code bits: they
are never stored, and are recomputed from the code secret at trace time.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rapidfuzz.distance import Levenshtein

from tapak.llm.provider import is_capitalized
from tapak.marker import semantic as sem
from tapak.marker.layout import Row, RowId, WordId
from tapak.marker.master import MasterDocument
from tapak.marker.plan import CHANNEL_LEXICAL, RETYPE_STREAM, Slot, assign_positions, retype_pool
from tapak.marker.semantic import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED, STATUSES, IssuanceBlocked

LEXICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "leksikon"
DEFAULT_LEXICON = "naskah_dinas_v1"
SELECTION_FORMAT = "tapak-leksikal-1"

GUARD_WINDOW = 2          # words on each side of a point that must be harmless
MIN_GAP_FACTOR = 1.0      # a justified gap is never narrower than a normal space
MAX_GAP_FACTOR = 3.0      # nor wider than 3 spaces (or the row's widest original gap)
FULL_TOL = 1.5            # pt: a row ending this close to the right margin is justified
EDGE_TOL = 0.5            # pt: overshoot tolerated for a left-aligned row
MIN_FORM_DISTANCE = 3     # characters between any two forms of a rule
MAX_ROW_COMBINATIONS = 256
CONTEXT_WORDS = 30        # words shown on each side of a point to the reviewer

# Lone-leaker level for retyped text, fixed before the measurements of this table: about 95 %
# detection at eps = 1e-6 from 48 to 64 band bits under heavy noise or a typist's habit
# (research simulation, N = 20 to 100). The issuer sees whether a document reaches it; it says
# "cukup untuk satu pembocor" only from this level on.
LONE_LEAKER_BITS = 64
# Average bits per 100 body words with this table (tier A), measured on the two sample notes
# and the long synthetic documents (research/ketik/ukur.py kapasitas). Used only to turn a bit
# count into an indicative word count for the issuer and the berita acara.
BITS_PER_100_WORDS = 3.6
LONE_LEAKER_WORDS = 1800  # LONE_LEAKER_BITS at BITS_PER_100_WORDS, rounded to 100 words
# Issuer note for word choice on a document meant for printing (the print background profile).
# Rows holding a point leave the shift channel, the only channel of the default profile on
# paper. Measured in research/ocr (hasil/terbit.jsonl, hasil/ringkas_uji.json; simulated prints
# with the default background profile): the sample nota dinas carried 314 shift positions with
# word choice and sentence variants against 439 without, OCR gave back at most 9 bits per page,
# and the issuance without either named the right printed copy at least as often in every cell.
# A note only: issuance itself is unchanged.
PRINT_NOTE = (
    "Untuk dokumen cetak, pilihan kata mengambil lebih banyak posisi geser daripada yang dikembalikan OCR: pada "
    "nota dinas contoh 439 menjadi 314 posisi geser (bersama varian kalimat), sedangkan OCR mengembalikan paling "
    "banyak 9 bit per halaman; dalam uji foto cetak simulasi (profil latar bawaan), penerbitan tanpa keduanya "
    "menyebut salinan yang benar sama sering atau lebih sering di setiap sel"
)

POLICIES = ("lokal", "kalimat")
_STRIP = ".,;:!?\"'()[]{}"
_GUARD_WORDS = frozenset({"agar", "supaya", "harap", "mohon", "diminta", "dimohon", "perlu", "paling"})
_GUARD_TIME = frozenset({"selama", "sampai", "hingga", "lambat"})
_GUARD_QUANTITY = frozenset({"beberapa", "seluruh", "semua"})

# Refusal categories (Indonesian, shown to the issuer; never document words).
REFUSE_DIGIT = "angka"
REFUSE_NAME = "nama/satuan/jabatan"
REFUSE_TIME = "waktu"
REFUSE_COORD = "koordinat"
REFUSE_NUMBER = "bilangan"
REFUSE_ORDER = "perintah"
REFUSE_NEGATION = "ingkar"
REFUSE_HEADING = "judul paragraf"
REFUSE_CONTEXT = "konteks aturan tidak cocok"
REFUSE_SENTENCE = "kalimat memuat unsur terlindungi"
REFUSE_FIT = "tidak muat pada baris"
REFUSE_FONT = "baris memakai lebih dari satu jenis huruf"
REFUSE_GLYPH = "huruf tidak tersedia pada font"


class LexiconError(ValueError):
    """The lexicon file is missing or breaks the table rules."""


# ---------------------------------------------------------------------------------------
# Lexicon


@dataclass(frozen=True)
class LexRule:
    """Equivalent forms (lowercase, single spaces) and an optional context condition.

    Attributes:
        rule_id: identifier (lowercase, digits and underscores).
        forms: equivalent forms; a point uses the matched form first, then the others in
            this order, truncated to a power of two.
        tier: "A" (function words and fixed phrases, scanned by default) or "B" (content
            words, scanned only on request).
        match: forms that may be matched in the master (default: all forms).
        next_re, prev_re: regular expressions for the lowercased word right after / before
            the phrase in the same sentence (punctuation stripped from ``next``); None means
            no condition.
        note, example: shown to the reviewer.
    """

    rule_id: str
    forms: tuple[str, ...]
    tier: str = "A"
    match: tuple[str, ...] = ()
    next_re: str | None = None
    prev_re: str | None = None
    note: str = ""
    example: str = ""

    @property
    def matchable(self) -> tuple[str, ...]:
        """Forms that may be found in the master."""
        return self.match or self.forms


@dataclass(frozen=True)
class Lexicon:
    """A versioned lexicon file.

    Attributes:
        name: file stem, e.g. "naskah_dinas_v1" (recorded as ``lexicon_version``).
        version: version number inside the file.
        status: "draf" until a language reviewer signs the table off.
        rules: the rules in file order.
        digest: SHA-256 of the canonical JSON of the file content.
    """

    name: str
    version: int
    status: str
    rules: tuple[LexRule, ...]
    digest: str

    def rule(self, rule_id: str) -> LexRule:
        """The rule with this id (KeyError if unknown)."""
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        raise KeyError(rule_id)

    @property
    def is_draft(self) -> bool:
        """True while the table has not been signed off by a language reviewer."""
        return self.status != "disahkan"


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _sha256(obj: object) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _minus_one_word(a: str, b: str) -> bool:
    """True if form ``b`` is form ``a`` with exactly one word left out."""
    wa, wb = a.split(), b.split()
    return len(wa) == len(wb) + 1 and any(wa[:i] + wa[i + 1:] == wb for i in range(len(wa)))


def lexicon_problems(data: Mapping[str, object]) -> list[str]:
    """Problems (Indonesian) with a parsed lexicon file; empty when it follows the table rules.

    Every rule needs an id, a tier A or B and at least two distinct lowercase forms; forms of
    one rule differ by at least MIN_FORM_DISTANCE characters and none is another minus one
    word; no form appears in two rules; no word of a form is a protected token (digit,
    capital, time, coordinate, number, order or negation word); ``match`` forms belong to
    the rule and the context conditions compile.
    """
    problems: list[str] = []
    if not isinstance(data.get("id"), str) or not isinstance(data.get("version"), int):
        problems.append("leksikon wajib memiliki id dan version")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        return problems + ["leksikon tidak memiliki aturan"]
    seen_ids: set[str] = set()
    owner: dict[str, str] = {}
    for r in rules:
        if not isinstance(r, dict):
            problems.append("aturan harus berupa objek")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[a-z0-9_]+", rid):
            problems.append(f"id aturan tidak sah: {rid!r}")
            continue
        if rid in seen_ids:
            problems.append(f"id aturan ganda: {rid}")
        seen_ids.add(rid)
        forms = r.get("forms")
        if (not isinstance(forms, list) or len(forms) < 2
                or not all(isinstance(f, str) and f == " ".join(f.split()) and f == f.lower() and f for f in forms)):
            problems.append(f"{rid}: perlu sedikitnya dua bentuk huruf kecil dengan satu spasi")
            continue
        if len(set(forms)) != len(forms):
            problems.append(f"{rid}: bentuk ganda")
        if r.get("tier") not in ("A", "B"):
            problems.append(f"{rid}: tingkat harus A atau B")
        for a, b in itertools.combinations(forms, 2):
            if Levenshtein.distance(a, b) < MIN_FORM_DISTANCE:
                problems.append(f"{rid}: bentuk '{a}' dan '{b}' berbeda kurang dari {MIN_FORM_DISTANCE} karakter")
            if _minus_one_word(a, b) or _minus_one_word(b, a):
                problems.append(f"{rid}: bentuk '{a}' dan '{b}' hanya berbeda satu kata yang dihilangkan")
        for f in forms:
            if f in owner and owner[f] != rid:
                problems.append(f"bentuk '{f}' ada di aturan {owner[f]} dan {rid}")
            owner[f] = rid
            for w in f.split():
                why = _token_problem(w, sentence_start=False)
                if why is not None:
                    problems.append(f"{rid}: bentuk '{f}' memuat kata terlindungi ({why})")
        match = r.get("match", [])
        if not isinstance(match, list) or not set(match) <= set(forms):
            problems.append(f"{rid}: match harus berisi bentuk dari aturan ini")
        for key in ("next", "prev"):
            if key in r:
                try:
                    re.compile(str(r[key]))
                except re.error:
                    problems.append(f"{rid}: ekspresi {key} tidak sah")
    return problems


def load_lexicon(name: str = DEFAULT_LEXICON, path: Path | None = None) -> Lexicon:
    """Read and check a lexicon file (LexiconError, in Indonesian, if it breaks a rule)."""
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise LexiconError(f"nama leksikon tidak sah: {name!r}")
    path = Path(path) if path is not None else LEXICON_DIR / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LexiconError(f"leksikon {name} tidak dapat dibaca") from exc
    if not isinstance(data, dict):
        raise LexiconError(f"leksikon {name} bukan objek JSON")
    problems = lexicon_problems(data)
    if problems:
        raise LexiconError(f"leksikon {name} tidak sah: " + "; ".join(problems[:5]))
    rules = tuple(
        LexRule(rule_id=r["id"], forms=tuple(r["forms"]), tier=r["tier"], match=tuple(r.get("match", ())),
                next_re=r.get("next"), prev_re=r.get("prev"), note=str(r.get("note", "")),
                example=str(r.get("example", "")))
        for r in data["rules"]
    )
    return Lexicon(name=name, version=int(data["version"]), status=str(data.get("status", "draf")),
                   rules=rules, digest=_sha256(data))


# ---------------------------------------------------------------------------------------
# Points and the reviewed selection


@dataclass
class LexPoint:
    """One substitution point: words [start, end) of a master row, with its review state.

    Attributes:
        point_id: "l0", "l1", ... in reading order.
        page, row: master row.
        start, end: word indices in the row (end exclusive).
        rule_id: lexicon rule.
        forms: forms as drawn in a copy (case and trailing punctuation applied); forms[0] is
            the master text; the count is a power of two.
        context: the sentence holding the phrase, with the phrase in square brackets, across
            rows (at most ``CONTEXT_WORDS`` words on each side; shown to the reviewer, document
            content, part of the scan digest).
        status: "menunggu" | "disetujui" | "ditolak".
        repeated: another place of the master text fits this point's phrase with its context
            closely enough for the decoder to read it there (``repeated_points``). If the
            leaker reorders sentences, such a point can be read at that other place; this
            lowers the leaker's score and never points at another copy. Shown to the reviewer.
    """

    point_id: str
    page: int
    row: int
    start: int
    end: int
    rule_id: str
    forms: tuple[str, ...]
    context: str = ""
    status: str = STATUS_PENDING
    repeated: bool = False

    @property
    def row_id(self) -> RowId:
        """(page, row) of the point."""
        return (self.page, self.row)

    @property
    def bits(self) -> int:
        """Code bits carried when approved: log2 of the number of forms."""
        return len(self.forms).bit_length() - 1 if self.forms else 0

    @property
    def carrying(self) -> bool:
        """True if the point is approved and carries at least one bit."""
        return self.status == STATUS_APPROVED and self.bits > 0

    def word_ids(self) -> list[WordId]:
        """Master words of the phrase."""
        return [(self.page, self.row, k) for k in range(self.start, self.end)]

    def structure(self) -> dict[str, object]:
        """Every field except the review status (what the scan determines)."""
        return {"point_id": self.point_id, "page": self.page, "row": self.row, "start": self.start,
                "end": self.end, "rule_id": self.rule_id, "forms": list(self.forms), "context": self.context,
                "repeated": self.repeated}

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return {**self.structure(), "status": self.status}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "LexPoint":
        """Inverse of :meth:`to_dict`."""
        return cls(str(d["point_id"]), int(d["page"]), int(d["row"]), int(d["start"]),  # type: ignore[arg-type]
                   int(d["end"]), str(d["rule_id"]), tuple(str(f) for f in d["forms"]),  # type: ignore[arg-type,union-attr]
                   str(d.get("context", "")), str(d.get("status", STATUS_PENDING)), bool(d.get("repeated", False)))


@dataclass
class LexicalSelection:
    """Scan result for one master and the reviewer's decision on every point.

    Holds document text (forms and row context), so it is stored next to the master
    (``leksikal.json``) and never in the registry; the issuance record keeps ``digest``.

    Attributes:
        doc_hash: SHA-256 of the master PDF the scan ran on.
        lexicon: lexicon name (``lexicon_version`` in the manifest).
        lexicon_digest: digest of that lexicon file.
        tiers, policy: scan options.
        points: every point found, in reading order.
        body_words: words of justified body rows (capacity context).
        refused: refusal counts per category (no document words).
        scan_digest: digest of the scan result without review statuses; a file whose points
            or forms were edited by hand no longer matches it (statuses are not covered).
    """

    doc_hash: str
    lexicon: str
    lexicon_digest: str
    tiers: str
    policy: str
    points: list[LexPoint]
    body_words: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    scan_digest: str = ""

    def compute_scan_digest(self) -> str:
        """Digest of everything the scan determines (statuses excluded)."""
        return _sha256({"format": SELECTION_FORMAT, "doc_hash": self.doc_hash, "lexicon": self.lexicon,
                        "lexicon_digest": self.lexicon_digest, "tiers": self.tiers, "policy": self.policy,
                        "points": [p.structure() for p in self.points]})

    @property
    def digest(self) -> str:
        """Digest of the scan and every review decision (recorded instead of the text)."""
        return _sha256({"scan": self.compute_scan_digest(),
                        "status": [[p.point_id, p.status] for p in self.points]})

    def point(self, point_id: str) -> LexPoint:
        """The point with this id (KeyError if unknown)."""
        for p in self.points:
            if p.point_id == point_id:
                return p
        raise KeyError(point_id)

    def set_status(self, point_id: str, status: str) -> None:
        """Record a reviewer decision for one point."""
        if status not in STATUSES:
            raise ValueError(f"status tidak dikenal: {status!r}")
        try:
            self.point(point_id).status = status
        except KeyError:
            raise ValueError(f"titik tidak dikenal: {point_id}") from None

    def pending(self) -> list[str]:
        """Ids of points still awaiting a decision."""
        return [p.point_id for p in self.points if p.status == STATUS_PENDING]

    def carrying(self) -> list[LexPoint]:
        """Approved points that carry bits, in reading order."""
        return [p for p in self.points if p.carrying]

    @property
    def bits(self) -> int:
        """Code bits of the approved points."""
        return sum(p.bits for p in self.carrying())

    @property
    def candidate_bits(self) -> int:
        """Code bits if every point not rejected were approved."""
        return sum(p.bits for p in self.points if p.status != STATUS_REJECTED)

    def counts(self) -> dict[str, int]:
        """Number of points per review status."""
        return {s: sum(1 for p in self.points if p.status == s) for s in STATUSES}

    def shift_excluded_rows(self) -> set[RowId]:
        """Rows holding a carrying point (redrawn word by word, so they leave the shift channel)."""
        return {p.row_id for p in self.carrying()}

    def excluded_words(self) -> set[WordId]:
        """Master words of carrying points (they carry no zero-width mark or homoglyph)."""
        return {w for p in self.carrying() for w in p.word_ids()}

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return {"format": SELECTION_FORMAT, "doc_hash": self.doc_hash, "lexicon": self.lexicon,
                "lexicon_digest": self.lexicon_digest, "tiers": self.tiers, "policy": self.policy,
                "body_words": self.body_words, "refused": dict(self.refused), "scan_digest": self.scan_digest,
                "points": [p.to_dict() for p in self.points]}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "LexicalSelection":
        """Inverse of :meth:`to_dict` (ValueError for a file that is not a selection)."""
        if d.get("format") != SELECTION_FORMAT:
            raise ValueError("bukan berkas pilihan kata TAPAK")
        try:
            return cls(str(d["doc_hash"]), str(d["lexicon"]), str(d["lexicon_digest"]), str(d["tiers"]),
                       str(d["policy"]), [LexPoint.from_dict(p) for p in d["points"]],  # type: ignore[union-attr]
                       int(d.get("body_words", 0)),  # type: ignore[arg-type]
                       {str(k): int(v) for k, v in dict(d.get("refused", {})).items()},  # type: ignore[arg-type]
                       str(d.get("scan_digest", "")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("berkas pilihan kata rusak") from exc

    def to_json(self) -> str:
        """Pretty JSON for the review file."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------------------
# Body text detection


def _bare(word: str) -> str:
    return word.strip(_STRIP).lower()


def _common_edge(rows: Iterable[Row]) -> float | None:
    """Most common right edge (rounded) of rows with at least 3 words, or None."""
    ends = [round(r.words[-1].x1) for r in rows if len(r.words) >= 3]
    return max(sorted(set(ends)), key=ends.count) if ends else None


def page_edges(master: MasterDocument) -> dict[int, float]:
    """Right edge of the justified column per page.

    The column edge is the most common right edge of the whole document, so a page without
    body text (a tembusan list, a signature) does not get an edge of its own; on each page it
    is refined to the widest row ending within 1 pt of it.
    """
    common = _common_edge(r for p in master.layout.pages for r in p.rows)
    out: dict[int, float] = {}
    for p in master.layout.pages:
        if not p.rows:
            continue
        if common is None:
            out[p.index] = max(r.words[-1].x1 for r in p.rows)
            continue
        near = [r.words[-1].x1 for r in p.rows if abs(r.words[-1].x1 - common) <= 1.0]
        out[p.index] = max(near) if near else float(common)
    return out


def _running_rows(master: MasterDocument) -> set[tuple[str, int]]:
    """(text, baseline) of rows repeated at the same height on several pages (running header,
    classification, footer)."""
    seen: dict[tuple[str, int], set[int]] = {}
    for p in master.layout.pages:
        for r in p.rows:
            seen.setdefault((r.text, round(r.baseline)), set()).add(p.index)
    return {key for key, pages in seen.items() if len(pages) > 1}


_TEMBUSAN_RE = re.compile(r"^tembusan\s*:$", re.IGNORECASE)


def body_rows(master: MasterDocument) -> list[Row]:
    """Rows of justified paragraphs: a full row, or the row right after a full body row.

    A full row ends at the column edge (within FULL_TOL, never beyond it) and starts in the
    left half of the column. Rows repeated on several pages (header, footer) and everything
    from a "Tembusan:" row on are never body rows, so signature blocks, tembusan lists and
    page footers are not counted as body text and never hold a point.
    """
    edges = page_edges(master)
    running = _running_rows(master)
    left = min((r.words[0].x0 for p in master.layout.pages for r in p.rows), default=0.0)
    out: list[Row] = []
    for page in master.layout.pages:
        if not page.rows:
            continue
        edge = edges[page.index]
        middle = (left + edge) / 2
        prev_full = False
        for k, row in enumerate(page.rows):
            if _TEMBUSAN_RE.match(row.text.strip()):
                return out
            if (row.text, round(row.baseline)) in running:
                prev_full = False
                continue
            full = (abs(edge - row.words[-1].x1) <= FULL_TOL and len(row.words) > 2
                    and row.words[0].x0 < middle)
            cont = prev_full and k > 0 and sem._same_block(page.rows[k - 1], row)
            if full or cont:
                out.append(row)
            prev_full = full
    return out


LABEL_RE = re.compile(r"(?:\d{1,3}|[a-zA-Z]|[ivxIVX]{2,4})[.)]")
LABEL_COLUMN_TOL = 1.0    # pt: the word after a label starts at a text column of the page


def _text_columns(rows: Sequence[Row]) -> list[float]:
    """Left edges where text rows of a page start: rows that do not begin with a label, and the
    word after a label when at least two labelled rows share it."""
    cols = [r.words[0].x0 for r in rows if not LABEL_RE.fullmatch(r.words[0].text)]
    after = [r.words[1].x0 for r in rows if len(r.words) > 1 and LABEL_RE.fullmatch(r.words[0].text)]
    cols += [x for x in after if sum(abs(x - y) <= LABEL_COLUMN_TOL for y in after) >= 2]
    return cols


def label_count(master: MasterDocument, row: Row) -> int:
    """Number of leading words that form a hanging label ("1.", "14.", "a.") kept in place.

    A label is a list marker by its shape (digits, one letter or a roman numeral, then "." or
    ")") whose next word starts at a text column of the page (where other rows start), so the
    text stays in its hanging indent. The gap after the label plays no part: "10." leaves a
    narrower gap than "1.".
    """
    if len(row.words) < 2 or not LABEL_RE.fullmatch(row.words[0].text):
        return 0
    x = row.words[1].x0
    if x <= row.words[0].x1:
        return 0
    cols = _text_columns(master.layout.pages[row.page].rows)
    return 1 if any(abs(x - c) <= LABEL_COLUMN_TOL for c in cols) else 0


def _row_state(row: Row) -> tuple[str, float, int] | None:
    """(font, size, colour) shared by every glyph of the row, or None if they differ."""
    states = {(g.font, g.size, g.color) for w in row.words for g in w.glyphs}
    return next(iter(states)) if len(states) == 1 else None


# ---------------------------------------------------------------------------------------
# Guards


def _token_problem(tok: str, sentence_start: bool) -> str | None:
    """Category if this token must not change or sit next to a changed word."""
    bare = tok.strip(_STRIP)
    if not bare:
        return None
    if any(ch.isdigit() for ch in bare):
        return REFUSE_DIGIT
    if is_capitalized(bare) and not sentence_start:
        return REFUSE_NAME
    low = bare.lower()
    parts = [p for p in low.split("-") if p]
    if any(sem._TIME_WORD_RE.match(p) for p in parts) or low in _GUARD_TIME:
        return REFUSE_TIME
    if any(p in sem.COORD_WORDS for p in parts):
        return REFUSE_COORD
    if any(sem._NUMBER_WORD_RE.match(p) for p in parts) or low in _GUARD_QUANTITY:
        return REFUSE_NUMBER
    if low not in sem.FORMULA_WORDS and any(stem in low for stem in sem.ORDER_STEMS):
        return REFUSE_ORDER
    if low in _GUARD_WORDS:
        return REFUSE_ORDER
    if any(sem._NEGATION_RE.match(p) for p in parts):
        return REFUSE_NEGATION
    return None


def _display_context(stream: Sequence[str], gi: int, ge: int, labels: set[int]) -> str:
    """The sentence holding stream[gi:ge] with the phrase in square brackets, for the reviewer.

    The sentence may span several rows, so the reviewer sees what a phrase at the start or
    end of a row joins. At most CONTEXT_WORDS words are shown on each side ("..." marks a cut).
    """
    s, e = _sentence_bounds(stream, gi)
    lo, hi = max(s, gi - CONTEXT_WORDS), min(e, ge + CONTEXT_WORDS)
    words = ([stream[i] for i in range(lo, gi) if i not in labels] + ["[" + " ".join(stream[gi:ge]) + "]"]
             + [stream[i] for i in range(ge, hi) if i not in labels])
    return ("... " if lo > s else "") + " ".join(words) + (" ..." if hi < e else "")


def _sentence_bounds(tokens: Sequence[str], i: int) -> tuple[int, int]:
    """[start, end) of the sentence holding token i (split after . ! ? ; :)."""
    s = i
    while s > 0 and not tokens[s - 1].rstrip("\"')").endswith((".", "!", "?", ";", ":")):
        s -= 1
    e = i
    while e < len(tokens) - 1 and not tokens[e].rstrip("\"')").endswith((".", "!", "?", ";", ":")):
        e += 1
    return s, e + 1


def _is_sentence_start(tokens: Sequence[str], i: int, labels: set[int]) -> bool:
    if i == 0 or (i - 1) in labels:
        return True
    return tokens[i - 1].rstrip("\"')").endswith((".", "!", "?", ":"))


def _guard(stream: Sequence[str], gi: int, ge: int, labels: set[int], rule: LexRule, policy: str) -> str | None:
    """Refusal category for the phrase at stream[gi:ge], or None if it may change."""
    s, e = _sentence_bounds(stream, gi)
    # A heading such as "Maksud dan tujuan." right after a paragraph label.
    if ((s in labels or (s - 1) in labels) and e - s <= 5) or ((gi - 1) in labels and e - s <= 5):
        return REFUSE_HEADING
    nxt = _bare(stream[ge]) if ge < e and ge < len(stream) else ""
    prv = stream[gi - 1].lower() if gi - 1 >= s and (gi - 1) not in labels else ""
    if rule.next_re and not re.match(rule.next_re, nxt):
        return REFUSE_CONTEXT
    if rule.prev_re and not re.match(rule.prev_re, prv):
        return REFUSE_CONTEXT
    if policy == "kalimat":
        sentence = " ".join(stream[i] for i in range(s, e) if i not in labels)
        return REFUSE_SENTENCE if sem.safety_check(sentence) else None
    for i in range(max(s, gi - GUARD_WINDOW), min(e, ge + GUARD_WINDOW)):
        if i in labels:
            continue
        why = _token_problem(stream[i], _is_sentence_start(stream, i, labels))
        if why is not None:
            return why
    return None


# ---------------------------------------------------------------------------------------
# Layout fit


def _word_width(master: MasterDocument, row: Row, text: str, wid: WordId | None) -> float:
    if wid is not None:
        w = master.layout.word(wid)
        return w.x1 - w.x0
    g0 = row.words[0].glyphs[0]
    return master.fonts[g0.font].font.text_length(text, g0.size)


def fit_row(master: MasterDocument, row: Row, words: Sequence[tuple[str, WordId | None]],
            edge: float) -> list[tuple[float, str, WordId | None]] | None:
    """Positions of ``words`` (text, master word or None) laid out in ``row``, or None if they do not fit.

    A hanging label stays where it is. A row that ended at the right edge is justified
    again between the same edges, with gaps between MIN_GAP_FACTOR and MAX_GAP_FACTOR
    spaces (or the widest original gap); a shorter row keeps its median gap and must stay
    within the edge. Master words keep their own width (kerning included).
    """
    g0 = row.words[0].glyphs[0]
    font = master.fonts[g0.font].font
    space = font.text_length(" ", g0.size)
    lab = label_count(master, row)
    if any(wid is None and not all(font.has_glyph(ord(ch)) for ch in text) for text, wid in words):
        return None
    placed: list[tuple[float, str, WordId | None]] = [
        (round(row.words[k].x0, 3), words[k][0], words[k][1]) for k in range(lab)]
    seg = list(words[lab:])
    left = row.words[lab].x0
    widths = [_word_width(master, row, t, wid) for t, wid in seg]
    gaps = [b.x0 - a.x1 for a, b in zip(row.words[lab:], row.words[lab + 1:])]
    justified = edge - row.words[-1].x1 <= FULL_TOL
    if justified and len(seg) > 1:
        gap = (row.words[-1].x1 - left - sum(widths)) / (len(seg) - 1)
        widest = max(gaps, default=space)
        if gap < MIN_GAP_FACTOR * space - 1e-6 or gap > max(MAX_GAP_FACTOR * space, widest + 0.01):
            return None
    else:
        gap = float(np.median(gaps)) if gaps else space
        if left + sum(widths) + gap * (len(seg) - 1) > edge + EDGE_TOL:
            return None
    x = left
    for (text, wid), wd in zip(seg, widths):
        placed.append((round(x, 3), text, wid))
        x += wd + gap
    return placed


def row_words_for(row: Row, points: Sequence[LexPoint], choice: Mapping[str, int]) -> list[tuple[str, WordId | None]]:
    """Copy words of ``row`` (text, master word id or None for point words) with form
    ``choice[point_id]`` at each of its points (form 0 where no choice is given)."""
    words: list[tuple[str, WordId | None]] = [(w.text, w.id) for w in row.words]
    for pt in sorted(points, key=lambda p: -p.start):  # right to left keeps indices valid
        words[pt.start:pt.end] = [(t, None) for t in pt.forms[choice.get(pt.point_id, 0)].split()]
    return words


def _row_fits_all(master: MasterDocument, row: Row, points: Sequence[LexPoint], edge: float) -> bool:
    n = 1
    for p in points:
        n *= len(p.forms)
    if n > MAX_ROW_COMBINATIONS:
        return False
    for combo in itertools.product(*[range(len(p.forms)) for p in points]):
        choice = {p.point_id: k for p, k in zip(points, combo)}
        if fit_row(master, row, row_words_for(row, points, choice), edge) is None:
            return False
    return True


# ---------------------------------------------------------------------------------------
# Scan


@dataclass
class ScanReport:
    """Counts behind a scan: body words, matched phrases, refusals per category, kept points."""

    body_words: int = 0
    matched: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    points: list[LexPoint] = field(default_factory=list)

    def refuse(self, why: str) -> None:
        """Count one refused phrase under ``why`` (a category, never document words)."""
        self.refused[why] = self.refused.get(why, 0) + 1


def _apply_case(master_text: str, form: str) -> str:
    return form[:1].upper() + form[1:] if master_text[:1].isupper() else form


def _semantic_rows(master: MasterDocument) -> set[RowId]:
    """Rows of suggested semantic units (left to the semantic channel)."""
    return {rid for unit in sem.find_candidate_units(master) for rid in unit.row_ids}


def scan_points(master: MasterDocument, lexicon: Lexicon | None = None, tiers: str = "A",
                policy: str = "lokal", layout: bool = True) -> ScanReport:
    """Every point of ``master`` that passes the guards and, with ``layout``, the row fit.

    Deterministic: the same master, lexicon and options always give the same points.
    """
    if policy not in POLICIES:
        raise ValueError(f"kebijakan tidak dikenal: {policy!r}")
    lexicon = lexicon or load_lexicon()
    by_first: dict[str, list[tuple[LexRule, str]]] = {}
    for r in lexicon.rules:
        if r.tier in tiers:
            for form in r.matchable:
                by_first.setdefault(form.split()[0], []).append((r, form))
    for v in by_first.values():
        v.sort(key=lambda rf: -len(rf[1].split()))
    rep = ScanReport()
    skip = _semantic_rows(master)
    rows = [r for r in body_rows(master) if r.id not in skip]
    stream: list[str] = []          # body tokens across rows, for guard windows and sentences
    index: dict[tuple[RowId, int], int] = {}
    labels: set[int] = set()
    for row in rows:
        lab = label_count(master, row)
        for k, w in enumerate(row.words):
            if k < lab:
                labels.add(len(stream))
            index[(row.id, k)] = len(stream)
            stream.append(w.text)
    rep.body_words = len(stream) - len(labels)
    candidates: list[LexPoint] = []
    for row in rows:
        k, n = label_count(master, row), len(row.words)
        while k < n:
            hit = None
            for rule, form in by_first.get(_bare(row.words[k].text), []):
                fw = form.split()
                span = row.words[k:k + len(fw)]
                if len(span) != len(fw) or [_bare(w.text) for w in span] != fw:
                    continue
                if any(w.text.strip(_STRIP).lower() != w.text.lower() for w in span[:-1]):
                    continue  # punctuation only after the last word of the phrase
                if span[0].text[:1] in _STRIP:
                    continue
                hit = (rule, form)
                break
            if hit is None:
                k += 1
                continue
            rule, form = hit
            size = len(form.split())
            rep.matched += 1
            gi = index[(row.id, k)]
            why = _guard(stream, gi, gi + size, labels, rule, policy)
            if why is None and _row_state(row) is None:
                why = REFUSE_FONT
            if why is None:
                others = [f for f in rule.forms if f != form]
                usable = ([form] + others)[: 1 << (len(rule.forms).bit_length() - 1)]
                master_text = " ".join(w.text for w in row.words[k:k + size])
                tail = row.words[k + size - 1].text
                trail = tail[len(tail.rstrip(_STRIP)):]
                shown = (master_text,) + tuple(_apply_case(master_text, f) + trail for f in usable[1:])
                candidates.append(LexPoint(f"c{len(candidates)}", row.page, row.index, k, k + size,
                                           rule.rule_id, shown, _display_context(stream, gi, gi + size, labels)))
            else:
                rep.refuse(why)
            k += size
    kept: list[LexPoint] = []
    edges = page_edges(master)
    by_row: dict[RowId, list[LexPoint]] = {}
    for pt in candidates:
        by_row.setdefault(pt.row_id, []).append(pt)
    for rid in sorted(by_row):
        pts = by_row[rid]
        if layout:
            row = master.layout.row(rid)
            g0 = row.words[0].glyphs[0]
            font = master.fonts[g0.font].font
            missing = [p for p in pts if not all(font.has_glyph(ord(ch)) for f in p.forms for ch in f)]
            for _ in missing:
                rep.refuse(REFUSE_GLYPH)
            pts = [p for p in pts if p not in missing]
            def change(p: LexPoint, k: int) -> float:
                return abs(font.text_length(p.forms[k], g0.size) - font.text_length(p.forms[0], g0.size))

            while pts and not _row_fits_all(master, row, pts, edges[rid[0]]):
                worst = max(pts, key=lambda p: (max(change(p, k) for k in range(len(p.forms))), p.start))
                if len(worst.forms) > 2:
                    # Halve the forms (master form plus those closest in width) before giving up.
                    keep = sorted(sorted(range(1, len(worst.forms)), key=lambda k: (change(worst, k), k))
                                  [: len(worst.forms) // 2 - 1])
                    narrower = LexPoint(worst.point_id, worst.page, worst.row, worst.start, worst.end, worst.rule_id,
                                        (worst.forms[0],) + tuple(worst.forms[k] for k in keep), worst.context)
                    pts = [narrower if p is worst else p for p in pts]
                    continue
                pts = [p for p in pts if p is not worst]
                rep.refuse(REFUSE_FIT)
        kept += pts
    points = [LexPoint(f"l{i}", p.page, p.row, p.start, p.end, p.rule_id, p.forms, p.context)
              for i, p in enumerate(kept)]
    repeated = repeated_points(master, points)
    for p in points:
        p.repeated = p.point_id in repeated
    rep.points = points
    return rep


def repeated_points(master: MasterDocument, points: Sequence[LexPoint]) -> set[str]:
    """Ids of points whose pattern (decoder context + any form) also fits elsewhere in the master.

    Uses the decoder's own reference text and context (``ch_lexical.LexReference``): the
    point's own stretch is blanked out and every form's pattern is searched in the rest. A
    point is repeated when the closest other place needs at most the decoder's
    ``MAX_EDIT_FRACTION`` of the pattern length in edits, i.e. when the decoder could read the
    point there. Documents without repeated passages have none (the sample notes: the closest
    other place needs at least a third of the pattern in edits).
    """
    from tapak.decoder.ch_lexical import MAX_EDIT_FRACTION, LexReference
    from tapak.decoder.ch_semantic import semiglobal_distance

    if not points:
        return set()
    ref = LexReference(master, points)
    out: set[str] = set()
    for p in points:
        left, right, lo, hi = ref.context(p.point_id)
        masked = ref.text[:lo] + "\x00" * (hi - lo) + ref.text[hi:]
        for form in p.forms:
            pattern = left + sem.match_key(form) + right
            if semiglobal_distance(pattern, masked) <= MAX_EDIT_FRACTION * len(pattern):
                out.add(p.point_id)
                break
    return out


def scan_candidates(master: MasterDocument, lexicon: Lexicon | None = None, tiers: str = "A",
                    policy: str = "lokal") -> LexicalSelection:
    """Scan ``master`` and return a selection with every point awaiting review.

    The refusal counts name categories only (never document words), so they may be shown
    or logged.
    """
    lexicon = lexicon or load_lexicon()
    rep = scan_points(master, lexicon, tiers, policy, layout=True)
    sel = LexicalSelection(master.doc_hash, lexicon.name, lexicon.digest, tiers, policy, rep.points,
                           rep.body_words, dict(sorted(rep.refused.items())))
    sel.scan_digest = sel.compute_scan_digest()
    return sel


# ---------------------------------------------------------------------------------------
# Review gate


def require_reviewed(selection: LexicalSelection) -> None:
    """Raise IssuanceBlocked while any point still awaits a decision."""
    waiting = selection.pending()
    if waiting:
        shown = ", ".join(waiting[:10]) + (" ..." if len(waiting) > 10 else "")
        raise IssuanceBlocked(
            f"penerbitan diblokir: {len(waiting)} titik pilihan kata masih menunggu keputusan ({shown}); "
            "setujui atau tolak setiap titik terlebih dahulu (tapak leksikal review)")


def validate_selection(master: MasterDocument, selection: LexicalSelection, lexicon: Lexicon | None = None) -> None:
    """Re-check a selection right before issuance; IssuanceBlocked (Indonesian) on any problem.

    Runs ``require_reviewed``, then checks that the selection belongs to this master, that
    its points were not edited by hand (scan digest), that the lexicon is the one it was
    scanned with, that a fresh scan of the master gives exactly the same points, and that
    every combination of approved forms still fits its row.
    """
    require_reviewed(selection)
    if selection.doc_hash != master.doc_hash:
        raise IssuanceBlocked("penerbitan diblokir: berkas pilihan kata dibuat untuk dokumen lain")
    if any(p.status not in STATUSES for p in selection.points):
        raise IssuanceBlocked("penerbitan diblokir: status titik pilihan kata tidak dikenal")
    if selection.scan_digest != selection.compute_scan_digest():
        raise IssuanceBlocked("penerbitan diblokir: titik di berkas pilihan kata diubah di luar TAPAK (digest "
                              "pemindaian tidak cocok); pindai ulang dengan tapak leksikal scan")
    try:
        lexicon = lexicon or load_lexicon(selection.lexicon)
    except LexiconError as exc:
        raise IssuanceBlocked(f"penerbitan diblokir: {exc}") from exc
    if lexicon.digest != selection.lexicon_digest:
        raise IssuanceBlocked("penerbitan diblokir: leksikon berubah sejak pemindaian; pindai ulang dokumen")
    fresh = scan_points(master, lexicon, selection.tiers, selection.policy, layout=True)
    if [p.structure() for p in fresh.points] != [p.structure() for p in selection.points]:
        raise IssuanceBlocked("penerbitan diblokir: titik pilihan kata tidak cocok dengan pemindaian ulang "
                              "dokumen induk; pindai ulang dengan tapak leksikal scan")
    edges = page_edges(master)
    by_row: dict[RowId, list[LexPoint]] = {}
    for p in selection.carrying():
        by_row.setdefault(p.row_id, []).append(p)
    for rid, pts in by_row.items():
        if not _row_fits_all(master, master.layout.row(rid), pts, edges[rid[0]]):
            raise IssuanceBlocked(f"penerbitan diblokir: titik pilihan kata di halaman {rid[0] + 1} tidak muat "
                                  "pada barisnya")


# ---------------------------------------------------------------------------------------
# Embedding


def lexical_slot_refs(selection: LexicalSelection) -> list[tuple[int, tuple[int, ...], int]]:
    """(page, (point_index,), bits) per carrying point, for ``plan.assign_positions``."""
    return [(p.page, (i,), p.bits) for i, p in enumerate(selection.points) if p.carrying]


def lexical_slots(selection: LexicalSelection, m: int, key: bytes, p: np.ndarray | None,
                  rule: str | None) -> list[Slot]:
    """Slots of the lexical channel: positions from the retype band (``rule``) when given,
    walked from the back of the shared "ketik" sequence; uniform positions otherwise."""
    refs = lexical_slot_refs(selection)
    if rule is None:
        return assign_positions(CHANNEL_LEXICAL, refs, m, key)
    if p is None:
        raise ValueError("vektor bias diperlukan untuk aturan posisi ketik ulang")
    return assign_positions(CHANNEL_LEXICAL, refs, m, key, pool=retype_pool(p, rule), stream=RETYPE_STREAM,
                            from_end=True)


def choices_for_codeword(slots: Iterable[Slot], codeword: np.ndarray,
                         points: Sequence[LexPoint]) -> dict[str, int]:
    """Form index per carrying point: its whitened bits read as a binary number (MSB first).

    The result is derived from the codeword: never store it.
    """
    out: dict[str, int] = {}
    for slot in slots:
        if slot.channel != CHANNEL_LEXICAL:
            continue
        pt = points[slot.ref[0]]
        if len(pt.forms) != 1 << len(slot.positions):
            raise ValueError(f"jumlah bentuk titik {pt.point_id} tidak sesuai dengan rencana penyematan")
        bits = [int(codeword[q]) ^ w for q, w in zip(slot.positions, slot.whiten)]
        out[pt.point_id] = sem.bits_to_index(bits)
    return out


def copy_rows(master: MasterDocument, points: Sequence[LexPoint],
              choice: Mapping[str, int]) -> dict[RowId, list[tuple[str, WordId | None]]]:
    """Words of every row that holds one of ``points``, as drawn in the copy."""
    by_row: dict[RowId, list[LexPoint]] = {}
    for p in points:
        by_row.setdefault(p.row_id, []).append(p)
    return {rid: row_words_for(master.layout.row(rid), pts, choice) for rid, pts in by_row.items()}


def copy_text(master: MasterDocument, points: Sequence[LexPoint], choice: Mapping[str, int]) -> str:
    """Plain text of a copy's rows (joined by newlines) with the chosen forms, as a reader sees it."""
    changed = copy_rows(master, points, choice)
    lines = []
    for row in master.layout.rows():
        words = changed.get(row.id)
        lines.append(" ".join(t for t, _ in words) if words is not None else row.text)
    return "\n".join(lines)


def lexical_marks(slots: Iterable[Slot], codeword: np.ndarray, master: MasterDocument,
                  selection: LexicalSelection) -> dict[RowId, list[tuple[float, str, WordId | None]]]:
    """Row replacements for ``CopyMarks.row_words``: every row holding a carrying point, word by
    word (master words keep their id, so their text marks are drawn too)."""
    slots = [s for s in slots if s.channel == CHANNEL_LEXICAL]
    choice = choices_for_codeword(slots, codeword, selection.points)
    points = [selection.points[s.ref[0]] for s in slots]
    edges = page_edges(master)
    out: dict[RowId, list[tuple[float, str, WordId | None]]] = {}
    for rid, words in copy_rows(master, points, choice).items():
        fitted = fit_row(master, master.layout.row(rid), words, edges[rid[0]])
        if fitted is None:
            raise ValueError(f"titik pilihan kata di halaman {rid[0] + 1} tidak muat pada barisnya")
        out[rid] = fitted
    return out


def format_count(n: int) -> str:
    """An integer with the Indonesian thousands separator (1.800)."""
    return f"{n:,}".replace(",", ".")


def words_for_bits(bits: int, body_words: int | None = None, lexical_bits: int | None = None) -> int:
    """Indicative body words that carry ``bits`` lexical bits, rounded up to 100 words.

    Uses the document's own density (``lexical_bits`` per ``body_words``) when both are known
    and positive, else the table average BITS_PER_100_WORDS.
    """
    if bits <= 0:
        return 0
    if body_words and lexical_bits:
        per_word = lexical_bits / body_words
    else:
        per_word = BITS_PER_100_WORDS / 100
    return math.ceil(round(bits / per_word / 100, 6)) * 100


def capacity_verdict(bits: int, body_words: int | None = None, lexical_bits: int | None = None) -> str:
    """Plain Indonesian verdict for the issuer: is a retyped leak of this document enough to name
    one leaker?

    ``bits`` counts every retype-surviving bit (word choice and semantic). Below
    LONE_LEAKER_BITS the verdict says how many bits are missing and, from the document's own
    density (``lexical_bits`` per ``body_words``), roughly how many more body words that is.
    """
    words = f" dari {format_count(body_words)} kata isi" if body_words else ""
    if bits >= LONE_LEAKER_BITS:
        return (f"{bits} bit tahan ketik ulang{words}: cukup untuk satu pembocor (teks ketikan ulang dari satu "
                "salinan); tidak tahan kolusi")
    missing = LONE_LEAKER_BITS - bits
    more = words_for_bits(missing, body_words, lexical_bits)
    density = ("dengan kepadatan dokumen ini" if body_words and lexical_bits
               else f"dengan rata-rata tabel ini ({str(BITS_PER_100_WORDS).replace('.', ',')} bit per 100 kata isi)")
    return (f"{bits} bit tahan ketik ulang{words}: belum mencapai {LONE_LEAKER_BITS} bit, batas TAPAK untuk "
            f"menyebut satu pembocor dari teks ketikan ulang (kurang {missing} bit, {density} kira-kira "
            f"{format_count(more)} kata isi lagi)")
