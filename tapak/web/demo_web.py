"""The guided demo of the web UI (``/demo``).

Everything happens in a sandbox next to the operator's data, ``<data>/demo`` (own registry,
own code secret and signing key), so the demo never touches the real registry or keys:

1. the sample nota dinas is issued to the 20 fictional sample recipients, with the semantic
   variants approved by a simulated reviewer, as in ``tapak demo``;
2. one copy "leaks" through a simulated medium (phone photo, screenshot, photo of a monitor,
   a cropped screenshot, the forwarded PDF, or its copied text);
3. the leak is traced like any evidence on the Lacak page.

All documents, names and evidence are synthetic.
"""

from __future__ import annotations

import dataclasses
import shutil
import time
from pathlib import Path

import numpy as np

from tapak.config import Settings

DEMO_DIR = "demo"
MARKER = ".tapak-demo"
ISSUER = "Kasi Ops Brigif 9905 (fiktif)"
SAMPLE = "nota_dinas.pdf"
RECIPIENTS = "recipients.csv"
# medium key -> (label, what happens, icon)
MEDIA: dict[str, tuple[str, str, str]] = {
    "foto": ("Difoto dengan ponsel", "Halaman 1 difoto miring dengan bayangan dan sedikit buram, lalu dikirim lewat "
             "aplikasi pesan.", "camera"),
    "layar": ("Tangkapan layar", "Halaman 1 dibuka di penampil PDF, ditangkap layarnya, lalu dikompresi aplikasi "
              "pesan.", "monitor"),
    "monitor": ("Foto layar monitor", "Salinan ditampilkan di monitor, lalu layarnya difoto dengan ponsel.", "image"),
    "potong": ("Potongan halaman", "Hanya bagian tengah halaman 1 yang ditangkap layarnya.", "scan"),
    "pdf": ("PDF diteruskan", "Berkas salinan dikirim apa adanya.", "file-text"),
    "teks": ("Teks disalin", "Isi dokumen disalin dari PDF dan ditempel ke percakapan.", "type"),
}


def demo_settings(base: Settings) -> Settings:
    """Settings of the sandbox: ``<data>/demo/data`` and ``<data>/demo/keys``, no anchor log."""
    root = base.data_dir / DEMO_DIR
    return dataclasses.replace(base, data_dir=root / "data", key_dir=root / "keys", signing_key=None,
                               public_key=None, anchor_log=None)


def demo_root(base: Settings) -> Path:
    """The sandbox folder."""
    return base.data_dir / DEMO_DIR


def demo_manifest(base: Settings):
    """The sandbox issuance (an ``IssueManifest``), or None when there is none yet."""
    from tapak.service import list_workspaces

    s = demo_settings(base)
    if not s.workspaces.exists():
        return None
    docs = list_workspaces(s)
    return docs[0] if docs else None


def issue_demo(base: Settings):
    """Issue the sample nota dinas to the 20 sample recipients in a fresh sandbox.

    Returns (manifest, seconds). An earlier sandbox is removed first, but only a folder that
    carries the demo marker: a folder the demo did not create is never deleted."""
    from tapak.demo import samples_dir
    from tapak.llm.provider import get_provider
    from tapak.marker.issue import IssueSettings, SemanticSelection, read_recipients
    from tapak.marker.master import load_master
    from tapak.marker.semantic import STATUS_APPROVED, find_candidate_units, generate_variant_set
    from tapak.service import ensure_keys, issue_document

    root = demo_root(base)
    if root.exists():
        if not (root / MARKER).exists():
            raise FileExistsError(f"{root} bukan folder demo TAPAK; folder itu tidak disentuh")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / MARKER).write_text("folder demo TAPAK; boleh dihapus\n", encoding="utf-8")
    s = demo_settings(base)
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


def copy_bytes(base: Settings, manifest, seq: int) -> bytes:
    """The PDF of copy ``seq`` (1-based) of the sandbox issuance."""
    from tapak.service import load_workspace

    _, _, folder = load_workspace(demo_settings(base), manifest.doc_hash)
    return (folder / "salinan" / manifest.copies[seq - 1].file).read_bytes()


def page_png(pdf: bytes, dpi: float) -> bytes:
    """Page 1 of a PDF as a PNG."""
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def difference_png(base: Settings, manifest, a: int, b: int, gain: float = 40.0) -> bytes:
    """Where copies ``a`` and ``b`` differ on page 1 (top half), amplified ``gain`` times: dark
    is no difference. Rendered at 100 dpi."""
    import cv2

    from tapak.marker.render import render_pages

    pa = render_pages(copy_bytes(base, manifest, a), 100, [0])[0].astype(np.float32)
    pb = render_pages(copy_bytes(base, manifest, b), 100, [0])[0].astype(np.float32)
    h = pa.shape[0] // 2
    diff = np.clip(np.abs(pa[:h] - pb[:h]) * gain, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", 255 - diff)
    if not ok:
        raise RuntimeError("gambar selisih tidak dapat dibuat")
    return buf.tobytes()


def leak(base: Settings, manifest, seq: int, medium: str, rng: np.random.Generator) -> tuple[str, bytes]:
    """(file name, bytes) of copy ``seq`` leaked through ``medium`` (a key of MEDIA)."""
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, ScreenshotParams, decode_jpeg, encode_jpeg, photo_jpeg, \
        screen_photo_jpeg, screenshot_jpeg
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    if medium not in MEDIA:
        raise ValueError(f"cara bocor tidak dikenal: {medium}")
    pdf = copy_bytes(base, manifest, seq)
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
    """'412 KB' or '1,2 MB'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB".replace(".", ",")
    return f"{max(1, round(n / 1000))} KB"
