"""TAPAK web UI (FastAPI + HTMX). Two entry points: Terbitkan (issue) and Lacak (trace).

Runs locally (bind to 127.0.0.1 or inside the unit's network). Nothing is fetched from or
sent to the internet; HTMX is served from ./static.
"""

from __future__ import annotations

import csv
import html
import io
import secrets
import shutil
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import os
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tapak.config import Settings, load_settings
from tapak.decoder.accuse import VERDICT_IDENTIFIED
from tapak.decoder.report import format_datetime, format_number, format_probability_html, software_version
from tapak.marker.issue import IssueSettings, Recipient, SemanticSelection, read_recipients

HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 40 * 1024 * 1024
CHANNEL_NAMES = {
    "shift": "Geser kata dan baris", "background": "Pola latar", "zw": "Karakter tak terlihat",
    "homoglyph": "Huruf kembar", "semantic": "Varian kalimat", "canary": "Token kanari",
    "geser": "Geser", "latar": "Latar", "teks": "Teks", "semantik": "Semantik",
}
EPS_CHOICES = [("1e-4", "1 dari 10.000"), ("1e-6", "1 dari 1.000.000"), ("1e-8", "1 dari 100.000.000")]


@dataclass
class Staging:
    """An issuance being prepared (before copies exist)."""

    sid: str
    folder: Path
    doc_name: str
    recipients: list[Recipient]
    settings: IssueSettings
    issuer: str
    units: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    sets: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    issued_doc: str | None = None


_STAGING: dict[str, Staging] = {}
_TRACES: dict[str, object] = {}
_LOCK = threading.Lock()
# Image decoding and registration take hundreds of MB each: at most two traces at a time.
_TRACE_SLOTS = threading.BoundedSemaphore(2)

# Files written by the app (masters, copies, manifests) are readable by the operator only.
os.umask(0o077)

STAGING_TTL_S = 2 * 3600
# Host names the app answers to (TrustedHostMiddleware syntax: exact names or "*.domain").
# Add the public name when the app sits behind a reverse proxy, e.g.
# TAPAK_ALLOWED_HOSTS=127.0.0.1,localhost,tapak.satuan.mil
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    "TAPAK_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

app = FastAPI(title="TAPAK", docs_url=None, redoc_url=None, openapi_url=None)
# Host allowlist: a page on another site cannot reach this app through DNS rebinding.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def _same_origin_posts(request: Request, call_next):
    """Refuse state-changing requests sent by another origin (cross-site form posts).

    Accepted: an Origin (or Referer) naming the host the request was sent to, or one of
    ALLOWED_HOSTS (with the same "*.domain" wildcards as the host check; a bare "*" never
    accepts a foreign origin).
    """
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            parts = urlsplit(origin)
            same = parts.netloc.lower() == request.headers.get("host", "").lower()
            if not (same or _host_allowed(parts.hostname or "")):
                return HTMLResponse('<div class="notice notice-error">Permintaan dari asal lain ditolak.</div>',
                                    status_code=403)
    return await call_next(request)


def _host_allowed(host: str) -> bool:
    host = host.lower()
    for pattern in ALLOWED_HOSTS:
        pattern = pattern.lower()
        if pattern == host or (pattern.startswith("*.") and host.endswith(pattern[1:])):
            return True
    return False


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["num"] = lambda v, d=0: format_number(float(v), d)
templates.env.filters["prob"] = lambda p, log10=None: format_probability_html(float(p), log10)
templates.env.filters["waktu"] = lambda v: format_datetime(str(v))
templates.env.globals["channel_name"] = lambda c: CHANNEL_NAMES.get(c, c)
templates.env.globals["inf"] = float("inf")


def _fap(candidate, n_copies: int):
    """False-accusation probability of a named copy, exact even when it underflows a float."""
    import math

    log10 = candidate.log10_false_accusation
    return format_probability_html(candidate.false_accusation_probability, log10 if math.isfinite(log10) else None)


templates.env.globals["fap"] = _fap


def _notice(request: Request, message: str, status: int, restart: bool = False) -> HTMLResponse:
    """An Indonesian error notice. For htmx requests it is placed in the page-level alert
    region (HX-Retarget) so the current form stays intact."""
    link = ' <a class="link" href="/terbitkan">Mulai lagi</a>' if restart else ""
    body = f'<div class="notice notice-error">{html.escape(message)}{link}</div>'
    headers = {"HX-Retarget": "#galat-global", "HX-Reswap": "innerHTML"} if request.headers.get("HX-Request") else {}
    return HTMLResponse(body, status_code=status, headers=headers)


