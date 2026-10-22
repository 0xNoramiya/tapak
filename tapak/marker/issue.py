"""Issue N marked copies of a master PDF.

For a document the issuer:
1. hashes the master (doc_hash) and builds the layout model;
2. runs the visual gate (an unmarked re-render must equal the original);
3. derives the Tardos bias vector and the embedding plan from the code secret;
4. for each recipient: draws a copy id, derives its codeword, commits to it with
   code_digest, renders the marked PDF;
5. writes a manifest (and, from M2, registry rows). Codewords themselves are never stored.

The lexical channel (word choice) is opt-in: only an explicit, fully reviewed
``LexicalSelection`` turns it on. Such a document also records ``retype_positions``, and its
semantic and lexical positions come from the retype band (``plan.RETYPE_BAND``). Without a
selection, plan, manifest and copies are exactly those of a document issued before the
channel existed.

Copies are rendered in parallel worker processes.
"""

from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import re
import secrets
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tapak.marker.background import (
    BackgroundSettings,
    PageGrid,
    background_hook,
    build_background_slots,
    cell_levels,
    page_grids,
)
from tapak.marker.canary import canary_token, canary_url, pdf_canary_hook
from tapak.marker.layout import RowId, WordId, sha256_hex
from tapak.marker.lexical import LexicalSelection, lexical_marks, lexical_slots
from tapak.marker.lexical import require_reviewed as require_lexical_reviewed
from tapak.marker.lexical import validate_selection as validate_lexical_selection
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.pdf_shift import DEFAULT_SCHEME, SCHEME_V1, ShiftSettings, build_shift_slots, shift_marks
from tapak.marker.pdf_zerowidth import build_text_slots, text_marks
from tapak.marker.plan import (
    CHANNEL_BACKGROUND,
    CHANNEL_LEXICAL,
    CHANNEL_SEMANTIC,
    RETYPE_BAND,
    RETYPE_STREAM,
    EmbeddingPlan,
    assign_positions,
    plan_key,
    retype_pool,
)
from tapak.marker.raster import ScanBoxes, attach_scan_layout, prepare_scans
from tapak.marker.semantic import (
    IssuanceBlocked,
    SemanticUnit,
    VariantSet,
    bits_per_unit,
    index_sets,
    require_approved,
    semantic_marks,
    semantic_slot_refs,
    validate_selection,
    variant_sets_digest,
)
from tapak.marker.render import CopyMarks, _AdvanceCache, render_copy, visual_gate
from tapak.tardos.accuse import threshold
from tapak.tardos.code import code_digest, derive_bias, derive_codeword
from tapak.tardos.params import TardosParams


@dataclass
class Recipient:
    """One addressee. Extra CSV columns are kept in ``extra``."""

    recipient_id: str
    nama: str
    jabatan: str = ""
    satuan: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class IssueSettings:
    """Issuance options (no secrets here)."""

    c: int = 3
    eps: float = 1e-6
    n_max: int | None = None          # default: number of recipients
    constant: str = "skoric"
    shift: ShiftSettings = field(default_factory=lambda: ShiftSettings.for_scheme(DEFAULT_SCHEME))
    background: BackgroundSettings = field(default_factory=BackgroundSettings)
    channels: tuple[str, ...] = ("shift", "zw", "homoglyph", "background", "canary", "semantic")
    canary_domain: str | None = None  # the canary channel is used only when a domain is set
    workers: int | None = None
    excluded_rows: tuple[RowId, ...] = ()


@dataclass
class SemanticSelection:
    """Sentences chosen for the semantic channel and their reviewed variants.

    This holds document text, so it is stored next to the master (``varian.json``) and
    never in the registry; the manifest keeps only ``variant_sets_digest``.
    """

    units: list[SemanticUnit]
    sets: list[VariantSet]

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return {"units": [u.to_dict() for u in self.units], "sets": [v.to_dict() for v in self.sets]}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "SemanticSelection":
        """Inverse of :meth:`to_dict`."""
        return cls([SemanticUnit.from_dict(u) for u in d["units"]],  # type: ignore[union-attr]
                   [VariantSet.from_dict(v) for v in d["sets"]])  # type: ignore[union-attr]

    @property
    def digest(self) -> str:
        """Hash of the approved variant sets (recorded instead of the text)."""
        return variant_sets_digest(self.sets)

    def carrying_rows(self) -> set[RowId]:
        """Rows of units that carry at least one bit (excluded from the other channels)."""
        idx = index_sets(self.sets)
        rows: set[RowId] = set()
        for u in self.units:
            vs = idx.get(u.unit_id)
            if vs is not None and bits_per_unit(vs) > 0:
                rows.update(u.row_ids)
        return rows


