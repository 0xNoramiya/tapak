"""Berita acara: the forensic examination report as a PDF (Jinja2 template, WeasyPrint).

Input is an ``Attribution`` (see ``decoder/accuse.py``) plus a ``ReportInfo`` with the case,
evidence and issuance details. The rules that protect recipients are enforced here, in
Python, not in the template:

* the template never receives the ``ReportInfo`` object or any candidate list, only the
  formatted strings built by ``_view``;
* a recipient's identity (copy number, recipient id, name, code digest) reaches the
  template only for a copy whose score reached the threshold Z, and always in the same row
  as its score, Z and the bound on the false-accusation probability. A copy named at a later
  stage of a staged accusation is shown only in that stage's rows, with the stage score, the
  stage's Z and bound, and the copies named before it that the stage rests on (which are
  always shown too, since a later stage runs only after them);
* every other copy is shown without identity: ranked score rows marked "identitas tidak
  dicantumkan", and counts instead of copy numbers in the per-channel table and in canary
  events. With the verdict "tidak cukup bukti" this means no identity at all;
* free text that the report repeats (evidence file name, master and manifest names, notes,
  canary fields) passes through a redactor that masks the recipient id, name, copy id and
  copy number of every copy that is not accused. The leaker controls the evidence file
  name, and issued files are named ``<stem>__salinan005_<recipient id>.pdf``;
* the report refuses an Attribution whose verdict, accusation flags, scores and Z disagree;
* rendering is offline: the bundled DejaVu fonts are referenced by ``file://`` URLs and the
  URL fetcher refuses every URL outside the font and template folders.

Probabilities printed as upper bounds are rounded up, never to the nearest value, so the
printed bound is never below the computed one. The report never contains document text or
images, only hashes, parameters and scores.
"""

from __future__ import annotations

import math
import re
import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from tapak.decoder.accuse import (
    VERDICT_IDENTIFIED,
    VERDICT_INSUFFICIENT,
    VISIBLE_MARKS_NOTE,
    Attribution,
    CopyCandidate,
    CopyRef,
    ThresholdRecord,
    is_caveat,
)
from tapak.decoder.manipulation import is_manipulation_note, manipulation_parts
from tapak.decoder.softbits import SoftBits
from tapak import i18n
from tapak.fonts import FONT_DIR, font_path
from tapak.i18n import N_
from tapak.i18n import gettext as _
from tapak.marker.layout import sha256_hex
from tapak.marker.plan import (
    CHANNEL_BACKGROUND,
    CHANNEL_HOMOGLYPH,
    CHANNEL_LEXICAL,
    CHANNEL_LEXICAL_OCR,
    CHANNEL_SEMANTIC,
    CHANNEL_SEMANTIC_OCR,
    CHANNEL_SHIFT,
    CHANNEL_ZW,
    PHYSICAL_CHANNEL,
)
from tapak.tardos.params import TardosParams

if TYPE_CHECKING:
    from tapak.decoder.trace import TraceContext

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "berita_acara.html"
STYLESHEET_NAME = "berita_acara.css"
# Optional: if this file is added to tapak/assets/fonts, hashes use it. Without it they are
# set in the bundled DejaVu Sans; no system font is ever used.
MONO_FONT_FILE = "DejaVuSansMono.ttf"

EVIDENCE_TYPES = ("foto", "tangkapan layar", "berkas PDF", "teks")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Marker that replaces an identifier of a copy that is not accused.
REDACTED = "[disamarkan]"
# Anonymous score rows shown below the accused rows (or alone, without a verdict).
RUNNER_UP_ROWS = 3

# Labels are Indonesian (the CLI prints them as they are); the berita acara translates them.
SUBCHANNEL_LABELS = {
    CHANNEL_SHIFT: N_("Pergeseran kata dan baris"),
    CHANNEL_BACKGROUND: N_("Pola latar halus"),
    CHANNEL_ZW: N_("Karakter tak terlihat (zero-width)"),
    CHANNEL_HOMOGLYPH: N_("Huruf kembar (homoglyph)"),
    CHANNEL_SEMANTIC: N_("Variasi kalimat (semantik)"),
    CHANNEL_LEXICAL: N_("Pilihan kata (leksikal)"),
    CHANNEL_SEMANTIC_OCR: N_("Variasi kalimat (semantik, OCR gambar)"),
    CHANNEL_LEXICAL_OCR: N_("Pilihan kata (leksikal, OCR gambar)"),
}
PHYSICAL_LABELS = {
    "geser": N_("Geser (pergeseran kata dan baris)"),
    "latar": N_("Latar (pola latar halus)"),
    "teks": N_("Teks (karakter tak terlihat dan huruf kembar)"),
    "semantik": N_("Semantik (variasi kalimat)"),
    "leksikal": N_("Leksikal (pilihan kata; bertahan saat diketik ulang, tetapi terlihat di kertas sehingga dapat "
                   "ditiru; satu pembocor, tidak tahan kolusi)"),
}
_DIGITAL_SUBCHANNELS = {CHANNEL_ZW, CHANNEL_HOMOGLYPH}

# Physical channel states in Section IV.
STATUS_READ = "terbaca"
STATUS_UNREAD = "tidak terbaca"  # the decoder ran on the evidence and read nothing
STATUS_NOT_EXAMINED = "tidak diperiksa"  # no decoder for this channel ran on this evidence

_MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
           "September", "Oktober", "November", "Desember")
_DAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_ZONES = {0: "UTC", 7: "WIB", 8: "WITA", 9: "WIT"}

TIMES = "\u00d7"
MINUS = "\u2212"
INFINITY = "\u221e"

