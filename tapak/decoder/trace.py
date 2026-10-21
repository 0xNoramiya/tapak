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
from tapak.marker.issue import IssueManifest, build_document_plan
from tapak.marker.layout import RowId, sha256_hex
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.pdf_shift import ShiftSettings
from tapak.marker.plan import EmbeddingPlan
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

    @property
    def shift(self) -> ShiftSettings:
        """Shift magnitudes used at issuance."""
        return self.manifest.shift_settings


def load_context(master_pdf: bytes, manifest: IssueManifest, secret: bytes) -> TraceContext:
    """Rebuild plan and codewords; refuse if the master or any commitment does not match."""
    master = load_master(master_pdf)
    if master.doc_hash != manifest.doc_hash:
        raise TraceError("dokumen induk tidak cocok dengan catatan penerbitan (hash berbeda)")
    params = manifest.tardos_params
    excluded = {tuple(r) for r in manifest.excluded_rows}
    plan = build_document_plan(master, params, secret, tuple(manifest.channels), excluded)  # type: ignore[arg-type]
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
    return TraceContext(master, manifest, params, plan, p, np.vstack(rows), refs, excluded)  # type: ignore[arg-type]


def collect_from_text(text: str, ctx: TraceContext) -> list[SoftBits]:
    """Channel 3 from pasted or retyped text (semantic channel added in M2)."""
    return decode_text(text, ctx.master, ctx.plan)


def collect_from_pdf(pdf_bytes: bytes, ctx: TraceContext) -> list[SoftBits]:
    """Channels readable from a forwarded PDF: shift (vector readout) and text layer."""
    return [decode_vector(pdf_bytes, ctx.master, ctx.plan, ctx.shift, ctx.excluded)] + collect_from_text(
        extract_pdf_text(pdf_bytes), ctx
    )


def run_trace(observations: list[SoftBits], ctx: TraceContext, notes: list[str] | None = None) -> Attribution:
    """Fuse, accuse, explain."""
    fused = fuse(observations, ctx.params.length)
    per_channel = fuse_by_physical_channel(observations, ctx.params.length)
    result = attribute(fused, per_channel, ctx.p, ctx.codewords, ctx.refs, ctx.params)
    result.notes = list(notes or []) + result.notes
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
    elif suffix in IMAGE_SUFFIXES:
        from tapak.decoder.image import collect_from_image  # M3

        obs = collect_from_image(data, ctx)
    else:
        raise TraceError(f"jenis berkas tidak dikenal: {suffix}")
    return run_trace(obs, ctx, notes), obs