@dataclass
class IssuedCopy:
    """Record of one issued copy (no codeword, only its commitment)."""

    seq: int
    copy_id: str
    recipient: Recipient
    file: str
    file_sha256: str
    code_digest: str
    channels_used: list[str]
    semantic_variant_ids: list[str] = field(default_factory=list)
    canary_token: str | None = None


@dataclass
class IssueManifest:
    """Everything needed later to trace a leak of this document (except the secret)."""

    doc_hash: str
    doc_name: str
    issued_at: str
    issuer: str
    params: dict[str, object]
    shift_mm: dict[str, float]
    channels: list[str]
    excluded_rows: list[list[int]]
    plan_summary: dict[str, dict[str, int]]
    threshold_full: float
    gate: dict[str, object]
    copies: list[IssuedCopy]
    elapsed_s: float = 0.0
    background: dict[str, float] | None = None
    canary_domain: str | None = None
    semantic_digest: str | None = None
    # Lexical channel (opt-in). All None for a document without it, and then left out of the
    # JSON, so the record of such a document is exactly what it was before the channel.
    retype_positions: str | None = None
    lexical_digest: str | None = None
    lexicon_version: str | None = None
    lexicon_digest: str | None = None
    shift_excluded_rows: list[list[int]] | None = None
    text_excluded_words: list[list[int]] | None = None
    # Scanned pages (raster.scan_record): page numbers, resolution, pages whose OCR layer was
    # dropped, OCR engine and the digest of the word boxes; never a box, word or image. None
    # (and left out of the JSON) for a document without scanned pages.
    scan: dict[str, object] | None = None
    # Shift scheme name (pdf_shift.SHIFT_SCHEMES), only the name. None (and left out of the JSON)
    # means geser-v1: every document issued before geser-v2, and any geser-v1 issuance since.
    shift_scheme: str | None = None

    def to_json(self) -> str:
        """Serialize to pretty JSON (lexical, scan and shift scheme fields only when used)."""
        d = asdict(self)
        for key in LEXICAL_MANIFEST_FIELDS + (SCAN_MANIFEST_FIELD, SHIFT_SCHEME_FIELD):
            if d.get(key) is None:
                d.pop(key, None)
        return json.dumps(d, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "IssueManifest":
        """Inverse of :meth:`to_json`."""
        d = json.loads(text)
        copies = []
        for c in d.pop("copies"):
            rec = Recipient(**c.pop("recipient"))
            copies.append(IssuedCopy(recipient=rec, **c))
        return cls(copies=copies, **d)

    @property
    def tardos_params(self) -> TardosParams:
        """Parameters of the document's code."""
        return TardosParams.from_dict(self.params)

    @property
    def shift_settings(self) -> ShiftSettings:
        """Shift magnitudes and scheme used at issuance (geser-v1 when none is recorded)."""
        return ShiftSettings(word_mm=self.shift_mm["word_mm"], row_mm=self.shift_mm["row_mm"],
                             scheme=self.shift_scheme or SCHEME_V1)

    @property
    def background_settings(self) -> BackgroundSettings | None:
        """Background pattern parameters used at issuance (None if the channel was off)."""
        if not self.background or "background" not in self.channels:
            return None
        return BackgroundSettings(**self.background)  # type: ignore[arg-type]


LEXICAL_MANIFEST_FIELDS = ("retype_positions", "lexical_digest", "lexicon_version", "lexicon_digest",
                           "shift_excluded_rows", "text_excluded_words")
SCAN_MANIFEST_FIELD = "scan"
SHIFT_SCHEME_FIELD = "shift_scheme"


def lexical_exclusions(manifest: IssueManifest) -> tuple[set[RowId], set[WordId]]:
    """Rows left out of the shift channel and words left out of the text channel because of
    lexical points, as recorded at issuance (empty for a document without the channel)."""
    rows = {(int(r[0]), int(r[1])) for r in manifest.shift_excluded_rows or []}
    words = {(int(w[0]), int(w[1]), int(w[2])) for w in manifest.text_excluded_words or []}
    return rows, words


RECIPIENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def read_recipients(path: Path) -> list[Recipient]:
    """Read a recipients CSV with at least ``recipient_id`` and ``nama`` columns."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError("daftar penerima kosong")
    out = []
    seen: set[str] = set()
    for r in rows:
        rid = (r.pop("recipient_id", "") or "").strip()
        nama = (r.pop("nama", "") or "").strip()
        if not rid or not nama:
            raise ValueError("setiap baris wajib memiliki recipient_id dan nama")
        if not RECIPIENT_ID.fullmatch(rid):
            raise ValueError(f"recipient_id tidak sah: {rid[:40]!r}; gunakan huruf, angka, titik, garis bawah "
                             "atau tanda hubung (maksimal 64 karakter), karena dipakai dalam nama berkas")
        if rid in seen:
            raise ValueError(f"recipient_id ganda: {rid}")
        seen.add(rid)
        out.append(Recipient(rid, nama, (r.pop("jabatan", "") or "").strip(),
                             (r.pop("satuan", "") or "").strip(), {k: v for k, v in r.items() if k}))
    return out


def document_grids(master: MasterDocument, secret: bytes, settings: BackgroundSettings) -> list[PageGrid]:
    """Background cell grids of every page (keyed by the document's plan key)."""
    key = plan_key(secret, master.doc_hash)
    return page_grids([(p.width, p.height) for p in master.layout.pages], key, settings)


def build_document_plan(
    master: MasterDocument,
    params: TardosParams,
    secret: bytes,
    channels: tuple[str, ...],
    excluded_rows: set[RowId] | None = None,
    background: BackgroundSettings | None = None,
    semantic: SemanticSelection | None = None,
    lexical: LexicalSelection | None = None,
    retype_positions: str | None = None,
    shift_excluded_rows: set[RowId] | None = None,
    text_excluded_words: set[WordId] | None = None,
    shift_scheme: str = SCHEME_V1,
) -> EmbeddingPlan:
    """The embedding plan for a document (same result at issuance and at decoding).

    ``retype_positions`` (recorded at issuance) selects the position rule of the semantic and
    lexical channels; None is the original uniform rule. ``shift_excluded_rows`` and
    ``text_excluded_words`` are the lexical exclusions recorded at issuance, so the shift and
    text plans are right even when the lexical selection itself is unavailable.
    ``shift_scheme`` (recorded at issuance; geser-v1 when absent) decides which word groups
    carry shift bits; scanned pages follow the same scheme on their word boxes.
    """
    key = plan_key(secret, master.doc_hash)
    m = params.length
    excluded = excluded_rows or set()
    slots = []
    if "shift" in channels:
        slots += build_shift_slots(master.shift_layout, m, key, excluded | (shift_excluded_rows or set()),
                                   late_pages=frozenset(master.scans), scheme=shift_scheme)
    text_slots = build_text_slots(master, m, key, excluded, text_excluded_words)
    slots += [s for s in text_slots if s.channel in channels]
    if "background" in channels:
        grids = document_grids(master, secret, background or BackgroundSettings())
        slots += build_background_slots(grids, m, key)
    p = derive_bias(secret, master.doc_hash, params) if retype_positions is not None else None
    if semantic is not None and "semantic" in channels:
        refs = semantic_slot_refs(semantic.units, semantic.sets)
        if retype_positions is None:
            slots += assign_positions(CHANNEL_SEMANTIC, refs, m, key)
        else:
            slots += assign_positions(CHANNEL_SEMANTIC, refs, m, key, pool=retype_pool(p, retype_positions),
                                      stream=RETYPE_STREAM)
    if lexical is not None and "lexical" in channels:
        slots += lexical_slots(lexical, m, key, p, retype_positions)
    return EmbeddingPlan(m=m, slots=slots)


def check_retype_band(plan: EmbeddingPlan, p: np.ndarray, rule: str = RETYPE_BAND) -> None:
    """Refuse (IssuanceBlocked) a plan whose semantic and lexical bits do not fit the retype band.

    Both channels walk one shared sequence of band positions from opposite ends, so they
    never collide while the band has room. With a small code (``--c 1``) or many points the
    sequence wraps: positions would repeat and the two channels would share some, so the
    stated retype capacity would be overstated. Issuance stops instead.
    """
    positions = [q for name in (CHANNEL_SEMANTIC, CHANNEL_LEXICAL) for s in plan.channel(name) for q in s.positions]
    if len(set(positions)) < len(positions):
        pool = int(retype_pool(p, rule).sum())
        raise IssuanceBlocked(
            f"penerbitan diblokir: pita bias 0,3 sampai 0,7 hanya memuat {pool} posisi kode, sedangkan kanal "
            f"semantik dan pilihan kata memerlukan {len(positions)} posisi berbeda; tolak sebagian titik pilihan "
            "kata atau terbitkan dengan c lebih besar")


def marks_for_codeword(
    master: MasterDocument,
    plan: EmbeddingPlan,
    codeword: np.ndarray,
    settings: IssueSettings,
    grids: list[PageGrid] | None = None,
    semantic: SemanticSelection | None = None,
    lexical: LexicalSelection | None = None,
) -> tuple[CopyMarks, list[str]]:
    """All per-copy marks implied by a codeword, plus the semantic variant ids used.

    The lexical form choices are code bits and are not returned: they are never stored.
    """
    group_dx, row_dy = shift_marks(plan, codeword, settings.shift)
    marks = CopyMarks(group_dx=group_dx, row_dy=row_dy, text=text_marks(plan, master, codeword))
    if grids and "background" in settings.channels:
        # Text pages draw the pattern under their content; scanned pages add it to the page image.
        text_grids = [g for g in grids if g.page not in master.scans]
        if text_grids:
            marks.page_hooks.append(background_hook(plan, codeword, text_grids))
        slots = plan.channel(CHANNEL_BACKGROUND)
        marks.scan_patterns = {g.page: (g, cell_levels(g, slots, codeword)) for g in grids if g.page in master.scans}
    variant_ids: list[str] = []
    if semantic is not None and plan.channel(CHANNEL_SEMANTIC):
        marks.row_words, variant_ids = semantic_marks(plan.channel(CHANNEL_SEMANTIC), codeword, master,
                                                      semantic.units, semantic.sets)
    if lexical is not None and plan.channel(CHANNEL_LEXICAL):
        rows = lexical_marks(plan.channel(CHANNEL_LEXICAL), codeword, master, lexical)
        if set(rows) & set(marks.row_words):
            raise ValueError("baris titik pilihan kata juga dipakai kanal semantik")
        marks.row_words.update(rows)
    return marks, variant_ids


# Worker process state (set by the initializer, one master per process).
_W: dict[str, object] = {}


def _worker_init(pdf_bytes: bytes, secret: bytes, settings: IssueSettings,
                 semantic: SemanticSelection | None = None, lexical: LexicalSelection | None = None,
                 scan_boxes: ScanBoxes | None = None) -> None:
    if mp.parent_process() is not None:  # a pool worker (this also runs in-process when serial)
        import signal

        signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl-C is handled by the parent, which stops the pool
    master = load_master(pdf_bytes)
    if scan_boxes is not None:  # word boxes found once by the parent (Tesseract is not rerun per worker)
        attach_scan_layout(master, scan_boxes)
    params = _params_for(settings, None)
    if lexical is not None:
        validate_lexical_selection(master, lexical)  # once per worker: nothing drawn from an edited file
    _W.update(
        master=master,
        secret=secret,
        settings=settings,
        params=params,
        plan=build_document_plan(master, params, secret, settings.channels, set(settings.excluded_rows),
                                 settings.background, semantic, **_lexical_plan_args(lexical),
                                 shift_scheme=settings.shift.scheme),
        grids=document_grids(master, secret, settings.background),
        semantic=semantic,
        lexical=lexical,
        p=derive_bias(secret, master.doc_hash, params),
        cache=_AdvanceCache(master),
    )


def _lexical_plan_args(lexical: LexicalSelection | None) -> dict[str, object]:
    """Plan arguments of an opted-in document (empty without the lexical channel)."""
    if lexical is None:
        return {}
    return {"lexical": lexical, "retype_positions": RETYPE_BAND,
            "shift_excluded_rows": lexical.shift_excluded_rows(),
            "text_excluded_words": lexical.excluded_words()}


def _params_for(settings: IssueSettings, n_recipients: int | None) -> TardosParams:
    n_max = settings.n_max if settings.n_max is not None else n_recipients
    if n_max is None:
        raise ValueError("n_max tidak diketahui")
    return TardosParams(c=settings.c, eps=settings.eps, n_max=n_max, constant=settings.constant)  # type: ignore[arg-type]


def _main_importable() -> bool:
    """True if worker processes can re-import ``__main__`` (not an interactive or stdin session)."""
    import sys

    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    return bool(main_file) and Path(main_file).exists()


def _canary_enabled(settings: IssueSettings) -> bool:
    return "canary" in settings.channels and bool(settings.canary_domain)


def _render_one(job: tuple[int, str, str]) -> tuple[int, str, str, str | None, list[str]]:
    seq, copy_id, out_path = job
    master: MasterDocument = _W["master"]  # type: ignore[assignment]
    settings: IssueSettings = _W["settings"]  # type: ignore[assignment]
    x = derive_codeword(_W["secret"], master.doc_hash, copy_id, _W["p"])  # type: ignore[arg-type]
    marks, variant_ids = marks_for_codeword(master, _W["plan"], x, settings, _W["grids"],  # type: ignore[arg-type]
                                            _W["semantic"], _W["lexical"])  # type: ignore[arg-type]
    token = None
    if _canary_enabled(settings):
        token = canary_token(_W["secret"], master.doc_hash, copy_id)  # type: ignore[arg-type]
        marks.doc_hooks.append(pdf_canary_hook(canary_url(token, settings.canary_domain)))  # type: ignore[arg-type]
    data = render_copy(master, marks, _W["cache"])  # type: ignore[arg-type]
    Path(out_path).write_bytes(data)
    return seq, code_digest(master.doc_hash, copy_id, x), sha256_hex(data), token, variant_ids


def issue(
    pdf_path: Path,
    recipients: list[Recipient],
    out_dir: Path,
    secret: bytes,
    settings: IssueSettings | None = None,
    issuer: str = "operator",
    semantic: SemanticSelection | None = None,
    file_stem: str | None = None,
    lexical: LexicalSelection | None = None,
) -> IssueManifest:
    """Render one marked copy per recipient into ``out_dir`` and return the manifest.

    With a semantic selection, issuance is refused (IssuanceBlocked) while any variant is
    still awaiting review, and the unit rows are excluded from the other channels. A lexical
    selection opts the document into the word-choice channel: issuance is refused while any
    point is undecided or the file fails ``lexical.validate_selection``; rows holding a
    carrying point leave the shift channel and the point words leave the text channel.

    Scanned pages (``raster.py``) are marked in their page image: their resolution is checked,
    their word boxes are found once with Tesseract, and only the digest of the boxes is
    recorded (``manifest.scan``).
    """
    t0 = time.perf_counter()
    settings = settings or IssueSettings()
    if lexical is not None:
        require_lexical_reviewed(lexical)
        if CHANNEL_LEXICAL not in settings.channels:
            settings = IssueSettings(**{**settings.__dict__,
                                        "channels": tuple(settings.channels) + (CHANNEL_LEXICAL,)})
    if semantic is not None and "semantic" in settings.channels:
        require_approved(semantic.sets)
        rows = sorted(set(settings.excluded_rows) | semantic.carrying_rows())
        settings = IssueSettings(**{**settings.__dict__, "excluded_rows": tuple(rows)})
    else:
        semantic = None
    if settings.n_max is None:
        settings = IssueSettings(**{**settings.__dict__, "n_max": len(recipients)})
    if len(recipients) > settings.n_max:  # type: ignore[operator]
        raise ValueError("jumlah penerima melebihi n_max kode")
    pdf_bytes = Path(pdf_path).read_bytes()
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise ValueError("dokumen induk bukan berkas PDF")
    try:
        master = load_master(pdf_bytes)
    except RuntimeError as exc:  # pymupdf.FileDataError for a damaged file
        raise ValueError("dokumen induk PDF tidak dapat dibuka atau rusak") from exc
    if not master.scans and not any(True for _ in master.layout.words()):
        raise ValueError("PDF ini tidak memiliki lapisan teks dan tidak dikenali sebagai hasil pindai (setiap "
                         "halaman pindaian harus berupa satu gambar halaman penuh). Tidak ada yang dapat ditandai.")
    # Scanned pages: resolution check and word boxes (Tesseract, once, here in the parent).
    scan_record, scan_boxes = prepare_scans(master)
    if semantic is not None:
        validate_selection(master, semantic.units, semantic.sets)  # fail before any rendering
    if lexical is not None:
        validate_lexical_selection(master, lexical)
        if semantic is not None and lexical.shift_excluded_rows() & semantic.carrying_rows():
            raise IssuanceBlocked("penerbitan diblokir: baris titik pilihan kata juga dipakai kanal semantik")
    gate = visual_gate(master)
    if not gate.passed:
        if gate.scan_identical is False:
            raise RuntimeError("gerbang visual gagal: salinan tanpa tanda dari halaman pindaian tidak identik piksel "
                               "demi piksel dengan gambar halaman dokumen induk, atau tampilan halamannya berbeda")
        raise RuntimeError(
            "gerbang visual gagal: render ulang tanpa tanda berbeda dari dokumen asli "
            f"(selisih maks {gate.max_diff}, rata-rata {gate.mean_diff:.3f})"
        )
    params = _params_for(settings, len(recipients))
    plan = build_document_plan(master, params, secret, settings.channels, set(settings.excluded_rows),
                               settings.background, semantic, **_lexical_plan_args(lexical),
                               shift_scheme=settings.shift.scheme)
    p = derive_bias(secret, master.doc_hash, params)
    if lexical is not None:
        check_retype_band(plan, p)
    z_full = threshold(p, params.eps1)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or Path(pdf_path).stem
    jobs = []
    copy_ids = []
    for seq, rec in enumerate(recipients, start=1):
        copy_id = secrets.token_hex(8)
        copy_ids.append(copy_id)
        jobs.append((seq, copy_id, str(out_dir / f"{stem}__salinan{seq:03d}_{rec.recipient_id}.pdf")))

    workers = settings.workers or min(len(jobs), os.cpu_count() or 1, 8)
    if not _main_importable():
        workers = 1  # interactive session or stdin script: child processes cannot re-import it
    results: dict[int, tuple[str, str, str | None, list[str]]] = {}
    if workers <= 1:
        _worker_init(pdf_bytes, secret, settings, semantic, lexical, scan_boxes)
        for job in jobs:
            seq, digest, fhash, token, vids = _render_one(job)
            results[seq] = (digest, fhash, token, vids)
    else:
        # forkserver: workers fork from a clean single-threaded server, never from this
        # (possibly multi-threaded) process; spawn where forkserver is unavailable.
        if "forkserver" in mp.get_all_start_methods():
            ctx = mp.get_context("forkserver")
            ctx.set_forkserver_preload(["tapak.marker.issue"])
        else:
            ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_worker_init,
                                 initargs=(pdf_bytes, secret, settings, semantic, lexical, scan_boxes)) as pool:
            for seq, digest, fhash, token, vids in pool.map(_render_one, jobs):
                results[seq] = (digest, fhash, token, vids)

    channels_used = [c for c in settings.channels if plan.channel(c)]
    if _canary_enabled(settings):
        channels_used.append("canary")
    copies = [
        IssuedCopy(
            seq=seq,
            copy_id=copy_ids[seq - 1],
            recipient=rec,
            file=Path(jobs[seq - 1][2]).name,
            file_sha256=results[seq][1],
            code_digest=results[seq][0],
            channels_used=channels_used,
            canary_token=results[seq][2],
            semantic_variant_ids=results[seq][3],
        )
        for seq, rec in enumerate(recipients, start=1)
    ]
    manifest = IssueManifest(
        doc_hash=master.doc_hash,
        doc_name=Path(pdf_path).name,
        issued_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        issuer=issuer,
        params=params.to_dict(),
        shift_mm={"word_mm": settings.shift.word_mm, "row_mm": settings.shift.row_mm},
        channels=list(settings.channels),
        excluded_rows=[list(r) for r in settings.excluded_rows],
        plan_summary=plan.summary(),
        threshold_full=z_full,
        gate={k: v for k, v in asdict(gate).items() if not (k == "scan_identical" and v is None)},
        copies=copies,
        elapsed_s=time.perf_counter() - t0,
        background=asdict(settings.background) if "background" in settings.channels else None,
        canary_domain=settings.canary_domain if _canary_enabled(settings) else None,
        semantic_digest=semantic.digest if semantic is not None and plan.channel(CHANNEL_SEMANTIC) else None,
        scan=scan_record,
        shift_scheme=settings.shift.scheme if settings.shift.scheme != SCHEME_V1 else None,
    )
    if lexical is not None:
        manifest.retype_positions = RETYPE_BAND
        manifest.lexical_digest = lexical.digest
        manifest.lexicon_version = lexical.lexicon
        manifest.lexicon_digest = lexical.lexicon_digest
        manifest.shift_excluded_rows = [list(r) for r in sorted(lexical.shift_excluded_rows())]
        manifest.text_excluded_words = [list(w) for w in sorted(lexical.excluded_words())]
    (out_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest
