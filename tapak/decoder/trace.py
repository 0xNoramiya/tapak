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
    """The approved semantic selection stored with the issuance (``varian.json``), if any.

    It is looked up in ``folder`` and in its parent, so both the workspace manifest and the
    copy next to the issued files (``salinan/manifest.json``) find it.
    """
    if folder is None:
        return None
    import json

    for candidate in (Path(folder) / "varian.json", Path(folder).parent / "varian.json"):
        if candidate.exists():
            try:
                return SemanticSelection.from_dict(json.loads(candidate.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError) as exc:
                raise TraceError(f"{candidate.name} rusak atau bukan berkas varian TAPAK") from exc
    return None


def load_context(master_pdf: bytes, manifest: IssueManifest, secret: bytes,
                 semantic: SemanticSelection | None = None, folder: Path | None = None) -> TraceContext:
    """Rebuild plan and codewords; refuse if the master or any commitment does not match.

    The semantic channel needs the approved variant sets used at issuance; they are taken
    from ``semantic`` or from ``folder/varian.json`` and checked against the digest in the
    manifest. Without them the semantic channel is skipped (with a warning).
    """
    try:
        master = load_master(master_pdf)
    except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError is a RuntimeError
        raise TraceError("dokumen induk tidak dapat dibuka (bukan PDF yang sah atau rusak)") from exc
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

    from tapak.decoder.ch_background import decode_background
    from tapak.decoder.rectify import render_page
    from tapak.marker.background import page_grids

    from tapak.decoder.ch_shift import map_pages
    from tapak.marker.layout import extract_layout

    pairs = map_pages(ctx.master.layout, extract_layout(pdf_bytes))  # evidence page -> master page
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    grids = page_grids(sizes, ctx.key, ctx.background)
    parts = []
    for li, mi in pairs.items():
        img = render_page(pdf_bytes, li, dpi, supersample=1)
        master = render_page(ctx.master.pdf_bytes, mi, dpi, supersample=1)
        if img.shape != master.shape:
            continue  # scaled to another paper size: the cell grid would not line up
        parts.append(decode_background(img, np.ones(img.shape, dtype=bool), master, dpi, grids[mi],
                                       ctx.plan.channel("background")))
    return [SoftBits.concat("background", parts, pages=len(parts))] if parts else []


def collect_from_pdf(pdf_bytes: bytes, ctx: TraceContext) -> list[SoftBits]:
    """Channels readable from a forwarded PDF: shifts (vector readout), background (render),
    text layer and semantic variants."""
    return ([decode_vector(pdf_bytes, ctx.master, ctx.plan, ctx.shift, ctx.excluded)]
            + collect_background_from_pdf(pdf_bytes, ctx)
            + collect_from_text(extract_pdf_text(pdf_bytes), ctx))


RASTER_DPI = 200.0
RASTER_MAX_PIXELS = 25_000_000
RASTER_MAX_PAGES = 20


def collect_rasterized_pages(pdf_bytes: bytes, ctx: TraceContext, name: str) -> tuple[list[SoftBits], list[str]]:
    """PDF pages the vector readout cannot use, decoded as images.

    A page with no text layer matching the master (a scan or photo saved as PDF) is rendered
    and decoded like a photo. A page whose text matches but whose paper size differs (printed
    to another paper size) keeps its shifts from the vector readout; only the background, whose
    cell grid would not line up, is taken from the rendered image.
    """
    from tapak.decoder.ch_shift import map_pages
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.rectify import render_page
    from tapak.marker.layout import extract_layout

    layout = extract_layout(pdf_bytes)
    pairs = map_pages(ctx.master.layout, layout)
    obs: list[SoftBits] = []
    notes: list[str] = []
    todo = []
    for page in layout.pages:
        mi = pairs.get(page.index)
        if mi is None:
            todo.append((page, None))
            continue
        mp = ctx.master.layout.pages[mi]
        if (abs(page.width - mp.width) > 1 or abs(page.height - mp.height) > 1) and ctx.background is not None:
            todo.append((page, {"background"}))
    if len(todo) > RASTER_MAX_PAGES:
        notes.append(f"{name}: hanya {RASTER_MAX_PAGES} dari {len(todo)} halaman tanpa lapisan teks yang cocok "
                     "dibaca sebagai gambar")
        todo = todo[:RASTER_MAX_PAGES]
    for page, keep in todo:
        area_in2 = max(page.width * page.height, 1.0) / 72.0**2
        dpi = min(RASTER_DPI, (RASTER_MAX_PIXELS / area_in2) ** 0.5)
        found = [sb for sb in collect_from_gray(render_page(pdf_bytes, page.index, dpi, supersample=1), ctx)
                 if keep is None or sb.channel in keep]
        reg = next((sb.meta for sb in found if "correlation" in sb.meta), None)
        if reg is None:
            if keep is None:
                notes.append(f"{name} halaman {page.index + 1}: tidak memiliki lapisan teks yang cocok dan "
                             "tidak dikenali sebagai halaman dokumen induk")
            continue
        obs += found
        why = "ukuran kertas berbeda" if keep else "tanpa lapisan teks yang cocok"
        notes.append(f"{name} halaman {page.index + 1}: dibaca sebagai gambar ({why}), dipetakan ke halaman "
                     f"{reg['page'] + 1} (korelasi {reg['correlation']:.3f})")
    return obs, notes


def run_trace(observations: list[SoftBits], ctx: TraceContext, notes: list[str] | None = None) -> Attribution:
    """Fuse, accuse, explain."""
    fused = fuse(observations, ctx.params.length)
    per_channel = fuse_by_physical_channel(observations, ctx.params.length)
    result = attribute(fused, per_channel, ctx.p, ctx.codewords, ctx.refs, ctx.params)
    result.notes = list(ctx.warnings) + list(notes or []) + result.notes
    return result


def decode_text_evidence(data: bytes) -> str:
    """Text evidence in UTF-8, UTF-16 or UTF-32 (with or without BOM), as Windows Notepad saves it."""
    import codecs

    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                     (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
                     (codecs.BOM_UTF8, "utf-8-sig")):
        if data.startswith(bom):
            return data.decode(enc, errors="replace")
    if len(data) >= 4:
        even, odd = data[0::2], data[1::2]
        if odd.count(0) > 0.2 * len(odd):
            return data.decode("utf-16-le", errors="replace")
        if even.count(0) > 0.2 * len(even):
            return data.decode("utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def collect_file(name: str, data: bytes, ctx: TraceContext) -> tuple[list[SoftBits], list[str]]:
    """Observations and notes from one evidence file (PDF, DOCX, text or image)."""
    notes = []
    digest = sha256_hex(data)
    for c in ctx.manifest.copies:
        if c.file_sha256 == digest:
            notes.append(f"berkas identik byte demi byte dengan salinan #{c.seq} (bukti pendukung)")
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise TraceError(f"{name}: bukan berkas PDF yang sah")
        try:
            obs = collect_from_pdf(data, ctx)
            raster_obs, raster_notes = collect_rasterized_pages(data, ctx, name)
        except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError is a RuntimeError
            raise TraceError(f"{name}: berkas PDF tidak dapat dibuka atau rusak") from exc
        obs += raster_obs
        notes += raster_notes
    elif suffix in (".txt", ".md", ""):
        text = decode_text_evidence(data)
        if "\ufffd" in text:
            notes.append(f"{name}: sebagian karakter tidak dapat diterjemahkan (pengodean teks tidak dikenal)")
        obs = collect_from_text(text, ctx)
    elif suffix == ".docx":  # leaked text pasted into a Word file
        from tapak.decoder.ch_docx import extract_docx_text

        try:
            text = extract_docx_text(data)
        except Exception as exc:  # noqa: BLE001 - zip/xml errors from a damaged file
            raise TraceError(f"{name}: berkas DOCX tidak dapat dibaca") from exc
        obs = collect_from_text(text, ctx)
    elif suffix in IMAGE_SUFFIXES:
        from tapak.decoder.image import collect_from_image

        obs = collect_from_image(data, ctx)
        if obs and all(sb.meta.get("registered") is False for sb in obs):
            notes.append(f"{name}: halaman dokumen induk tidak ditemukan pada gambar (bukan dokumen ini, "
                         "terlalu buram, atau terpotong)")
        else:
            reg = next((sb.meta for sb in obs if "correlation" in sb.meta), None)
            if reg:
                notes.append(f"{name}: dipetakan ke halaman {reg['page'] + 1} (metode {reg['method']}, "
                             f"korelasi {reg['correlation']:.3f}, resolusi efektif {reg['effective_dpi']:.0f} dpi)")
            bg = next((sb.meta for sb in obs if sb.channel == "background"), None)
            if bg is not None and not bg.get("pattern_found", True):
                notes.append(f"{name}: pola latar tidak terdeteksi (kertas cetak, foto terlalu terang, atau "
                             "bukan salinan bertanda); hanya kanal geser yang dipakai")
    else:
        raise TraceError(f"jenis berkas tidak dikenal: {suffix or '(tanpa akhiran)'}")
    return obs, notes


def trace_files(items: list[tuple[str, bytes]], ctx: TraceContext) -> tuple[Attribution, list[SoftBits]]:
    """Trace several evidence files of the same leak together (for example one photo per page
    of a printed copy): their observations are fused before the single accusation, so slices
    carried by different pages add up. The threshold covers the combined set."""
    obs: list[SoftBits] = []
    notes: list[str] = []
    for name, data in items:
        o, n = collect_file(name, data, ctx)
        obs += o
        notes += n
    if len(items) > 1:
        notes.insert(0, f"{len(items)} berkas bukti digabung dalam satu atribusi")
    return run_trace(obs, ctx, notes), obs


def trace_file(path: Path, ctx: TraceContext) -> tuple[Attribution, list[SoftBits]]:
    """Trace one evidence file (PDF, DOCX, text or image)."""
    path = Path(path)
    return trace_files([(path.name, path.read_bytes())], ctx)