# Messages for errors raised by Starlette itself (its details are English).
_FRAMEWORK_MESSAGES = {
    400: "Permintaan tidak dapat dibaca. Periksa isian dan berkas, lalu kirim lagi.",
    404: "Halaman tidak ditemukan.",
    405: "Tindakan ini tidak tersedia di alamat tersebut.",
    413: "Kiriman terlalu besar (maksimum 40 MB seluruhnya).",
}


@app.exception_handler(FileNotFoundError)
async def _not_found(request: Request, exc: FileNotFoundError) -> HTMLResponse:
    """Missing or invalid documents become a 404 with an Indonesian message, never a 500."""
    return _notice(request, str(exc), 404)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    """HTTP errors (413, 404, 400) as Indonesian notices instead of JSON. TAPAK's own errors
    (fastapi.HTTPException) already carry Indonesian text; Starlette's are replaced."""
    if isinstance(exc, HTTPException):
        message = str(exc.detail)
    elif "maximum size" in str(exc.detail):
        message = "Teks yang ditempel terlalu panjang (maksimum 1 MB). Simpan sebagai berkas .txt lalu unggah."
    else:
        message = _FRAMEWORK_MESSAGES.get(exc.status_code, f"Permintaan ditolak (kode {exc.status_code}).")
    restart = bool(exc.headers and exc.headers.get("X-Tapak-Mulai-Lagi"))
    return _notice(request, message, exc.status_code, restart=restart)


@app.exception_handler(RequestValidationError)
async def _invalid_form(request: Request, exc: RequestValidationError) -> HTMLResponse:
    """A form field of the wrong type (normally caught by the form itself)."""
    fields = sorted({str(e.get("loc", ["", "?"])[-1]) for e in exc.errors()})
    return _notice(request, f"Isian tidak sah: {', '.join(fields)}. Periksa lalu kirim lagi.", 422)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> HTMLResponse:
    """Anything unexpected: a generic Indonesian notice (details stay in the server log)."""
    import logging

    logging.getLogger("tapak.web").exception("kesalahan tak terduga")
    return _notice(request, "Terjadi kesalahan tak terduga di server TAPAK. Coba lagi; bila berulang, periksa log server.", 500)


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
        raise HTTPException(413, "Berkas terlalu besar (maksimum 40 MB)")
    return data


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """Start on the issue page."""
    return RedirectResponse("/terbitkan", status_code=303)


# --- Terbitkan -------------------------------------------------------------------------------


