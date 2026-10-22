"""Trace pipeline: evidence file in, attribution out.

``load_context`` rebuilds everything the decoder needs from the master PDF, the issuance
record and the code secret, and checks every regenerated codeword against the commitment
stored at issuance. The ``collect_*`` functions run the channel decoders that apply to an
input type; ``run_trace`` fuses and accuses with the false-accusation budget of this trace
(``TraceSpending``: trace number k of a document spends eps * 6 / (pi^2 k^2)).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tapak.decoder.accuse import VISIBLE_MARKS_NOTE, Attribution, CopyRef, attribute
from tapak.decoder.ch_shift import PageFrame
from tapak.decoder.ch_zerowidth import decode_text, extract_pdf_text
from tapak.decoder.erasure import erasure_check, erasure_note
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.decoder.softbits import SoftBits
from tapak.marker.issue import (
    IssueManifest,
    SemanticSelection,
    apply_shift_scheme,
    build_document_plan,
    lexical_exclusions,
)
from tapak.marker.layout import RowId, sha256_hex
from tapak.marker.lexical import LONE_LEAKER_BITS, LexicalSelection, format_count, words_for_bits
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.background import BackgroundSettings
from tapak.marker.pdf_shift import ShiftSettings
from tapak.marker.plan import CHANNEL_LEXICAL, PHYSICAL_CHANNEL, EmbeddingPlan, plan_key
from tapak.tardos.code import code_digest, derive_bias, derive_codeword
from tapak.tardos.params import TardosParams
from tapak.tardos.spending import TraceSpending

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TEXT_SUFFIXES = {".txt", ".md", ""}
EVIDENCE_SUFFIXES = {".pdf", ".docx"} | TEXT_SUFFIXES | IMAGE_SUFFIXES


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
    lexical: LexicalSelection | None = None
    lexical_ref: object | None = None  # ch_lexical.LexReference, built once per context

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


def load_lexical(folder: Path | None) -> LexicalSelection | None:
    """The reviewed lexical selection stored with the issuance (``leksikal.json``), if any.

    Looked up in ``folder`` and in its parent, like ``varian.json``.
    """
    if folder is None:
        return None
    import json

    for candidate in (Path(folder) / "leksikal.json", Path(folder).parent / "leksikal.json"):
        if candidate.exists():
            try:
                return LexicalSelection.from_dict(json.loads(candidate.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise TraceError(f"{candidate.name} rusak atau bukan berkas pilihan kata TAPAK") from exc
    return None


LEXICAL_SKIPPED = "kanal pilihan kata dilewati"


def _usable_lexical(lexical: LexicalSelection | None, manifest: IssueManifest, doc_hash: str,
                    warnings: list[str]) -> LexicalSelection | None:
    """The lexical selection if it is the one recorded at issuance; otherwise warn and skip it."""
    if not manifest.lexical_digest:
        return None
    if lexical is None:
        warnings.append(f"pilihan kata saat penerbitan (leksikal.json) tidak tersedia; {LEXICAL_SKIPPED}")
        return None
    rows, words = lexical_exclusions(manifest)
    if (lexical.digest != manifest.lexical_digest or lexical.doc_hash != doc_hash
            or lexical.shift_excluded_rows() != rows or lexical.excluded_words() != words):
        warnings.append(f"pilihan kata (leksikal.json) tidak cocok dengan catatan penerbitan; {LEXICAL_SKIPPED}")
        return None
    return lexical


SCAN_SHIFT_SKIPPED = "kanal geser halaman pindaian dilewati"


def attach_recorded_scans(master: MasterDocument, manifest: IssueManifest) -> str | None:
    """Give the scanned pages of the master their word boxes, as at issuance.

    The decoder needs the same rows the issuer planned on. They are found again with the same
    deterministic Tesseract call on the master page images and accepted only when their digest
    equals the one recorded at issuance (``manifest.scan``). Otherwise (another Tesseract
    version, missing language data, a different page set) the shift channel of the scanned
    pages is left out and a note says why: TAPAK does not guess where the words were. The
    background pattern does not depend on the boxes and is still read. Returns that note, or
    None when the boxes are attached or the document has no scanned pages.
    """
    record = manifest.scan
    if not record:
        return None
    from tapak.marker.raster import OcrUnavailable, attach_scan_layout, boxes_digest, ocr_engine, scan_boxes

    if sorted(master.scans) != sorted(int(k) for k in record.get("pages", [])):  # type: ignore[union-attr]
        return f"{SCAN_SHIFT_SKIPPED}: halaman pindaian dokumen induk tidak sama dengan catatan penerbitan"
    try:
        boxes = scan_boxes(master)
    except (OcrUnavailable, RuntimeError, OSError) as exc:
        return f"{SCAN_SHIFT_SKIPPED}: kotak kata tidak dapat dibaca ulang ({exc})"
    if boxes_digest(master, boxes) != record.get("boxes_sha256"):
        return (f"{SCAN_SHIFT_SKIPPED}: kotak kata hasil Tesseract berbeda dari saat penerbitan (sekarang "
                f"{ocr_engine()}, saat penerbitan {record.get('ocr_engine')}); TAPAK tidak menebak letak kata, "
                "pola latar tetap dibaca")
    attach_scan_layout(master, boxes)
    return None


def load_context(master_pdf: bytes, manifest: IssueManifest, secret: bytes,
                 semantic: SemanticSelection | None = None, folder: Path | None = None,
                 lexical: LexicalSelection | None = None) -> TraceContext:
    """Rebuild plan and codewords; refuse if the master or any commitment does not match.

    The semantic channel needs the approved variant sets used at issuance; they are taken
    from ``semantic`` or from ``folder/varian.json`` and checked against the digest in the
    manifest. Without them the semantic channel is skipped (with a warning). The lexical
    channel likewise needs ``lexical`` or ``folder/leksikal.json`` with the recorded digest;
    on a mismatch it is skipped with a warning, and every other channel is still read with
    the exclusions recorded in the manifest. Scanned pages get their word boxes back through
    :func:`attach_recorded_scans` (a warning, and no shift channel there, when they drifted).
    """
    try:
        master = load_master(master_pdf)
    except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError is a RuntimeError
        raise TraceError("dokumen induk tidak dapat dibuka (bukan PDF yang sah atau rusak)") from exc
    if master.doc_hash != manifest.doc_hash:
        raise TraceError("dokumen induk tidak cocok dengan catatan penerbitan (hash berbeda)")
    apply_shift_scheme(master, manifest.shift_settings.scheme)
    params = manifest.tardos_params
    excluded = {tuple(r) for r in manifest.excluded_rows}
    background = manifest.background_settings
    warnings: list[str] = []
    scan_note = attach_recorded_scans(master, manifest)
    if scan_note:
        warnings.append(scan_note)
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
    if lexical is None and manifest.lexical_digest:
        lexical = load_lexical(folder)
    lexical = _usable_lexical(lexical, manifest, master.doc_hash, warnings)
    shift_rows, text_words = lexical_exclusions(manifest)
    retype = {"retype_positions": manifest.retype_positions, "shift_excluded_rows": shift_rows,
              "text_excluded_words": text_words, "shift_scheme": manifest.shift_settings.scheme}
    try:
        plan = build_document_plan(master, params, secret, tuple(manifest.channels), excluded,  # type: ignore[arg-type]
                                   background, semantic, lexical, **retype)  # type: ignore[arg-type]
    except ValueError:
        warnings.append("varian semantik tidak cocok dengan catatan penerbitan; kanal semantik dilewati")
        semantic = None
        plan = build_document_plan(master, params, secret, tuple(manifest.channels), excluded,  # type: ignore[arg-type]
                                   background, None, lexical, **retype)  # type: ignore[arg-type]
    lexical_ref = None
    if lexical is not None and plan.channel(CHANNEL_LEXICAL):
        from tapak.decoder.ch_lexical import LexReference

        lexical_ref = LexReference(master, lexical.carrying())
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
                        warnings=warnings, lexical=lexical, lexical_ref=lexical_ref)


def collect_from_text(text: str, ctx: TraceContext) -> list[SoftBits]:
    """Channels readable from text: the text layer (channel 3), semantic variants (channel 4) and,
    for a document that uses it, word choice (channel 6)."""
    obs = decode_text(text, ctx.master, ctx.plan)
    if ctx.semantic is not None and ctx.plan.channel("semantic"):
        from tapak.decoder.ch_semantic import decode_semantic

        obs.append(decode_semantic(text, ctx.semantic.units, ctx.semantic.sets, ctx.plan.channel("semantic")))
    if ctx.lexical is not None and ctx.lexical_ref is not None and ctx.plan.channel(CHANNEL_LEXICAL):
        from tapak.decoder.ch_lexical import decode_lexical

        obs.append(decode_lexical(text, ctx.lexical_ref, ctx.lexical.points,  # type: ignore[arg-type]
                                  ctx.plan.channel(CHANNEL_LEXICAL)))
    return obs


def _num(value: float, decimals: int) -> str:
    """A number with the Indonesian decimal comma, for notes."""
    return f"{value:.{decimals}f}".replace(".", ",")


def pdf_frames(pdf_bytes: bytes, ctx: TraceContext) -> dict[int, "PageFrame"]:
    """Evidence page -> master page and fitted frame (scale, offset, invisible OCR text)."""
    from tapak.decoder.ch_shift import invisible_text_pages, page_frames
    from tapak.marker.layout import extract_layout

    return page_frames(ctx.master.layout, extract_layout(pdf_bytes), invisible_text_pages(pdf_bytes))


def collect_background_from_pdf(pdf_bytes: bytes, ctx: TraceContext, dpi: float = 100.0,
                                frames: dict[int, "PageFrame"] | None = None) -> list[SoftBits]:
    """Channel 2 from a forwarded PDF: render each page that lies exactly in the master's frame
    (same paper, not scaled or moved); other pages are read from a registered image instead."""
    if ctx.background is None or not ctx.plan.channel("background"):
        return []

    from tapak.decoder.ch_background import decode_background
    from tapak.decoder.rectify import render_page
    from tapak.marker.background import page_grids

    frames = pdf_frames(pdf_bytes, ctx) if frames is None else frames
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    grids = page_grids(sizes, ctx.key, ctx.background)
    parts = []
    for li, f in frames.items():
        if f.invisible or not f.in_master_frame:
            continue
        img = render_page(pdf_bytes, li, dpi, supersample=1, cache=False)
        master = render_page(ctx.master.pdf_bytes, f.master_page, dpi, supersample=1)
        if img.shape != master.shape:
            continue  # another paper size: the cell grid would not line up
        parts.append(decode_background(img, np.ones(img.shape, dtype=bool), master, dpi, grids[f.master_page],
                                       ctx.plan.channel("background")))
    return [SoftBits.concat("background", parts, pages=len(parts))] if parts else []


def collect_from_pdf(pdf_bytes: bytes, ctx: TraceContext,
                     frames: dict[int, "PageFrame"] | None = None) -> list[SoftBits]:
    """Channels readable from a forwarded PDF: shifts (vector readout, in the master's frame),
    background (render), text layer and semantic variants."""
    from tapak.decoder.ch_shift import decode_displacements, match_words
    from tapak.marker.layout import extract_layout

    frames = pdf_frames(pdf_bytes, ctx) if frames is None else frames
    disp = match_words(ctx.master.layout, extract_layout(pdf_bytes), frames)
    return ([decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)]
            + collect_background_from_pdf(pdf_bytes, ctx, frames=frames)
            + collect_from_text(extract_pdf_text(pdf_bytes), ctx))


RASTER_DPI = 200.0
RASTER_MAX_PIXELS = 25_000_000      # one rendered page
RASTER_TRACE_PIXELS = 60_000_000    # all rendered pages of one trace together
RASTER_GIVE_UP_AFTER = 2            # consecutive pages of a file that match no master page


@dataclass
class RasterBudget:
    """How many PDF pages one trace may still render and decode as images."""

    pages: int
    pixels: float = RASTER_TRACE_PIXELS

    @classmethod
    def for_context(cls, ctx: TraceContext) -> "RasterBudget":
        """Twice the master's page count, at least 4."""
        return cls(pages=max(4, 2 * len(ctx.master.layout.pages)))


def collect_rasterized_pages(pdf_bytes: bytes, ctx: TraceContext, name: str,
                             frames: dict[int, "PageFrame"] | None = None,
                             budget: RasterBudget | None = None) -> tuple[list[SoftBits], list[str]]:
    """PDF pages the vector readout cannot use, decoded as images.

    A page with no text matching the master, or with an invisible OCR layer over a scan, is
    rendered and decoded like a photo. A page whose text matches but is scaled, moved or on
    another paper size keeps its shifts from the (frame-corrected) vector readout; only the
    background, whose cell grid would not line up, is taken from the rendered image. Rendering
    is bounded per trace (``budget``) and stops after pages that match nothing.
    """
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.rectify import render_page
    from tapak.marker.layout import extract_layout

    layout = extract_layout(pdf_bytes)
    frames = pdf_frames(pdf_bytes, ctx) if frames is None else frames
    budget = RasterBudget.for_context(ctx) if budget is None else budget
    obs: list[SoftBits] = []
    notes: list[str] = []
    todo = []
    for page in layout.pages:
        f = frames.get(page.index)
        if f is None or f.invisible:
            todo.append((page, None, "tanpa lapisan teks yang cocok" if f is None else "lapisan teks OCR"))
            continue
        mp = ctx.master.layout.pages[f.master_page]
        resized = abs(page.width - mp.width) > 1 or abs(page.height - mp.height) > 1
        if ctx.background is not None and (resized or not f.in_master_frame):
            todo.append((page, {"background"}, "diperkecil, digeser, atau ukuran kertas berbeda"))
    misses = 0
    for k, (page, keep, why) in enumerate(todo):
        area_in2 = max(page.width * page.height, 1.0) / 72.0**2
        dpi = min(RASTER_DPI, (RASTER_MAX_PIXELS / area_in2) ** 0.5)
        pixels = area_in2 * dpi * dpi
        if budget.pages <= 0 or budget.pixels < pixels:
            notes.append(f"{name}: {len(todo) - k} halaman tidak dibaca sebagai gambar (batas pembacaan gambar "
                         "per pelacakan tercapai)")
            break
        if misses >= RASTER_GIVE_UP_AFTER:
            notes.append(f"{name}: {len(todo) - k} halaman berikutnya dilewati; halaman sebelumnya tidak cocok "
                         "dengan dokumen induk")
            break
        budget.pages -= 1
        budget.pixels -= pixels
        found = [sb for sb in collect_from_gray(render_page(pdf_bytes, page.index, dpi, supersample=1, cache=False),
                                                ctx)
                 if keep is None or sb.channel in keep]
        reg = next((sb.meta for sb in found if "correlation" in sb.meta), None)
        if reg is None:
            misses += 1
            if keep is None:
                notes.append(f"{name} halaman {page.index + 1}: tidak memiliki lapisan teks yang cocok dan "
                             "tidak dikenali sebagai halaman dokumen induk")
            continue
        misses = 0
        obs += found
        kind = "halaman pindaian, " if reg["page"] in ctx.master.scans else ""
        notes.append(f"{name} halaman {page.index + 1}: dibaca sebagai gambar ({why}), dipetakan ke halaman "
                     f"{reg['page'] + 1} ({kind}korelasi {_num(reg['correlation'], 3)})")
    return obs, notes


# Physical channels whose marks survive retyping. They are also the marks a reader can see on
# paper, so anyone who has read a copy can copy them.
RETYPE_PHYSICAL = frozenset({"semantik", "leksikal"})


def retyped_text_note(observations: list[SoftBits], attribution: Attribution,
                      body_words: int | None = None, lexical_bits: int | None = None) -> str | None:
    """Plain note when only retype-surviving channels (semantic, word choice) were read and they
    carry fewer bits than the lone-leaker level; None otherwise (also when someone was named).

    ``body_words`` and ``lexical_bits`` (the document's body words and issued lexical bits)
    turn the missing bits into an indicative word count. The note explains a "tidak cukup
    bukti" verdict; it never changes the threshold.
    """
    read = {PHYSICAL_CHANNEL.get(sb.channel, sb.channel) for sb in observations if len(sb)}
    if not read or not read <= RETYPE_PHYSICAL or attribution.accused:
        return None
    bits = attribution.threshold.n_observed
    if bits >= LONE_LEAKER_BITS:
        return None
    doc = f" Dokumen ini memuat {format_count(body_words)} kata isi." if body_words else ""
    words = format_count(words_for_bits(LONE_LEAKER_BITS, body_words, lexical_bits))
    return (f"tidak cukup bukti: bukti ini hanya memuat tanda yang bertahan saat diketik ulang (pilihan kata dan "
            f"varian kalimat), {bits} bit. TAPAK baru menyebut satu pembocor dari teks ketikan ulang mulai "
            f"{LONE_LEAKER_BITS} bit, kira-kira dokumen dengan {words} kata isi.{doc}")


def visible_marks_note(observations: list[SoftBits], attribution: Attribution, ctx: TraceContext,
                       spending: TraceSpending | None = None) -> str | None:
    """Caveat when a named copy is named only thanks to marks visible on paper; None otherwise.

    Word choice and sentence variants can be read off a printed copy. A leaker who has seen
    another recipient's copy can retype the leak with that copy's forms, and the text then
    carries that copy's marks: the statistics name it correctly as the source of the word
    choices, not as the typist. The caveat is added when some accused copy is not accused by
    the other channels alone (always the case when only these channels were read). The check
    reruns the same code-blind accusation on the other channels with the same budget and
    stages (a copy named at a later stage is checked too); it never changes the verdict or
    the threshold.
    """
    if not attribution.accused:
        return None
    visible = [sb for sb in observations if len(sb) and PHYSICAL_CHANNEL.get(sb.channel, sb.channel) in RETYPE_PHYSICAL]
    if not visible:
        return None
    hidden = [sb for sb in observations
              if len(sb) and PHYSICAL_CHANNEL.get(sb.channel, sb.channel) not in RETYPE_PHYSICAL]
    named: set[int] = set()
    if hidden:
        m = ctx.params.length
        alone = attribute(fuse(hidden, m), fuse_by_physical_channel(hidden, m), ctx.p, ctx.codewords, ctx.refs,
                          ctx.params, spending)
        named = alone.named_seqs
    only_visible = [c.copy.seq for _, c in attribution.named if c.copy.seq not in named]
    if not only_visible:
        return None
    return "salinan " + ", ".join(f"#{k}" for k in only_visible) + ": " + VISIBLE_MARKS_NOTE


def run_trace(observations: list[SoftBits], ctx: TraceContext, notes: list[str] | None = None,
              spending: TraceSpending | None = None) -> Attribution:
    """Fuse, accuse, explain. ``spending`` is this trace's part of eps (None: not logged, all of eps).

    The erasure check (``decoder/erasure.py``) runs on the same observations with the bias
    vector only; when it flags the evidence, a warning is added to the notes. It never changes
    the verdict, a threshold or a score, and never names anyone.
    """
    fused = fuse(observations, ctx.params.length)
    per_channel = fuse_by_physical_channel(observations, ctx.params.length)
    result = attribute(fused, per_channel, ctx.p, ctx.codewords, ctx.refs, ctx.params, spending)
    result.notes = list(ctx.warnings) + list(notes or []) + result.notes
    result.erasure = erasure_check(observations, ctx.p)
    if result.erasure.flagged:
        result.notes.append(erasure_note(result.erasure))
    if ctx.plan.channel(CHANNEL_LEXICAL):  # documents without the channel keep their output unchanged
        lexical_bits = sum(len(s.positions) for s in ctx.plan.channel(CHANNEL_LEXICAL))
        body_words = ctx.lexical.body_words if ctx.lexical is not None else None
        for note in (retyped_text_note(observations, result, body_words, lexical_bits),
                     visible_marks_note(observations, result, ctx, spending)):
            if note is not None:
                result.notes.append(note)
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


def check_evidence_types(names: list[str]) -> None:
    """Refuse (TraceError) an evidence file whose type no decoder reads, before anything is
    logged or decoded: a file that cannot be read should not use up a trace number."""
    for name in names:
        suffix = Path(name).suffix.lower()
        if suffix not in EVIDENCE_SUFFIXES:
            raise TraceError(f"jenis berkas tidak dikenal: {suffix}")


def collect_file(name: str, data: bytes, ctx: TraceContext,
                 budget: RasterBudget | None = None) -> tuple[list[SoftBits], list[str]]:
    """Observations and notes from one evidence file (PDF, DOCX, text or image). ``budget``
    bounds the PDF pages rendered as images (shared by all files of one trace)."""
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
            frames = pdf_frames(data, ctx)
            obs = collect_from_pdf(data, ctx, frames=frames)
            raster_obs, raster_notes = collect_rasterized_pages(data, ctx, name, frames=frames, budget=budget)
        except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError is a RuntimeError
            raise TraceError(f"{name}: berkas PDF tidak dapat dibuka atau rusak") from exc
        obs += raster_obs
        notes += raster_notes
    elif suffix in TEXT_SUFFIXES:
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
                             f"korelasi {_num(reg['correlation'], 3)}, resolusi efektif {reg['effective_dpi']:.0f} dpi)")
            bg = next((sb.meta for sb in obs if sb.channel == "background"), None)
            if bg is not None and not bg.get("pattern_found", True):
                notes.append(f"{name}: pola latar tidak terdeteksi (kertas cetak, foto terlalu terang, atau "
                             "bukan salinan bertanda); hanya kanal geser yang dipakai")
    else:
        raise TraceError(f"jenis berkas tidak dikenal: {suffix or '(tanpa akhiran)'}")
    return obs, notes


def trace_files(items: list[tuple[str, bytes]], ctx: TraceContext,
                spending: TraceSpending | None = None) -> tuple[Attribution, list[SoftBits]]:
    """Trace several evidence files of the same leak together (for example one photo per page
    of a printed copy): their observations are fused before the single accusation, so slices
    carried by different pages add up. The threshold covers the combined set and uses this
    trace's part of eps (``spending``; None: a trace that is not logged spends all of eps)."""
    obs: list[SoftBits] = []
    notes: list[str] = []
    budget = RasterBudget.for_context(ctx)
    for name, data in items:
        o, n = collect_file(name, data, ctx, budget)
        obs += o
        notes += n
    if len(items) > 1:
        notes.insert(0, f"{len(items)} berkas bukti digabung dalam satu atribusi")
    return run_trace(obs, ctx, notes, spending), obs


def trace_file(path: Path, ctx: TraceContext,
               spending: TraceSpending | None = None) -> tuple[Attribution, list[SoftBits]]:
    """Trace one evidence file (PDF, DOCX, text or image)."""
    path = Path(path)
    return trace_files([(path.name, path.read_bytes())], ctx, spending)