# Rounding up ignores float noise smaller than this fraction of the last printed digit.
_FLOAT_SLACK = 1e-9


def _now_iso() -> str:
    """Current local time with its UTC offset (WIB on a machine set to Asia/Jakarta)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class ReportInfo:
    """Case, evidence and issuance details printed in the report.

    Attributes:
        case_number: nomor perkara.
        examiner_name: name of the examiner (Pemeriksa).
        examiner_rank: rank or position of the examiner.
        evidence_name: file name of the evidence as received (several names joined by ", ").
        evidence_sha256: hex SHA-256 of the evidence file.
        evidence_type: one of EVIDENCE_TYPES, or several joined by ", " for mixed evidence.
        document_name: file name of the master document.
        doc_hash: hex SHA-256 of the master PDF.
        issued_at: ISO time of issuance.
        params: Tardos parameters of the document's code (c, eps, n_max, m, constant, cutoff).
        copies_issued: number of issued copies.
        plan_summary: per sub-channel: slots, bits, positions, pages (from the manifest).
        channel_observations: one dict per sub-channel whose decoder ran on the evidence,
            with keys ``channel``, ``observations``, ``slots_read`` and ``slots_total`` (each
            optional, None if the decoder does not report it) and ``noise`` (text or None).
            A planned channel with no entry here is reported as "tidak diperiksa", not as
            destroyed.
        software_version: TAPAK version used for the examination.
        registry_ok: registry chain verification result; None if it was not checked.
        registry_entries: number of registry entries verified.
        canary_events: optional dicts with keys ``seq``, ``time`` and ``source_ip``.
        code_digests: copy number -> code commitment, as recorded at issuance.
        examined_at: ISO time of the examination (default: now, local time zone).
        evidence_received_at: ISO time the evidence was received (optional).
        manifest_name: file name of the issuance manifest (for the re-run command).
        evidence_names: every evidence file of a multi-file trace (for the re-run command);
            empty means the single ``evidence_name``.
        institution: issuing unit printed above the title (optional).
        place: place of signing (optional).
        trace_entry, trace_entry_hash: number and hash of the registry entry that logged this
            trace (None and "" when it was not logged). Printed as an anchor for
            ``tapak verify --jangkar``, so deleting the entry later is detected.
        anchor_text: the state of the external anchor log for this trace (one sentence, see
            ``tapak.registry.anchor``); "" prints nothing.
    """

    case_number: str
    examiner_name: str
    examiner_rank: str
    evidence_name: str
    evidence_sha256: str
    evidence_type: str
    document_name: str
    doc_hash: str
    issued_at: str
    params: TardosParams
    copies_issued: int
    plan_summary: dict[str, dict[str, int]]
    channel_observations: list[dict[str, Any]]
    software_version: str
    registry_ok: bool | None = None
    registry_entries: int = 0
    registry_unsigned: int = 0
    canary_events: list[dict[str, Any]] = field(default_factory=list)
    code_digests: dict[int, str] = field(default_factory=dict)
    examined_at: str = field(default_factory=_now_iso)
    evidence_received_at: str = ""
    manifest_name: str = "manifest.json"
    evidence_names: list[str] = field(default_factory=list)
    institution: str = ""
    place: str = ""
    trace_entry: int | None = None
    trace_entry_hash: str = ""
    anchor_text: str = ""

    def __post_init__(self) -> None:
        if any(t not in EVIDENCE_TYPES for t in self.evidence_type.split(", ")):
            raise ValueError(
                f"jenis barang bukti tidak dikenal: {self.evidence_type!r}; "
                f"pilihan: {', '.join(EVIDENCE_TYPES)}"
            )


# --- formatting helpers ----------------------------------------------------------------


def _strip_zeros(text: str) -> str:
    """'1,0' -> '1', '0,50' -> '0,5'; text without a decimal comma is unchanged."""
    if "," not in text:
        return text
    return text.rstrip("0").rstrip(",")


def format_number(value: float, decimals: int = 1) -> str:
    """Indonesian number format: '.' groups thousands, ',' is the decimal mark (1.234,5)."""
    if math.isnan(value):
        return "-"
    if math.isinf(value):
        return INFINITY if value > 0 else "-" + INFINITY
    if round(value, decimals) == 0:
        value = 0.0  # no '-0,0'
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_int(value: int) -> str:
    """Integer with '.' as thousands separator (12.345)."""
    return format_number(float(value), 0)


def _ceil_decimals(value: float, digits: int) -> float:
    """Round ``value`` up to ``digits`` decimals (float noise below _FLOAT_SLACK is ignored)."""
    scale = 10.0 ** digits
    return math.ceil(value * scale - _FLOAT_SLACK) / scale


def scientific_parts(value: float, digits: int = 1, log10_value: float | None = None,
                     round_up: bool = False) -> tuple[str, int]:
    """(mantissa, exponent) with an Indonesian mantissa: 2.3e-12 -> ('2,3', -12).

    ``log10_value`` may be given instead of ``value`` for numbers too small for a float.
    ``round_up=True`` rounds the mantissa up (2.34e-12 -> ('2,4', -12)), which is the only
    honest rounding for an upper bound.
    """
    if log10_value is None:
        if not (value > 0 and math.isfinite(value)):
            raise ValueError("nilai harus positif dan terhingga")
        log10_value = math.log10(value)
    exponent = math.floor(log10_value)
    raw = 10.0 ** (log10_value - exponent)
    mantissa = _ceil_decimals(raw, digits) if round_up else round(raw, digits)
    if mantissa >= 10.0:
        mantissa /= 10.0
        exponent += 1
    return _strip_zeros(format_number(mantissa, digits)), exponent


def _probability_parts(p: float, log10_value: float | None, round_up: bool) -> tuple[str, int | None]:
    """Mantissa and exponent, or (decimal text, None) for values that read better plainly."""
    if log10_value is None:
        if p <= 0:
            return "0", None
        log10_value = math.log10(p)
    if log10_value == -math.inf:
        return "0", None
    if log10_value >= -2:
        value = 10.0 ** log10_value
        if round_up:
            value = _ceil_decimals(value, 2)
        return _strip_zeros(format_number(value, 2)), None
    return scientific_parts(0.0, log10_value=log10_value, round_up=round_up)


def format_probability_html(p: float, log10_value: float | None = None, round_up: bool = True) -> Markup:
    """Probability for the report: '2,3 x 10<sup>-12</sup>' with a real superscript.

    Values of at least 0,01 are written as decimals ('0,35'). ``log10_value`` takes
    precedence over ``p`` (use it when ``p`` underflowed to 0). By default the value is
    rounded up because the report prints probabilities as upper bounds; pass
    ``round_up=False`` for parameters such as eps.
    """
    mantissa, exponent = _probability_parts(p, log10_value, round_up)
    if exponent is None:
        return Markup(escape(mantissa))
    sign = MINUS if exponent < 0 else ""
    return Markup(f"{escape(mantissa)} {TIMES} 10<sup>{sign}{abs(exponent)}</sup>")


def format_probability_text(p: float, log10_value: float | None = None, round_up: bool = True) -> str:
    """Plain-text form of :func:`format_probability_html`: '2,3 x 10^-12'."""
    mantissa, exponent = _probability_parts(p, log10_value, round_up)
    return mantissa if exponent is None else f"{mantissa} x 10^{exponent}"


def format_datetime(value: str, with_day: bool = False, with_time: bool = True) -> str:
    """ISO time in Indonesian: 'Rabu, 21 Oktober 2026 pukul 15.09.12 WIB'.

    ``with_time=False`` gives the date only. A value that is not ISO 8601 is returned
    unchanged (free text entered by the examiner).
    """
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    text = f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    if with_day:
        text = f"{_DAYS[dt.weekday()]}, {text}"
    if not with_time or ("T" not in value and " " not in value.strip()):
        return text
    text += f" pukul {dt:%H.%M.%S}"
    offset = dt.utcoffset()
    if offset is not None:
        minutes = int(offset.total_seconds() // 60)
        zone = _ZONES.get(minutes // 60) if minutes % 60 == 0 else None
        if zone is None:
            sign = "+" if minutes >= 0 else "-"
            zone = f"UTC{sign}{abs(minutes) // 60:02d}.{abs(minutes) % 60:02d}"
        text += f" {zone}"
    return text


# --- building ReportInfo from a trace ---------------------------------------------------


def evidence_types_for(names: list[str]) -> str:
    """Evidence type of several files: one type, or the distinct types joined by ", "."""
    return ", ".join(dict.fromkeys(evidence_type_for(n) for n in names))


def evidence_type_for(name: str) -> str:
    """Default evidence type from a file name (images default to 'foto')."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        return "berkas PDF"
    if suffix in _IMAGE_SUFFIXES:
        return "foto"
    return "teks"


