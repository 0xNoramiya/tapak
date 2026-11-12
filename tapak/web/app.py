"""TAPAK web UI (FastAPI + HTMX). Two entry points: Terbitkan (issue) and Lacak (trace).

Runs locally (bind to 127.0.0.1 or inside the unit's network). Nothing is fetched from or
sent to the internet; HTMX is served from ./static.
"""

from __future__ import annotations

import base64
import copy
import csv
import difflib
import html
import io
import itertools
import json
import re
import secrets
import shutil
import threading
import zipfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import os
import time
from urllib.parse import quote, urlencode, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tapak.config import Settings, load_settings, total_memory_mb, trace_slots, worker_limit
from tapak.decoder.accuse import VERDICT_IDENTIFIED
from tapak.decoder.report import (
    _strip_zeros,
    format_datetime,
    format_number,
    format_probability_html,
    software_version,
)
from tapak.marker.background import PRINT_BACKGROUND_WARNING, background_profile
from tapak.marker.issue import IssueSettings, Recipient, SemanticSelection, read_recipients
from tapak.marker.lexical import LexicalSelection, LexPoint
from tapak.marker.master import MasterDocument
from tapak.marker.pdf_shift import DEFAULT_SCHEME, SCHEME_CHOICES
from tapak.marker.raster import GATE_MAX_DIFF as RASTER_GATE_MAX_DIFF
from tapak import i18n
from tapak.i18n import N_
from tapak.i18n import gettext as _

HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 40 * 1024 * 1024
# One name per channel on every page: the physical channels of a trace (geser, latar, teks,
# semantik, leksikal) carry the names of the sub-channels they are made of, as on Terbitkan.
# Indonesian, like every message here (N_ marks it for the catalog; i18n translates it when shown).
CHANNEL_NAMES = {
    "shift": N_("Geser kata dan baris"), "background": N_("Pola latar"), "zw": N_("Karakter tak terlihat"),
    "homoglyph": N_("Huruf kembar"), "semantic": N_("Varian kalimat"), "canary": N_("Token kanari"),
    "lexical": N_("Pilihan kata"), "semantic_ocr": N_("Varian kalimat (OCR gambar)"),
    "lexical_ocr": N_("Pilihan kata (OCR gambar)"), "geser": N_("Geser kata dan baris"), "latar": N_("Pola latar"),
    "teks": N_("Karakter tak terlihat dan huruf kembar"), "semantik": N_("Varian kalimat"), "leksikal": N_("Pilihan kata"),
}
EPS_CHOICES = [("1e-4", N_("1 dari 10.000")), ("1e-6", N_("1 dari 1.000.000")), ("1e-8", N_("1 dari 100.000.000"))]
# Progress header of Terbitkan. Step 3 covers both text reviews (safe sentences and word choice).
ISSUE_STEPS = (N_("Dokumen"), N_("Rencana"), N_("Tinjau teks"), N_("Terbitkan"))
NOTHING_TO_MARK = N_("PDF ini tidak memiliki lapisan teks dan tidak dikenali sebagai hasil pindai (setiap halaman "
                     "pindaian harus berupa satu gambar halaman penuh). Tidak ada yang dapat ditandai.")
# What the visual gate found on scanned pages (GateResult.scan_identical, raster.scan_gate):
# the unmarked copy holds the master page image sample for sample, and its rendered page stays
# within the text-page gate's limits of the master's (not "renders the same": that is not tested).
SCAN_GATE_LINES = {
    True: N_("Halaman pindaian: gambar halaman salinan tanpa tanda identik piksel demi piksel dengan gambar induk, "
             "dan render halamannya berselisih paling banyak %(n)s tingkat abu-abu dari halaman induk."),
    False: N_("Halaman pindaian: gambar halaman salinan tanpa tanda tidak identik dengan gambar induk, atau render "
              "halamannya melewati batas gerbang visual; penerbitan ditolak."),
}
# Busy line of the analysis step: Tesseract reads every scanned page once there.
SCAN_READ_BUSY = N_("Membaca kotak kata halaman pindaian dengan Tesseract (beberapa detik per halaman).")
SCAN_ALL_NA = N_("Tidak berlaku: semua halaman dokumen ini hasil pindai")


def _sentence(text: str) -> str:
    """A message as a sentence: first letter upper case, a final period."""
    text = text.strip()
    if not text:
        return text
    return text[:1].upper() + text[1:] + ("" if text[-1] in ".!?" else ".")


@dataclass
class Staging:
    """An issuance being prepared (before copies exist)."""

    sid: str
    folder: Path
    doc_name: str
    recipients: list[Recipient]
    settings: IssueSettings
    issuer: str
    # Background profile chosen in step 1 ("layar" or "cetak"); st.settings.background holds its pattern.
    latar: str = "layar"
    # Shift scheme chosen in step 1 ("v1" or "v2", pdf_shift.SCHEME_CHOICES); st.settings.shift holds it.
    geser: str = "v1"
    units: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    sets: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    issued_doc: str | None = None
    # Word-choice channel: None until the issuer opts in and scans (a LexicalSelection after).
    lexical: LexicalSelection | None = None
    # The parsed master, loaded once for the word-choice scan and its sample copies.
    master: MasterDocument | None = field(default=None, repr=False)
    # (approved point ids, sample-copy rows): recomputed only when the approvals change.
    lex_preview: tuple | None = field(default=None, repr=False)
    # Set (under _LOCK) while the copies are being issued: review actions are refused meanwhile.
    issuing: bool = False
    # Last request on this session; idle sessions expire STAGING_TTL_S after it.
    last_used: float = field(default_factory=time.time)
    # Scanned pages: the record raster.prepare_scans returned (page numbers, resolution, OCR
    # engine, digest of the word boxes; never a box or a word), or None for a text-only master.
    scan: dict | None = None
    # The word boxes behind that record, so the word-choice preview counts the same shift slots
    # as the issuance plan (kept in memory only, never shown or stored).
    scan_boxes: dict | None = field(default=None, repr=False)

    @property
    def pdf(self) -> bool:
        """True for a PDF master (the word-choice channel exists only for PDF)."""
        return (self.folder / "induk.pdf").is_file()

    @property
    def all_scanned(self) -> bool:
        """True when every page is a scanned page: no text layer, so neither safe sentences nor
        word choice can be marked."""
        return bool(self.plan.get("all_scanned"))


_STAGING: dict[str, Staging] = {}
_TRACES: dict[str, object] = {}
_LOCK = threading.Lock()
# TAPAK_WORKERS caps the worker processes of an issuance (tapak.marker.issue) and the traces
# that run at once. Checked when the server starts: a bad value stops it with the reason.
try:
    WORKER_LIMIT = worker_limit()
except ValueError as _exc:
    raise SystemExit(f"galat: {_exc}") from None
# Image decoding and registration take a CPU each and, for a phone photo, more than a gigabyte:
# at most two traces at a time, no more than TAPAK_WORKERS, and one at a time on a small host.
TRACE_SLOTS = trace_slots(WORKER_LIMIT, total_memory_mb())
_TRACE_SLOTS = threading.BoundedSemaphore(TRACE_SLOTS)

# Files written by the app (masters, copies, manifests) are readable by the operator only.
os.umask(0o077)

STAGING_TTL_S = 2 * 3600
# Host names the app answers to (TrustedHostMiddleware syntax: exact names or "*.domain").
# Add the public name when the app sits behind a reverse proxy, e.g.
# TAPAK_ALLOWED_HOSTS=127.0.0.1,localhost,tapak.satuan.mil
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    "TAPAK_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
# On a public address the operator's pages ask for this password (HTTP Basic, user "operator");
# the product page, the sandboxed demo and the static files stay open. Unset: no password.
OPERATOR_PASSWORD = os.environ.get("TAPAK_OPERATOR_PASSWORD", "")
OPERATOR_USER = "operator"

app = FastAPI(title="TAPAK", docs_url=None, redoc_url=None, openapi_url=None)
# Host allowlist: a page on another site cannot reach this app through DNS rebinding.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def _same_origin_posts(request: Request, call_next):
    """Refuse state-changing requests sent by another origin (cross-site form posts).

    Accepted: an Origin (or Referer) naming exactly the host and port the request was sent to,
    or a non-loopback name in ALLOWED_HOSTS (the public name behind a reverse proxy, with the
    same "*.domain" wildcards as the host check; a bare "*" never accepts a foreign origin).
    """
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            parts = urlsplit(origin)
            host = (parts.hostname or "").lower()
            same = parts.netloc.lower() == request.headers.get("host", "").lower()
            # Another app on this machine (any localhost port) is a different origin: loopback
            # names count only as the exact host:port of this app. ALLOWED_HOSTS admits the
            # public names a reverse proxy serves.
            if not (same or (host not in _LOOPBACK and _host_allowed(host))):
                return HTMLResponse(f'<div class="notice notice-error">{_("Permintaan dari asal lain ditolak.")}</div>',
                                    status_code=403)
    return await call_next(request)


_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _public_path(path: str) -> bool:
    """Pages anyone may open when the operator's pages need a password."""
    return path in ("/", "/healthz", "/demo") or path.startswith(("/static/", "/demo/"))


def _is_operator(authorization: str) -> bool:
    scheme, _space, encoded = authorization.partition(" ")
    try:
        user, _colon, password = base64.b64decode(encoded, validate=True).decode().partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return (scheme.lower() == "basic" and user == OPERATOR_USER
            and secrets.compare_digest(password.encode(), OPERATOR_PASSWORD.encode()))


