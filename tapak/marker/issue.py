"""Issue N marked copies of a master PDF.

For a document the issuer:
1. hashes the master (doc_hash) and builds the layout model;
2. runs the visual gate (an unmarked re-render must equal the original);
3. derives the Tardos bias vector and the embedding plan from the code secret;
4. for each recipient: draws a copy id, derives its codeword, commits to it with
   code_digest, renders the marked PDF;
5. writes a manifest (and, from M2, registry rows). Codewords themselves are never stored.

Copies are rendered in parallel worker processes.
"""

from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import secrets
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tapak.marker.background import BackgroundSettings, PageGrid, background_hook, build_background_slots, page_grids
from tapak.marker.canary import canary_token, canary_url, pdf_canary_hook
from tapak.marker.layout import RowId, sha256_hex
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.pdf_shift import ShiftSettings, build_shift_slots, shift_marks
from tapak.marker.pdf_zerowidth import build_text_slots, text_marks
from tapak.marker.plan import CHANNEL_SEMANTIC, EmbeddingPlan, assign_positions, plan_key
from tapak.marker.semantic import (
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
    shift: ShiftSettings = field(default_factory=ShiftSettings)
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

    def to_json(self) -> str:
        """Serialize to pretty JSON."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

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
        """Shift magnitudes used at issuance."""
        return ShiftSettings(word_mm=self.shift_mm["word_mm"], row_mm=self.shift_mm["row_mm"])

    @property
    def background_settings(self) -> BackgroundSettings | None:
        """Background pattern parameters used at issuance (None if the channel was off)."""
        if not self.background or "background" not in self.channels:
            return None
        return BackgroundSettings(**self.background)  # type: ignore[arg-type]


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
) -> EmbeddingPlan:
    """The embedding plan for a document (same result at issuance and at decoding)."""
    key = plan_key(secret, master.doc_hash)
    m = params.length
    excluded = excluded_rows or set()
    slots = []
    if "shift" in channels:
        slots += build_shift_slots(master.layout, m, key, excluded)
    text_slots = build_text_slots(master, m, key, excluded)
    slots += [s for s in text_slots if s.channel in channels]
    if "background" in channels:
        grids = document_grids(master, secret, background or BackgroundSettings())
        slots += build_background_slots(grids, m, key)
    if semantic is not None and "semantic" in channels:
        slots += assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(semantic.units, semantic.sets), m, key)
    return EmbeddingPlan(m=m, slots=slots)


def marks_for_codeword(
    master: MasterDocument,
    plan: EmbeddingPlan,
    codeword: np.ndarray,
    settings: IssueSettings,
    grids: list[PageGrid] | None = None,
    semantic: SemanticSelection | None = None,
) -> tuple[CopyMarks, list[str]]:
    """All per-copy marks implied by a codeword, plus the semantic variant ids used."""
    group_dx, row_dy = shift_marks(plan, codeword, settings.shift)
    marks = CopyMarks(group_dx=group_dx, row_dy=row_dy, text=text_marks(plan, master, codeword))
    if grids and "background" in settings.channels:
        marks.page_hooks.append(background_hook(plan, codeword, grids))
    variant_ids: list[str] = []
    if semantic is not None and plan.channel(CHANNEL_SEMANTIC):
        marks.row_words, variant_ids = semantic_marks(plan.channel(CHANNEL_SEMANTIC), codeword, master,
                                                      semantic.units, semantic.sets)
    return marks, variant_ids


# Worker process state (set by the initializer, one master per process).
_W: dict[str, object] = {}


def _worker_init(pdf_bytes: bytes, secret: bytes, settings: IssueSettings,
                 semantic: SemanticSelection | None = None) -> None:
    master = load_master(pdf_bytes)
    params = _params_for(settings, None)
    _W.update(
        master=master,
        secret=secret,
        settings=settings,
        params=params,
        plan=build_document_plan(master, params, secret, settings.channels, set(settings.excluded_rows),
                                 settings.background, semantic),
        grids=document_grids(master, secret, settings.background),
        semantic=semantic,
        p=derive_bias(secret, master.doc_hash, params),
        cache=_AdvanceCache(master),
    )


def _params_for(settings: IssueSettings, n_recipients: int | None) -> TardosParams:
    n_max = settings.n_max if settings.n_max is not None else n_recipients
    if n_max is None:
        raise ValueError("n_max unknown")
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
                                            _W["semantic"])  # type: ignore[arg-type]
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
) -> IssueManifest:
    """Render one marked copy per recipient into ``out_dir`` and return the manifest.

    With a semantic selection, issuance is refused (IssuanceBlocked) while any variant is
    still awaiting review, and the unit rows are excluded from the other channels.
    """
    t0 = time.perf_counter()
    settings = settings or IssueSettings()
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
    master = load_master(pdf_bytes)
    if semantic is not None:
        validate_selection(master, semantic.units, semantic.sets)  # fail before any rendering
    gate = visual_gate(master)
    if not gate.passed:
        raise RuntimeError(
            "gerbang visual gagal: render ulang tanpa tanda berbeda dari dokumen asli "
            f"(selisih maks {gate.max_diff}, rata-rata {gate.mean_diff:.3f})"
        )
    params = _params_for(settings, len(recipients))
    plan = build_document_plan(master, params, secret, settings.channels, set(settings.excluded_rows),
                               settings.background, semantic)
    p = derive_bias(secret, master.doc_hash, params)
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
        _worker_init(pdf_bytes, secret, settings, semantic)
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
                                 initargs=(pdf_bytes, secret, settings, semantic)) as pool:
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
        gate=asdict(gate),
        copies=copies,
        elapsed_s=time.perf_counter() - t0,
        background=asdict(settings.background) if "background" in settings.channels else None,
        canary_domain=settings.canary_domain if _canary_enabled(settings) else None,
        semantic_digest=semantic.digest if semantic is not None and plan.channel(CHANNEL_SEMANTIC) else None,
    )
    (out_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest
