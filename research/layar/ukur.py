"""Screenshots rendered by real PDF renderers: measurements behind batasan 5 in docs/keamanan.md.

A simulation study with real renderers. The pages are drawn by the libraries PDF viewers use,
not by the screenshot simulator of ``tapak/photos.py`` (which downsamples a 200 dpi render):

* ``mupdf``: MuPDF through pymupdf (``Page.get_pixmap`` at the zoom's resolution, default
  anti-aliasing), as in SumatraPDF, mupdf and zathura-mupdf;
* ``poppler``: Poppler's Splash rasterizer through ``pdftoppm -aa yes -aaVector yes`` (font and
  vector anti-aliasing on, FreeType hinting off), as in Okular and qpdfview with their default
  settings. pdftoppm 24.02 has no hinting option, so the text hinting setting of Okular (off by
  default) is not covered;
* ``poppler_tanpa_aa``: the same with ``-aa no -aaVector no`` (anti-aliasing switched off);
* ``cairo``: Poppler's Cairo backend through ``pdftocairo`` (default anti-aliasing), as in
  Evince, GNOME Papers, Atril and Xreader.

The protocol and every seed are fixed here, before any run (``PROTOCOL``):

* Two fictional masters, ``samples/nota_dinas.pdf`` and ``samples/surat_telegram.pdf``, each
  issued with ``tapak issue --benih-riset`` (code secret and copy ids from a public research
  seed, no registry, no canary) to N = 20 recipients (c = 3, eps = 1e-6, default background
  profile), once with shift scheme geser-v2 (``--geser v2``, the default) and once with geser-v1
  (``--geser v1``) under the same seed: same code secret, copy ids and codewords, so a v1 image
  and a v2 image of one job differ only in the issued copy. Evidence is page 1.
* Two disjoint seed sets: ``dev`` (development; every decoder choice is made on it) and ``uji``
  (held out; generated and traced once, at the end). Each has its own research seeds, so its
  code secrets and codewords are new.
* A job is (document, scheme, renderer, resolution, capture format, framing, copy). Resolution
  is the effective resolution of the page in the image, ``RESOLUTIONS``, 28 to 150 dpi: a laptop
  viewer at fit page (about 60 to 85 dpi), at 100 % (72 or 96 dpi) and zoomed in, a phone at fit
  width (about 90 to 130 dpi) and two-page or thumbnail views (below 50 dpi). Capture formats:
  - ``png``: the screen capture saved losslessly (what Android, iOS, Windows and GNOME save);
  - ``pesan``: the capture sent through a messenger: long side limited to 1600 px (area
    interpolation), JPEG quality 68 to 72, forwarded once more at 58 to 62 (like the screenshot
    simulator of ``tapak/photos.py``);
  - ``kecil``: the page drawn at 1.5 times the resolution (a high-density screen) and the
    capture downscaled by the messenger to the effective resolution (area interpolation), then
    limited and compressed as ``pesan``.
  Framings: ``utuh`` (the page only), ``bingkai`` (the page inside viewer chrome: window
  background, toolbar, page border and shadow, light or dark theme), ``potong_atas`` and
  ``potong_tengah`` (a viewport showing 55 % of the page height, from the top or from 25 %
  down, inside viewer chrome: a zoomed-in view).
* Grids (``PROTOCOL["grids"]``): ``utama`` crosses the three main renderers, every resolution and
  the three formats with whole-page framings (utuh and bingkai alternate over the copies);
  ``tanpa_aa`` is Poppler without anti-aliasing (png and pesan); ``potong`` are partial
  viewports at 64 to 150 dpi (png and pesan); ``induk`` are captures of the unmarked masters,
  traced against both issuances of the split: nobody may be accused.
* Every image is traced as ``make bench`` does (not logged in a registry, all of eps, one stage)
  through the production path (``collect_from_gray``). The same observations are accused three
  times: all channels (``semua``), the shift channel only (``geser``) and the background channel
  only (``latar``). Verdicts: ``benar`` (exactly the leaked copy), ``tidak cukup bukti``,
  ``salah`` (anyone else; anyone at all for an unmarked master). Per image: positions read and
  bit errors against the leaked copy's codeword (sign of the LLR) for shift rows, shift word
  groups and background, the confidently wrong bits (abs LLR >= 2 and >= 4), the score of the
  leaked copy and the highest innocent score as multiples of the threshold, the false
  accusation bound, the erasure warning, and per kind the LLR weight bins of
  ``research/deteksi/llr_foto.py`` (w = tanh(abs(L) / 2), 21 bins) with the wrong bits per bin.
* Floors (``PROTOCOL["floor_rule"]``, fixed before the run): per renderer, format and channel
  set, the floor is the lowest grid resolution from which every whole-page image at that and
  every higher resolution names the leaked copy.

The registration and the word displacements of every image are kept (``obs/``) so decoder
candidates can be compared on the development set without registering again
(``research/layar/kandidat.py``). Evidence images, issuances and observations go to
``$TAPAK_LAYAR_KERJA`` (default ``out/riset_layar``; large, not committed); the JSON lines quoted
in the docs go to ``research/layar/hasil/``. Process pools are capped at 3 workers, BLAS and
OpenCV at one thread each (shared machine). Usage, from the repository root:

    python research/layar/ukur.py terbit          # issuances of both splits and schemes
    python research/layar/ukur.py lacak --split dev
    python research/layar/ukur.py lacak --split uji   # once, at the end
    python research/layar/ukur.py ringkas --split uji
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the working tree's tapak, not an installed copy

WORK = Path(os.environ.get("TAPAK_LAYAR_KERJA") or ROOT / "out" / "riset_layar")
HASIL = ROOT / "research" / "layar" / "hasil"
WORKERS = 3
DOCS = ("nota_dinas", "surat_telegram")
SCHEMES = ("v2", "v1")
RENDERERS = ("mupdf", "poppler", "cairo", "poppler_tanpa_aa")
MAIN_RENDERERS = ("mupdf", "poppler", "cairo")
FORMATS = ("png", "pesan", "kecil")
FRAMINGS = ("utuh", "bingkai", "potong_atas", "potong_tengah")
RESOLUTIONS = (28, 32, 40, 48, 56, 64, 72, 84, 96, 120, 150)
KINDS = ("baris", "kata", "latar")
LONG_SIDE = 1600
KECIL_FACTOR = 1.5
VIEWPORT = 0.55   # share of the page height a partial viewport shows
CONFIDENT = (2.0, 4.0)

PROTOCOL: dict = {
    "n": 20, "c": 3, "eps": 1e-6, "page": 1,
    "issue": ("tapak issue --benih-riset BENIH --no-registry --canary-domain '' --workers 3 --geser v2 atau v1, "
              "profil latar bawaan; v1 dan v2 dengan benih yang sama (kode dan id salinan sama)"),
    "benih_riset": {"dev": {"nota_dinas": 7501, "surat_telegram": 7502},
                    "uji": {"nota_dinas": 7601, "surat_telegram": 7602}},
    "evidence_seed": {"dev": 7511, "uji": 7611},
    "unmarked_seed": {"dev": 7599, "uji": 7699},
    "renderers": {
        "mupdf": "pymupdf Page.get_pixmap(matrix=R/72, csGRAY), anti-aliasing bawaan (8 bit)",
        "poppler": "pdftoppm -r R -gray -png -aa yes -aaVector yes (Splash, FreeType tanpa hinting)",
        "poppler_tanpa_aa": "pdftoppm -r R -gray -png -aa no -aaVector no",
        "cairo": "pdftocairo -r R -gray -png (antialias bawaan)",
    },
    "resolutions_dpi": list(RESOLUTIONS),
    "formats": {
        "png": "tangkapan tanpa kompresi (PNG)",
        "pesan": "sisi panjang paling besar 1600 px (INTER_AREA), JPEG mutu 68 sampai 72 lalu 58 sampai 62",
        "kecil": "halaman digambar pada 1,5 R, tangkapan diperkecil ke R (INTER_AREA), lalu seperti pesan",
    },
    "framings": {
        "utuh": "halaman saja",
        "bingkai": "halaman di dalam jendela penampil (latar, bilah alat, tepi dan bayangan halaman; tema terang "
                   "atau gelap diundi)",
        "potong_atas": "jendela penampil yang memperlihatkan 55 % tinggi halaman dari atas",
        "potong_tengah": "sama, mulai 25 % tinggi halaman",
    },
    "grids": {
        "dev": {
            "utama": {"renderers": list(MAIN_RENDERERS), "resolutions": list(RESOLUTIONS), "formats": list(FORMATS),
                      "copies": {"v2": [1, 8, 15], "v1": [1, 8]}, "framings": ["utuh", "bingkai"]},
            "tanpa_aa": {"renderers": ["poppler_tanpa_aa"], "resolutions": list(RESOLUTIONS),
                         "formats": ["png", "pesan"], "copies": {"v2": [1, 8]}, "framings": ["utuh", "bingkai"]},
            "potong": {"renderers": list(MAIN_RENDERERS), "resolutions": [64, 84, 96, 120, 150],
                       "formats": ["png", "pesan"], "copies": {"v2": [1, 8]},
                       "framings": ["potong_atas", "potong_tengah"]},
            "induk": {"renderers": list(MAIN_RENDERERS), "resolutions": [32, 56, 96, 150], "formats": ["png", "pesan"],
                      "reps": 1, "framings": ["utuh"]},
        },
        "uji": {
            "utama": {"renderers": list(MAIN_RENDERERS), "resolutions": list(RESOLUTIONS), "formats": list(FORMATS),
                      "copies": {"v2": [2, 5, 9, 12, 16, 19], "v1": [2, 9, 16]}, "framings": ["utuh", "bingkai"]},
            "tanpa_aa": {"renderers": ["poppler_tanpa_aa"], "resolutions": list(RESOLUTIONS),
                         "formats": ["png", "pesan"], "copies": {"v2": [2, 9, 16]}, "framings": ["utuh", "bingkai"]},
            "potong": {"renderers": list(MAIN_RENDERERS), "resolutions": [64, 84, 96, 120, 150],
                       "formats": ["png", "pesan"], "copies": {"v2": [2, 9, 16, 19]},
                       "framings": ["potong_atas", "potong_tengah"]},
            "induk": {"renderers": list(MAIN_RENDERERS), "resolutions": [32, 56, 96, 150], "formats": ["png", "pesan"],
                      "reps": 2, "framings": ["utuh"]},
        },
    },
    "framing_design": "salinan ke-k dalam daftar salinan grid (mulai 0): framings[k % len(framings)]",
    "generators": ("default_rng([benih bukti, indeks dokumen, indeks penggambar, R, indeks format, indeks bingkai, "
                   "s (induk: 1000 + ulangan)]); skema tidak ikut, jadi gambar v1 dan v2 satu pekerjaan berbagi "
                   "bingkai dan mutu JPEG"),
    "trace": "seperti make bench: tanpa registri, seluruh eps, satu tahap; collect_from_gray (jalur produksi)",
    "accusations": {"semua": "semua kanal", "geser": "kanal geser saja", "latar": "kanal latar saja"},
    "confident_llr": list(CONFIDENT),
    "floor_rule": ("per penggambar, format, dan kumpulan kanal: resolusi grid terendah yang mulai dari sana setiap "
                   "gambar halaman utuh (utuh dan bingkai) pada resolusi itu dan semua resolusi di atasnya menyebut "
                   "salinan yang bocor; ditetapkan sebelum dijalankan"),
    "spending": "tidak dicatat (seluruh eps), satu tahap, seperti make bench",
}


# --- issuance ------------------------------------------------------------------------------


def _tapak(*args: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    run = subprocess.run([sys.executable, "-m", "tapak.cli", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"tapak {' '.join(args[:2])} gagal: {run.stderr.strip()[-400:]}")
    return run.stdout


def issuance_dir(split: str, doc: str, scheme: str) -> Path:
    return WORK / split / f"{doc}_{scheme}"


def issue(split: str, doc: str, scheme: str) -> dict:
    """Issue one (split, document, scheme) with the CLI, once; returns its summary."""
    folder = issuance_dir(split, doc, scheme)
    seed = PROTOCOL["benih_riset"][split][doc]
    if not list((folder / "data" / "dokumen").glob("*/manifest.json")):
        folder.mkdir(parents=True, exist_ok=True)
        _tapak("--data", str(folder / "data"), "--keys", str(folder / "keys"), "issue", str(ROOT / "samples" / f"{doc}.pdf"),
               str(ROOT / "samples" / "recipients.csv"), "--no-registry", "--canary-domain", "", "--workers",
               str(WORKERS), "--benih-riset", str(seed), "--geser", scheme)
    ctx, manifest, _ = context(split, doc, scheme)
    from tapak.marker.plan import CHANNEL_SHIFT

    slots = ctx.plan.channel(CHANNEL_SHIFT)
    page = PROTOCOL["page"] - 1
    return {"split": split, "doc": doc, "scheme": scheme, "benih_riset": seed, "copies": len(manifest.copies),
            "shift_scheme": manifest.shift_settings.scheme, "plan_summary": manifest.plan_summary,
            "page1_shift_slots": {"baris": sum(1 for s in slots if s.page == page and len(s.ref) == 1),
                                  "kata": sum(1 for s in slots if s.page == page and len(s.ref) == 2)},
            "copy_ids_sha256": hashlib.sha256(",".join(c.copy_id for c in manifest.copies).encode()).hexdigest(),
            "codewords_sha256": hashlib.sha256(ctx.codewords.tobytes()).hexdigest()}


# --- rendering and capture -----------------------------------------------------------------


def render(pdf: bytes, page: int, dpi: float, renderer: str) -> np.ndarray:
    """Page ``page`` (0-based) of ``pdf`` drawn by ``renderer`` at ``dpi``, as uint8 gray."""
    import cv2

    if renderer == "mupdf":
        import pymupdf

        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0), colorspace=pymupdf.csGRAY,
                                       alpha=False)
            return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    (WORK / "tmp").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK / "tmp") as tmp:
        src, out = Path(tmp) / "in.pdf", Path(tmp) / "out"
        src.write_bytes(pdf)
        common = ["-r", f"{dpi:g}", "-f", str(page + 1), "-l", str(page + 1), "-singlefile", "-gray", "-png"]
        if renderer == "cairo":
            cmd = ["pdftocairo", *common, str(src), str(out)]
        else:
            aa = "no" if renderer == "poppler_tanpa_aa" else "yes"
            cmd = ["pdftoppm", *common, "-aa", aa, "-aaVector", aa, str(src), str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
        img = cv2.imread(str(out) + ".png", cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"{renderer} tidak menghasilkan gambar")
    return img


def frame(page_img: np.ndarray, framing: str, rng: np.random.Generator, scale: float = 1.0) -> tuple[np.ndarray, dict]:
    """The screen capture of a rendered page: the page alone, or the page (or a part of it) in viewer
    chrome. ``scale`` multiplies the chrome sizes (device pixels of a high-density screen)."""
    h, w = page_img.shape
    meta: dict = {"framing": framing}
    if framing == "utuh":
        return page_img, meta
    dark = bool(rng.random() < 0.5)
    background = int(rng.integers(45, 80)) if dark else int(rng.integers(195, 220))
    bar_level = int(rng.integers(30, 50)) if dark else int(rng.integers(225, 245))
    bar_h = int(round(rng.integers(36, 65) * scale))
    side = int(round(rng.integers(16, 81) * scale))
    gap = int(round(rng.integers(8, 25) * scale))
    meta.update(dark=dark, background=background, bar=bar_level, bar_px=bar_h, side_px=side, gap_px=gap)
    if framing == "bingkai":
        y0, y1, top_gap, bottom_gap = 0, h, gap, int(round(rng.integers(8, 41) * scale))
    else:
        view = int(round(VIEWPORT * h))
        y0 = 0 if framing == "potong_atas" else int(round(0.25 * h))
        y1 = min(h, y0 + view)
        top_gap = gap if framing == "potong_atas" else 0
        bottom_gap = 0
    meta.update(page_rows=[y0, y1])
    part = page_img[y0:y1]
    ph = part.shape[0]
    canvas = np.full((bar_h + top_gap + ph + bottom_gap, w + 2 * side), background, dtype=np.uint8)
    canvas[:bar_h] = bar_level
    button = 200 if dark else 90
    import cv2

    for b in range(int(rng.integers(3, 8))):
        x = int(12 * scale) + b * (bar_h + int(6 * scale))
        if x + bar_h - int(12 * scale) < canvas.shape[1]:
            cv2.rectangle(canvas, (x, int(8 * scale)), (x + bar_h - int(16 * scale), bar_h - int(9 * scale)), button,
                          thickness=max(1, int(round(2 * scale))))
    ox, oy = side, bar_h + top_gap
    shadow = max(0, background - 35)
    canvas[oy + 3:oy + ph + 3, ox + 3:ox + w + 3] = shadow
    canvas[oy:oy + ph, ox:ox + w] = part
    cv2.rectangle(canvas, (ox - 1, oy - 1), (ox + w, oy + ph), 150, thickness=1)
    return canvas, meta


def _area_resize(img: np.ndarray, factor: float) -> np.ndarray:
    import cv2

    new = (max(1, int(round(img.shape[1] * factor))), max(1, int(round(img.shape[0] * factor))))
    return cv2.resize(img, new, interpolation=cv2.INTER_AREA)


def _double_jpeg(img: np.ndarray, rng: np.random.Generator, meta: dict) -> bytes:
    import cv2

    q1, q2 = int(rng.integers(68, 73)), int(rng.integers(58, 63))
    meta.update(jpeg_quality_1=q1, jpeg_quality_2=q2)
    ok, first = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q1])
    again = cv2.imdecode(first, cv2.IMREAD_GRAYSCALE)
    ok, data = cv2.imencode(".jpg", again, [cv2.IMWRITE_JPEG_QUALITY, q2])
    return data.tobytes()


def capture(pdf: bytes, job: dict, rng: np.random.Generator) -> tuple[bytes, dict]:
    """The evidence file of a job (PNG or JPEG bytes) and its ground truth."""
    import cv2

    page = PROTOCOL["page"] - 1
    r = float(job["dpi"])
    device = r * KECIL_FACTOR if job["fmt"] == "kecil" else r
    img = render(pdf, page, device, job["renderer"])
    canvas, meta = frame(img, job["framing"], rng, scale=device / r)
    meta.update(device_dpi=device, page_px=[int(img.shape[1]), int(img.shape[0])])
    factor = 1.0
    if job["fmt"] == "kecil":
        factor = 1.0 / KECIL_FACTOR
        canvas = _area_resize(canvas, factor)
    if job["fmt"] in ("pesan", "kecil") and max(canvas.shape) > LONG_SIDE:
        f = LONG_SIDE / max(canvas.shape)
        canvas = _area_resize(canvas, f)
        factor *= f
    meta.update(effective_dpi=round(device * factor, 2), image_px=[int(canvas.shape[1]), int(canvas.shape[0])])
    if job["fmt"] == "png":
        ok, data = cv2.imencode(".png", canvas)
        return data.tobytes(), meta
    return _double_jpeg(canvas, rng, meta), meta


# --- jobs ----------------------------------------------------------------------------------


def jobs_for(split: str) -> list[dict]:
    """Every job of a split, in a fixed order."""
    grids = PROTOCOL["grids"][split]
    out = []
    for grid, g in grids.items():
        for doc in DOCS:
            for renderer in g["renderers"]:
                for dpi in g["resolutions"]:
                    for fmt in g["formats"]:
                        if grid == "induk":
                            for rep in range(g["reps"]):
                                out.append({"split": split, "grid": grid, "doc": doc, "scheme": None, "renderer": renderer,
                                            "dpi": dpi, "fmt": fmt, "framing": g["framings"][0], "seq": None,
                                            "rep": rep})
                            continue
                        for scheme, copies in g["copies"].items():
                            for k, seq in enumerate(copies):
                                out.append({"split": split, "grid": grid, "doc": doc, "scheme": scheme,
                                            "renderer": renderer, "dpi": dpi, "fmt": fmt,
                                            "framing": g["framings"][k % len(g["framings"])], "seq": seq})
    return out


def job_key(job: dict) -> str:
    who = f"s{job['seq']:03d}" if job["seq"] is not None else f"induk{job['rep']}"
    scheme = job["scheme"] or "induk"
    return f"{job['grid']}_{job['doc']}_{scheme}_{job['renderer']}_{job['dpi']}_{job['fmt']}_{job['framing']}_{who}"


def job_rng(job: dict) -> np.random.Generator:
    who = job["seq"] if job["seq"] is not None else 1000 + job["rep"]
    seed = PROTOCOL["unmarked_seed" if job["seq"] is None else "evidence_seed"][job["split"]]
    return np.random.default_rng([seed, DOCS.index(job["doc"]), RENDERERS.index(job["renderer"]), int(job["dpi"]),
                                  FORMATS.index(job["fmt"]), FRAMINGS.index(job["framing"]), who])


def evidence(job: dict) -> tuple[bytes, dict]:
    """The evidence file of a job (cached on disk with its truth)."""
    path = WORK / "bukti" / job["split"] / f"{job_key(job)}.bin"
    meta_path = path.with_suffix(".json")
    if path.exists() and meta_path.exists():
        return path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
    if job["seq"] is None:
        pdf = (ROOT / "samples" / f"{job['doc']}.pdf").read_bytes()
    else:
        _, manifest, folder = context(job["split"], job["doc"], job["scheme"])
        pdf = (folder / "salinan" / manifest.copies[job["seq"] - 1].file).read_bytes()
    data, meta = capture(pdf, job, job_rng(job))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return data, meta


# --- worker side ---------------------------------------------------------------------------

_CTX: dict = {}
_CAUGHT: dict = {}


def _init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    import cv2

    cv2.setNumThreads(1)
    _watch()


def _watch() -> None:
    """Keep the registration and the word displacements of the production path (no change to it)."""
    import tapak.decoder.image as image_mod

    if getattr(image_mod, "_layar_watch", False):
        return
    register, measure = image_mod.register, image_mod.measure_image

    def register_kept(*a, **k):
        reg = register(*a, **k)
        _CAUGHT["reg"] = reg
        return reg

    def measure_kept(*a, **k):
        disp = measure(*a, **k)
        _CAUGHT["disp"] = disp
        return disp

    image_mod.register, image_mod.measure_image = register_kept, measure_kept
    image_mod._layar_watch = True


def context(split: str, doc: str, scheme: str):
    """(trace context, manifest, workspace folder) of an issuance, cached per process."""
    key = (split, doc, scheme)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest

        root = issuance_dir(split, doc, scheme)
        folder = next((root / "data" / "dokumen").glob("*/manifest.json")).parent
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        secret = load_code_secret(root / "keys" / "code_secret.key")
        _CTX[key] = (load_context((folder / "induk.pdf").read_bytes(), manifest, secret, folder=folder), manifest,
                     folder)
    return _CTX[key]


def shift_kinds(ctx) -> dict[int, str]:
    """Code position -> 'baris' or 'kata' for the shift slots of a context."""
    from tapak.marker.plan import CHANNEL_SHIFT

    return {s.positions[0]: ("baris" if len(s.ref) == 1 else "kata") for s in ctx.plan.channel(CHANNEL_SHIFT)}


def bit_stats(obs, ctx, x: np.ndarray | None) -> dict:
    """Per kind (rows, word groups, background): read, wrong, confidently wrong, sum w^2, weight bins."""
    kinds = shift_kinds(ctx)
    out: dict = {}
    for kind in KINDS:
        channel = "background" if kind == "latar" else "shift"
        sb = next((o for o in obs if o.channel == channel), None)
        if sb is None or not len(sb):
            out[kind] = {"read": 0}
            continue
        if kind == "latar":
            sel = np.ones(len(sb), dtype=bool)
        else:
            sel = np.array([kinds.get(int(p)) == kind for p in sb.positions], dtype=bool)
        llr = sb.llr[sel]
        w = np.tanh(np.abs(llr) / 2.0)
        d = {"read": int(sel.sum()), "sum_w2": round(float(np.sum(w ** 2)), 2)}
        if x is not None and sel.any():
            bad = (llr > 0).astype(int) != x[sb.positions[sel]]
            d["wrong"] = int(bad.sum())
            for c in CONFIDENT:
                d[f"wrong_llr{int(c)}"] = int((bad & (np.abs(llr) >= c)).sum())
                d[f"read_llr{int(c)}"] = int((np.abs(llr) >= c).sum())
            k = np.clip(np.ceil(w * 20.0).astype(int), 0, 20)
            d["bins_n"] = np.bincount(k, minlength=21).tolist()
            d["bins_wrong"] = np.bincount(k, weights=bad.astype(float), minlength=21).astype(int).tolist()
            d["bins_wsum"] = [round(v, 3) for v in np.bincount(k, weights=w, minlength=21).tolist()]
        out[kind] = d
    sb = next((o for o in obs if o.channel == "shift"), None)
    if sb is not None:
        out["sigma_pt"] = {k: round(float(v), 5) for k, v in (sb.meta.get("sigma_pt") or {}).items()}
        out["slots_implausible"] = sb.meta.get("slots_implausible")
    bg = next((o for o in obs if o.channel == "background"), None)
    if bg is not None:
        out["pattern_found"] = bg.meta.get("pattern_found")
    return out


def verdict(obs, ctx, expected: int | None) -> dict:
    """Accuse with the fixed rule (all of eps, one stage) and compare with the leaked copy."""
    from tapak.decoder.trace import run_trace

    a = run_trace(obs, ctx)
    accused = sorted(c.copy.seq for c in a.accused)
    if not accused:
        v = "tidak cukup bukti"
    elif expected is not None and accused == [expected]:
        v = "benar"
    else:
        v = "salah"
    z = a.threshold.threshold
    scores = {c.copy.seq: c.score for c in a.candidates}
    innocent = [s for k, s in scores.items() if k != expected]
    finite = bool(np.isfinite(z) and z > 0)
    return {"verdict": v, "accused": accused, "n_observed": int(a.threshold.n_observed),
            "score_z": round(scores.get(expected, 0.0) / z, 4) if finite and expected is not None else None,
            "max_innocent_z": round(max(innocent) / z, 4) if finite and innocent else None,
            "log10_fa": round(a.accused[0].log10_false_accusation, 2) if a.accused else None,
            "erasure_flagged": bool(a.erasure.flagged) if a.erasure is not None else None}


def accusations(obs, ctx, expected: int | None) -> dict:
    """Verdicts with all channels, the shift channel only and the background channel only."""
    return {"semua": verdict(obs, ctx, expected),
            "geser": verdict([o for o in obs if o.channel == "shift"], ctx, expected),
            "latar": verdict([o for o in obs if o.channel == "background"], ctx, expected)}


def save_obs(job: dict, scheme: str, obs, reg, disp) -> None:
    """Observations, registration and word displacements of one trace (for kandidat.py)."""
    arrays: dict = {}
    for k, sb in enumerate(obs):
        arrays[f"obs{k}_{sb.channel}_pos"] = sb.positions
        arrays[f"obs{k}_{sb.channel}_llr"] = sb.llr
    if reg is not None:
        arrays["reg_h"] = np.asarray(reg.h_page_to_img, dtype=np.float64)
        arrays["reg_meta"] = np.array([reg.page, reg.dpi, reg.effective_dpi, reg.correlation], dtype=np.float64)
    if disp:
        ids = sorted(disp)
        arrays["disp_ids"] = np.array(ids, dtype=np.int32).reshape(-1, 3)
        arrays["disp_xy"] = np.array([disp[i] for i in ids], dtype=np.float64).reshape(-1, 2)
    path = WORK / "obs" / job["split"] / f"{job_key(job)}__{scheme}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def trace_one(job: dict, scheme: str, data: bytes) -> dict:
    """Decode the evidence of a job against the issuance of ``scheme`` and accuse."""
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.rectify import load_gray

    ctx, _, _ = context(job["split"], job["doc"], scheme)
    _CAUGHT.clear()
    t0 = time.perf_counter()
    obs = collect_from_gray(load_gray(data), ctx)
    seconds = round(time.perf_counter() - t0, 1)
    save_obs(job, scheme, obs, _CAUGHT.get("reg"), _CAUGHT.get("disp"))
    reg = next((o.meta for o in obs if "correlation" in o.meta), None)
    x = ctx.codewords[job["seq"] - 1] if job["seq"] is not None else None
    return {"against": scheme, "registered": reg is not None,
            "registration": ({"method": reg["method"], "dpi": reg["dpi"], "effective_dpi": reg["effective_dpi"],
                              "correlation": reg["correlation"], "page": reg["page"] + 1} if reg else None),
            "bits": bit_stats(obs, ctx, x), "accuse": accusations(obs, ctx, job["seq"]), "seconds": seconds}


def trace_job(job: dict) -> dict:
    """One job: make (or reuse) its evidence and trace it (an unmarked master against both schemes)."""
    data, truth = evidence(job)
    row = {k: job.get(k) for k in ("split", "grid", "doc", "scheme", "renderer", "dpi", "fmt", "framing", "seq", "rep")}
    row["truth"] = truth
    row["evidence_sha256"] = hashlib.sha256(data).hexdigest()
    row["evidence_bytes"] = len(data)
    schemes = [job["scheme"]] if job["scheme"] is not None else list(SCHEMES)
    row["traces"] = [trace_one(job, s, data) for s in schemes]
    return row


# --- driver --------------------------------------------------------------------------------


def _pool(fn, jobs: list[dict], out_path: Path) -> list[dict]:
    """Run jobs with WORKERS processes; rows are appended to ``out_path`` as they finish (a rerun
    skips the jobs already there)."""
    import multiprocessing as mp

    done = {job_key(r): r for r in _load(out_path)}
    todo = [j for j in jobs if job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            out_path.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(pool.map(fn, todo, chunksize=1)):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            done[job_key(r)] = r
            t = r["traces"][0]
            print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {job_key(r)}: "
                  + " ".join(f"{k}={v['verdict']}" for k, v in t["accuse"].items()), flush=True)
    return [done[job_key(j)] for j in jobs]


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def run_terbit() -> None:
    rows = [issue(split, doc, scheme) for split in ("dev", "uji") for doc in DOCS for scheme in SCHEMES]
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / "terbit.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                                        encoding="utf-8")
    proto = dict(PROTOCOL, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 versions=versions())
    (HASIL / "protokol.json").write_text(json.dumps(proto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in rows:
        print(json.dumps({k: r[k] for k in ("split", "doc", "scheme", "page1_shift_slots")}, ensure_ascii=False))


def versions() -> dict:
    """Renderer and library versions (the results depend on them)."""
    import cv2
    import pymupdf

    def first_line(cmd: list[str]) -> str:
        run = subprocess.run(cmd, capture_output=True, text=True)
        return (run.stdout + run.stderr).strip().splitlines()[0]

    return {"pymupdf": pymupdf.__version__, "mupdf": pymupdf.mupdf_version, "pdftoppm": first_line(["pdftoppm", "-v"]),
            "pdftocairo": first_line(["pdftocairo", "-v"]), "opencv": cv2.__version__, "numpy": np.__version__}


def run_lacak(split: str, again: bool) -> None:
    out = HASIL / f"{split}.jsonl"
    if split == "uji" and out.exists() and not again and len(_load(out)) >= len(jobs_for("uji")):
        raise SystemExit(f"{out} sudah lengkap: set uji dilacak sekali (pakai --ulang untuk menimpa)")
    if split == "uji":
        mark = HASIL / "uji_dekoder.json"
        if not mark.exists():
            mark.write_text(json.dumps(decoder_fingerprint(), indent=2) + "\n", encoding="utf-8")
    _pool(trace_job, jobs_for(split), out)


def decoder_fingerprint() -> dict:
    """Hashes of the decoder sources the held-out run used (written before the run)."""
    files = sorted((ROOT / "tapak" / "decoder").glob("*.py"))
    return {"git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "decoder_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("terbit")
    lc = sub.add_parser("lacak")
    lc.add_argument("--split", choices=("dev", "uji"), required=True)
    lc.add_argument("--ulang", action="store_true")
    rk = sub.add_parser("ringkas")
    rk.add_argument("--split", choices=("dev", "uji"), required=True)
    args = ap.parse_args(argv)
    if args.cmd == "terbit":
        run_terbit()
    elif args.cmd == "lacak":
        run_lacak(args.split, args.ulang)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ringkas import summarize  # noqa: PLC0415

        summarize(args.split)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