@app.get("/terbitkan", response_class=HTMLResponse)
def terbitkan_page(request: Request) -> HTMLResponse:
    """Step 1 form."""
    return _page(request, "terbitkan.html", title="Terbitkan", active="terbitkan", eps_choices=EPS_CHOICES,
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
) -> HTMLResponse:
    """Validate inputs, analyse the master, show the embedding plan and safe sentences."""
    from tapak.marker.master import load_master
    from tapak.marker.render import visual_gate
    from tapak.marker.semantic import scan_candidates

    errors: dict[str, str] = {}
    values = {"c": c, "eps": eps, "penerbit": penerbit, "kanari": kanari}
    pdf = await _read_upload(dokumen)
    csv_bytes = await _read_upload(penerima)
    if not pdf:
        errors["dokumen"] = "Pilih berkas PDF dokumen induk."
    elif b"%PDF-" not in pdf[:1024]:
        errors["dokumen"] = "Berkas ini bukan PDF. Ekspor dokumen ke PDF lalu unggah lagi."
    recipients: list[Recipient] = []
    if not csv_bytes:
        errors["penerima"] = "Pilih berkas CSV daftar penerima."
    else:
        try:
            tmp = io.StringIO(csv_bytes.decode("utf-8-sig"))
            rows = list(csv.DictReader(tmp))
            if not rows or "recipient_id" not in rows[0] or "nama" not in rows[0]:
                raise ValueError("CSV harus memiliki kolom recipient_id dan nama.")
            staging_csv = settings().data_dir / "staging"
            staging_csv.mkdir(parents=True, exist_ok=True)
            probe = staging_csv / f"probe-{secrets.token_hex(4)}.csv"
            probe.write_bytes(csv_bytes)
            try:
                recipients = read_recipients(probe)
            finally:
                probe.unlink(missing_ok=True)
        except (ValueError, UnicodeDecodeError) as exc:
            errors["penerima"] = str(exc) if isinstance(exc, ValueError) else "CSV harus berenkode UTF-8."
    c_text = c.strip()
    c = int(c_text) if c_text.isdigit() else 0  # type: ignore[assignment]
    if not 1 <= c <= 10:  # type: ignore[operator]
        errors["c"] = "Ukuran koalisi harus bilangan bulat antara 1 dan 10."
    if eps not in {e for e, _ in EPS_CHOICES}:
        errors["eps"] = "Pilih salah satu tingkat peluang tuduhan salah."
    master = None
    if pdf and "dokumen" not in errors:
        try:
            master = await run_in_threadpool(load_master, pdf)
            if not list(master.layout.words()):
                errors["dokumen"] = "PDF ini tidak memiliki lapisan teks (hasil pindai). TAPAK memerlukan PDF teks."
        except Exception:  # noqa: BLE001 - any parse failure is a user-facing input error
            errors["dokumen"] = "PDF tidak dapat dibaca."
    existing = False
    if master is not None and "dokumen" not in errors:
        from tapak.service import workspace_dir

        if (workspace_dir(settings(), master.doc_hash) / "manifest.json").exists():
            errors["dokumen"] = "Dokumen ini sudah pernah diterbitkan."
            existing = True
    if errors:
        return _step1_errors(request, errors, values, kanari, existing)
    assert master is not None
    gate = await run_in_threadpool(visual_gate, master)
    if not gate.passed:
        errors["dokumen"] = ("Penerbitan ditolak: TAPAK tidak dapat menggambar ulang dokumen ini tanpa "
                             f"perubahan yang terlihat (selisih maksimum {gate.max_diff} tingkat abu-abu).")
        return _step1_errors(request, errors, values, kanari, False)

    _expire_staging()
    sid = secrets.token_hex(8)
    folder = settings().data_dir / "staging" / sid
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(dokumen.filename or "dokumen.pdf").name  # type: ignore[union-attr]
    (folder / "induk.pdf").write_bytes(pdf)
    issue_settings = IssueSettings(c=c, eps=float(eps), canary_domain=kanari.strip() or None)
    st = Staging(sid, folder, name, recipients, issue_settings, penerbit.strip() or "operator")
    st.candidates = scan_candidates(master)
    st.units = [u for u, reasons in st.candidates if not reasons]
    st.plan = await run_in_threadpool(_plan_summary, master, issue_settings, len(recipients))
    with _LOCK:
        _STAGING[sid] = st
    return _page(request, "_rencana.html", st=st, gate=gate)


def _step1_errors(request: Request, errors: dict[str, str], values: dict[str, object], kanari: str,
                  existing: bool) -> HTMLResponse:
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
            stale = not st.folder.exists() or now - st.folder.stat().st_mtime > STAGING_TTL_S
            if stale:
                shutil.rmtree(st.folder, ignore_errors=True)
                _STAGING.pop(sid, None)
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and d.name not in _STAGING and now - d.stat().st_mtime > STAGING_TTL_S:
                shutil.rmtree(d, ignore_errors=True)


def _plan_summary(master, s: IssueSettings, n: int) -> dict[str, object]:
    """Embedding plan and the exact full-observation threshold this document will get."""
    from tapak.marker.issue import build_document_plan
    from tapak.service import ensure_keys
    from tapak.tardos.accuse import threshold
    from tapak.tardos.code import derive_bias
    from tapak.tardos.params import TardosParams

    params = TardosParams(c=s.c, eps=s.eps, n_max=n, constant=s.constant)  # type: ignore[arg-type]
    secret = ensure_keys(settings(), create_signing_key=False).code_secret
    plan = build_document_plan(master, params, secret, s.channels, set(), s.background)
    p = derive_bias(secret, master.doc_hash, params)
    return {"params": params, "summary": plan.summary(), "threshold": threshold(p, params.eps1),
            "pages": len(master.layout.pages), "words": sum(1 for _ in master.layout.words())}


def _staging(sid: str) -> Staging:
    st = _STAGING.get(sid)
    if st is None:
        raise HTTPException(404, "Sesi penerbitan tidak ditemukan atau sudah kedaluwarsa.",
                            headers={"X-Tapak-Mulai-Lagi": "1"})
    return st