def _rounded_rows_text(meta: dict[str, Any]) -> str | None:
    """The rounding step of rows read with the pixel-grid model (shift channel of a screenshot)."""
    model = meta.get("row_model")
    steps = [p["q_pt"] for p in (model or {}).get("pages", []) if isinstance(p, dict) and "q_pt" in p]
    if not steps:
        return None
    return f"baris dibulatkan ke piksel, langkah {format_number(float(steps[0]), 3)} pt"


def _noise_text(channel: str, meta: dict[str, Any]) -> str:
    sigma = meta.get("sigma_pt")
    rounded = _rounded_rows_text(meta)
    if isinstance(sigma, dict) and (sigma or rounded):
        parts = [f"sigma {k} {format_number(float(v), 3)} pt" for k, v in sigma.items()]
        return "; ".join(parts + ([rounded] if rounded else []))
    if isinstance(sigma, (int, float)):
        return f"sigma {format_number(float(sigma), 3)} pt"
    if "noise" in meta:
        return str(meta["noise"])
    snr = meta.get("snr")
    if isinstance(snr, (int, float)):
        return f"SNR {format_number(float(snr), 2)}"
    if channel in _DIGITAL_SUBCHANNELS:
        return "pembacaan digital (tanpa derau terukur)"
    return "-"


def channel_observations(observations: list[SoftBits]) -> list[dict[str, Any]]:
    """Per sub-channel summary of the decoder output, in the shape ReportInfo expects."""
    rows = []
    for sb in observations:
        rows.append({
            "channel": sb.channel,
            "observations": len(sb),
            "slots_read": sb.meta.get("slots_read"),  # None if the decoder does not report it
            "slots_total": sb.meta.get("slots_total"),
            "noise": _noise_text(sb.channel, sb.meta),
        })
    return rows


def software_version() -> str:
    """Installed TAPAK version."""
    try:
        return metadata.version("tapak")
    except metadata.PackageNotFoundError:
        return "tidak diketahui"


