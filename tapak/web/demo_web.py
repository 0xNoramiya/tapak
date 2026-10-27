"""The guided demo of the web UI (``/demo``).

Everything happens in a sandbox next to the operator's data, ``<data>/demo/<visitor>`` (own
registry, own code secret and signing key), so the demo never touches the real registry or keys.
Each visitor (the ``demo`` cookie) has a sandbox of their own, so visitors at the same time do
not replace each other's copies:

1. the sample nota dinas is issued to the 20 fictional sample recipients, with the semantic
   variants approved by a simulated reviewer, as in ``tapak demo``;
2. one copy "leaks" through a simulated medium (phone photo, screenshot, photo of a monitor,
   a cropped screenshot, the forwarded PDF, or its copied text);
3. the leak is traced like any evidence on the Lacak page.

All documents, names and evidence are synthetic.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import time
from pathlib import Path

import numpy as np

from tapak.config import Settings
from tapak.i18n import N_, localize

DEMO_DIR = "demo"
MARKER = ".tapak-demo"
VISITOR = re.compile(r"[0-9a-f]{16}")  # a visitor id: the value of the demo cookie
SANDBOX_TTL_S = 6 * 3600  # a sandbox older than this is removed at the next demo issuance
MAX_SANDBOXES = 30        # and only the newest are kept
ISSUER = "Kasi Ops Brigif 9905 (fiktif)"
SAMPLE = "nota_dinas.pdf"
RECIPIENTS = "recipients.csv"
# medium key -> (label, what happens, icon); the texts are translated where they are shown
MEDIA: dict[str, tuple[str, str, str]] = {
    "foto": (N_("Difoto dengan ponsel"), N_("Halaman 1 difoto miring dengan bayangan dan sedikit buram, lalu dikirim "
                                           "lewat aplikasi pesan."), "camera"),
    "layar": (N_("Tangkapan layar"), N_("Halaman 1 dibuka di penampil PDF, ditangkap layarnya, lalu dikompresi "
                                        "aplikasi pesan."), "monitor"),
    "monitor": (N_("Foto layar monitor"), N_("Salinan ditampilkan di monitor, lalu layarnya difoto dengan ponsel."),
                "image"),
    "potong": (N_("Potongan halaman"), N_("Hanya bagian tengah halaman 1 yang ditangkap layarnya."), "scan"),
    "pdf": (N_("PDF diteruskan"), N_("Berkas salinan dikirim apa adanya."), "file-text"),
    "teks": (N_("Teks disalin"), N_("Isi dokumen disalin dari PDF dan ditempel ke percakapan."), "type"),
}


def demo_root(base: Settings, visitor: str) -> Path:
    """The sandbox folder of one visitor (16 hexadecimal characters; anything else is refused,
    so a cookie cannot point outside ``<data>/demo``)."""
    if not VISITOR.fullmatch(visitor):
        raise ValueError(f"id pengunjung demo tidak sah: {visitor!r}")
    return base.data_dir / DEMO_DIR / visitor


def demo_settings(base: Settings, visitor: str) -> Settings:
    """Settings of a visitor's sandbox: ``data`` and ``keys`` in :func:`demo_root`, no anchor log."""
    root = demo_root(base, visitor)
    return dataclasses.replace(base, data_dir=root / "data", key_dir=root / "keys", signing_key=None,
                               public_key=None, anchor_log=None)


def demo_manifest(base: Settings, visitor: str):
    """The visitor's sandbox issuance (an ``IssueManifest``), or None when there is none yet."""
    from tapak.service import list_workspaces

    s = demo_settings(base, visitor)
    if not s.workspaces.exists():
        return None
    docs = list_workspaces(s)
    return docs[0] if docs else None


def prune_sandboxes(base: Settings, keep: str, now: float | None = None) -> list[str]:
    """Remove the sandboxes of other visitors that are older than :data:`SANDBOX_TTL_S` or beyond
    the newest :data:`MAX_SANDBOXES`, and the single shared sandbox of earlier versions. Only
    folders that carry the demo marker are removed. Returns the visitor ids removed."""
    parent = base.data_dir / DEMO_DIR
    if not parent.is_dir():
        return []
    if (parent / MARKER).exists():  # the shared sandbox of earlier versions: data/ and keys/
        for name in ("data", "keys"):
            shutil.rmtree(parent / name, ignore_errors=True)
        (parent / MARKER).unlink()
    now = time.time() if now is None else now
    boxes = sorted(((d / MARKER).stat().st_mtime, d.name) for d in parent.iterdir()
                   if VISITOR.fullmatch(d.name) and d.name != keep and (d / MARKER).is_file())
    stale = [name for i, (made, name) in enumerate(reversed(boxes))
             if now - made > SANDBOX_TTL_S or i >= MAX_SANDBOXES - 1]
    for name in stale:
        shutil.rmtree(parent / name)
    return stale