@app.post("/terbitkan/{sid}/varian", response_class=HTMLResponse)
async def terbitkan_varian(request: Request, sid: str) -> HTMLResponse:
    """Generate variants (local LLM) for the sentences the issuer selected."""
    from tapak.llm.provider import get_provider
    from tapak.marker.master import load_master
    from tapak.marker.semantic import generate_variant_set

    st = _staging(sid)
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
        old = st.sets
        st.sets = await run_in_threadpool(_generate)
        for uid, vs in st.sets.items():  # keep reviewer decisions for variants whose text is unchanged
            prev = old.get(uid)
            if prev is None:
                continue
            decided = {t: st_ for t, st_ in zip(prev.variants[1:], prev.status[1:]) if st_ != "menunggu"}
            for i, text in enumerate(vs.variants[1:], start=1):
                if text in decided:
                    vs.set_status(i, decided[text])
    except (RuntimeError, ValueError) as exc:
        return _page(request, "_semantik.html", oob=True, st=st, block_error=f"Varian tidak dapat dibuat: {exc}")
    return _page(request, "_semantik.html", oob=True, st=st)


@app.post("/terbitkan/{sid}/varian/{unit_id}/{index}/{status}", response_class=HTMLResponse)
def terbitkan_putusan(request: Request, sid: str, unit_id: str, index: int, status: str) -> HTMLResponse:
    """Record a reviewer decision for one variant."""
    st = _staging(sid)
    vs = st.sets.get(unit_id)
    if vs is None or status not in ("disetujui", "ditolak", "menunggu"):
        raise HTTPException(400, "Permintaan tidak valid")
    try:
        vs.set_status(index, status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _page(request, "_semantik.html", oob=True, st=st)


@app.post("/terbitkan/{sid}/varian/{unit_id}/semua", response_class=HTMLResponse)
def terbitkan_setujui_semua(request: Request, sid: str, unit_id: str) -> HTMLResponse:
    """Approve every pending variant of one sentence (still an explicit reviewer decision)."""
    st = _staging(sid)
    vs = st.sets.get(unit_id)
    if vs is None:
        raise HTTPException(400, "Permintaan tidak valid")
    for i in vs.pending():
        vs.set_status(i, "disetujui")
    return _page(request, "_semantik.html", oob=True, st=st)


@app.post("/terbitkan/{sid}/terbitkan", response_class=HTMLResponse)
def terbitkan_eksekusi(request: Request, sid: str) -> HTMLResponse:
    """Issue the copies (blocked while any variant awaits review)."""
    from tapak.marker.semantic import IssuanceBlocked
    from tapak.service import issue_document

    st = _staging(sid)
    s = settings()
    sel = None
    if st.sets:
        units = [u for u in st.units if u.unit_id in st.sets]
        sel = SemanticSelection(units, list(st.sets.values()))
    try:
        out = issue_document(s, st.folder / "induk.pdf", st.recipients, st.settings, st.issuer,
                             semantic=sel, doc_name=st.doc_name)
    except IssuanceBlocked as exc:
        return _page(request, "_semantik.html", oob=True, st=st, block_error=str(exc))
    except (ValueError, RuntimeError) as exc:
        return _page(request, "_semantik.html", oob=True, st=st, block_error=f"Penerbitan gagal: {exc}")
    except FileExistsError:
        return _page(request, "_galat.html", message="Dokumen ini sudah pernah diterbitkan. Buka halaman Lacak "
                     "untuk dokumen tersebut, atau mulai lagi dengan dokumen lain.", restart=True)
    st.issued_doc = out.manifest.doc_hash
    shutil.rmtree(st.folder, ignore_errors=True)
    with _LOCK:
        _STAGING.pop(sid, None)
    return _page(request, "_hasil_terbit.html", out=out, manifest=out.manifest)


@app.get("/dokumen/{doc}/salinan.zip")
def unduh_zip(doc: str) -> StreamingResponse:
    """All copies of a document as one ZIP."""
    from tapak.service import load_workspace

    manifest, _, folder = load_workspace(settings(), doc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in manifest.copies:
            z.write(_copy_path(folder, c.file), c.file)
    buf.seek(0)
    name = Path(manifest.doc_name).stem + "_salinan.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/dokumen/{doc}/salinan/{seq}")
def unduh_salinan(doc: str, seq: int) -> FileResponse:
    """One copy, looked up by its sequence number (never by a client-supplied path)."""
    from tapak.service import load_workspace

    manifest, _, folder = load_workspace(settings(), doc)
    match = [c for c in manifest.copies if c.seq == seq]
    if not match:
        raise HTTPException(404, "Salinan tidak ditemukan")
    return FileResponse(_copy_path(folder, match[0].file), filename=match[0].file)


def _copy_path(folder: Path, name: str) -> Path:
    """A copy's file inside the workspace; a manifest naming anything else is refused."""
    if (not name or name != Path(name).name or name.startswith(".")
            or Path(name).suffix.lower() not in (".pdf", ".docx")):  # never the manifest or a key
        raise HTTPException(400, "Nama berkas salinan di catatan penerbitan tidak valid")
    path = (folder / "salinan" / name).resolve()
    if path.parent != (folder / "salinan").resolve() or not path.is_file():
        raise HTTPException(404, "Berkas salinan tidak ditemukan")
    return path


# --- Lacak ----------------------------------------------------------------------------------


@app.get("/lacak", response_class=HTMLResponse)
def lacak_page(request: Request) -> HTMLResponse:
    """Evidence form."""
    from tapak.service import list_workspaces

    return _page(request, "lacak.html", title="Lacak", active="lacak", docs=list_workspaces(settings()),
                 errors={})


@app.post("/lacak", response_class=HTMLResponse)
async def lacak_run(
    request: Request,
    dokumen: str = Form(""),
    bukti: list[UploadFile] | None = File(None),
    teks: str = Form(""),
) -> HTMLResponse:
    """Run the trace and show the attribution (several evidence files are fused)."""
    from tapak.decoder.trace import TraceError
    from tapak.service import list_workspaces, trace_evidence

    errors: dict[str, str] = {}
    items: list[tuple[str, bytes]] = []
    total = 0
    for f in bukti or []:
        content = await _read_upload(f)
        total += len(content)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "Berkas terlalu besar (maksimum 40 MB seluruhnya)")
        if content:
            items.append((Path(f.filename or "bukti").name, content))
    if not items and teks.strip():
        items = [("teks_tempel.txt", teks.encode("utf-8"))]
    data, name = (items[0][1], items[0][0]) if items else (b"", "")
    if not dokumen:
        errors["dokumen"] = "Pilih dokumen yang diduga bocor."
    if not data:
        errors["bukti"] = "Unggah foto, tangkapan layar, PDF, atau DOCX, atau tempel teksnya."
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
        return _page(request, "_galat.html", message=f"Pelacakan tidak dapat dilakukan: {exc}")
    tid = secrets.token_hex(8)
    with _LOCK:
        _TRACES[tid] = outcome
        while len(_TRACES) > 50:
            _TRACES.pop(next(iter(_TRACES)))
    from tapak.decoder.report import make_redactor

    a = outcome.attribution
    # As in the berita acara: file names and notes never identify a copy that is not accused.
    redact = make_redactor((c.copy for c in a.candidates if not c.accused), {c.copy.seq for c in a.accused})
    return _page(request, "_hasil_lacak.html", o=outcome, a=a, tid=tid,
                 identified=a.verdict == VERDICT_IDENTIFIED, redact=redact,
                 eps_label=_eps_label(a.threshold.eps))