def build_report_info(
    ctx: TraceContext,
    evidence_name: str,
    evidence_bytes: bytes,
    observations: list[SoftBits],
    *,
    case_number: str,
    examiner_name: str,
    examiner_rank: str,
    evidence_type: str | None = None,
    registry_ok: bool | None = None,
    registry_entries: int = 0,
    canary_events: list[dict[str, Any]] | None = None,
    manifest_name: str = "manifest.json",
    evidence_received_at: str = "",
    institution: str = "",
    place: str = "",
) -> ReportInfo:
    """Collect everything the report needs from a trace context and the evidence file."""
    m = ctx.manifest
    return ReportInfo(
        case_number=case_number,
        examiner_name=examiner_name,
        examiner_rank=examiner_rank,
        evidence_name=Path(evidence_name).name,
        evidence_sha256=sha256_hex(evidence_bytes),
        evidence_type=evidence_type or evidence_type_for(evidence_name),
        document_name=m.doc_name,
        doc_hash=m.doc_hash,
        issued_at=m.issued_at,
        params=ctx.params,
        copies_issued=len(m.copies),
        plan_summary=m.plan_summary,
        channel_observations=channel_observations(observations),
        software_version=software_version(),
        registry_ok=registry_ok,
        registry_entries=registry_entries,
        canary_events=list(canary_events or []),
        code_digests={c.seq: c.code_digest for c in m.copies},
        evidence_received_at=evidence_received_at,
        manifest_name=manifest_name,
        institution=institution,
        place=place,
    )


# --- protecting recipients that are not accused -----------------------------------------


def check_consistent(attribution: Attribution) -> None:
    """Refuse an Attribution whose verdict, accusation flags, scores and Z disagree.

    A copy must be accused exactly when Z is finite and its score is at least Z, and the
    verdict must be "teridentifikasi" exactly when some copy is accused.
    """
    z = attribution.threshold.threshold
    if attribution.verdict not in (VERDICT_IDENTIFIED, VERDICT_INSUFFICIENT):
        raise ValueError(f"putusan tidak dikenal: {attribution.verdict!r}")
    for c in attribution.candidates:
        if c.accused != (math.isfinite(z) and c.score >= z):
            raise ValueError("hasil atribusi tidak konsisten: status tuduhan suatu salinan "
                             "tidak sesuai dengan skornya dan ambang Z")
    if (attribution.verdict == VERDICT_IDENTIFIED) != any(c.accused for c in attribution.candidates):
        raise ValueError("hasil atribusi tidak konsisten: putusan tidak sesuai dengan daftar "
                         "salinan yang dituduh")
    _check_stages(attribution)


def _check_stages(attribution: Attribution) -> None:
    """Later stages: numbered 2, 3, ...; each runs only after a stage that named someone, rests on
    exactly the copies named before it, scores only the others, and names by its own Z."""
    named = [c.copy.seq for c in attribution.accused]
    for k, st in enumerate(attribution.stages, start=2):
        z = st.threshold.threshold
        if st.stage != k or st.threshold.stage != k or not named or sorted(st.basis) != sorted(named):
            raise ValueError(f"hasil atribusi tidak konsisten: tahap {st.stage} tidak bersandar pada salinan "
                             "yang dituduh pada tahap sebelumnya")
        if any(c.copy.seq in named for c in st.candidates):
            raise ValueError(f"hasil atribusi tidak konsisten: tahap {st.stage} menilai ulang salinan yang "
                             "sudah dituduh")
        for c in st.candidates:
            if c.accused != (math.isfinite(z) and c.score >= z):
                raise ValueError(f"hasil atribusi tidak konsisten: status tuduhan tahap {st.stage} tidak sesuai "
                                 "dengan skor dan ambang tahap itu")
        if k > 2 and not attribution.stages[k - 3].accused:
            raise ValueError(f"hasil atribusi tidak konsisten: tahap {st.stage} berjalan setelah tahap yang "
                             "tidak menuduh siapa pun")
        named += [c.copy.seq for c in st.accused]


# Copy numbers in free text: '#5', 'salinan005', 'salinan #5', 'salinan nomor 5', 'copy-5'.
_COPY_NUMBER = re.compile(
    r"((?:salinan|copy)[\s_#:.-]*(?:(?:nomor|no|ke)[\s_#:.-]*)?|#)(\d+)", re.IGNORECASE)


def make_redactor(hidden: Iterable[CopyRef], shown_seqs: set[int]) -> Callable[[str], str]:
    """A function that masks identifiers of copies that are not accused in free text.

    Masked with ``REDACTED``: the recipient id, copy id and name of every ``hidden`` copy
    (any case; any separator or none between the words of a name), and every copy number
    that is not in ``shown_seqs``. Matching has no word boundaries on purpose: masking too
    much is harmless, missing an id is not.
    """
    words: set[str] = set()
    for ref in hidden:
        for token in (ref.recipient_id, ref.copy_id):
            if token.strip():
                words.add(re.escape(token.strip()))
        parts = re.findall(r"[^\W_]+", ref.nama)
        if parts:
            words.add(r"[\W_]*".join(re.escape(p) for p in parts))
    pattern = (re.compile("|".join(sorted(words, key=len, reverse=True)), re.IGNORECASE)
               if words else None)

    def keep_or_mask(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(2)) in shown_seqs else match.group(1) + REDACTED

    def redact(text: str) -> str:
        if pattern is not None:
            text = pattern.sub(REDACTED, text)
        return _COPY_NUMBER.sub(keep_or_mask, text)

    return redact


def _seq_list_text(seqs: list[int], shown_seqs: set[int]) -> str:
    """'#7', '#7; 2 salinan lain (nomor tidak dicantumkan)' or '2 salinan (nomor ...)'."""
    if not seqs:
        return _("tidak ada")
    named = [f"#{s}" for s in seqs if s in shown_seqs]
    others = len(seqs) - len(named)
    if others:
        named.append(_("%(n)s salinan lain (nomor tidak dicantumkan)", n=others) if named
                     else _("%(n)s salinan (nomor tidak dicantumkan)", n=others))
    return "; ".join(named)