def issue_demo(base: Settings, visitor: str):
    """Issue the sample nota dinas to the 20 sample recipients in a fresh sandbox of ``visitor``.

    Returns (manifest, seconds). The visitor's earlier sandbox is removed first, but only a
    folder that carries the demo marker: a folder the demo did not create is never deleted.
    Stale sandboxes of other visitors go too (:func:`prune_sandboxes`)."""
    from tapak.demo import samples_dir
    from tapak.llm.provider import get_provider
    from tapak.marker.issue import IssueSettings, SemanticSelection, read_recipients
    from tapak.marker.master import load_master
    from tapak.marker.semantic import STATUS_APPROVED, find_candidate_units, generate_variant_set
    from tapak.service import ensure_keys, issue_document

    root = demo_root(base, visitor)
    prune_sandboxes(base, keep=visitor)
    if root.exists():
        if not (root / MARKER).exists():
            raise FileExistsError(f"{root} bukan folder demo TAPAK; folder itu tidak disentuh")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / MARKER).write_text("folder demo TAPAK; boleh dihapus\n", encoding="utf-8")
    s = demo_settings(base, visitor)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    samples = samples_dir()
    t0 = time.perf_counter()
    keys = ensure_keys(s)
    sample = samples / SAMPLE
    master = load_master(sample.read_bytes())
    provider = get_provider("mock")
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, provider) for u in units]
    for vs in sets:  # the simulated reviewer of tapak demo: every variant approved
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED)
    out = issue_document(s, sample, read_recipients(samples / RECIPIENTS), IssueSettings(canary_domain=s.canary_domain),
                         issuer=ISSUER, keys=keys, semantic=SemanticSelection(units, sets))
    return out.manifest, time.perf_counter() - t0


def copy_bytes(base: Settings, visitor: str, manifest, seq: int) -> bytes:
    """The PDF of copy ``seq`` (1-based) of the visitor's sandbox issuance."""
    from tapak.service import load_workspace

    _, _, folder = load_workspace(demo_settings(base, visitor), manifest.doc_hash)
    return (folder / "salinan" / manifest.copies[seq - 1].file).read_bytes()


def page_png(pdf: bytes, dpi: float) -> bytes:
    """Page 1 of a PDF as a PNG."""
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def difference_png(base: Settings, visitor: str, manifest, a: int, b: int, gain: float = 40.0) -> bytes:
    """Where copies ``a`` and ``b`` differ on page 1 (top half), amplified ``gain`` times: dark
    is no difference. Rendered at 100 dpi."""
    import cv2

    from tapak.marker.render import render_pages

    pa = render_pages(copy_bytes(base, visitor, manifest, a), 100, [0])[0].astype(np.float32)
    pb = render_pages(copy_bytes(base, visitor, manifest, b), 100, [0])[0].astype(np.float32)
    h = pa.shape[0] // 2
    diff = np.clip(np.abs(pa[:h] - pb[:h]) * gain, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", 255 - diff)
    if not ok:
        raise RuntimeError("gambar selisih tidak dapat dibuat")
    return buf.tobytes()


def leak(base: Settings, visitor: str, manifest, seq: int, medium: str, rng: np.random.Generator) -> tuple[str, bytes]:
    """(file name, bytes) of copy ``seq`` leaked through ``medium`` (a key of MEDIA)."""
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, ScreenshotParams, decode_jpeg, encode_jpeg, photo_jpeg, \
        screen_photo_jpeg, screenshot_jpeg
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    if medium not in MEDIA:
        raise ValueError(f"cara bocor tidak dikenal: {medium}")
    pdf = copy_bytes(base, visitor, manifest, seq)
    if medium == "pdf":
        return "salinan_bocor.pdf", pdf
    if medium == "teks":
        import pymupdf

        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            text = "\n".join(p.get_text() for p in doc)
        return "teks_disalin.txt", text.encode("utf-8")
    page = render_pages(pdf, 200, [0])[0]
    if medium == "foto":
        data, _ = photo_jpeg(page, rng, PhotoParams(angle_deg=float(rng.uniform(15.0, 25.0))))
        return "foto_bocor.jpg", data
    if medium == "monitor":
        isp_rng = np.random.default_rng(int(rng.integers(2**62)))
        data, _ = screen_photo_jpeg(page, rng, PhotoParams(angle_deg=10.0, long_side=1600), ScreenParams(),
                                    isp=ISP_PROFILES["ponsel"], isp_rng=isp_rng, render_dpi=200.0)
        return "foto_monitor.jpg", data
    data, _ = screenshot_jpeg(page, rng, ScreenshotParams(render_dpi=200.0, long_side=1600))
    if medium == "layar":
        return "tangkapan_layar.jpg", data
    img = decode_jpeg(data)  # potong: the middle of the screenshot only
    h = img.shape[0]
    crop = img[int(0.28 * h):int(0.72 * h)]
    return "potongan_layar.jpg", encode_jpeg(np.ascontiguousarray(crop), 70)


def evidence_preview(name: str, data: bytes) -> tuple[bytes, str]:
    """(bytes, media type) to show a piece of evidence: images as they are, page 1 of a PDF as
    a PNG, text as a PNG of its first lines."""
    if name.endswith(".jpg"):
        return data, "image/jpeg"
    if name.endswith(".pdf"):
        return page_png(data, 70), "image/png"
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    text = data.decode("utf-8", errors="replace")[:900]
    page.insert_textbox(pymupdf.Rect(16, 16, 404, 284), text, fontsize=8.5, fontname="cour")
    png = page.get_pixmap(dpi=144, alpha=False).tobytes("png")
    doc.close()
    return png, "image/png"


def size_label(n: int) -> str:
    """'412 KB' or '1,2 MB' (1.2 MB in English)."""
    if n >= 1_000_000:
        return localize(f"{n / 1_000_000:.1f} MB".replace(".", ","))
    return f"{max(1, round(n / 1000))} KB"