def _eps_label(eps: float) -> str:
    """'1 dari 1.000.000' for the offered choices and any other 1/n; else an Indonesian number."""
    for value, label in EPS_CHOICES:
        if abs(float(value) - eps) <= 1e-9 * eps:
            return label
    n = 1.0 / eps
    if abs(n - round(n)) < 1e-6 * n:
        return "1 dari " + f"{round(n):,}".replace(",", ".")
    return format_number(eps, 6)


@app.get("/lacak/{tid}/berita-acara.pdf")
def berita_acara(tid: str) -> Response:
    """The forensic report of a trace."""
    from tapak.service import write_report

    outcome = _TRACES.get(tid)
    if outcome is None:
        raise HTTPException(404, "Hasil pelacakan tidak ditemukan; jalankan pelacakan lagi")
    try:
        pdf = write_report(outcome)  # type: ignore[arg-type]
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(500, f"Berita acara tidak dapat dibuat: {exc}") from exc
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="berita_acara_{tid}.pdf"'})


# --- Registri ------------------------------------------------------------------------------


@app.get("/registri", response_class=HTMLResponse)
def registri_page(request: Request) -> HTMLResponse:
    """Registry verification, canary alerts and Merkle export."""
    from tapak.service import canary_alerts, list_workspaces

    s = settings()
    report = None
    if s.registry_path.exists() and s.public_key_path.exists():
        from tapak.registry.verify import verify_registry

        report = verify_registry(s.registry_path, s.public_key_path.read_text().strip(), require_signed=False)
    docs = list_workspaces(s)
    alerts = []
    for m in docs:
        for a in canary_alerts(s, m):
            alerts.append({**a, "doc_name": m.doc_name})
    alerts.sort(key=lambda a: str(a["time"]), reverse=True)
    return _page(request, "registri.html", title="Registri", active="registri", report=report, docs=docs,
                 alerts=alerts, public_key=(s.public_key_path.read_text().strip()
                                            if s.public_key_path.exists() else None))


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