# --- view model: the only data the template sees ----------------------------------------
# Numbers and dates of the view follow the language of the berita acara (tapak.i18n): Indonesian
# unless an English rendition is asked for.


def _num(value: float, decimals: int = 1) -> str:
    return i18n.localize(format_number(value, decimals))


def _int(value: int) -> str:
    return i18n.localize(format_int(value))


def _prob(p: float, log10_value: float | None = None, round_up: bool = True) -> Markup:
    return Markup(i18n.localize(format_probability_html(p, log10_value, round_up)))


def _pct(value: float) -> str:
    return i18n.localize(_strip_zeros(format_number(value, 2)))


def _log10_false_accusation(c: CopyCandidate, n_copies: int, share: float = 1.0) -> float:
    """log10 of the bound (n - 1) * P(innocent >= S) / share, exact where the float underflows.

    ``share`` is the fraction of eps the stage that scored the copy spends
    (``ThresholdRecord.stage_share``: the trace's share without stages, 1 for a trace that is
    not logged): dividing by it makes the bound hold for all stages and traces of the document
    together, as in ``attribute``. The float ``false_accusation_probability`` loses precision
    below about 1e-308 (subnormal numbers), so it is never used here: a rounded-down bound
    would understate the risk.
    """
    if math.isfinite(c.log10_bound):
        return min(0.0, math.log10(max(n_copies - 1, 1)) + c.log10_bound - math.log10(share))
    return -math.inf


def _score_cells(c: CopyCandidate, z: float, n_copies: int, n_read: int, share: float = 1.0) -> dict[str, Any]:
    """Score, Z, probability bound (rounded up) and agreeing channels of one copy."""
    return {
        "score": _num(c.score),
        "threshold": _num(z),
        "probability": _prob(c.false_accusation_probability, _log10_false_accusation(c, n_copies, share)),
        "channels": _("%(n)s dari %(total)s", n=len(c.channels_agreeing), total=n_read)
                    + (f": {', '.join(c.channels_agreeing)}" if c.channels_agreeing else ""),
    }


def _accused_rows(attribution: Attribution, n_read: int) -> list[dict[str, Any]]:
    """Identity rows, one per accused copy; each carries score, Z and probability."""
    z = attribution.threshold.threshold
    n_copies = len(attribution.candidates)
    share = attribution.threshold.stage_share
    return [
        {
            "seq": f"#{c.copy.seq}",
            "recipient_id": c.copy.recipient_id,
            "nama": c.copy.nama,
            "jabatan": ", ".join(x for x in (c.copy.jabatan, c.copy.satuan) if x),
            **_score_cells(c, z, n_copies, n_read, share),
        }
        for c in attribution.accused
    ]


def _anonymous_rows(attribution: Attribution, n_read: int) -> list[dict[str, Any]]:
    """The best non-accused copies by rank, with score, Z and bound but no identity."""
    z = attribution.threshold.threshold
    if not math.isfinite(z):
        return []
    n_copies = len(attribution.candidates)
    share = attribution.threshold.stage_share
    rows = []
    for rank, c in enumerate(attribution.candidates, 1):
        if c.accused:
            continue
        rows.append({"rank": rank, **_score_cells(c, z, n_copies, n_read, share)})
        if len(rows) == RUNNER_UP_ROWS:
            break
    return rows


def _stage_views(attribution: Attribution) -> list[dict[str, Any]]:
    """Later stages of a staged accusation, in order, as formatted strings.

    A copy named at a stage appears only in its stage's rows, with that stage's score, Z and
    bound, and every stage states the copies named before it that its weights rest on.
    """
    n_copies = len(attribution.candidates)
    views = []
    for st in attribution.stages:
        t = st.threshold
        others = [c for c in st.candidates if not c.accused]
        views.append({
            "stage": st.stage,
            "basis": ", ".join(f"#{s}" for s in st.basis),
            "positions": _int(t.n_observed),
            "z": _num(t.threshold),
            "z_finite": math.isfinite(t.threshold),
            "eps_stage": _prob(t.stage_spent, round_up=False),
            "eps1": _prob(t.eps1, round_up=False),
            "fraction": _pct(100 * t.stage_spent / t.spent),
            "fixed_at": i18n.format_datetime(t.fixed_at),
            "fixed_at_raw": t.fixed_at,
            "best_other_score": _num(others[0].score) if others else None,
            "rows": [
                {
                    "seq": f"#{c.copy.seq}",
                    "recipient_id": c.copy.recipient_id,
                    "nama": c.copy.nama,
                    "jabatan": ", ".join(x for x in (c.copy.jabatan, c.copy.satuan) if x),
                    "score": _num(c.score),
                    "threshold": _num(t.threshold),
                    "probability": _prob(c.false_accusation_probability,
                                         _log10_false_accusation(c, n_copies, t.stage_share)),
                    "basis_text": i18n.translate_text(st.basis_text()),
                }
                for c in st.accused
            ],
        })
    return views


def _in_label_order(names: Iterable[str], labels: dict[str, str]) -> list[str]:
    """Known channels in the order of ``labels``, unknown ones after them alphabetically."""
    order = list(labels)
    return sorted(set(names), key=lambda n: (order.index(n) if n in order else len(order), n))