@app.middleware("http")
async def _operator_password(request: Request, call_next):
    """With TAPAK_OPERATOR_PASSWORD set, every page but the public ones needs the operator's
    password; the browser asks for it."""
    if (OPERATOR_PASSWORD and not _public_path(request.url.path)
            and not _is_operator(request.headers.get("authorization", ""))):
        resp = _notice(request, _("Halaman operator memerlukan kata sandi."), 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="TAPAK", charset="UTF-8"'
        return resp
    return await call_next(request)

# No page of another site may frame TAPAK (clickjacking of "Terbitkan" or the review buttons),
# and the browser itself keeps the app offline: data, images, fonts and form posts go to this
# origin only. script-src and style-src stay open: htmx injects its indicator styles and
# evaluates the hx-trigger filter of the Lacak form (Ctrl+Enter) with Function().
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": ("frame-ancestors 'none'; connect-src 'self'; img-src 'self'; font-src 'self'; "
                                "form-action 'self'; base-uri 'none'; object-src 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Frame, content-type and referrer policy on every response."""
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


DEMO_COOKIE = "demo"


@app.middleware("http")
async def _demo_visitor(request: Request, call_next):
    """Each visitor of the guided demo has a sandbox of their own, named by the demo cookie
    (``request.state.demo_visitor``); a visitor without a valid cookie gets a new one."""
    path = request.url.path
    if path != "/demo" and not path.startswith("/demo/"):
        return await call_next(request)
    from tapak.web.demo_web import SANDBOX_TTL_S, VISITOR

    visitor = request.cookies.get(DEMO_COOKIE, "")
    fresh = not VISITOR.fullmatch(visitor)
    request.state.demo_visitor = secrets.token_hex(8) if fresh else visitor
    response = await call_next(request)
    if fresh:
        response.set_cookie(DEMO_COOKIE, request.state.demo_visitor, max_age=SANDBOX_TTL_S, samesite="lax",
                            httponly=True)
    return response


def _request_lang(request: Request) -> str:
    return i18n.choose(request.query_params.get("lang"), request.cookies.get(i18n.COOKIE))


@app.middleware("http")
async def _language(request: Request, call_next):
    """The language of everything this request renders (``i18n``); ``?lang=`` also sets the
    cookie that keeps it for the following pages and htmx requests. Added last, so it runs
    first: the other middleware's refusals are in the page language too."""
    token = i18n.use(_request_lang(request))
    try:
        response = await call_next(request)
    finally:
        i18n.reset(token)
    if request.query_params.get("lang") in i18n.LANGS:
        response.set_cookie(i18n.COOKIE, i18n.choose(request.query_params.get("lang"), None),
                            max_age=365 * 24 * 3600, samesite="lax", httponly=True)
    return response


def _host_allowed(host: str) -> bool:
    host = host.lower()
    for pattern in ALLOWED_HOSTS:
        pattern = pattern.lower()
        if pattern == host or (pattern.startswith("*.") and host.endswith(pattern[1:])):
            return True
    return False


# Step-1 shift scheme choice matching the default scheme of a new issuance.
DEFAULT_GESER = next(k for k, v in SCHEME_CHOICES.items() if v == DEFAULT_SCHEME)

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.add_extension("jinja2.ext.i18n")
templates.env.add_extension("jinja2.ext.do")
templates.env.install_gettext_callables(i18n.translate, i18n.translate_plural, newstyle=True)  # type: ignore[attr-defined]
templates.env.policies["ext.i18n.trimmed"] = True
templates.env.globals["bahasa"] = i18n.current
templates.env.filters["tr"] = i18n.translate_text
templates.env.filters["num"] = lambda v, d=0: i18n.localize(format_number(float(v), d))
templates.env.filters["prob"] = lambda p, log10=None: Markup(i18n.localize(format_probability_html(float(p), log10)))
# A fraction as a percentage, written as the berita acara writes shares of eps: '60,79', '7,35', '90'.
templates.env.filters["persen"] = lambda v: i18n.localize(_strip_zeros(format_number(100 * float(v), 2)))
templates.env.filters["waktu"] = lambda v: i18n.format_datetime(str(v))
templates.env.filters["tanggal"] = lambda v: i18n.format_datetime(str(v), with_time=False)
templates.env.filters["jam"] = lambda v: i18n.format_clock(str(v))
templates.env.globals["channel_name"] = lambda c: _(CHANNEL_NAMES.get(c, c))


def _lang_url(request: Request, lang: str) -> str:
    """The current page in ``lang``: its path and query with ``lang`` replaced."""
    query = [(k, v) for k, v in request.query_params.multi_items() if k != "lang"] + [("lang", lang)]
    return f"{request.url.path}?{urlencode(query)}"


templates.env.globals["lang_url"] = _lang_url


def _channel_label(ch) -> str:
    """Name of a physical channel row of a trace, with how it was read when that is not the
    obvious way (for example "Pilihan kata (OCR gambar)": word choices read from the OCR text of
    a photo). Never any OCR text."""
    name = _(CHANNEL_NAMES.get(ch.channel, ch.channel))
    return f"{name} ({i18n.translate_text(ch.source_label)})" if ch.source_label else name


def _agreeing_labels(candidate, attribution) -> list[str]:
    """The channels that independently name ``candidate``, labelled like the channel table."""
    rows = {ch.channel: ch for ch in attribution.channels}
    return [_channel_label(rows[k]) if k in rows else _(CHANNEL_NAMES.get(k, k)) for k in candidate.channels_agreeing]


templates.env.globals["channel_label"] = _channel_label
templates.env.globals["agreeing_labels"] = _agreeing_labels
templates.env.globals["inf"] = float("inf")
templates.env.globals["langkah_terbit"] = ISSUE_STEPS
templates.env.globals["peringatan_cetak"] = PRINT_BACKGROUND_WARNING
templates.env.globals["gerbang_pindaian"] = SCAN_GATE_LINES
templates.env.globals["gerbang_maks"] = RASTER_GATE_MAX_DIFF
templates.env.globals["sibuk_pindaian"] = SCAN_READ_BUSY
templates.env.globals["pindaian_na"] = SCAN_ALL_NA
templates.env.globals["geser_bawaan"] = DEFAULT_GESER


def _visible_marks_caveats(notes: list[str]) -> list[str]:
    """Notes shown as warnings next to the verdict rather than among the other notes: a name
    that rests only on marks visible on paper (word choices, variants), the one merged warning
    of the manipulation checks (reversed marks, a deliberate erasure pattern, a clear read that
    names nobody; ``decoder/manipulation.py``), and the shift channel of
    scanned pages left out because Tesseract's word boxes differ from issuance (only the
    background pattern of those pages was read)."""
    from tapak.decoder.accuse import is_caveat
    from tapak.decoder.trace import SCAN_SHIFT_SKIPPED

    return [n for n in notes if is_caveat(n) or n.startswith(SCAN_SHIFT_SKIPPED)]


templates.env.globals["peringatan_terlihat"] = _visible_marks_caveats

# Registry sentences that say why a name is not (yet) confirmed: the problem reported by
# service.check_registry and what it means for the name. Shown under an identified verdict and
# then left out of the validity box, so the page says it once.
REGISTRY_NO_KEY = "kunci publik tidak tersedia"
REGISTRY_UNRECORDED = "dokumen ini diterbitkan tanpa registri"


def _clause(text: str) -> str:
    """A finding that follows "Perhatian:" under the verdict: lower case kept, as the decoder
    writes it (and as the merged manipulation warning starts), with a final period."""
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _lead(text: str, sep: str) -> list[str]:
    """``text`` cut at the first ``sep`` into its finding (set in bold under the verdict) and
    the rest (a sentence on its own line); ``[text]`` as one finding when ``sep`` does not occur."""
    head, found, tail = text.partition(sep)
    return [_clause(head), _sentence(tail)] if found and tail.strip() else [_clause(text)]


# A pair of channels as the decoder writes it in a note ("kanal geser|latar saling bertentangan").
_CHANNEL_PAIR = re.compile(r"\bkanal (\w+)\|(\w+)\b")


def _page_note(note: str) -> str:
    """A trace note in the words of this page: a channel pair is named as the channel table
    names its channels (one name per channel), not with the decoder's keys."""
    def pair(m: re.Match) -> str:
        a, b = (_(CHANNEL_NAMES.get(k, k)).lower() for k in (m[1], m[2]))
        return _("kanal %(a)s dan kanal %(b)s", a=a, b=b)

    return _CHANNEL_PAIR.sub(pair, note)


def _verdict_notes(outcome, attribution, identified: bool, redact) -> dict[str, object]:
    """Everything said under the verdict, in the order it changes what the operator does, and
    what is left for the validity box.

    Under an identified verdict: a name that rests only on marks visible on paper (it needs
    supporting evidence), then why the recipient's identity is not confirmed by the registry,
    then the merged manipulation warning, then a shift channel of scanned pages left out. Under
    "tidak cukup bukti" only the last two apply. The merged warning is shown without the
    statistic of each check: the validity box lists those, each with its own row.

    Every warning starts with its finding, set in bold, and gives the rest on its own lines, so
    a warning ranked higher never reads lighter than one below it. For the registry the finding
    is what it means for the name; the registry problem behind it follows.

    Returns ``notes`` (each a list of sentences: the first is the finding, the others go on
    their own lines; ``manipulation`` marks the merged warning), ``notes_rest`` (the trace notes
    for the validity box, without one the verdict already says) and ``problems`` (the registry
    problems for the validity box).
    """
    from tapak.decoder.accuse import NO_MARKS_NOTE, VISIBLE_MARKS_NOTE
    from tapak.decoder.manipulation import is_manipulation_note, manipulation_note, manipulation_parts
    from tapak.decoder.trace import SCAN_SHIFT_SKIPPED

    a, r = attribution, outcome.registry
    shown = _visible_marks_caveats(a.notes)
    rest = [n for n in a.notes if n not in shown]
    if not identified and not a.threshold.n_observed:
        rest = [n for n in rest if n != NO_MARKS_NOTE]  # the verdict says "Tidak ada tanda yang terbaca"
    problems = list(r.problems)
    ranked: list[tuple[int, dict[str, object]]] = []
    for n in shown:
        if VISIBLE_MARKS_NOTE in n:
            ranked.append((0, {"parts": _lead(redact(n), ". ")}))
        elif is_manipulation_note(n):
            short = manipulation_note(a.erasure, a.contradiction, a.reversal, statistics=False) or n
            ranked.append((2, {"parts": manipulation_parts(short), "manipulation": True}))
        elif n.startswith(SCAN_SHIFT_SKIPPED):
            ranked.append((3, {"parts": _lead(redact(n), ": ")}))
    if identified:
        parts = None
        if not r.recorded:
            note = next((n for n in rest if n.startswith(REGISTRY_UNRECORDED)), None)
            if note is not None:
                rest.remove(note)
                parts = [_clause(note)]
            else:
                parts = [_("identitas penerima hanya berasal dari catatan lokal dan belum dikonfirmasi."),
                         _("Dokumen ini tidak tercatat di registri.")]
        elif r.chain_ok is not True:
            p = next((p for p in problems if p.startswith(REGISTRY_NO_KEY)), None)
            if p is not None:
                problems.remove(p)
            parts = [_("identitas penerima belum dikonfirmasi oleh rantai bertanda tangan."),
                     _sentence(i18n.translate_text(p) if p else _("registri tidak diverifikasi karena kunci publik "
                                                                   "tidak tersedia"))]
        elif r.copies_unsigned:
            prefix = f"{r.copies_unsigned} entri salinan dokumen ini belum bertanda tangan"
            p = next((p for p in problems if p.startswith(prefix)), None)
            if p is not None:
                problems.remove(p)
            parts = [_("identitas penerima belum dilindungi tanda tangan registri."),
                     _sentence(i18n.translate_text(p or prefix))]
        if parts:
            ranked.append((1, {"parts": parts}))
    ranked.sort(key=lambda item: item[0])  # stable: notes of one kind keep their order
    return {"notes": [note for _, note in ranked], "notes_rest": [_page_note(n) for n in rest], "problems": problems}


_POWER = re.compile(r"(?:(\d+(?:[.,]\d+)?) x )?10\^(-?)(\d+)")


def _powers(text: object) -> Markup:
    """Escaped text with every power of ten written as the verdict writes it: '9,5 x 10^-6'
    becomes 9,5, a multiplication sign and 10 with a superscript exponent (a true minus sign),
    and a screen reader hears '9,5 kali 10 pangkat minus 6' (a superscript is not announced)."""
    out, last = [], 0
    raw = str(text)
    for m in _POWER.finditer(raw):
        out.append(str(escape(raw[last:m.start()])))
        mant, minus, exp = m.group(1), m.group(2), m.group(3)
        sign = "\u2212" if minus else ""
        seen = (f"{mant} \u00d7 " if mant else "") + f"10<sup>{sign}{exp}</sup>"
        power = {"m": mant, "minus": _("minus ") if minus else "", "e": exp}
        heard = _("%(m)s kali 10 pangkat %(minus)s%(e)s", **power) if mant else _("10 pangkat %(minus)s%(e)s", **power)
        out.append(f'<span class="nowrap" aria-hidden="true">{seen}</span><span class="sr-only">{heard}</span>')
        last = m.end()
    out.append(str(escape(raw[last:])))
    return Markup("".join(out))


templates.env.filters["pangkat"] = _powers

# A TAPAK command in running text ("tapak verify --jangkar", "tapak jangkar mulai"): in the
# monospace face commands have everywhere else on these pages, and a flag is never broken after
# its dashes ("tapak verify --" at the end of a line, "jangkar" on the next). Lines may still
# break between words, so a long command fits a phone. At most two subcommand words, then any
# flags: "tapak jangkar mulai --ulang --alasan", but not the prose after a command ("tapak
# registry sign lebih dulu").
_COMMAND = re.compile(r"\btapak(?:(?: [a-z][a-z-]*){1,2}(?: --?[a-z][a-z-]*)*|(?: --?[a-z][a-z-]*)+)")


def _command(m: re.Match) -> str:
    words = (f'<span class="nowrap">{w}</span>' if "-" in w else w for w in m[0].split(" "))
    return f'<span class="mono">{" ".join(words)}</span>'


def _prose(text: object) -> Markup:
    """Escaped running text as :func:`_powers` writes it, with every TAPAK command set as one."""
    return Markup(_COMMAND.sub(_command, str(_powers(text))))


templates.env.filters["prosa"] = _prose
templates.env.filters["kalimat"] = _sentence


def _fap(candidate, n_copies: int):
    """False-accusation probability of a named copy, exact even when it underflows a float."""
    import math

    log10 = candidate.log10_false_accusation
    return Markup(i18n.localize(format_probability_html(candidate.false_accusation_probability,
                                                        log10 if math.isfinite(log10) else None)))


templates.env.globals["fap"] = _fap


def _fap_spoken(candidate, n_copies: int) -> str:
    """The value of fap() as it is read aloud: '1,1 kali 10 pangkat minus 133'. Screen readers
    do not announce a superscript, so the written form would be heard as '10 minus 133'."""
    import math

    from tapak.decoder.report import _probability_parts

    log10 = candidate.log10_false_accusation
    mantissa, exponent = _probability_parts(candidate.false_accusation_probability,
                                            log10 if math.isfinite(log10) else None, True)
    if exponent is None:
        return i18n.localize(mantissa)
    return _("%(m)s kali 10 pangkat %(minus)s%(e)s", m=i18n.localize(mantissa), minus=_("minus ") if exponent < 0 else "",
             e=abs(exponent))


templates.env.globals["fap_lisan"] = _fap_spoken


def _subchannel_summary(sb) -> str:
    """Decoder diagnostics of one sub-channel in plain words (no raw keys or values)."""
    from tapak.decoder.report import _noise_text

    def num(value: float, decimals: int = 0) -> str:
        return i18n.localize(format_number(float(value), decimals))

    m = sb.meta
    parts = []
    if isinstance(m.get("page"), int):
        parts.append(_("halaman %(n)s", n=m["page"] + 1))
    elif isinstance(m.get("pages"), int):
        parts.append(_("%(n)s halaman dibaca", n=m["pages"]))
    for key, label in (("slots", N_("slot terbaca %(n)s dari %(total)s")), ("bits", N_("bit terbaca %(n)s dari %(total)s"))):
        if isinstance(m.get(f"{key}_read"), int) and isinstance(m.get(f"{key}_total"), int):
            parts.append(_(label, n=num(m[f"{key}_read"]), total=num(m[f"{key}_total"])))
    if m.get("registered") is False:
        parts.append(_("halaman tidak dikenali"))
    if m.get("pattern_found") is False:
        parts.append(_("pola tidak terdeteksi"))
    if isinstance(m.get("slots_outside_image"), int) and m["slots_outside_image"]:
        parts.append(_("%(n)s tanda di luar gambar, tidak dibaca", n=num(m["slots_outside_image"])))
    if m.get("ocr_failed"):
        parts.append(_("OCR gagal membaca halaman"))
    elif isinstance(m.get("ocr_seconds"), (int, float)):
        parts.append(_("dibaca dengan OCR dalam %(s)s detik", s=num(m["ocr_seconds"], 1)))
    if isinstance(m.get("signal_z"), (int, float)):
        parts.append(_("uji pola z = %(z)s", z=num(m["signal_z"], 1)))
    noise = _noise_text(sb.channel, m)
    if noise not in ("-", ""):
        parts.extend(i18n.translate_text(part) for part in noise.split("; "))
    if isinstance(m.get("correlation"), (int, float)):
        parts.append(_("korelasi %(r)s", r=num(m["correlation"], 3)))
    if isinstance(m.get("effective_dpi"), (int, float)):
        parts.append(_("resolusi efektif %(dpi)s dpi", dpi=num(m["effective_dpi"])))
    return "; ".join(parts) or "-"


templates.env.globals["subchannel_summary"] = _subchannel_summary


def _beda(original: object, variant: object) -> Markup:
    """The variant with the words that differ from the original wrapped in <mark class="diff">.

    Words are compared as whitespace-separated tokens (difflib), so punctuation stuck to a word
    counts as part of it. Everything else is escaped; the variant's own spacing is kept.
    """
    words = str(variant).split()
    gaps = re.findall(r"\s+", str(variant))
    lead = gaps.pop(0) if gaps and str(variant)[:1].isspace() else ""
    changed = [False] * len(words)
    matcher = difflib.SequenceMatcher(a=str(original).split(), b=words, autojunk=False)
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            changed[j1:j2] = [True] * (j2 - j1)
    out = [str(escape(lead))]
    open_mark = False
    for i, word in enumerate(words):
        gap = str(escape(gaps[i - 1])) if i else ""
        if changed[i] and open_mark:
            out.append(gap + str(escape(word)))
            continue
        if open_mark:
            out.append("</mark>")
            open_mark = False
        out.append(gap)
        if changed[i]:
            out.append('<mark class="diff">')
            open_mark = True
        out.append(str(escape(word)))
    if open_mark:
        out.append("</mark>")
    if len(gaps) >= len(words) and words:
        out.append(str(escape(gaps[-1])))
    return Markup("".join(out))


templates.env.filters["beda"] = _beda


def _meter(value: float, mark: float | None = None, peak: float | None = None) -> dict[str, float | None]:
    """Positions (0..1) of a score and its threshold on one scale for a .meter.

    The scale runs from 0 to 15 % past the larger of the two, so neither touches the end;
    negative scores sit at 0 and an infinite threshold has no mark (None). ``peak`` (the highest
    score of a group) puts several meters on one scale, so their thresholds line up and their
    fills compare, as in the score ranking.
    """
    import math

    v = max(float(value), 0.0)
    m = float(mark) if mark is not None and math.isfinite(float(mark)) else None
    top = max(v, m or 0.0, float(peak or 0.0)) * 1.15 or 1.0
    return {"value": round(v / top, 4), "mark": None if m is None else round(max(m, 0.0) / top, 4)}


templates.env.globals["meter"] = _meter

_STATIC_FILES = ("tapak.css", "tapak.js")


def _asset_version() -> str:
    """Cache-busting query value for the stylesheets and script (newest modification time)."""
    static = HERE / "static"
    files = [static / n for n in _STATIC_FILES] + sorted((static / "css").glob("*.css"))
    return str(max(int(p.stat().st_mtime) for p in files))


templates.env.globals["asset_v"] = _asset_version


def _size_label(n: int) -> str:
    from tapak.web.demo_web import size_label

    return size_label(n)


templates.env.globals["size_label"] = _size_label

_REGISTRY_STATUS: dict[str, object] = {}


def _registry_key(s: Settings) -> str:
    """Path, size and modification time of the registry, the public key file and the anchor log."""
    stamp = []
    for p in (s.registry_path, s.public_key_path, *([s.anchor_log] if s.anchor_log else [])):
        try:
            st = p.stat()
            stamp.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            stamp.append((str(p), None, None))
    return repr(stamp)


def _registry_status() -> dict[str, object]:
    """Registry state for the sidebar and Beranda: state ok / warn / danger / none, label,
    entries, unsigned, and counted (False when the entry count is unknown: show no count).

    Verifying the chain reads every row, so the result is kept until the registry or the
    public key file changes (keyed by path, size and modification time).
    """
    s = settings()
    key = _registry_key(s)
    with _LOCK:
        if _REGISTRY_STATUS.get("key") == key:
            return _REGISTRY_STATUS["value"]  # type: ignore[return-value]
    value = _verify_status(s)
    with _LOCK:
        _REGISTRY_STATUS.update(key=key, value=value)
    return value


def _verify_status(s: Settings) -> dict[str, object]:
    if not s.registry_path.exists():
        return {"state": "none", "label": N_("Belum ada"), "entries": 0, "unsigned": 0, "counted": False}
    unreadable = {"state": "danger", "label": N_("Tak terbaca"), "entries": 0, "unsigned": 0, "counted": False}
    if not s.public_key_path.exists():
        # Entries exist but cannot be verified without the public key: count them read-only.
        import sqlite3

        try:
            conn = sqlite3.connect(s.registry_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            return unreadable
        return {"state": "warn", "label": N_("Tanpa kunci"), "entries": entries, "unsigned": 0, "counted": True}
    from tapak.registry.verify import verify_registry

    try:
        report = verify_registry(s.registry_path, s.public_key_path.read_text().strip(), require_signed=False,
                                 anchor_log=s.anchor_log)
    except (OSError, ValueError):  # SigningKeyError and UnicodeDecodeError are ValueErrors
        return unreadable
    return _report_status(report)


def _report_status(report) -> dict[str, object]:
    return {"state": "ok" if report.ok else "danger", "label": N_("Utuh") if report.ok else N_("Rusak"),
            "entries": report.entries, "unsigned": report.unsigned, "counted": True}


templates.env.globals["registry_status"] = _registry_status


def _preview_url(manifest) -> str | None:
    """URL of the page-1 thumbnail of an issued document (PDF masters only)."""
    from tapak.service import workspace_dir

    if (workspace_dir(settings(), manifest.doc_hash) / "induk.pdf").is_file():
        return f"/dokumen/{manifest.doc_hash[:16]}/pratinjau.png"
    return None


templates.env.globals["pratinjau_url"] = _preview_url


def _notice(request: Request, message: str, status: int, restart: bool = False,
            field: str = "") -> HTMLResponse:
    """An error notice in the page language. For htmx requests it is placed in the page-level alert
    region (HX-Retarget) so the current form stays intact; a plain link (a download, an old
    bookmark) gets a full page with navigation. ``field`` names the error slot of the input
    at fault: the message is also put there (out of band), which marks that input invalid."""
    if not request.headers.get("HX-Request"):
        resp = _page(request, "galat.html", title=N_("Galat"), message=message, restart=restart, code=status)
        resp.status_code = status
        return resp
    link = f' <a class="link" href="/terbitkan">{html.escape(_("Mulai lagi"))}</a>' if restart else ""
    body = f'<div class="notice notice-error">{html.escape(message)}{link}</div>'
    if field:
        body += (f'<span id="{field}" hx-swap-oob="innerHTML"><span class="field-error">'
                 f'{html.escape(message)}</span></span>')
    headers = {"HX-Retarget": "#galat-global", "HX-Reswap": "innerHTML"} if request.headers.get("HX-Request") else {}
    return HTMLResponse(body, status_code=status, headers=headers)


# Messages for errors raised by Starlette itself (its details are English).
_FRAMEWORK_MESSAGES = {
    400: N_("Permintaan tidak dapat dibaca. Periksa isian dan berkas, lalu kirim lagi."),
    404: N_("Halaman tidak ditemukan. Periksa alamatnya, atau pilih tujuan dari menu."),
    405: N_("Tindakan ini tidak tersedia di alamat tersebut."),
    413: N_("Kiriman terlalu besar (maksimum 40 MB seluruhnya)."),
}


_PATH_SUFFIX = re.compile(r" tidak ditemukan di \S+$")


def _public_text(exc: Exception) -> str:
    """The message of a library error for the page, in the page language: "dokumen <key> tidak
    ditemukan di <data folder>" loses the folder, which stays in the server log."""
    text = str(exc)
    if _PATH_SUFFIX.search(text):
        import logging

        logging.getLogger("tapak.web").info("%s", text)
        text = _PATH_SUFFIX.sub(" tidak ditemukan", text)
    return i18n.translate_text(text)


@app.exception_handler(FileNotFoundError)
async def _not_found(request: Request, exc: FileNotFoundError) -> HTMLResponse:
    """Missing or invalid documents become a 404 with a message, never a 500."""
    text = _public_text(exc)
    return _notice(request, text[:1].upper() + text[1:], 404)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    """HTTP errors (413, 404, 400) as notices instead of JSON. TAPAK's own errors
    (fastapi.HTTPException) already carry text in the page language; Starlette's are replaced."""
    field = ""
    if isinstance(exc, HTTPException):
        message = str(exc.detail)
    elif "maximum size" in str(exc.detail):
        message = _("Teks yang ditempel terlalu panjang (maksimum 1 MB). Simpan sebagai berkas .txt lalu unggah.")
        if request.url.path == "/lacak":
            field = "teks-err"
    else:
        message = (_(_FRAMEWORK_MESSAGES[exc.status_code]) if exc.status_code in _FRAMEWORK_MESSAGES
                   else _("Permintaan ditolak (kode %(code)s).", code=exc.status_code))
    restart = bool(exc.headers and exc.headers.get("X-Tapak-Mulai-Lagi"))
    return _notice(request, message, exc.status_code, restart=restart, field=field)


@app.exception_handler(RequestValidationError)
async def _invalid_form(request: Request, exc: RequestValidationError) -> HTMLResponse:
    """A form field of the wrong type (normally caught by the form itself)."""
    fields = sorted({str(e.get("loc", ["", "?"])[-1]) for e in exc.errors()})
    return _notice(request, _("Isian tidak sah: %(fields)s. Periksa lalu kirim lagi.", fields=", ".join(fields)), 422)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> HTMLResponse:
    """Anything unexpected: a generic notice (details stay in the server log). It runs outside
    the language middleware, so it sets the language of the request itself."""
    import logging

    logging.getLogger("tapak.web").exception("kesalahan tak terduga")
    i18n.use(_request_lang(request))
    return _notice(request, _("Terjadi kesalahan tak terduga di server TAPAK. Coba lagi; bila berulang, periksa log server."), 500)


def settings() -> Settings:
    """Current settings (read per request so tests can point TAPAK_DATA elsewhere)."""
    return load_settings()


def _ctx(request: Request, **kw: object) -> dict[str, object]:
    s = settings()
    return {"request": request, "version": software_version(), "registry_path": str(s.registry_path), **kw}


def _page(request: Request, name: str, **kw: object) -> HTMLResponse:
    return templates.TemplateResponse(request, name, _ctx(request, **kw))


async def _read_upload(f: UploadFile | None) -> bytes:
    if f is None or not f.filename:
        return b""
    data = await f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, _("Berkas terlalu besar (maksimum 40 MB)"))
    return data


async def _read_field(f: UploadFile | None, errors: dict[str, str], key: str, too_big: str) -> bytes:
    """An upload, or b"" with ``too_big`` as the error of field ``key`` when it is over the
    limit: the message then sits next to that field, like any other input error."""
    try:
        return await _read_upload(f)
    except HTTPException as exc:
        if exc.status_code != 413:
            raise
        errors[key] = too_big
        return b""


LANDING_DATA = Path(__file__).resolve().parent / "landing.json"


@lru_cache(maxsize=1)
def landing_numbers() -> dict[str, object]:
    """The numbers behind the landing page (``landing.json``, written by docs/figures/fig_landing.py)."""
    return json.loads(LANDING_DATA.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    """The product page: what TAPAK does, for whom, and the numbers behind it."""
    return _page(request, "landing.html", angka=landing_numbers())


@app.get("/beranda", response_class=HTMLResponse)
def beranda(request: Request) -> HTMLResponse:
    """Overview: issued documents, registry state and recent canary queries."""
    from tapak.service import list_workspaces

    s = settings()
    docs = list_workspaces(s)
    alerts = _canary_events(s, docs)
    return _page(request, "beranda.html", title=N_("Beranda"), active="beranda", docs=docs, recent=docs[:5],
                 n_copies=sum(len(m.copies) for m in docs), alerts=alerts, recent_alerts=alerts[:5],
                 registry=_registry_status())


def _canary_events(s: Settings, docs: list) -> list[dict[str, object]]:
    """Canary DNS queries of every issued document, newest first (each with its doc_name).

    The log is read once and matched against the tokens of all documents. Recipient names
    are left out: a canary query is supporting evidence, not an attribution.
    """
    import sqlite3

    from tapak.canary_dns.store import events

    if not s.canary_db.exists():
        return []
    try:
        evs = events(s.canary_db)
    except sqlite3.Error:  # an unreadable log is reported on /registri (check_events_chain)
        return []
    copies = {c.canary_token: (m, c) for m in docs for c in m.copies if c.canary_token}
    alerts = []
    for ev in evs:
        if ev.token in copies:
            m, c = copies[ev.token]
            alerts.append({"seq": c.seq, "time": ev.received_at, "src_ip": ev.src_ip, "qtype": ev.qtype,
                           "doc_name": m.doc_name, "doc": m.doc_hash[:16]})
    alerts.sort(key=lambda a: str(a["time"]), reverse=True)
    return alerts


def _thumbnail(pdf: bytes, dpi: int = 60) -> Response:
    """Page 1 of a PDF as a small PNG, rendered per request and never stored."""
    import pymupdf

    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise HTTPException(404, _("Dokumen tidak memiliki halaman"))
            png = doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(404, _("Pratinjau dokumen tidak dapat dibuat")) from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/dokumen/{doc}/pratinjau.png")
def pratinjau_dokumen(doc: str, ukuran: str = "") -> Response:
    """Page-1 thumbnail of an issued document's master (PDF masters only).

    ?ukuran=kecil renders at 20 dpi (about 165 x 234 px) for the 44 px list thumbnails.
    """
    from tapak.service import load_workspace

    _manifest, master, folder = load_workspace(settings(), doc)
    if not (folder / "induk.pdf").is_file():
        raise HTTPException(404, _("Pratinjau hanya tersedia untuk dokumen PDF"))
    return _thumbnail(master, dpi=20 if ukuran == "kecil" else 60)


@app.get("/terbitkan/{sid}/pratinjau.png")
def pratinjau_staging(sid: str) -> Response:
    """Page-1 thumbnail of the master being prepared in an issuance session."""
    st = _staging(sid)
    master = st.folder / "induk.pdf"
    if not master.is_file():
        raise HTTPException(404, _("Sesi penerbitan tidak ditemukan atau sudah kedaluwarsa."),
                            headers={"X-Tapak-Mulai-Lagi": "1"})
    return _thumbnail(master.read_bytes())


# --- Terbitkan -------------------------------------------------------------------------------


@app.get("/terbitkan", response_class=HTMLResponse)
def terbitkan_page(request: Request) -> HTMLResponse:
    """Step 1 form."""
    return _page(request, "terbitkan.html", title=N_("Terbitkan"), active="terbitkan", eps_choices=EPS_CHOICES,
                 canary_domain=settings().canary_domain, errors={}, values={})


@app.post("/terbitkan/analisis", response_class=HTMLResponse)
async def terbitkan_analisis(
    request: Request,
    dokumen: UploadFile | None = File(None),
    penerima: UploadFile | None = File(None),
    c: str = Form("3"),
    eps: str = Form("1e-6"),
    penerbit: str = Form(""),
    kanari: str = Form(""),
    latar: str = Form("layar"),
    geser: str = Form(""),
) -> HTMLResponse:
    """Validate inputs, analyse the master, show the embedding plan and safe sentences.

    Scanned pages are checked and read with Tesseract here (raster.prepare_scans), before
    the visual gate and the plan, as ``tapak issue`` does.
    """
    from tapak.marker.master import load_master
    from tapak.marker.raster import prepare_scans
    from tapak.marker.render import visual_gate
    from tapak.marker.pdf_shift import ShiftSettings
    from tapak.marker.semantic import scan_candidates

    errors: dict[str, str] = {}
    geser = geser or DEFAULT_GESER
    values = {"c": c, "eps": eps, "penerbit": penerbit, "kanari": kanari, "latar": latar, "geser": geser}
    pdf = await _read_field(dokumen, errors, "dokumen", _("PDF ini terlalu besar (maksimum 40 MB)."))
    csv_bytes = await _read_field(penerima, errors, "penerima", _("CSV ini terlalu besar (maksimum 40 MB)."))
    if not pdf and "dokumen" not in errors:
        errors["dokumen"] = _("Pilih berkas PDF dokumen induk.")
    elif pdf and b"%PDF-" not in pdf[:1024]:
        errors["dokumen"] = _("Berkas ini bukan PDF. Ekspor dokumen ke PDF lalu unggah lagi.")
    recipients: list[Recipient] = []
    if not csv_bytes and "penerima" not in errors:
        errors["penerima"] = _("Pilih berkas CSV daftar penerima.")
    elif csv_bytes:
        try:
            tmp = io.StringIO(csv_bytes.decode("utf-8-sig"))
            rows = list(csv.DictReader(tmp))
            if not rows or "recipient_id" not in rows[0] or "nama" not in rows[0]:
                raise ValueError(_("CSV harus memiliki kolom recipient_id dan nama."))
            staging_csv = settings().data_dir / "staging"
            staging_csv.mkdir(parents=True, exist_ok=True)
            probe = staging_csv / f"probe-{secrets.token_hex(4)}.csv"
            probe.write_bytes(csv_bytes)
            try:
                recipients = read_recipients(probe)
            finally:
                probe.unlink(missing_ok=True)
        except (ValueError, UnicodeDecodeError) as exc:
            errors["penerima"] = (i18n.translate_text(str(exc)) if isinstance(exc, ValueError)
                                  else _("CSV harus berenkode UTF-8."))
    c_text = c.strip()
    c = int(c_text) if c_text.isdigit() else 0  # type: ignore[assignment]
    if not 1 <= c <= 10:  # type: ignore[operator]
        errors["c"] = _("Ukuran koalisi harus bilangan bulat antara 1 dan 10.")
    if eps not in {e for e, _ in EPS_CHOICES}:
        errors["eps"] = _("Pilih salah satu tingkat peluang tuduhan salah.")
    try:
        # No profile name is longer than 5 characters: a crafted long value stays unknown and
        # its echo in the message stays short.
        background = background_profile(latar[:32])
    except ValueError as exc:
        errors["latar"] = _sentence(i18n.translate_text(str(exc)))
    if geser not in SCHEME_CHOICES:
        errors["geser"] = _("Pilih skema geser v1 atau v2.")
    master = None
    if pdf and "dokumen" not in errors:
        try:
            master = await run_in_threadpool(load_master, pdf)
            if not master.scans and not list(master.layout.words()):
                errors["dokumen"] = _(NOTHING_TO_MARK)
        except Exception:  # noqa: BLE001 - any parse failure is a user-facing input error
            errors["dokumen"] = _("PDF tidak dapat dibaca.")
    existing = ""  # key of the already issued document: the error links to Lacak with it preselected
    if master is not None and "dokumen" not in errors:
        from tapak.service import workspace_dir

        if (workspace_dir(settings(), master.doc_hash) / "manifest.json").exists():
            errors["dokumen"] = _("Dokumen ini sudah pernah diterbitkan.")
            existing = master.doc_hash[:16]
    if errors:
        return _step1_errors(request, errors, values, kanari, existing)
    assert master is not None
    scan = scan_boxes = None
    if master.scans:
        # Resolution and image checks, then the word boxes (Tesseract, a few seconds per page).
        # OcrUnavailable (no Tesseract) is a RuntimeError; its message is shown as written.
        try:
            scan, scan_boxes = await run_in_threadpool(prepare_scans, master)
        except (ValueError, RuntimeError) as exc:
            errors["dokumen"] = _sentence(i18n.translate_text(str(exc)))
            return _step1_errors(request, errors, values, kanari, "")
    gate = await run_in_threadpool(visual_gate, master)
    if not gate.passed:
        if gate.scan_identical is False:
            errors["dokumen"] = _(SCAN_GATE_LINES[False])
        else:
            errors["dokumen"] = _("Penerbitan ditolak: TAPAK tidak dapat menggambar ulang dokumen ini tanpa "
                                  "perubahan yang terlihat (selisih maksimum %(n)s tingkat abu-abu).", n=gate.max_diff)
        return _step1_errors(request, errors, values, kanari, "")

    _expire_staging()
    sid = secrets.token_hex(8)
    folder = settings().data_dir / "staging" / sid
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(dokumen.filename or "dokumen.pdf").name  # type: ignore[union-attr]
    (folder / "induk.pdf").write_bytes(pdf)
    issue_settings = IssueSettings(c=c, eps=float(eps), canary_domain=kanari.strip() or None, background=background,
                                   shift=ShiftSettings.for_scheme(SCHEME_CHOICES[geser]))
    st = Staging(sid, folder, name, recipients, issue_settings, penerbit.strip() or "operator", latar=latar,
                 geser=geser, scan=scan, scan_boxes=scan_boxes)
    st.candidates = scan_candidates(master)
    st.units = [u for u, reasons in st.candidates if not reasons]
    st.plan = await run_in_threadpool(_plan_summary, master, issue_settings, len(recipients), scan)
    with _LOCK:
        _STAGING[sid] = st
    return _page(request, "_rencana.html", st=st, gate=gate)


def _step1_errors(request: Request, errors: dict[str, str], values: dict[str, object], kanari: str,
                  existing: str) -> HTMLResponse:
    """Step-1 validation errors: out-of-band error slots for htmx (the form keeps its files),
    the whole form otherwise."""
    if request.headers.get("HX-Request"):
        resp = _page(request, "_langkah1_galat.html", errors=errors, existing=existing)
        resp.headers["HX-Reswap"] = "none"
        return resp
    return _page(request, "_langkah1.html", eps_choices=EPS_CHOICES, errors=errors, values=values,
                 canary_domain=kanari)


def _expire_staging() -> None:
    """Drop issuance sessions (and their copy of the master) idle for more than STAGING_TTL_S."""
    root = settings().data_dir / "staging"
    now = time.time()
    with _LOCK:
        for sid, st in list(_STAGING.items()):
            stale = not st.folder.exists() or (now - st.last_used > STAGING_TTL_S and not st.issuing)
            if stale:
                shutil.rmtree(st.folder, ignore_errors=True)
                _STAGING.pop(sid, None)
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and d.name not in _STAGING and now - d.stat().st_mtime > STAGING_TTL_S:
                shutil.rmtree(d, ignore_errors=True)


def _plan_summary(master, s: IssueSettings, n: int, scan: dict | None = None) -> dict[str, object]:
    """Embedding plan and the exact full-observation threshold this document will get.

    With scanned pages (their word boxes attached by raster.prepare_scans, ``scan`` its
    record) it also gives the mode of every page and counts the word boxes Tesseract found
    there; their text is never read. The master is regrouped for the chosen shift scheme first.
    """
    from tapak.marker.issue import apply_shift_scheme, build_document_plan
    from tapak.marker.raster import page_modes, plan_lines
    from tapak.service import ensure_keys
    from tapak.tardos.accuse import threshold
    from tapak.tardos.code import derive_bias
    from tapak.tardos.params import TardosParams

    params = TardosParams(c=s.c, eps=s.eps, n_max=n, constant=s.constant)  # type: ignore[arg-type]
    secret = ensure_keys(settings(), create_signing_key=False).code_secret
    apply_shift_scheme(master, s.shift.scheme)
    plan = build_document_plan(master, params, secret, s.channels, set(), s.background, shift_scheme=s.shift.scheme)
    p = derive_bias(secret, master.doc_hash, params)
    pages = len(master.layout.pages)
    out: dict[str, object] = {"params": params, "summary": plan.summary(), "threshold": threshold(p, params.eps1),
                              "pages": pages, "words": sum(1 for _ in master.layout.words()),
                              "scan_pages": 0, "all_scanned": False}
    if scan:
        dpi = {int(k): int(d) for k, d in zip(scan["pages"], scan["dpi"])}
        words_on = Counter(w.id[0] for w in master.layout.words())
        out.update(
            scan_pages=len(dpi), text_pages=pages - len(dpi), all_scanned=len(dpi) == pages,
            scan_dpi=sorted(set(dpi.values())),
            scan_words=sum(1 for w in master.shift_layout.words() if w.id[0] in master.scans),
            scan_nums=", ".join(str(k + 1) for k in sorted(dpi)),
            # A page on the text path without a single word (a blank page, or an image page not
            # recognised as a scan) is not called a text page: it has no word to mark.
            modes=[{"mode": mode, "page": k + 1, "dpi": dpi.get(k), "words": bool(words_on[k])}
                   for k, mode in enumerate(page_modes(master))],
            # the first line (page counts) is what the stat tile and the page list show
            scan_lines=plan_lines(scan, pages)[1:])
    return out


def _staging(sid: str) -> Staging:
    """The issuance session ``sid``; every request on it counts as activity."""
    st = _STAGING.get(sid)
    if st is None:
        raise HTTPException(404, _("Sesi penerbitan tidak ditemukan atau sudah kedaluwarsa."),
                            headers={"X-Tapak-Mulai-Lagi": "1"})
    st.last_used = time.time()
    return st


ISSUING_MESSAGE = N_("Penerbitan sedang berjalan. Keputusan tidak dapat diubah lagi; tunggu hasilnya.")


def _review_session(sid: str) -> Staging:
    """The session for a review action: refused (409) once its copies are being issued, so the
    copies and their record are made from the same decisions."""
    st = _staging(sid)
    if st.issuing:
        raise HTTPException(409, _(ISSUING_MESSAGE))
    return st


@contextmanager
def _reviewing(sid: str) -> Iterator[Staging]:
    """_review_session held under _LOCK, for a change to the review state (publishing takes
    its snapshot under the same lock)."""
    with _LOCK:
        yield _review_session(sid)


# --- Terbitkan: word choice (opt-in lexical channel) -------------------------------------------


def _staging_master(st: Staging) -> MasterDocument:
    """The parsed master of an issuance session (parsed once, kept with the session), grouped
    for the chosen shift scheme and with the word boxes of its scanned pages attached as at
    issuance."""
    from tapak.marker.issue import apply_shift_scheme
    from tapak.marker.master import load_master
    from tapak.marker.raster import attach_scan_layout

    if st.master is None:
        master = load_master((st.folder / "induk.pdf").read_bytes())
        apply_shift_scheme(master, st.settings.shift.scheme)
        if st.scan_boxes:
            attach_scan_layout(master, st.scan_boxes)
        st.master = master
    return st.master


def _retype_bits(st: Staging) -> dict[str, int]:
    """Bits that survive retyping as the review stands: approved word-choice points and
    approved semantic variants (what the live counter and the plan tile show)."""
    from tapak.marker.semantic import bits_per_unit

    lex = st.lexical.bits if st.lexical is not None else 0
    sem = sum(bits_per_unit(vs) for vs in st.sets.values())
    return {"lex": lex, "sem": sem, "total": lex + sem}


templates.env.globals["ketik_bits"] = _retype_bits


def _marked_context(point: LexPoint) -> Markup:
    """The point's sentence with its phrase in <mark class="diff"> (the scan writes it in
    square brackets); everything else is escaped."""
    text, phrase = point.context, point.forms[0]
    i = text.find(f"[{phrase}]")
    if i < 0:
        return Markup(escape(text))
    after = text[i + len(phrase) + 2:]
    return Markup(f'{escape(text[:i])}<mark class="diff">{escape(phrase)}</mark>{escape(after)}')


def _point_runs(words: list) -> list[tuple[str, bool]]:
    """A copy row (copy_rows words: text, master word id or None) as runs of (text, is_point)."""
    runs: list[tuple[str, bool]] = []
    for text, wid in words:
        if runs and runs[-1][1] == (wid is None):
            runs[-1] = (runs[-1][0] + " " + text, wid is None)
        else:
            runs.append((text, wid is None))
    return runs


def _sample_line(words: list, other: list) -> Markup:
    """One printed row of a sample copy with its point words marked: <mark class="diff"> where
    the other sample copy shows another form (also said in words for screen readers),
    <mark class="lex-same"> where both agree."""
    theirs = [t for t, point in _point_runs(other) if point]
    out, k = [], 0
    for text, point in _point_runs(words):
        if point:
            if k < len(theirs) and theirs[k] == text:
                out.append(f'<mark class="lex-same">{escape(text)}</mark>')
            else:
                out.append(f'<mark class="diff">{escape(text)}<span class="sr-only"> ({escape(_("berbeda"))})</span></mark>')
            k += 1
        else:
            out.append(str(escape(text)))
    return Markup(" ".join(out))


SAMPLE_LABELS = tuple(f"pratinjau-{i}" for i in range(1, 9))


def _sample_copies(st: Staging, sel: LexicalSelection) -> dict[str, object] | None:
    """The rows holding approved points as two sample copies print them, and the shift bits
    those rows cost.

    The forms come from the slots the issuance plan gives the lexical channel and from
    codewords drawn like a recipient's for a few fixed labels (SAMPLE_LABELS, so the sample
    does not change between clicks); the pair that differs on the most points is shown. The
    rows are lexical.copy_rows, the words copy_text joins. They are a preview only and never
    stored. Recomputed only when the set of approved points changes.
    """
    from tapak.marker import lexical as lx
    from tapak.marker.pdf_shift import build_shift_slots
    from tapak.marker.plan import RETYPE_BAND, plan_key
    from tapak.service import ensure_keys
    from tapak.tardos.code import derive_bias, derive_codeword

    carrying = sel.carrying()
    if not carrying:
        return None
    key = tuple(p.point_id for p in carrying)
    if st.lex_preview is not None and st.lex_preview[0] == key:
        return st.lex_preview[1]
    master = _staging_master(st)
    params = st.plan["params"]
    secret = ensure_keys(settings(), create_signing_key=False).code_secret
    pkey = plan_key(secret, master.doc_hash)
    p = derive_bias(secret, master.doc_hash, params)
    slots = lx.lexical_slots(sel, params.length, pkey, p, RETYPE_BAND)
    choices = [lx.choices_for_codeword(slots, derive_codeword(secret, master.doc_hash, label, p), sel.points)
               for label in SAMPLE_LABELS]

    def differ(pair: tuple[int, int]) -> int:
        return sum(1 for pt in carrying if choices[pair[0]][pt.point_id] != choices[pair[1]][pt.point_id])

    pair = max(itertools.combinations(range(len(choices)), 2), key=differ)  # first best pair: stable
    copies = [lx.copy_rows(master, carrying, choices[i]) for i in pair]
    rows = []
    for rid in sorted(copies[0]):
        a, b = copies[0][rid], copies[1][rid]
        rows.append({"page": rid[0] + 1, "a": _sample_line(a, b), "b": _sample_line(b, a),
                     "same": [t for t, _ in a] == [t for t, _ in b]})
    # the shift layout includes the word boxes of scanned pages, as in the issuance plan
    shift_all = len(build_shift_slots(master.shift_layout, params.length, pkey))
    shift_left = len(build_shift_slots(master.shift_layout, params.length, pkey, sel.shift_excluded_rows()))
    preview = {"differing": [r for r in rows if not r["same"]], "same": [r for r in rows if r["same"]],
               "points": len(carrying), "differ": differ(pair),
               "shift_all": shift_all, "shift_lost": shift_all - shift_left}
    st.lex_preview = (key, preview)
    return preview


def _bare_form(form: str) -> str:
    return form.lower().strip(".,;:!?\"'()")


def _rule_groups(sel: LexicalSelection, lexicon) -> list[dict[str, object]]:
    """Points grouped by lexicon rule (in order of first appearance), with the rule's forms
    and note and the counts its bulk buttons need."""
    from tapak.marker.semantic import STATUS_PENDING, STATUS_REJECTED

    groups: dict[str, dict] = {}
    for pt in sel.points:
        g = groups.get(pt.rule_id)
        if g is None:
            try:
                rule = lexicon.rule(pt.rule_id) if lexicon is not None else None
            except KeyError:
                rule = None
            # "first" names the rule in URLs and element ids (a point id, never a phrase)
            g = groups[pt.rule_id] = {"first": pt.point_id, "forms": rule.forms if rule else pt.forms,
                                      "note": rule.note if rule else "", "example": rule.example if rule else "",
                                      "points": [], "pending": 0, "rejectable": 0}
        # A point draws from fewer forms than its rule when the rule's count is not a power of
        # two: name them then (case and punctuation alone are not worth a line).
        own = {_bare_form(f) for f in pt.forms} != {_bare_form(f) for f in g["forms"]}
        g["points"].append({"p": pt, "context": _marked_context(pt), "own_forms": own})
        g["pending"] += pt.status == STATUS_PENDING
        g["rejectable"] += pt.status != STATUS_REJECTED
    return list(groups.values())


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _keep_units(text: str) -> str:
    """A number and the unit after it (bit, kata) never break across lines."""
    return re.sub(r"(\d) (bits?|kata|words?)\b", "\\1\u00a0\\2", text)


def _lexical_view(st: Staging) -> dict[str, object]:
    """Everything the word-choice step shows: lexicon state, rule groups, counter, verdict,
    refusal counts (categories only, never document words) and the two sample copies."""
    from tapak.marker import lexical as lx

    sel = st.lexical
    bits = _retype_bits(st)
    view: dict[str, object] = {"sel": sel, "bits": bits, "lexicon": None, "lexicon_title": "", "lexicon_error": "",
                               "lone_bits": lx.LONE_LEAKER_BITS, "lone_words": lx.format_count(lx.LONE_LEAKER_WORDS),
                               # the print profile marks a document meant for paper: say what word choice costs there
                               "print_note": _keep_units(_sentence(i18n.translate_text(lx.PRINT_NOTE)))
                               if st.latar == "cetak" else ""}
    try:
        lexicon = view["lexicon"] = lx.load_lexicon(sel.lexicon if sel is not None else lx.DEFAULT_LEXICON)
        # "naskah_dinas_v1" reads "naskah dinas" (the version is shown on its own)
        view["lexicon_title"] = re.sub(r"_v\d+$", "", lexicon.name).replace("_", " ")
    except lx.LexiconError as exc:
        view["lexicon_error"] = i18n.translate_text(str(exc))
    if sel is None:
        return view
    pending, total = len(sel.pending()), len(sel.points)
    enough = bits["total"] >= lx.LONE_LEAKER_BITS
    if not total:
        status = _("Tidak ada titik pilihan kata di dokumen ini. Salinan diterbitkan tanpa kanal pilihan kata.")
    else:
        status = " ".join([
            _("%(n)s dari %(total)s titik pilihan kata menunggu tinjauan Anda.", n=pending, total=total) if pending
            else _("Semua titik pilihan kata sudah ditinjau."),
            _("%(lex)s bit pilihan kata + %(sem)s bit varian kalimat.", lex=bits["lex"], sem=bits["sem"]),
            _("Cukup untuk satu pembocor.") if enough else _("Belum cukup untuk satu pembocor.")])
    view.update(
        groups=_rule_groups(sel, view["lexicon"]), pending=pending, total=total,
        # Body words still to add use the density of the points not rejected (the table average
        # when there are none).
        verdict=_keep_units(_sentence_case(i18n.translate_text(
            lx.capacity_verdict(bits["total"], sel.body_words or None, sel.candidate_bits or None)))),
        enough=enough,
        refused=[(_sentence_case(i18n.translate_text(c)), n)
                 for c, n in sorted(sel.refused.items(), key=lambda kv: (-kv[1], kv[0]))],
        refused_total=sum(sel.refused.values()),
        preview=_sample_copies(st, sel),
        status=status)
    return view


templates.env.globals["leksikal_view"] = _lexical_view


def _lexical_page(request: Request, st: Staging, **kw: object) -> HTMLResponse:
    """The review section after a word-choice action; the live region reads its new state."""
    return _page(request, "_semantik.html", oob=True, st=st, lex_announce=True, **kw)


def _lexical_or_400(st: Staging) -> LexicalSelection:
    if st.lexical is None:
        raise HTTPException(400, _("Permintaan tidak valid"))
    return st.lexical


@app.post("/terbitkan/{sid}/leksikal", response_class=HTMLResponse)
def terbitkan_leksikal(request: Request, sid: str) -> HTMLResponse:
    """Opt in: scan the master for word-choice points (each then awaits the issuer's review)."""
    from tapak.marker import lexical as lx

    with _reviewing(sid) as st:
        if not st.pdf:
            raise HTTPException(400, _("Pilihan kata hanya tersedia untuk dokumen induk PDF."))
        if st.all_scanned:  # no text layer: the scan would find nothing
            why = _(SCAN_ALL_NA)
            raise HTTPException(400, _("Pilihan kata %(why)s.", why=why[:1].lower() + why[1:]))
        scanned = st.lexical is not None
    if not scanned:
        try:
            found = lx.scan_candidates(_staging_master(st), lx.load_lexicon())
        except lx.LexiconError as exc:
            return _lexical_page(request, st, lex_error=_("Pemindaian tidak dapat dilakukan: %(why)s",
                                                          why=i18n.translate_text(str(exc))))
        with _reviewing(sid):
            if st.lexical is None:  # a second scan request does not replace the first one's decisions
                st.lexical = found
                st.lex_preview = None
    return _lexical_page(request, st, lex_focus=True)


@app.post("/terbitkan/{sid}/leksikal/batal", response_class=HTMLResponse)
def terbitkan_leksikal_batal(request: Request, sid: str) -> HTMLResponse:
    """Opt out again: drop the scan and every decision (copies are issued without the channel)."""
    with _reviewing(sid) as st:
        st.lexical = None
        st.lex_preview = None
    return _lexical_page(request, st, lex_focus=True)


@app.post("/terbitkan/{sid}/leksikal/aturan/{point_id}/{status}", response_class=HTMLResponse)
def terbitkan_leksikal_aturan(request: Request, sid: str, point_id: str, status: str,
                              konfirmasi: str = Form("")) -> HTMLResponse:
    """Decide every point of the rule of ``point_id``: reject all of them, or approve the
    pending ones. The rule is named by one of its points, so request URLs (and the server's
    access log) never carry a lexicon phrase found in the document.

    Approval in one action is an explicit choice after reading each sentence, so it needs
    konfirmasi=ya (the button asks first), as the CLI needs --ya. Rejecting needs none.
    """
    from tapak.marker.semantic import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED

    with _reviewing(sid) as st:
        sel = _lexical_or_400(st)
        try:
            rule_id = sel.point(point_id).rule_id
        except KeyError:
            raise HTTPException(400, _("Permintaan tidak valid")) from None
        points = [p for p in sel.points if p.rule_id == rule_id]
        if status not in (STATUS_APPROVED, STATUS_REJECTED):
            raise HTTPException(400, _("Permintaan tidak valid"))
        if status == STATUS_APPROVED:
            if konfirmasi != "ya":
                raise HTTPException(400, _("Persetujuan sekaligus memerlukan konfirmasi. Baca setiap kalimatnya, lalu "
                                           "setujui satu per satu atau konfirmasi persetujuan sekaligus."))
            points = [p for p in points if p.status == STATUS_PENDING]
        for p in points:
            sel.set_status(p.point_id, status)
    return _lexical_page(request, st)


@app.post("/terbitkan/{sid}/leksikal/{point_id}/{status}", response_class=HTMLResponse)
def terbitkan_leksikal_putusan(request: Request, sid: str, point_id: str, status: str) -> HTMLResponse:
    """Record the issuer's decision for one word-choice point."""
    from tapak.marker.semantic import STATUSES

    with _reviewing(sid) as st:
        sel = _lexical_or_400(st)
        if status not in STATUSES:
            raise HTTPException(400, _("Permintaan tidak valid"))
        try:
            sel.set_status(point_id, status)
        except ValueError as exc:
            raise HTTPException(400, i18n.translate_text(str(exc))) from exc
    return _lexical_page(request, st)


@app.post("/terbitkan/{sid}/varian", response_class=HTMLResponse)
async def terbitkan_varian(request: Request, sid: str) -> HTMLResponse:
    """Generate variants (local LLM) for the sentences the issuer selected."""
    from tapak.llm.provider import get_provider
    from tapak.marker.master import load_master
    from tapak.marker.semantic import generate_variant_set

    st = _review_session(sid)
    form = await request.form()
    chosen = set(form.getlist("unit"))
    s = settings()
    kwargs = {}
    if s.llm_provider == "llamacpp":
        kwargs = {"model_path": s.llm_model_path or None, "server_url": s.llm_server_url}
    def _generate() -> dict:
        provider = get_provider(s.llm_provider, **kwargs)
        master = load_master((st.folder / "induk.pdf").read_bytes())
        return {u.unit_id: generate_variant_set(master, u, provider) for u in st.units if u.unit_id in chosen}

    try:
        generated = await run_in_threadpool(_generate)
    except (RuntimeError, ValueError) as exc:
        return _page(request, "_semantik.html", oob=True, st=st,
                     block_error=_("Varian tidak dapat dibuat: %(why)s", why=i18n.translate_text(str(exc))))
    with _reviewing(sid):
        for uid, vs in generated.items():  # keep reviewer decisions for variants whose text is unchanged
            prev = st.sets.get(uid)
            if prev is None:
                continue
            decided = {t: st_ for t, st_ in zip(prev.variants[1:], prev.status[1:]) if st_ != "menunggu"}
            for i, text in enumerate(vs.variants[1:], start=1):
                if text in decided:
                    vs.set_status(i, decided[text])
        st.sets = generated
    return _page(request, "_semantik.html", oob=True, st=st)


@app.post("/terbitkan/{sid}/varian/{unit_id}/{index}/{status}", response_class=HTMLResponse)
def terbitkan_putusan(request: Request, sid: str, unit_id: str, index: int, status: str) -> HTMLResponse:
    """Record a reviewer decision for one variant."""
    with _reviewing(sid) as st:
        vs = st.sets.get(unit_id)
        if vs is None or status not in ("disetujui", "ditolak", "menunggu"):
            raise HTTPException(400, _("Permintaan tidak valid"))
        try:
            vs.set_status(index, status)
        except ValueError as exc:
            raise HTTPException(400, i18n.translate_text(str(exc))) from exc
    return _page(request, "_semantik.html", oob=True, st=st)


@app.post("/terbitkan/{sid}/varian/{unit_id}/semua", response_class=HTMLResponse)
def terbitkan_setujui_semua(request: Request, sid: str, unit_id: str) -> HTMLResponse:
    """Approve every pending variant of one sentence (still an explicit reviewer decision)."""
    from tapak.marker.semantic import bulk_approval_allowed

    with _reviewing(sid) as st:
        vs = st.sets.get(unit_id)
        if vs is None:
            raise HTTPException(400, _("Permintaan tidak valid"))
        if not bulk_approval_allowed(vs):
            raise HTTPException(400, _("Varian dari model bahasa harus disetujui satu per satu."))
        for i in vs.pending():
            vs.set_status(i, "disetujui")
    return _page(request, "_semantik.html", oob=True, st=st)


def _review_error(request: Request, st: "Staging", message: str) -> HTMLResponse:
    """A publish failure shown inside the review section; the plan and the decisions stay."""
    resp = _page(request, "_semantik.html", oob=True, st=st, block_error=message)
    resp.headers["HX-Retarget"] = "#semantik"
    resp.headers["HX-Reswap"] = "innerHTML show:#semantik-galat:center"
    return resp


@app.post("/terbitkan/{sid}/terbitkan", response_class=HTMLResponse)
def terbitkan_eksekusi(request: Request, sid: str) -> HTMLResponse:
    """Issue the copies (blocked while any variant or word-choice point awaits review).

    The copies are issued from a snapshot of the decisions taken under _LOCK, and review
    actions are refused until issuance ends, so the copies, the manifest and leksikal.json
    always describe the same choices.
    """
    with _LOCK:
        st = _review_session(sid)  # also refuses a second publish while the first one runs
        sets = copy.deepcopy(st.sets)
        lexical = LexicalSelection.from_dict(st.lexical.to_dict()) if st.lexical is not None else None
        waiting = lexical.pending() if lexical is not None else []
        st.issuing = not waiting
    if waiting:
        # The service would refuse it too, but its message names point ids and the CLI; the
        # list shows points by number.
        shown = ", ".join(str(int(pid[1:]) + 1) for pid in waiting[:10]) + (" ..." if len(waiting) > 10 else "")
        return _review_error(request, st, _("Penerbitan diblokir: %(n)s titik pilihan kata masih menunggu keputusan "
                                            "(titik %(shown)s). Setujui atau tolak setiap titik terlebih dahulu.",
                                            n=len(waiting), shown=shown))
    try:
        return _issue(request, st, sets, lexical)
    finally:
        st.issuing = False


def _issue(request: Request, st: Staging, sets: dict, lexical: LexicalSelection | None) -> HTMLResponse:
    """Issue the copies of a session from its snapshot of the review decisions."""
    from tapak.marker.lexical import LONE_LEAKER_BITS, capacity_verdict
    from tapak.marker.semantic import IssuanceBlocked
    from tapak.service import WorkspaceBusy, issue_document

    sel = None
    if sets:
        units = [u for u in st.units if u.unit_id in sets]
        sel = SemanticSelection(units, list(sets.values()))
    if lexical is not None and not lexical.carrying():  # every point rejected: issued as without the channel
        lexical = None
    try:
        out = issue_document(settings(), st.folder / "induk.pdf", st.recipients, st.settings, st.issuer,
                             semantic=sel, doc_name=st.doc_name, lexical=lexical, latar=st.latar)
    except (IssuanceBlocked, WorkspaceBusy) as exc:
        return _review_error(request, st, i18n.translate_text(str(exc)))
    except (ValueError, RuntimeError) as exc:
        return _review_error(request, st, _("Penerbitan gagal: %(why)s", why=i18n.translate_text(str(exc))))
    except FileExistsError:
        from tapak.marker.layout import sha256_hex

        key = sha256_hex((st.folder / "induk.pdf").read_bytes())[:16]
        return _page(request, "_galat.html", message=_("Dokumen ini sudah pernah diterbitkan. Buka halaman Lacak "
                                                       "untuk dokumen tersebut, atau mulai lagi dengan dokumen lain."),
                     restart=True, lacak=key)
    st.issued_doc = out.manifest.doc_hash
    shutil.rmtree(st.folder, ignore_errors=True)
    with _LOCK:
        _STAGING.pop(st.sid, None)
    retype = None
    if lexical is not None and out.manifest.lexical_digest:
        # Distinct band positions, as the CLI reports them (issuance refuses a band too small).
        summary = out.manifest.plan_summary
        lex_bits = summary.get("lexical", {}).get("positions", 0)
        sem_bits = summary.get("semantic", {}).get("positions", 0)
        verdict = capacity_verdict(lex_bits + sem_bits, lexical.body_words or None, lex_bits or None)
        retype = {"lex": lex_bits, "sem": sem_bits, "enough": lex_bits + sem_bits >= LONE_LEAKER_BITS,
                  "verdict": _keep_units(_sentence_case(i18n.translate_text(verdict)))}
    resp = _page(request, "_hasil_terbit.html", out=out, manifest=out.manifest, retype=retype,
                 scan=_issued_scan_view(out))
    resp.headers["HX-Trigger"] = "registri-berubah"  # the sidebar reloads its registry state
    return resp


def _issued_scan_view(out) -> dict[str, object] | None:
    """What the result shows about scanned pages, as ``tapak issue`` prints it: the page
    modes and channels (raster.plan_lines), the scan gate, and the copy sizes in MB measured
    on the files (the page images are stored without lossy compression). None without
    scanned pages."""
    import pymupdf

    from tapak.marker.raster import plan_lines

    m = out.manifest
    if not m.scan:
        return None
    master = out.folder / "induk.pdf"
    with pymupdf.open(master) as doc:
        pages = doc.page_count
    sizes = [(out.folder / "salinan" / c.file).stat().st_size / 1e6 for c in m.copies]
    gate = SCAN_GATE_LINES.get(m.gate.get("scan_identical"))
    return {"lines": plan_lines(m.scan, pages), "gate": gate and _(gate, n=RASTER_GATE_MAX_DIFF),
            "mean_mb": sum(sizes) / len(sizes), "max_mb": max(sizes), "master_mb": master.stat().st_size / 1e6}


@app.get("/dokumen/{doc}/salinan.zip")
def unduh_zip(doc: str) -> StreamingResponse:
    """All copies of a document as one ZIP."""
    from tapak.service import load_workspace

    manifest, _master, folder = load_workspace(settings(), doc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in manifest.copies:
            z.write(_copy_path(folder, c.file), c.file)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": _attachment(Path(manifest.doc_name).stem + "_salinan.zip")})


def _attachment(name: str) -> str:
    """Content-Disposition for a download named after an uploaded file: an ASCII fallback
    (headers are latin-1; quotes and backslashes removed) plus the exact UTF-8 name (RFC 5987)."""
    ascii_name = " ".join("".join(ch for ch in name if " " <= ch <= "~" and ch not in '"\\').split()) or "salinan.zip"
    return f"attachment; filename=\"{ascii_name}\"; filename*=utf-8''{quote(name, safe='')}"


@app.get("/dokumen/{doc}/salinan/{seq}")
def unduh_salinan(doc: str, seq: int) -> FileResponse:
    """One copy, looked up by its sequence number (never by a client-supplied path)."""
    from tapak.service import load_workspace

    manifest, _master, folder = load_workspace(settings(), doc)
    match = [c for c in manifest.copies if c.seq == seq]
    if not match:
        raise HTTPException(404, _("Salinan tidak ditemukan"))
    return FileResponse(_copy_path(folder, match[0].file), filename=match[0].file)


def _copy_path(folder: Path, name: str) -> Path:
    """A copy's file inside the workspace; a manifest naming anything else is refused."""
    if (not name or name != Path(name).name or name.startswith(".")
            or Path(name).suffix.lower() not in (".pdf", ".docx")):  # never the manifest or a key
        raise HTTPException(400, _("Nama berkas salinan di catatan penerbitan tidak valid"))
    path = (folder / "salinan" / name).resolve()
    if path.parent != (folder / "salinan").resolve() or not path.is_file():
        raise HTTPException(404, _("Berkas salinan tidak ditemukan"))
    return path


# --- Lacak ----------------------------------------------------------------------------------


@app.get("/lacak", response_class=HTMLResponse)
def lacak_page(request: Request, dokumen: str = "") -> HTMLResponse:
    """Evidence form; ?dokumen=<16-character key> preselects that document."""
    from tapak.service import list_workspaces

    key = dokumen.strip().lower()[:16]
    selected = key if re.fullmatch(r"[0-9a-f]{16}", key) else ""
    return _page(request, "lacak.html", title=N_("Lacak"), active="lacak", docs=list_workspaces(settings()),
                 errors={}, selected=selected)


@app.post("/lacak", response_class=HTMLResponse)
async def lacak_run(
    request: Request,
    dokumen: str = Form(""),
    bukti: list[UploadFile] | None = File(None),
    teks: str = Form(""),
) -> HTMLResponse:
    """Run the trace and show the attribution (several evidence files are fused)."""
    from tapak.decoder.trace import TraceError, check_evidence_types
    from tapak.service import list_workspaces, trace_evidence

    # A file that is too large or of an unknown type is reported next to the file field
    # (berkas-err); missing evidence (bukti-err) concerns the file and the text field alike.
    errors: dict[str, str] = {}
    items: list[tuple[str, bytes]] = []
    too_big = _("Bukti terlalu besar (maksimum 40 MB seluruhnya). Pilih lebih sedikit berkas atau foto yang lebih kecil.")
    total = 0
    for f in bukti or []:
        content = await _read_field(f, errors, "berkas", too_big)
        total += len(content)
        if "berkas" in errors or total > MAX_UPLOAD:
            errors["berkas"], items = too_big, []
            break
        if content:
            items.append((Path(f.filename or "bukti").name, content))
    if not items and teks.strip() and "berkas" not in errors:
        items = [("teks_tempel.txt", teks.encode("utf-8"))]
    for item_name, _content in items:
        try:
            check_evidence_types([item_name])
        except TraceError:
            errors["berkas"] = _("%(name)s: jenis berkas tidak dikenal. Unggah foto, tangkapan layar, PDF, DOCX, atau TXT.",
                                 name=item_name)
            break
    data, name = (items[0][1], items[0][0]) if items else (b"", "")
    if not dokumen:
        errors["dokumen"] = _("Pilih dokumen yang diduga bocor.")
    if not data and "berkas" not in errors:
        errors["bukti"] = _("Unggah foto, tangkapan layar, PDF, atau DOCX, atau tempel teksnya.")
    if errors:
        resp = _page(request, "_lacak_form.html", docs=list_workspaces(settings()), errors=errors,
                     selected=dokumen)
        resp.headers["HX-Retarget"] = "#form-lacak"
        resp.headers["HX-Reswap"] = "innerHTML"
        return resp
    def run() -> object:
        with _TRACE_SLOTS:
            return trace_evidence(settings(), dokumen, name, data, None, items[1:])

    try:
        outcome = await run_in_threadpool(run)
    except (TraceError, ValueError, FileNotFoundError, RuntimeError) as exc:
        # a refusal already says so ("pelacakan ditolak ..."): not "tidak dapat dilakukan: pelacakan ditolak"
        refused = str(exc).startswith("pelacakan ditolak")
        text = _public_text(exc)
        message = _sentence(text) if refused else _("Pelacakan tidak dapat dilakukan: %(reason)s", reason=text)
        return _page(request, "_galat.html", message=message)
    return _page(request, "_hasil_lacak.html", **_trace_view(outcome))


def _trace_view(outcome: object) -> dict[str, object]:
    """Template values of a trace result (``_hasil_lacak.html``); the outcome is kept for its
    berita acara under the returned ``tid``."""
    from tapak.decoder.report import make_redactor
    from tapak.decoder.trace import SCAN_SHIFT_SKIPPED

    tid = secrets.token_hex(8)
    with _LOCK:
        _TRACES[tid] = outcome
        while len(_TRACES) > 50:
            _TRACES.pop(next(iter(_TRACES)))
    a = outcome.attribution
    # As in the berita acara: file names and notes never identify a copy that is not named at
    # some stage. A copy named at a later stage is shown with its stage (tahap_lanjut).
    named = a.named_seqs
    redact = make_redactor((c.copy for c in a.candidates if c.copy.seq not in named), named)
    later = {c.copy.seq: (st, c) for st in a.stages for c in st.accused}
    # A document with scanned pages: a sentence under the channel table says whether the shift
    # channel covered them (it does not when their word boxes could not be found again as at
    # issuance; the note with the reason stands next to the verdict).
    shift_scan = None
    if getattr(getattr(outcome.ctx, "manifest", None), "scan", None):
        if any(str(n).startswith(SCAN_SHIFT_SKIPPED) for n in a.notes):
            shift_scan = _("Kanal geser tidak membaca halaman pindaian (lihat peringatan di atas); pola latar halaman "
                           "itu tetap dibaca.")
        elif any(ch.channel == "geser" for ch in a.channels):
            shift_scan = _("Kanal geser mencakup halaman pindaian: kotak katanya dibaca ulang dengan Tesseract dan "
                           "cocok dengan catatan penerbitan.")
    identified = a.verdict == VERDICT_IDENTIFIED
    return dict(o=outcome, a=a, tid=tid, identified=identified, redact=redact, tahap_lanjut=later,
                eps_label=_eps_label(a.threshold.eps), shift_scan=shift_scan, v=_verdict_notes(outcome, a, identified, redact))


def _eps_label(eps: float) -> str:
    """'1 dari 1.000.000' (1 in 1,000,000) for the offered choices and any other 1/n; else the number."""
    for value, label in EPS_CHOICES:
        if abs(float(value) - eps) <= 1e-9 * eps:
            return _(label)
    n = 1.0 / eps
    if abs(n - round(n)) < 1e-6 * n:
        return _("1 dari %(n)s", n=i18n.localize(format_number(round(n), 0)))
    return i18n.localize(format_number(eps, 6))


_REPORTS: dict[tuple[str, str], bytes] = {}  # (trace id, language) -> berita acara: a preview and the download agree


def _report_pdf(tid: str, lang: str | None = None) -> bytes:
    """The berita acara of trace ``tid`` in ``lang`` (the page language by default), made once
    (the newest 10 are kept). The English one is a rendition; the Indonesian one is official."""
    from tapak.service import write_report

    outcome = _TRACES.get(tid)
    if outcome is None:
        raise HTTPException(404, _("Hasil pelacakan tidak ditemukan; jalankan pelacakan lagi"))
    key = (tid, lang or i18n.current())
    pdf = _REPORTS.get(key)
    if pdf is None:
        token = i18n.use(key[1])
        try:
            pdf = write_report(outcome)  # type: ignore[arg-type]
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(500, _("Berita acara tidak dapat dibuat: %(reason)s",
                                       reason=i18n.translate_text(str(exc)))) from exc
        finally:
            i18n.reset(token)
        with _LOCK:
            _REPORTS[key] = pdf
            while len(_REPORTS) > 10:
                _REPORTS.pop(next(iter(_REPORTS)))
    return pdf


@app.get("/lacak/{tid}/berita-acara.pdf")
def berita_acara(tid: str, asli: int = 0) -> Response:
    """The forensic report of a trace, in the page language; ``asli=1`` gives the Indonesian
    original (the official form) from an English page."""
    lang = "id" if asli else i18n.current()
    name = f"berita_acara_{tid}.pdf" if lang == "id" else f"berita_acara_{tid}_{lang}.pdf"
    return Response(_report_pdf(tid, lang), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- Demo ----------------------------------------------------------------------------------

_DEMO_LOCK = threading.Lock()   # one sandbox issuance at a time; the next visitor waits for it
_DEMO_LEAKS: dict[str, dict[str, object]] = {}  # leak id -> visitor, name, bytes, copy, medium (newest 40)


def _visitor(request: Request) -> str:
    return request.state.demo_visitor


def _demo_leak(request: Request, lid: str) -> dict[str, object] | None:
    """A simulated leak of this visitor; another visitor's leak is not found."""
    item = _DEMO_LEAKS.get(lid)
    return item if item is not None and item["visitor"] == _visitor(request) else None


def _demo_state(request: Request, leak_id: str = "", result: dict[str, object] | None = None,
                seconds: float | None = None, baru: int | None = None, **kw: object) -> dict[str, object]:
    """Template values of the guided demo (``_demo_alur.html``): the sandbox issuance, the
    simulated leak and the trace result, whichever exist so far. ``baru`` is the step the
    request has just opened (it enters with an animation; a page load opens none)."""
    from tapak.web.demo_web import MEDIA, demo_manifest

    m = demo_manifest(settings(), _visitor(request))
    leak = _demo_leak(request, leak_id) if leak_id else None
    if leak is not None and m is not None and leak["doc"] != m.doc_hash:
        leak = None  # a leak of an earlier sandbox issuance
    step = 1 if m is None else 2 if leak is None else 3 if result is None else 4
    return dict(m=m, media=MEDIA, leak=leak, leak_id=leak_id if leak else "", hasil=result, issue_seconds=seconds,
                langkah=step, baru=baru if baru == step else None, **kw)


def _demo_plot(a) -> dict[str, object] | None:
    """The score strip of the demo's result: every copy's score and the threshold as positions
    (0..1) on one scale. Named copies carry their number; the others are anonymous dots, spread
    over four lanes so that close scores do not hide each other."""
    import math

    if not a.candidates:
        return None
    named = set(a.named_seqs)
    z = a.threshold.threshold if math.isfinite(a.threshold.threshold) else None
    scores = [c.score for c in a.candidates]
    lo = min(0.0, *scores)
    span = (max(*scores, z or 0.0) - lo) * 1.08 or 1.0
    others = sorted((c for c in a.candidates if c.copy.seq not in named), key=lambda c: c.score)
    dots = [{"x": round((c.score - lo) / span, 4), "lane": i % 4, "seq": None} for i, c in enumerate(others)]
    dots += [{"x": round((c.score - lo) / span, 4), "lane": None, "seq": c.copy.seq}
             for c in a.candidates if c.copy.seq in named]
    return {"dots": dots, "z": None if z is None else round((z - lo) / span, 4),
            "others_max": max((c.score for c in others), default=None)}


def _demo_page(request: Request, **kw: object) -> HTMLResponse:
    return _page(request, "_demo_alur.html", **_demo_state(request, **kw))


@app.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request) -> HTMLResponse:
    """The guided demo: issue the sample to 20 fictional recipients, leak one copy, trace it."""
    return _page(request, "demo.html", **_demo_state(request))


@app.post("/demo/terbitkan", response_class=HTMLResponse)
async def demo_issue(request: Request) -> HTMLResponse:
    """Step 1: a fresh sandbox issuance of the sample nota dinas."""
    from tapak.web.demo_web import issue_demo

    visitor = _visitor(request)

    def run() -> float:
        if not _DEMO_LOCK.acquire(timeout=60):
            raise RuntimeError(_("penerbitan demo lain sedang berjalan; coba lagi sebentar lagi"))
        try:
            return issue_demo(settings(), visitor)[1]
        finally:
            _DEMO_LOCK.release()

    try:
        seconds = await run_in_threadpool(run)
    except (RuntimeError, ValueError, FileExistsError, FileNotFoundError) as exc:
        return _demo_page(request, galat=_("Demo tidak dapat diterbitkan: %(reason)s",
                                            reason=i18n.translate_text(_public_text(exc))))
    with _LOCK:  # leaks of the visitor's earlier sandbox
        for lid in [k for k, v in _DEMO_LEAKS.items() if v["visitor"] == visitor]:
            del _DEMO_LEAKS[lid]
    return _demo_page(request, seconds=seconds, baru=2)


@app.get("/demo/contoh-penerima.csv")
def demo_recipients_csv() -> Response:
    """The fictional sample recipient list, as an example of the CSV the Terbitkan page takes."""
    from tapak.demo import samples_dir

    return Response((samples_dir() / "recipients.csv").read_bytes(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="contoh_penerima.csv"'})


@lru_cache(maxsize=1)
def _demo_master_png() -> bytes:
    from tapak.demo import samples_dir
    from tapak.web.demo_web import SAMPLE, page_png

    return page_png((samples_dir() / SAMPLE).read_bytes(), 60)


@app.get("/demo/induk.png")
def demo_master_preview() -> Response:
    """Page 1 of the sample nota dinas the demo issues (fictional)."""
    return Response(_demo_master_png(), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/demo/salinan/{seq}/pratinjau.png")
def demo_copy_preview(request: Request, seq: int) -> Response:
    """Page 1 of a sandbox copy, small."""
    from tapak.web.demo_web import copy_bytes, demo_manifest, page_png

    m = demo_manifest(settings(), _visitor(request))
    if m is None or not 1 <= seq <= len(m.copies):
        raise HTTPException(404, _("Salinan demo tidak ditemukan"))
    return Response(page_png(copy_bytes(settings(), _visitor(request), m, seq), 60), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/demo/selisih.png")
def demo_difference(request: Request) -> Response:
    """Where sandbox copies 1 and 2 differ (top half of page 1), amplified 40 times."""
    from tapak.web.demo_web import demo_manifest, difference_png

    m = demo_manifest(settings(), _visitor(request))
    if m is None or len(m.copies) < 2:
        raise HTTPException(404, _("Salinan demo tidak ditemukan"))
    return Response(difference_png(settings(), _visitor(request), m, 1, 2), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/demo/bocorkan", response_class=HTMLResponse)
async def demo_leak(request: Request, salinan: int = Form(0), cara: str = Form("")) -> HTMLResponse:
    """Step 2: leak one sandbox copy through a simulated medium."""
    from tapak.web.demo_web import MEDIA, demo_manifest, leak

    visitor = _visitor(request)
    m = demo_manifest(settings(), visitor)
    errors: dict[str, str] = {}
    if m is None:
        return _demo_page(request, galat=_("Terbitkan salinan demo lebih dulu (langkah 1)."))
    if not 1 <= salinan <= len(m.copies):
        errors["salinan"] = _("Pilih penerima yang membocorkan salinannya.")
    if cara not in MEDIA:
        errors["cara"] = _("Pilih cara salinan itu bocor.")
    if errors:
        return _demo_page(request, errors=errors, pilih=salinan, pilih_cara=cara)

    def run() -> tuple[str, bytes]:
        import numpy as np

        return leak(settings(), visitor, m, salinan, cara, np.random.default_rng(secrets.randbits(64)))

    name, data = await run_in_threadpool(run)
    lid = secrets.token_hex(8)
    with _LOCK:
        _DEMO_LEAKS[lid] = {"visitor": visitor, "name": name, "data": data, "seq": salinan, "cara": cara,
                            "doc": m.doc_hash}
        while len(_DEMO_LEAKS) > 40:
            _DEMO_LEAKS.pop(next(iter(_DEMO_LEAKS)))
    return _demo_page(request, leak_id=lid, baru=3)


@app.get("/demo/bukti/{lid}")
def demo_evidence(request: Request, lid: str, unduh: int = 0) -> Response:
    """A simulated leak: a preview image, or with ``unduh=1`` the file itself."""
    from tapak.web.demo_web import evidence_preview

    item = _demo_leak(request, lid)
    if item is None:
        raise HTTPException(404, _("Bukti demo tidak ditemukan; buat bukti baru di langkah 2"))
    name, data = str(item["name"]), bytes(item["data"])  # type: ignore[arg-type]
    if unduh:
        return Response(data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
    body, kind = evidence_preview(name, data)
    return Response(body, media_type=kind, headers={"Cache-Control": "no-store"})


@app.post("/demo/lacak", response_class=HTMLResponse)
async def demo_trace(request: Request, bukti: str = Form("")) -> HTMLResponse:
    """Step 3: trace the simulated leak in the sandbox, like evidence on the Lacak page."""
    from tapak.decoder.trace import TraceError
    from tapak.service import trace_evidence
    from tapak.web.demo_web import demo_manifest, demo_settings

    visitor = _visitor(request)
    m = demo_manifest(settings(), visitor)
    item = _demo_leak(request, bukti)
    if m is None or item is None or item["doc"] != m.doc_hash:
        return _demo_page(request, galat=_("Bukti demo tidak ditemukan. Buat bukti baru di langkah 2."))

    def run() -> object:
        with _TRACE_SLOTS:
            return trace_evidence(demo_settings(settings(), visitor), m.doc_hash, str(item["name"]),
                                  bytes(item["data"]))

    t0 = time.perf_counter()
    try:
        outcome = await run_in_threadpool(run)
    except (TraceError, ValueError, FileNotFoundError, RuntimeError) as exc:
        return _demo_page(request, leak_id=bukti, galat=_("Pelacakan tidak dapat dilakukan: %(reason)s",
                                                           reason=i18n.translate_text(_public_text(exc))))
    view = _trace_view(outcome)
    view["detik"] = time.perf_counter() - t0
    view["plot"] = _demo_plot(view["a"])
    return _demo_page(request, leak_id=bukti, result=view, baru=4)


@app.get("/demo/berita-acara/{tid}.png")
def demo_report_preview(tid: str) -> Response:
    """Page 1 of a demo trace's berita acara, small."""
    from tapak.web.demo_web import page_png

    return Response(page_png(_report_pdf(tid), 50), media_type="image/png", headers={"Cache-Control": "no-store"})


# --- Registri ------------------------------------------------------------------------------


@app.get("/registri", response_class=HTMLResponse)
def registri_page(request: Request) -> HTMLResponse:
    """Registry verification, canary alerts and Merkle export."""
    from tapak.canary_dns.store import check_events_chain
    from tapak.registry.signing import SigningKeyError, normalize_public_key
    from tapak.registry.verify import verify_registry
    from tapak.service import anchor_status, list_workspaces

    s = settings()
    key = _registry_key(s)
    report = key_error = public_key = None
    if s.public_key_path.exists():
        try:
            public_key = normalize_public_key(s.public_key_path.read_text())
        except UnicodeDecodeError:
            key_error = _("isi berkas bukan teks; kunci publik berupa 64 karakter heksadesimal")
        except SigningKeyError as exc:
            key_error = i18n.translate_text(str(exc))
        except OSError as exc:
            key_error = _("berkas tidak dapat dibaca (%(why)s)", why=exc.strerror or exc)
    if public_key and s.registry_path.exists():
        report = verify_registry(s.registry_path, public_key, require_signed=False, anchor_log=s.anchor_log)
        with _LOCK:  # the sidebar of this page reuses the check instead of verifying again
            _REGISTRY_STATUS.update(key=key, value=_report_status(report))
    docs = list_workspaces(s)
    return _page(request, "registri.html", title=N_("Registri"), active="registri", report=report, docs=docs,
                 alerts=_canary_events(s, docs), registry=_registry_status(), public_key=public_key,
                 key_error=key_error, public_key_path=str(s.public_key_path),
                 canary_log=check_events_chain(s.canary_db) if s.canary_db.exists() else None,
                 anchor=anchor_status(s))


@app.get("/registri/status", response_class=HTMLResponse)
def registri_status(request: Request) -> HTMLResponse:
    """The sidebar's registry state (stamp and entry count), reloaded after an issuance."""
    return _page(request, "_status_registri.html")


@app.post("/registri/merkle", response_class=HTMLResponse)
def registri_merkle(request: Request) -> HTMLResponse:
    """Export daily Merkle roots."""
    from tapak.registry.merkle import export_daily_roots

    s = settings()
    files = (export_daily_roots(s.registry_path, s.data_dir / "merkle", include_partial=True)
             if s.registry_path.exists() else [])
    return _page(request, "_merkle.html", files=[Path(f) for f in files or []])


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


__all__ = ["app"]
