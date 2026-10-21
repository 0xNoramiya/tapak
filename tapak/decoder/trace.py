"""Trace pipeline: evidence file in, attribution out.

``load_context`` rebuilds everything the decoder needs from the master PDF, the issuance
record and the code secret, and checks every regenerated codeword against the commitment
stored at issuance. The ``collect_*`` functions run the channel decoders that apply to an
input type; ``run_trace`` fuses and accuses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tapak.decoder.accuse import Attribution, CopyRef, attribute
from tapak.decoder.ch_shift import decode_vector
from tapak.decoder.ch_zerowidth import decode_text, extract_pdf_text
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.decoder.softbits import SoftBits
from tapak.marker.issue import IssueManifest, SemanticSelection, build_document_plan
from tapak.marker.layout import RowId, sha256_hex
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.background import BackgroundSettings
from tapak.marker.pdf_shift import ShiftSettings
from tapak.marker.plan import EmbeddingPlan, plan_key
from tapak.tardos.code import code_digest, derive_bias, derive_codeword
from tapak.tardos.params import TardosParams

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class TraceError(RuntimeError):
    """Raised when the trace cannot be performed honestly (wrong master, broken record)."""


@dataclass
class TraceContext:
    """Decoder-side reconstruction of one issued document."""

    master: MasterDocument
    manifest: IssueManifest
    params: TardosParams
    plan: EmbeddingPlan
    p: np.ndarray
    codewords: np.ndarray
    refs: list[CopyRef]
    excluded: set[RowId] = field(default_factory=set)
    key: bytes = b""
    background: BackgroundSettings | None = None
    semantic: SemanticSelection | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def shift(self) -> ShiftSettings:
        """Shift magnitudes used at issuance."""
        return self.manifest.shift_settings


def load_semantic(folder: Path | None) -> SemanticSelection | None:
    """The approved semantic selection stored next to the master (``varian.json``), if any."""
    if folder is None or not (Path(folder) / "varian.json").exists():
        return None
    import json

    return SemanticSelection.from_dict(json.loads((Path(folder) / "varian.json").read_text(encoding="utf-8")))


def load_context(master_pdf: bytes, manifest: IssueManifest, secret: bytes,
                 semantic: SemanticSelection | None = None, folder: Path | None = None) -> TraceContext:
    """Rebuild plan and codewords; refuse if the master or any commitment does not match.

    The semantic channel needs the approved variant sets used at issuance; they are taken
    from ``semantic`` or from ``folder/varian.json`` and checked against the digest in the
    manifest. Without them the semantic channel is skipped (with a warning).
    """
    master = load_master(master_pdf)
    if master.doc_hash != manifest.doc_hash:
        raise TraceError("dokumen induk tidak cocok dengan catatan penerbitan (hash berbeda)")
    params = manifest.tardos_params
    excluded = {tuple(r) for r in manifest.excluded_rows}
    background = manifest.background_settings
    warnings: list[str] = []
    if semantic is None:
        semantic = load_semantic(folder)
    if manifest.semantic_digest:
        if semantic is None:
            warnings.append("varian semantik saat penerbitan tidak tersedia; kanal semantik dilewati")
        elif semantic.digest != manifest.semantic_digest:
            warnings.append("varian semantik tidak cocok dengan catatan penerbitan; kanal semantik dilewati")
            semantic = None
    else:
        semantic = None
    try:
        plan = build_document_plan(master, params, secret, tuple(manifest.channels), excluded,  # type: ignore[arg-type]
                                   background, semantic)
    except ValueError:
        warnings.append("varian semantik tidak cocok dengan catatan penerbitan; kanal semantik dilewati")
        semantic = None
        plan = build_document_plan(master, params, secret, tuple(manifest.channels), excluded,  # type: ignore[arg-type]
                                   background, None)
    p = derive_bias(secret, master.doc_hash, params)
    rows = []
    refs = []
    for c in manifest.copies:
        x = derive_codeword(secret, master.doc_hash, c.copy_id, p)
        if code_digest(master.doc_hash, c.copy_id, x) != c.code_digest:
            raise TraceError(f"komitmen kode salinan #{c.seq} tidak cocok: rahasia kode salah atau catatan diubah")
        rows.append(x)
        r = c.recipient
        refs.append(CopyRef(c.seq, c.copy_id, r.recipient_id, r.nama, r.jabatan, r.satuan))
    return TraceContext(master, manifest, params, plan, p, np.vstack(rows), refs, excluded,  # type: ignore[arg-type]
                        key=plan_key(secret, master.doc_hash), background=background, semantic=semantic,
                        warnings=warnings)


def collect_from_text(text: str, ctx: TraceContext) -> list[SoftBits]:
    """Channels readable from text: the text layer (channel 3) and semantic variants (channel 4)."""
    obs = decode_text(text, ctx.master, ctx.plan)
    if ctx.semantic is not None and ctx.plan.channel("semantic"):
        from tapak.decoder.ch_semantic import decode_semantic

        obs.append(decode_semantic(text, ctx.semantic.units, ctx.semantic.sets, ctx.plan.channel("semantic")))
    return obs


def collect_background_from_pdf(pdf_bytes: bytes, ctx: TraceContext, dpi: float = 100.0) -> list[SoftBits]:
    """Channel 2 from a forwarded PDF: render each page (already aligned with the master)."""
    if ctx.background is None or not ctx.plan.channel("background"):
        return []
    import pymupdf

    from tapak.decoder.ch_background import decode_background
    from tapak.decoder.rectify import render_page
    from tapak.marker.background import page_grids

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        n_pages = min(doc.page_count, len(ctx.master.layout.pages))
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    grids = page_grids(sizes, ctx.key, ctx.background)
    parts = []
    for page in range(n_pages):
        img = render_page(pdf_bytes, page, dpi, supersample=1)
        master = render_page(ctx.master.pdf_bytes, page, dpi, supersample=1)
        if img.shape != master.shape:
            continue
        parts.append(decode_background(img, np.ones(img.shape, dtype=bool), master, dpi, grids[page],
                                       ctx.plan.channel("background")))
    return [SoftBits.concat("background", parts, pages=n_pages)] if parts else []


def collect_from_pdf(pdf_bytes: bytes, ctx: TraceContext) -> list[SoftBits]:
    """Channels readable from a forwarded PDF: shifts (vector readout), background (render),
    text layer and semantic variants."""
    return ([decode_vector(pdf_bytes, ctx.master, ctx.plan, ctx.shift, ctx.excluded)]
            + collect_background_from_pdf(pdf_bytes, ctx)
            + collect_from_text(extract_pdf_text(pdf_bytes), ctx))


def run_trace(observations: list[SoftBits], ctx: TraceContext, notes: list[str] | None = None) -> Attribution:
    """Fuse, accuse, explain."""
    fused = fuse(observations, ctx.params.length)
    per_channel = fuse_by_physical_channel(observations, ctx.params.length)
    result = attribute(fused, per_channel, ctx.p, ctx.codewords, ctx.refs, ctx.params)
    result.notes = list(ctx.warnings) + list(notes or []) + result.notes
    return result


def trace_file(path: Path, ctx: TraceContext) -> tuple[Attribution, list[SoftBits]]:
    """Trace any supported evidence file (PDF, text; images from M3)."""
    path = Path(path)
    data = path.read_bytes()
    notes = []
    digest = sha256_hex(data)
    for c in ctx.manifest.copies:
        if c.file_sha256 == digest:
            notes.append(f"berkas identik byte demi byte dengan salinan #{c.seq} (bukti pendukung)")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        obs = collect_from_pdf(data, ctx)
    elif suffix in (".txt", ".md", ""):
        obs = collect_from_text(data.decode("utf-8", errors="replace"), ctx)
    elif suffix == ".docx":  # leaked text pasted into a Word file
        from tapak.decoder.ch_docx import extract_docx_text

        obs = collect_from_text(extract_docx_text(data), ctx)
    elif suffix in IMAGE_SUFFIXES:
        from tapak.decoder.image import collect_from_image  # M3

        obs = collect_from_image(data, ctx)
        if obs and all(sb.meta.get("registered") is False for sb in obs):
            notes.append("halaman dokumen induk tidak ditemukan pada gambar (bukan dokumen ini, "
                         "terlalu buram, atau terpotong)")
        else:
            reg = next((sb.meta for sb in obs if "correlation" in sb.meta), None)
            if reg:
                notes.append(f"gambar dipetakan ke halaman {reg['page'] + 1} (metode {reg['method']}, "
                             f"korelasi {reg['correlation']:.3f}, resolusi efektif {reg['effective_dpi']:.0f} dpi)")
    else:
        raise TraceError(f"jenis berkas tidak dikenal: {suffix}")
    return run_trace(obs, ctx, notes), obs