def _channel_rows(attribution: Attribution, info: ReportInfo, shown_seqs: set[int]) -> list[dict[str, Any]]:
    """Section IV: one row per physical channel, with one of three states.

    terbaca: positions were read. tidak terbaca: a decoder for the channel ran on the
    evidence (it has an entry in ``info.channel_observations``) and read nothing.
    tidak diperiksa: the channel was planned but no decoder for it ran on this evidence type.
    """
    read = {ch.channel: ch for ch in attribution.channels if ch.n_observed > 0}
    planned = {PHYSICAL_CHANNEL.get(name, name) for name in info.plan_summary}
    examined = {PHYSICAL_CHANNEL.get(str(o["channel"]), str(o["channel"]))
                for o in info.channel_observations}
    m = _int(info.params.length)
    rows = []
    for name in _in_label_order(planned | set(read), PHYSICAL_LABELS):
        label = _(PHYSICAL_LABELS.get(name, name))
        ch = read.get(name)
        if ch is not None:
            if ch.source_label:  # read (also) from the OCR text of an image: say so
                label = _("%(label)s; dibaca dari %(source)s", label=label, source=i18n.translate_text(ch.source_label))
            rows.append({"label": label, "status": STATUS_READ,
                         "positions": _("%(n)s dari %(total)s", n=_int(ch.n_observed), total=m),
                         "threshold": _num(ch.threshold),
                         "accused": _seq_list_text(ch.accused_seqs, shown_seqs)})
        elif name in examined:
            rows.append({"label": label, "status": STATUS_UNREAD, "positions": _("%(n)s dari %(total)s", n=0, total=m),
                         "threshold": "-", "accused": _("tidak terbaca")})
        else:
            rows.append({"label": label, "status": STATUS_NOT_EXAMINED, "positions": "-",
                         "threshold": "-", "accused": _("tidak diperiksa untuk jenis bukti ini")})
    return rows


def _subchannel_rows(info: ReportInfo) -> list[dict[str, Any]]:
    rows = []
    for obs in info.channel_observations:
        read, total = obs.get("slots_read"), obs.get("slots_total")
        slots = "-" if read is None else _int(int(read))
        if read is not None and total is not None:
            slots = _("%(n)s dari %(total)s", n=slots, total=_int(int(total)))
        noise = obs.get("noise") or "-"
        rows.append({
            "label": _(SUBCHANNEL_LABELS.get(str(obs["channel"]), str(obs["channel"]))),
            "observations": _int(int(obs.get("observations", 0))),
            "slots": slots,
            "noise": "; ".join(i18n.translate_text(part) for part in str(noise).split("; ")),
        })
    return rows


def _plan_rows(plan_summary: dict[str, dict[str, int]]) -> list[dict[str, str]]:
    """Section II channel table; a key missing from the manifest summary prints '-'."""
    rows = []
    for name in _in_label_order(plan_summary, SUBCHANNEL_LABELS):
        entry = plan_summary[name] or {}
        row = {"label": _(SUBCHANNEL_LABELS.get(name, name))}
        for key in ("slots", "bits", "positions", "pages"):
            row[key] = _int(int(entry[key])) if key in entry else "-"
        rows.append(row)
    return rows


def _params_rows(p: TardosParams) -> list[tuple[str, str | Markup]]:
    return [
        (_("Ukuran koalisi rancangan (c)"), _int(p.c)),
        (_("Peluang tuduhan salah total (eps)"), _prob(p.eps, round_up=False)),
        (_("Jumlah penerima maksimum (n_max)"), _int(p.n_max)),
        (_("Peluang tuduhan salah per penerima pada rancangan kode (eps / n_max; ambang pelacakan memakai "
           "jatah eps pelacakan itu, lihat Bagian V)"),
         _prob(p.eps1, round_up=False)),
        (_("Panjang kode (m)"), _("%(n)s posisi", n=_int(p.length))),
        (_("Konstanta panjang kode"), f"{p.constant} (K = {_num(p.k_constant, 2)})"),
        (_("Batas bias (t = 1 / (300 c))"), _prob(p.cutoff, round_up=False)),
    ]


def _registry_text(info: ReportInfo) -> str:
    if info.registry_ok is None:
        return _("tidak diperiksa")
    if info.registry_ok and info.registry_unsigned:
        return _("rantai hash utuh (%(n)s entri), tetapi %(unsigned)s entri salinan dokumen ini belum bertanda tangan "
                 "sehingga belum terlindungi dari pemalsuan", n=_int(info.registry_entries),
                 unsigned=_int(info.registry_unsigned))
    if info.registry_ok:
        return _("utuh; %(n)s entri terverifikasi dengan tanda tangan", n=_int(info.registry_entries))
    return _("TIDAK UTUH (%(n)s entri); lihat Bagian VII", n=_int(info.registry_entries))


def rerun_command(info: ReportInfo, redact: Callable[[str], str] | None = None,
                  trace_no: int | None = None, stage_policy: str | None = None) -> str:
    """The command that repeats this examination (file names optionally redacted).

    For a logged trace, ``--pelacakan-ke`` repeats it with that trace's share of eps, and
    ``--bertahap`` with the staged accusation's policy, so the thresholds and the verdict
    come out the same.
    """
    evidence = list(info.evidence_names) or [info.evidence_name]
    names = evidence + [info.document_name, info.manifest_name]
    if redact is not None:
        names = [redact(n) for n in names]
    args = names[:-2] + ["--master", names[-2], "--manifest", names[-1]]
    if trace_no is not None:
        args += ["--pelacakan-ke", str(trace_no)]
    if stage_policy is not None:
        args += ["--bertahap", stage_policy]
    return "tapak trace " + " ".join(shlex.quote(a) for a in args)


