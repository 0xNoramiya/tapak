"""Visible text of image evidence: local Tesseract OCR for the semantic and word-choice readers.

Sentence variants (channel 4) and word choices (channel 6) are words printed on the page. They
survive printing, photographing and screenshots like any text, while the default background
pattern never reaches paper. So once the image path has found a master page in a photo,
screenshot or scanned copy (``rectify.register``), that page is read with the local Tesseract
and its text goes to the same readers as pasted text (``ch_semantic.decode_semantic``,
``ch_lexical.decode_lexical``), restricted to the slots of that page. Their soft bits are
reported as the sub-channels ``semantic_ocr`` and ``lexical_ocr``, which belong to the physical
channels "semantik" and "leksikal" (the same printed words as the text reads).

Rules:

* only these two readers ever see OCR text. The text-layer channel (zero-width symbols,
  look-alike letters) never does: OCR cannot see invisible symbols and reads look-alike
  letters as plain Latin, so its output says nothing about those marks;
* the readers stay code-blind: the page, its slots, the master text and the variant sets
  decide everything, never a recipient's codeword. A phrase that OCR garbled is an erasure,
  not a confident wrong read: both readers drop a unit or point whose closest variant is too
  far from the text or whose alignment shows dense edits at the phrase (cut, reworded or
  unreadable), and give a low LLR to clustered edits;
* the OCR settings (page segmentation, resolution, preprocessing) were chosen on development
  seeds only (``research/ocr``) and are fixed in ``DEFAULT_OCR``;
* data minimization: Tesseract reads the page image from stdin and writes the text to stdout
  (no temporary files), the text lives only in memory for the two readers, and is never
  logged, stored or put into diagnostics. ``SoftBits.meta`` holds counts, ids, the page and
  the OCR time only;
* without Tesseract (or its Indonesian language data) the trace proceeds without these
  sub-channels, and ``trace.trace_files`` adds one note saying so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import cv2
import numpy as np

from tapak.decoder.softbits import SoftBits
from tapak.marker.plan import (
    CHANNEL_LEXICAL,
    CHANNEL_LEXICAL_OCR,
    CHANNEL_SEMANTIC,
    CHANNEL_SEMANTIC_OCR,
    Slot,
)

if TYPE_CHECKING:
    from tapak.decoder.rectify import Registration
    from tapak.decoder.trace import TraceContext

OCR_LANGUAGES = ("ind", "eng")  # Indonesian is required, English is added when installed
OCR_TIMEOUT_S = 120
FLATTEN_SIGMA_IN = 0.25  # smoothing of the paper brightness estimate (inches) for ``flatten``
OCR_SKIPPED = "varian kalimat dan pilihan kata pada gambar tidak dibaca"


@dataclass(frozen=True)
class OcrSettings:
    """How a registered image page is read.

    Attributes:
        psm: Tesseract page segmentation mode (3 automatic, 4 one column, 6 one block).
        dpi: None reads the registration's rectified page at its analysis resolution (100 to
            300 dpi, close to the image's own); a number resamples the evidence image into the
            page frame at that resolution (cubic), for a larger x-height.
        flatten: divide the page by a smooth estimate of the paper brightness first (shadows,
            vignetting, uneven exposure).
    """

    psm: int = 3
    dpi: float | None = None
    flatten: bool = False


# Chosen on the development seeds of research/ocr with the rule fixed before the run (its README,
# hasil/pilihan.json): automatic segmentation on the flattened rectified page read 778 of 780
# printed bits with none wrong over 96 development images; without flattening 701, at 300 dpi 709.
DEFAULT_OCR = OcrSettings(psm=3, dpi=None, flatten=True)


class OcrUnavailable(RuntimeError):
    """Tesseract or its Indonesian language data is not installed."""


@lru_cache(maxsize=1)
def ocr_languages() -> str:
    """Tesseract language argument ("ind+eng" or "ind"); OcrUnavailable without "ind"."""
    exe = shutil.which("tesseract")
    if exe is None:
        raise OcrUnavailable("Tesseract tidak terpasang")
    try:
        run = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OcrUnavailable(f"Tesseract tidak dapat dijalankan ({type(exc).__name__})") from exc
    installed = set(((run.stdout or "") + (run.stderr or "")).split())
    if OCR_LANGUAGES[0] not in installed:
        raise OcrUnavailable("data bahasa Indonesia Tesseract (tesseract-ocr-ind) tidak terpasang")
    return "+".join(lang for lang in OCR_LANGUAGES if lang in installed)


def ocr_unavailable_reason() -> str | None:
    """None when OCR can run; otherwise why not, in Indonesian."""
    try:
        ocr_languages()
    except OcrUnavailable as exc:
        return str(exc)
    return None


def recognize(image: np.ndarray, dpi: float, psm: int = DEFAULT_OCR.psm) -> str:
    """Text Tesseract reads on a grayscale page image (0..255).

    One process per call, one thread (``OMP_THREAD_LIMIT=1``), LSTM engine, stated resolution.
    The image goes in through stdin and the text comes back through stdout, so neither is
    written to disk. The caller keeps the text in memory only. Raises OcrUnavailable without
    Tesseract and RuntimeError when Tesseract fails or times out.
    """
    langs = ocr_languages()
    ok, png = cv2.imencode(".png", np.ascontiguousarray(np.clip(image, 0, 255), dtype=np.uint8),
                           [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise RuntimeError("pengodean gambar untuk Tesseract gagal")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    cmd = [shutil.which("tesseract") or "tesseract", "stdin", "stdout", "-l", langs, "--oem", "1",
           "--psm", str(int(psm)), "--dpi", str(int(round(dpi)))]
    try:
        run = subprocess.run(cmd, input=png.tobytes(), capture_output=True, env=env, timeout=OCR_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Tesseract tidak selesai dalam {OCR_TIMEOUT_S} detik") from exc
    except OSError as exc:
        raise RuntimeError(f"Tesseract tidak dapat dijalankan ({type(exc).__name__})") from exc
    if run.returncode != 0:
        raise RuntimeError("Tesseract gagal membaca halaman")
    return run.stdout.decode("utf-8", errors="replace")


def page_image(gray: np.ndarray, reg: "Registration", page_size_pt: tuple[float, float],
               settings: OcrSettings = DEFAULT_OCR) -> tuple[np.ndarray, float]:
    """(image, dpi): the registered page as Tesseract reads it, in the master page frame.

    Pixels outside the evidence image (a cropped photo) are set to white instead of the
    replicated border the registration uses, so they hold no streaks that look like letters.
    """
    from tapak.decoder.rectify import flatten_illumination, warp_to_page

    if settings.dpi is None:
        img, valid, dpi = reg.rectified, reg.valid, float(reg.dpi)
    else:
        dpi = float(settings.dpi)
        s = dpi / float(reg.dpi)
        h = reg.h_page_to_img @ np.diag([1.0 / s, 1.0 / s, 1.0])
        size = (int(round(page_size_pt[0] * dpi / 72.0)), int(round(page_size_pt[1] * dpi / 72.0)))
        img, valid = warp_to_page(np.asarray(gray, dtype=np.float32), h, size)
    img = np.asarray(img, dtype=np.float32)
    if settings.flatten:
        img = 255.0 * np.clip(flatten_illumination(img, FLATTEN_SIGMA_IN * dpi), 0.0, 1.0)
    out = np.clip(img, 0, 255).astype(np.uint8)
    out[~valid] = 255
    return out, dpi


def ocr_applies(ctx: "TraceContext") -> bool:
    """True when the issuance carries semantic or word-choice marks the decoder can read."""
    semantic = ctx.semantic is not None and bool(ctx.plan.channel(CHANNEL_SEMANTIC))
    lexical = ctx.lexical is not None and ctx.lexical_ref is not None and bool(ctx.plan.channel(CHANNEL_LEXICAL))
    return semantic or lexical


def page_slots(ctx: "TraceContext", page: int) -> tuple[list[Slot], list[Slot]]:
    """(semantic slots, lexical slots) printed on master page ``page`` that this context can read."""
    semantic = [s for s in ctx.plan.channel(CHANNEL_SEMANTIC) if s.page == page] if ctx.semantic is not None else []
    lexical = ([s for s in ctx.plan.channel(CHANNEL_LEXICAL) if s.page == page]
               if ctx.lexical is not None and ctx.lexical_ref is not None else [])
    return semantic, lexical


def read_page_text(text: str, page: int, ctx: "TraceContext") -> list[SoftBits]:
    """Soft bits of the semantic and word-choice marks of master page ``page`` found in ``text``
    (the OCR text of that page), as ``semantic_ocr`` and ``lexical_ocr``.

    Only the slots printed on that page are read, the word-choice reference holds that page's
    rows only, and the readers are the ones for pasted text, unchanged. A sub-channel with no
    slot on the page is left out. ``text`` is not kept anywhere.
    """
    from tapak.decoder.ch_lexical import LexReference, decode_lexical
    from tapak.decoder.ch_semantic import decode_semantic

    sem_slots, lex_slots = page_slots(ctx, page)
    out: list[SoftBits] = []
    if sem_slots and ctx.semantic is not None:
        sb = decode_semantic(text, ctx.semantic.units, ctx.semantic.sets, sem_slots)
        out.append(SoftBits(CHANNEL_SEMANTIC_OCR, sb.positions, sb.llr, sb.meta))
    if lex_slots and ctx.lexical is not None:
        ref = LexReference(ctx.master, ctx.lexical.carrying(), pages={page})
        sb = decode_lexical(text, ref, ctx.lexical.points, lex_slots)
        out.append(SoftBits(CHANNEL_LEXICAL_OCR, sb.positions, sb.llr, sb.meta))
    return out


def read_visible_text(gray: np.ndarray, reg: "Registration", ctx: "TraceContext",
                      settings: OcrSettings = DEFAULT_OCR) -> list[SoftBits]:
    """OCR one registered page and read its semantic and word-choice marks.

    Returns nothing when the page carries no such slot or Tesseract is not available (the
    trace notes the latter once). When Tesseract fails on the page, each sub-channel is
    reported empty with ``ocr_failed`` so the page counts as examined and unread. Diagnostics
    hold the readers' counts and ids, ``page``, ``ocr_seconds`` and ``source`` = "ocr".
    """
    sem_slots, lex_slots = page_slots(ctx, reg.page)
    if not (sem_slots or lex_slots) or ocr_unavailable_reason() is not None:
        return []
    names = [n for n, slots in ((CHANNEL_SEMANTIC_OCR, sem_slots), (CHANNEL_LEXICAL_OCR, lex_slots)) if slots]
    p = ctx.master.layout.pages[reg.page]
    image, dpi = page_image(gray, reg, (p.width, p.height), settings)
    t0 = time.perf_counter()
    try:
        text = recognize(image, dpi, settings.psm)
    except (OcrUnavailable, RuntimeError):
        return [SoftBits.empty(n, page=reg.page, source="ocr", ocr_failed=True) for n in names]
    seconds = round(time.perf_counter() - t0, 2)
    del image
    out = read_page_text(text, reg.page, ctx)
    del text
    for sb in out:
        sb.meta.update(page=reg.page, source="ocr", ocr_seconds=seconds)
    return out