def _trace_text(t: ThresholdRecord) -> str:
    """Section V and VI: which trace of the document this was and the eps it spent."""
    if t.trace_no is None:
        text = (_("tidak dicatat di registri, sehingga pelacakan berulang atas dokumen ini tidak diperhitungkan; "
                  "pelacakan ini memakai seluruh eps") if t.stage_eps is not None
                else _("tidak dicatat di registri, sehingga pelacakan berulang atas dokumen ini tidak "
                       "diperhitungkan; ambang memakai seluruh eps"))
    else:
        text = _("pelacakan ke-%(k)s untuk dokumen ini, dicatat di registri sebelum dekode; jatah eps pelacakan ini "
                 "6 / (\u03c0\u00b2 \u00d7 %(k)s\u00b2) = %(pct)s %% dari eps", k=t.trace_no, pct=_pct(100 * t.share))
    if t.stage_eps is not None:
        pct = _pct(100 * t.stage_spent / t.spent)
        text += "; " + (_("pelacakan bertahap (kebijakan %(policy)s): tahap 1 memakai %(pct)s %% dari jatah itu",
                          policy=t.stage_policy, pct=pct) if t.trace_no is not None
                        else _("pelacakan bertahap (kebijakan %(policy)s): tahap 1 memakai %(pct)s %% dari eps itu",
                               policy=t.stage_policy, pct=pct))
    return text


def _canary_rows(info: ReportInfo, shown_seqs: set[int], redact: Callable[[str], str]) -> list[dict[str, str]]:
    """Canary events; the copy number is shown only for an accused copy."""
    rows = []
    for e in info.canary_events:
        seq = e.get("seq")
        if seq is None:
            seq_text = "-"
        elif int(seq) in shown_seqs:
            seq_text = f"#{int(seq)}"
        else:
            seq_text = _("salinan lain (nomor tidak dicantumkan)")
        rows.append({"seq": seq_text,
                     "time": redact(i18n.format_datetime(str(e.get("time", "-")))),
                     "source_ip": redact(str(e.get("source_ip", "-")))})
    return rows


def _view(attribution: Attribution, info: ReportInfo) -> dict[str, Any]:
    """Everything the template may show, as formatted strings.

    Identities enter only through ``accused_rows``, the rows of the later stages (``stages``)
    and ``digests``; free text is redacted.
    """
    check_consistent(attribution)
    t = attribution.threshold
    p = info.params
    identified = attribution.verdict == VERDICT_IDENTIFIED
    shown_seqs = attribution.named_seqs
    redact = make_redactor((c.copy for c in attribution.candidates if c.copy.seq not in shown_seqs), shown_seqs)
    channel_rows = _channel_rows(attribution, info, shown_seqs)
    n_read = sum(1 for r in channel_rows if r["status"] == STATUS_READ)
    others = [c for c in attribution.candidates if not c.accused]
    evidence_name = redact(info.evidence_name)
    say = i18n.translate_text
    anchor_text = say(info.anchor_text)

    def say_warning(note: str) -> str:
        """The merged manipulation warning; in English one sentence at a time (the rules know its
        sentences), without the final full stop the template adds."""
        if i18n.current() != "en":
            return note
        return " ".join(say(part) for part in manipulation_parts(note)).rstrip(".")

    return {
        "case": {
            "case_number": info.case_number,
            "examiner_name": i18n.translate_text(info.examiner_name),  # the "(nama pemeriksa)" placeholder
            "examiner_rank": i18n.translate_text(info.examiner_rank),
            "institution": info.institution,
            "place": info.place,
            "software_version": info.software_version,
            "evidence_name": evidence_name,
            "evidence_name_redacted": evidence_name != info.evidence_name,
            "evidence_type": ", ".join(_(t) for t in info.evidence_type.split(", ")),
            "evidence_sha256": info.evidence_sha256,
            "document_name": redact(info.document_name),
            "doc_hash": info.doc_hash,
            "copies_issued": _int(info.copies_issued),
            "c": _int(p.c),
            "n_max": _int(p.n_max),
            "constant": p.constant,
            "cutoff": _prob(p.cutoff, round_up=False),
        },
        "identified": identified,
        "accused_rows": _accused_rows(attribution, n_read),
        "anonymous_rows": _anonymous_rows(attribution, n_read),
        "best_other_score": _num(others[0].score) if others else None,
        "z": _num(t.threshold),
        "z_finite": math.isfinite(t.threshold),
        "z_fixed_at": i18n.format_datetime(t.fixed_at),
        "z_fixed_at_raw": t.fixed_at,
        "threshold_rule": t.rule,
        "n_observed": _int(t.n_observed),
        "effective_positions": _num(t.effective_positions, 0),
        "m": _int(p.length),
        "eps1": _prob(t.eps1, round_up=False),
        "eps": _prob(t.eps, round_up=False),
        "trace_no": t.trace_no,
        "eps_share": _prob(t.spent, round_up=False),
        "trace_text": _trace_text(t),
        "staged": t.stage_eps is not None,
        "stage_policy": t.stage_policy or "",
        "eps_stage1": _prob(t.stage_spent, round_up=False),
        "stage_rule": attribution.stages[0].threshold.rule if attribution.stages else "",
        "stages": _stage_views(attribution),
        "trace_anchor": (f"{info.trace_entry}:{info.trace_entry_hash}"
                         if info.trace_entry is not None and info.trace_entry_hash else ""),
        "anchor_text": anchor_text[:1].upper() + anchor_text[1:],
        "channel_rows": channel_rows,
        "unread_channels": [r["label"] for r in channel_rows if r["status"] == STATUS_UNREAD],
        "unexamined_channels": [r["label"] for r in channel_rows if r["status"] == STATUS_NOT_EXAMINED],
        "subchannel_rows": _subchannel_rows(info),
        "plan_rows": _plan_rows(info.plan_summary),
        "params_rows": _params_rows(p),
        "registry": _registry_text(info),
        "registry_failed": info.registry_ok is False,
        "notes": [say(redact(n)) for n in attribution.notes if not is_caveat(n)],
        "caveats": [say(redact(n)) for n in attribution.notes if VISIBLE_MARKS_NOTE in n],
        "manipulation_warnings": [say_warning(redact(n)) for n in attribution.notes if is_manipulation_note(n)],
        "reversal_text": say(attribution.reversal.text()) if attribution.reversal is not None else "",
        "erasure_text": say(attribution.erasure.text()) if attribution.erasure is not None else "",
        "contradiction_text": say(attribution.contradiction.text()) if attribution.contradiction is not None else "",
        "canary_rows": _canary_rows(info, shown_seqs, redact),
        "digests": [(f"#{c.copy.seq}", info.code_digests.get(c.copy.seq, _("tidak tersedia")))
                    for _stage, c in attribution.named],
        "command": rerun_command(info, redact, t.trace_no, t.stage_policy),
        "examined_at": i18n.format_datetime(info.examined_at, with_day=True),
        "received_at": i18n.format_datetime(info.evidence_received_at) if info.evidence_received_at else "",
        "issued_at": i18n.format_datetime(info.issued_at),
        "generated_at": i18n.format_datetime(_now_iso()),
        "signing_date": i18n.format_datetime(info.examined_at, with_time=False),
        "redacted": REDACTED,
        "inline_css": None,
    }


# --- rendering ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        extensions=["jinja2.ext.i18n"],
    )
    # Indonesian, or an English rendition when tapak.i18n is set to English (the web does that
    # for an English page); the Indonesian berita acara is the official one.
    env.install_gettext_callables(i18n.translate, i18n.translate_plural, newstyle=True)  # type: ignore[attr-defined]
    env.policies["ext.i18n.trimmed"] = True
    env.globals["bahasa"] = i18n.current
    return env


def render_html(attribution: Attribution, info: ReportInfo, *, standalone: bool = False) -> str:
    """The report as an HTML string (the same content that goes into the PDF).

    ``standalone=True`` inlines the report stylesheet in a ``<style>`` tag for a browser
    preview. The @font-face rules are not inlined: they hold local file paths that a page
    served over HTTP cannot load, so a browser uses its own sans-serif and monospace fonts.
    """
    view = _view(attribution, info)
    if standalone:
        view["inline_css"] = Markup((TEMPLATE_DIR / STYLESHEET_NAME).read_text(encoding="utf-8"))
    return _environment().get_template(TEMPLATE_NAME).render(**view)


def font_face_css() -> str:
    """@font-face rules for the bundled fonts, with absolute file:// URLs."""
    faces = [("TAPAK Sans", "normal", font_path("DejaVuSans")),
             ("TAPAK Sans", "bold", font_path("DejaVuSans-Bold"))]
    mono = FONT_DIR / MONO_FONT_FILE
    if mono.exists():
        faces.append(("TAPAK Mono", "normal", mono))
    return "\n".join(
        f'@font-face {{ font-family: "{family}"; font-weight: {weight}; src: url("{path.resolve().as_uri()}"); }}'
        for family, weight, path in faces
    )


def check_local_url(url: str) -> Path:
    """Allow only file:// URLs inside the bundled font and template folders."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise ValueError(f"sumber eksternal ditolak: {url}")
    path = Path(url2pathname(parsed.path)).resolve()
    if not any(path.is_relative_to(d.resolve()) for d in (FONT_DIR, TEMPLATE_DIR)):
        raise ValueError(f"berkas di luar folder aset ditolak: {path}")
    return path


def local_url_fetcher() -> Any:
    """A WeasyPrint URL fetcher that serves only :func:`check_local_url` URLs.

    ``fail_on_errors`` turns any refused or missing resource into an error instead of a
    silent fallback, so a report is never produced with a substituted font.
    """
    from weasyprint.urls import URLFetcher

    class LocalOnlyFetcher(URLFetcher):
        def fetch(self, url: str, headers: dict[str, str] | None = None) -> Any:
            check_local_url(url)
            return super().fetch(url, headers)

    return LocalOnlyFetcher(allowed_protocols=("file",), fail_on_errors=True)


def html_to_pdf(html: str) -> bytes:
    """Render report HTML to PDF bytes with the bundled fonts and the report stylesheet.

    Raises:
        RuntimeError: a resource was refused by the local-only fetcher or is missing.
            WeasyPrint signals this with FatalURLFetchingError, which derives from
            BaseException, so it is converted here for ordinary error handling.
    """
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import FatalURLFetchingError

    try:
        fetcher = local_url_fetcher()
        fonts = FontConfiguration()
        stylesheets = [
            CSS(string=font_face_css(), url_fetcher=fetcher, font_config=fonts),
            CSS(filename=str(TEMPLATE_DIR / STYLESHEET_NAME), url_fetcher=fetcher, font_config=fonts),
        ]
        document = HTML(string=html, base_url=TEMPLATE_DIR.as_uri() + "/", url_fetcher=fetcher)
        return document.write_pdf(stylesheets=stylesheets, font_config=fonts)
    except FatalURLFetchingError as exc:
        raise RuntimeError("gagal membuat berita acara: sumber lokal tidak tersedia atau "
                           "ditolak (hanya fon dan templat bawaan yang boleh dipakai)") from exc


def render_report(attribution: Attribution, info: ReportInfo, out_path: Path | None = None) -> bytes:
    """Render the berita acara as PDF bytes; also write them to ``out_path`` if given."""
    pdf = html_to_pdf(render_html(attribution, info))
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf)
    return pdf
