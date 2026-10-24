"""Registration of partial and low-resolution evidence: measurements behind batasan 5 in docs/keamanan.md.

The screenshot study (``research/layar``) found that registration, not decoding, sets the floor:
every whole-page miss was a page that was not found (28 to 32 dpi; 48 dpi for Poppler Splash
without anti-aliasing), a viewer window showing the middle 55 % of the page was not found on 60 of
120 captures, and every page that was found named the right copy. Leakers often send a crop of a
paragraph or a phone photo of part of a page. This study measures which evidence fails to
register and which stage gives up (page outline, SIFT features, Tesseract words, ECC refinement,
page choice), then measures the rescue stage chosen on development seeds (``tapak/decoder/
rectify.py``, ``rescue_register``) on held-out seeds, before and after.

Evidence (``PROTOCOL["grids"]``), both fictional sample documents, both pages, shift scheme
geser-v2, N = 20, issued with ``tapak issue --benih-riset`` (no registry, no canary):

* ``potong``: screenshot crops drawn by the real renderers of ``research/layar`` (MuPDF, Poppler
  Splash, Poppler Cairo): the top, the middle or the bottom of the page, 25 to 100 % of its
  height, full page width, with or without viewer chrome (alternating), at 48 to 150 dpi, saved as
  PNG or sent through a messenger (``pesan``: long side at most 1600 px, JPEG twice);
* ``paragraf``: a crop of one paragraph (its rows plus a margin of 3 to 12 pt, no chrome);
* ``rendah``: whole pages at 24 to 48 dpi (the page alone or in viewer chrome, alternating), the
  four renderers, PNG, ``pesan`` and ``kecil`` (drawn at 1.5 times the resolution and downscaled
  by the messenger) as in ``research/layar``;
* ``foto``: a phone photo of the whole page (``tapak.photos.photo_jpeg``, 0 to 30 degrees, the
  camera's JPEG at quality 90 to 95, half of them through the phone ISP), cropped by the user to the
  top, middle or bottom 25 to 70 % of the page or to one paragraph, then sent through a messenger;
* ``induk``: the unmarked masters through every evidence type above, traced against the issuance
  of their document: nobody may be accused;
* ``silang``: every eighth marked image of the grids above, traced against the issuance of the
  other document: every registration is to the wrong document and any accusation is false. Both
  documents share font, margins, header and footer, so this is the hardest test of the pose
  verification.

Every image is traced through the production path (``tapak.decoder.image.collect_from_gray``) as
``make bench`` does (not logged in a registry, all of eps, one stage), twice when the rescue stage
was used: ``sebelum`` with the pipeline before this study (the rescue switched off) and
``sesudah`` with the current one. Per trace: whether the page was found, the pose error against
the ground-truth homography over the visible part of the page and at the visible master words
(``pose_error``, ``pose_class``), what each registration stage did (``_summary_diag``; which stage
gave up is computed by ``ringkas.stage``), the verdict (all channels), the score of the leaked copy
and the highest innocent score as multiples of the threshold, the false accusation bound, the
erasure warning and the clear-read-no-name (contradiction) warning, and the seconds per trace.

Order of work: the development set was traced first with the pipeline before this study
(``hasil/dev_sebelum.jsonl``, written before the rescue stage existed); the rescue stage was
designed on the development images whose page that pipeline did not find; its two verification
settings were chosen by the rule of ``pilih.py`` (``hasil/pilihan.json``). The protocol, the seeds
and that rule are fixed here and in ``pilih.py`` before the held-out run; development seeds 9601,
9602 (evidence 9611), held-out seeds 9701, 9702 (evidence 9711); none is used by any other study.
``lacak --split uji`` refuses to start unless rectify.py carries the chosen settings. Process
pools are capped at 3 workers, BLAS and OpenCV at one thread. Usage, from the repository root:

    python research/registrasi/ukur.py terbit --split dev
    python research/registrasi/ukur.py lacak --split dev --berkas dev_sebelum.jsonl   # before the rescue existed
    python research/registrasi/pilih.py kumpul --hanya-gagal dev_sebelum.jsonl
    python research/registrasi/pilih.py pilih
    python research/registrasi/ukur.py lacak --split dev --hanya-gagal dev_sebelum.jsonl  # decode check
    python research/registrasi/ukur.py terbit --split uji
    python research/registrasi/ukur.py lacak --split uji      # once, at the end
    python research/registrasi/ringkas.py --split uji --json
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
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the working tree's tapak, not an installed copy


def _load_layar():
    """research/layar/ukur.py (renderers and capture helpers of the screenshot study), under its own name."""
    import importlib.util

    if "layar_ukur" in sys.modules:
        return sys.modules["layar_ukur"]
    spec = importlib.util.spec_from_file_location("layar_ukur", ROOT / "research" / "layar" / "ukur.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["layar_ukur"] = mod
    spec.loader.exec_module(mod)
    return mod


layar = _load_layar()

WORK = Path(os.environ.get("TAPAK_REGISTRASI_KERJA") or ROOT / "out" / "riset_registrasi")
HASIL = ROOT / "research" / "registrasi" / "hasil"
WORKERS = 3
DOCS = ("nota_dinas", "surat_telegram")
PAGES = (1, 2)
MAIN_RENDERERS = layar.MAIN_RENDERERS
RENDERERS = layar.RENDERERS
POSITIONS = ("atas", "tengah", "bawah")
HEIGHTS = (0.25, 0.40, 0.55, 0.70, 0.85, 1.00)
CROP_DPI = (48, 64, 84, 120, 150)
LOW_DPI = (24, 28, 32, 40, 48)
PHOTO_HEIGHTS = (0.25, 0.40, 0.55, 0.70)
LONG_SIDE = layar.LONG_SIDE
KECIL_FACTOR = layar.KECIL_FACTOR
PHOTO_DPI = 200          # page render the photo simulator photographs
PHOTO_SENSOR = 4000      # camera frame long side (12 MP)
POSE_STEP_PT = 14.0      # spacing of the points the pose error is measured on (about 5 mm)
CORRECT_POSE_PX = 1.5    # a pose is correct when the 95th percentile error is at most this (image px)
WRONG_POSE_PX = 5.0      # ... and wrong when the text is off by more than this (95th percentile at word centres)
# Each initial-pose stage on its own on every image whose page was not found (``oracle``): used while
# exploring the development set (hasil/dev_sebelum.jsonl has it), off afterwards (about 10 s per image).
ORACLE = bool(os.environ.get("TAPAK_REG_ORAKEL"))

PROTOCOL: dict = {
    "n": 20, "c": 3, "eps": 1e-6, "scheme": "v2", "pages": list(PAGES),
    "issue": ("tapak issue --benih-riset BENIH --no-registry --canary-domain '' --workers 3 --geser v2, profil latar "
              "bawaan"),
    "benih_riset": {"dev": {"nota_dinas": 9601, "surat_telegram": 9602},
                    "uji": {"nota_dinas": 9701, "surat_telegram": 9702}},
    "evidence_seed": {"dev": 9611, "uji": 9711},
    "unmarked_seed": {"dev": 9699, "uji": 9799},
    "renderers": layar.PROTOCOL["renderers"],
    "grids": {
        "dev": {
            "potong": {"dpi": list(CROP_DPI), "formats": ["png", "pesan"], "positions": list(POSITIONS),
                       "heights": list(HEIGHTS), "reps": 1, "copies": [1, 8, 15]},
            "paragraf": {"dpi": list(CROP_DPI), "formats": ["png", "pesan"], "reps": 3, "copies": [1, 8, 15]},
            "rendah": {"dpi": list(LOW_DPI), "reps": 1, "copies": [1, 8, 15]},
            "foto": {"positions": list(POSITIONS) + ["paragraf"], "heights": list(PHOTO_HEIGHTS), "reps": 2,
                     "copies": [1, 8, 15]},
            "induk": {"reps": 3},
            "silang": {"every": 8},
        },
        "uji": {
            "potong": {"dpi": list(CROP_DPI), "formats": ["png", "pesan"], "positions": list(POSITIONS),
                       "heights": list(HEIGHTS), "reps": 2, "copies": [2, 5, 9, 12, 16, 19]},
            "paragraf": {"dpi": list(CROP_DPI), "formats": ["png", "pesan"], "reps": 6,
                         "copies": [2, 5, 9, 12, 16, 19]},
            "rendah": {"dpi": list(LOW_DPI), "reps": 2, "copies": [2, 5, 9, 12, 16, 19]},
            "foto": {"positions": list(POSITIONS) + ["paragraf"], "heights": list(PHOTO_HEIGHTS), "reps": 4,
                     "copies": [2, 5, 9, 12, 16, 19]},
            "induk": {"reps": 6},
            "silang": {"every": 8},
        },
    },
    "design": ("dalam setiap grid pekerjaan ke-k (urutan tetap jobs_for) memakai penggambar MAIN_RENDERERS[k % 3] "
               "(rendah: semua penggambar, satu sel per penggambar), bingkai penampil bila (k // 3) % 2 == 1 "
               "(potong dan rendah; paragraf tanpa bingkai), salinan copies[(k // 6) % len(copies)], dan ISP ponsel "
               "pada foto bila k % 2 == 1; tinggi 100 % hanya dari atas (halaman utuh)"),
    "silang": ("satu dari setiap delapan bukti salinan bertanda (urutan jobs_for) dilacak terhadap penerbitan dokumen "
               "yang lain: setiap registrasi salah dokumen, setiap tuduhan salah"),
    "selection": ("RESCUE_MIN_AGREEMENT dan RESCUE_AMBIGUITY dari pilih.py (ATURAN) pada set dev; pengaturan tahap "
                  "penyelamat lainnya ditetapkan saat merancangnya pada gambar dev yang tidak ditemukan jalur lama"),
    "generators": "default_rng([benih bukti atau induk, indeks grid, k])",
    "trace": ("seperti make bench: tanpa registri, seluruh eps, satu tahap; collect_from_gray (jalur produksi); "
              "sebelum = registrasi tanpa tahap penyelamat, sesudah = registrasi sekarang"),
    "pose": (f"galat pose: jarak di gambar antara letak titik halaman menurut homografi registrasi dan menurut "
             f"homografi sebenarnya, pada titik berjarak {POSE_STEP_PT:g} pt di bagian halaman yang terlihat dan pada "
             f"titik tengah kata induk yang terlihat; pose benar bila persentil ke-95 seluruhnya paling besar "
             f"{CORRECT_POSE_PX:g} piksel gambar, salah bila halaman atau dokumennya salah, tidak ada kata induk yang "
             f"terlihat, atau persentil ke-95 pada kata lebih dari {WRONG_POSE_PX:g} piksel, selebihnya kasar (teks "
             f"pas, bagian kosong meleset)"),
}

GRID_INDEX = {"potong": 0, "paragraf": 1, "rendah": 2, "foto": 3, "induk": 4, "silang": 5}
OTHER_DOC = {"nota_dinas": "surat_telegram", "surat_telegram": "nota_dinas"}


# --- issuance ------------------------------------------------------------------------------


def _tapak(*args: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    run = subprocess.run([sys.executable, "-m", "tapak.cli", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"tapak {' '.join(args[:2])} gagal: {run.stderr.strip()[-400:]}")
    return run.stdout


def issuance_dir(split: str, doc: str) -> Path:
    return WORK / split / f"{doc}_v2"


def issue(split: str, doc: str) -> dict:
    """Issue one (split, document) with the CLI, once; returns its summary."""
    folder = issuance_dir(split, doc)
    seed = PROTOCOL["benih_riset"][split][doc]
    if not list((folder / "data" / "dokumen").glob("*/manifest.json")):
        folder.mkdir(parents=True, exist_ok=True)
        _tapak("--data", str(folder / "data"), "--keys", str(folder / "keys"), "issue", str(ROOT / "samples" / f"{doc}.pdf"),
               str(ROOT / "samples" / "recipients.csv"), "--no-registry", "--canary-domain", "", "--workers",
               str(WORKERS), "--benih-riset", str(seed), "--geser", "v2")
    ctx, manifest, _ = context(split, doc)
    from tapak.marker.plan import CHANNEL_SHIFT

    slots = ctx.plan.channel(CHANNEL_SHIFT)
    return {"split": split, "doc": doc, "benih_riset": seed, "copies": len(manifest.copies),
            "shift_scheme": manifest.shift_settings.scheme, "plan_summary": manifest.plan_summary,
            "shift_slots_per_page": [sum(1 for s in slots if s.page == p) for p in range(len(ctx.master.layout.pages))],
            "copy_ids_sha256": hashlib.sha256(",".join(c.copy_id for c in manifest.copies).encode()).hexdigest(),
            "codewords_sha256": hashlib.sha256(ctx.codewords.tobytes()).hexdigest()}


_CTX: dict = {}


def context(split: str, doc: str):
    """(trace context, manifest, workspace folder) of an issuance, cached per process."""
    key = (split, doc)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest

        root = issuance_dir(split, doc)
        folder = next((root / "data" / "dokumen").glob("*/manifest.json")).parent
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        secret = load_code_secret(root / "keys" / "code_secret.key")
        _CTX[key] = (load_context((folder / "induk.pdf").read_bytes(), manifest, secret, folder=folder), manifest,
                     folder)
    return _CTX[key]


# --- geometry ------------------------------------------------------------------------------


def _resize(sx: float, sy: float) -> np.ndarray:
    """Coordinate map of cv2.resize by (sx, sy) (pixel centres at integer coordinates)."""
    return np.array([[sx, 0.0, 0.5 * sx - 0.5], [0.0, sy, 0.5 * sy - 0.5], [0.0, 0.0, 1.0]])


def _shift(dx: float, dy: float) -> np.ndarray:
    return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])


def pt_to_px(dpi: float) -> np.ndarray:
    """Page points to pixel coordinates of a render at ``dpi`` (pixel j covers [j, j + 1) * 72 / dpi)."""
    s = dpi / 72.0
    return np.array([[s, 0.0, -0.5], [0.0, s, -0.5], [0.0, 0.0, 1.0]])


def apply(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Points (n, 2) through a homography."""
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ np.asarray(h, dtype=np.float64).T
    return p[:, :2] / p[:, 2:3]


def visible_points(h_true: np.ndarray, page_pt: tuple[float, float], image_px: tuple[int, int],
                   box_pt: tuple[float, float, float, float] | None = None) -> np.ndarray:
    """Page points (pt) on a POSE_STEP_PT grid that the image shows (inside ``box_pt`` when given)."""
    x0, y0, x1, y1 = box_pt if box_pt is not None else (0.0, 0.0, page_pt[0], page_pt[1])
    xs = np.arange(x0 + POSE_STEP_PT / 2, x1, POSE_STEP_PT)
    ys = np.arange(y0 + POSE_STEP_PT / 2, y1, POSE_STEP_PT)
    pts = np.array([(x, y) for y in ys for x in xs], dtype=np.float64).reshape(-1, 2)
    img = apply(h_true, pts)
    w, h = image_px
    inside = (img[:, 0] >= 1) & (img[:, 1] >= 1) & (img[:, 0] <= w - 2) & (img[:, 1] <= h - 2)
    return pts[inside]


def text_points(layout_page, h_true: np.ndarray, image_px: tuple[int, int],
                box_pt: tuple[float, float, float, float]) -> np.ndarray:
    """Centres (pt) of the master words of a page that lie inside the visible box and the image:
    where a pose must be right for the text to line up."""
    x0, y0, x1, y1 = box_pt
    pts = np.array([((w.bbox[0] + w.bbox[2]) / 2.0, (w.bbox[1] + w.bbox[3]) / 2.0)
                    for r in layout_page.rows for w in r.words
                    if w.bbox[0] >= x0 and w.bbox[1] >= y0 and w.bbox[2] <= x1 and w.bbox[3] <= y1],
                   dtype=np.float64).reshape(-1, 2)
    if not len(pts):
        return pts
    img = apply(h_true, pts)
    w, h = image_px
    return pts[(img[:, 0] >= 1) & (img[:, 1] >= 1) & (img[:, 0] <= w - 2) & (img[:, 1] <= h - 2)]


def pose_class(err_text: dict | None, err_all: dict | None, same_page: bool) -> str:
    """'benar' (95th percentile error over the visible page at most CORRECT_POSE_PX), 'kasar' (the
    text lines up within WRONG_POSE_PX but the blank part is off more) or 'salah' (another page or
    document, no master text visible, or the text off by more than WRONG_POSE_PX)."""
    if not same_page or err_text is None or err_text.get("p95") is None:
        return "salah"
    if err_text["p95"] > WRONG_POSE_PX:
        return "salah"
    if err_all is not None and err_all.get("p95") is not None and err_all["p95"] <= CORRECT_POSE_PX:
        return "benar"
    return "kasar"


def pose_error(h_page_to_img: np.ndarray, dpi: float, h_true: np.ndarray, pts: np.ndarray) -> dict:
    """Median, 95th percentile and maximum distance (image px) between where a registration puts
    the visible page points and where they are."""
    if not len(pts):
        return {"med": None, "p95": None, "max": None}
    found = apply(np.asarray(h_page_to_img) @ pt_to_px(dpi), pts)
    d = np.linalg.norm(found - apply(h_true, pts), axis=1)
    d = np.where(np.isfinite(d), d, 1e9)
    return {"med": round(float(np.median(d)), 3), "p95": round(float(np.percentile(d, 95)), 3),
            "max": round(float(d.max()), 3)}


# --- evidence ------------------------------------------------------------------------------


def paragraphs(pdf: bytes, page: int) -> list[tuple[float, float, float, float]]:
    """Boxes (pt) of the paragraphs of a page with at least two rows: rows closer than 4 pt."""
    from tapak.marker.layout import extract_layout

    rows = sorted(extract_layout(pdf).pages[page].rows, key=lambda r: r.bbox[1])
    out, cur = [], []
    for r in rows:
        if cur and r.bbox[1] - cur[-1].bbox[3] > 4.0:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    boxes = []
    for p in out:
        if len(p) >= 2:
            boxes.append((min(r.bbox[0] for r in p), min(r.bbox[1] for r in p), max(r.bbox[2] for r in p),
                          max(r.bbox[3] for r in p)))
    return boxes


def chrome_canvas(part: np.ndarray, rng: np.random.Generator, scale: float, top: bool, bottom: bool) -> tuple[np.ndarray, int, int, dict]:
    """A page part inside viewer chrome (the ``frame`` of research/layar for any part); returns the
    canvas and where the part's first pixel lies."""
    import cv2

    ph, w = part.shape
    dark = bool(rng.random() < 0.5)
    background = int(rng.integers(45, 80)) if dark else int(rng.integers(195, 220))
    bar_level = int(rng.integers(30, 50)) if dark else int(rng.integers(225, 245))
    bar_h = int(round(rng.integers(36, 65) * scale))
    side = int(round(rng.integers(16, 81) * scale))
    top_gap = int(round(rng.integers(8, 25) * scale)) if top else 0
    bottom_gap = int(round(rng.integers(8, 41) * scale)) if bottom else 0
    meta = {"dark": dark, "background": background, "bar": bar_level, "bar_px": bar_h, "side_px": side}
    canvas = np.full((bar_h + top_gap + ph + bottom_gap, w + 2 * side), background, dtype=np.uint8)
    canvas[:bar_h] = bar_level
    button = 200 if dark else 90
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
    return canvas, ox, oy, meta


def _messenger(img: np.ndarray, rng: np.random.Generator, meta: dict) -> tuple[bytes, np.ndarray]:
    """Long side at most LONG_SIDE (area interpolation), JPEG twice; returns the file and the
    coordinate map of the downscale."""
    m = np.eye(3)
    if max(img.shape) > LONG_SIDE:
        f = LONG_SIDE / max(img.shape)
        small = layar._area_resize(img, f)
        m = _resize(small.shape[1] / img.shape[1], small.shape[0] / img.shape[0])
        img = small
    meta["image_px"] = [int(img.shape[1]), int(img.shape[0])]
    return layar._double_jpeg(img, rng, meta), m


def screenshot(pdf: bytes, job: dict, rng: np.random.Generator) -> tuple[bytes, dict]:
    """A screen capture of a page part drawn by a real renderer (potong, paragraf, rendah)."""
    import cv2

    page = job["page"] - 1
    r = float(job["dpi"])
    device = r * KECIL_FACTOR if job["fmt"] == "kecil" else r
    img = layar.render(pdf, page, device, job["renderer"])
    ph, pw = img.shape
    page_pt = (pw * 72.0 / device, ph * 72.0 / device)
    if job["grid"] == "paragraf":
        boxes = paragraphs(pdf, page)
        bx = boxes[int(rng.integers(len(boxes)))]
        margin = float(rng.uniform(3.0, 12.0))
        box_pt = (max(0.0, bx[0] - margin), max(0.0, bx[1] - margin), min(page_pt[0], bx[2] + margin),
                  min(page_pt[1], bx[3] + margin))
    else:
        hfrac = job["height"]
        y0 = {"atas": 0.0, "tengah": 0.5 - hfrac / 2, "bawah": 1.0 - hfrac}[job["position"]]
        box_pt = (0.0, y0 * page_pt[1], page_pt[0], (y0 + hfrac) * page_pt[1])
    s = device / 72.0
    X0, Y0 = int(round(box_pt[0] * s)), int(round(box_pt[1] * s))
    X1, Y1 = min(pw, int(round(box_pt[2] * s))), min(ph, int(round(box_pt[3] * s)))
    part = img[Y0:Y1, X0:X1]
    meta: dict = {"device_dpi": device, "box_px": [X0, Y0, X1, Y1], "chrome": bool(job["chrome"])}
    if job["chrome"]:
        canvas, ox, oy, cm = chrome_canvas(part, rng, device / r, top=Y0 == 0, bottom=Y1 == ph)
        meta.update(cm)
    else:
        canvas, ox, oy = part, 0, 0
    h_true = _shift(ox - X0, oy - Y0) @ pt_to_px(device)
    if job["fmt"] == "kecil":
        small = layar._area_resize(canvas, 1.0 / KECIL_FACTOR)
        h_true = _resize(small.shape[1] / canvas.shape[1], small.shape[0] / canvas.shape[0]) @ h_true
        canvas = small
    if job["fmt"] == "png":
        ok, data = cv2.imencode(".png", canvas)
        meta["image_px"] = [int(canvas.shape[1]), int(canvas.shape[0])]
        data = data.tobytes()
    else:
        data, m = _messenger(canvas, rng, meta)
        h_true = m @ h_true
    vis = (X0 / s, Y0 / s, X1 / s, Y1 / s)
    meta.update(h_true=h_true.tolist(), page_pt=list(page_pt), visible_pt=list(vis),
                effective_dpi=round(float(device * np.sqrt(abs(np.linalg.det(h_true[:2, :2]))) / s), 2))
    return data, meta


def photo(pdf: bytes, job: dict, rng: np.random.Generator) -> tuple[bytes, dict]:
    """A phone photo of the whole page, cropped by the user to part of it, then sent on."""
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, decode_jpeg, photo_jpeg
    from tapak.ponsel import ISP_PROFILES

    page = job["page"] - 1
    img = render_pages(pdf, PHOTO_DPI, [page])[0]
    page_pt = (img.shape[1] * 72.0 / PHOTO_DPI, img.shape[0] * 72.0 / PHOTO_DPI)
    params = PhotoParams(sensor_long_side=PHOTO_SENSOR, long_side=PHOTO_SENSOR, jpeg_quality_1=(90, 95),
                         jpeg_quality_2=(90, 95))
    isp = ISP_PROFILES["ponsel"] if job["isp"] else None
    cam_rng = np.random.default_rng(rng.integers(2**63))
    jpeg, pmeta = photo_jpeg(img, cam_rng, params, isp=isp)
    cam = decode_jpeg(jpeg)
    h_cam = np.array(pmeta["homography"]) @ pt_to_px(PHOTO_DPI)
    if job["position"] == "paragraf":
        boxes = paragraphs(pdf, page)
        bx = boxes[int(rng.integers(len(boxes)))]
        margin = float(rng.uniform(3.0, 12.0))
        box_pt = (max(0.0, bx[0] - margin), max(0.0, bx[1] - margin), min(page_pt[0], bx[2] + margin),
                  min(page_pt[1], bx[3] + margin))
    else:
        hfrac = job["height"]
        y0 = {"atas": 0.0, "tengah": 0.5 - hfrac / 2, "bawah": 1.0 - hfrac}[job["position"]]
        box_pt = (0.0, y0 * page_pt[1], page_pt[0], (y0 + hfrac) * page_pt[1])
    corners = np.array([[box_pt[0], box_pt[1]], [box_pt[2], box_pt[1]], [box_pt[2], box_pt[3]], [box_pt[0], box_pt[3]]])
    q = apply(h_cam, corners)
    pad = float(rng.uniform(0.0, 0.03)) * max(cam.shape)
    X0 = int(max(0, np.floor(q[:, 0].min() - pad)))
    Y0 = int(max(0, np.floor(q[:, 1].min() - pad)))
    X1 = int(min(cam.shape[1], np.ceil(q[:, 0].max() + pad)))
    Y1 = int(min(cam.shape[0], np.ceil(q[:, 1].max() + pad)))
    crop = np.ascontiguousarray(cam[Y0:Y1, X0:X1])
    h_true = _shift(-X0, -Y0) @ h_cam
    meta: dict = {"view_angle_deg": round(float(pmeta["view_angle_deg"]), 2), "isp": bool(job["isp"]),
                  "crop_px": [X0, Y0, X1, Y1], "camera_px": [int(cam.shape[1]), int(cam.shape[0])]}
    data, m = _messenger(crop, rng, meta)
    h_true = m @ h_true
    centre = np.array([[(box_pt[0] + box_pt[2]) / 2, (box_pt[1] + box_pt[3]) / 2]])
    jac = apply(h_true, np.vstack([centre, centre + [1.0, 0.0], centre + [0.0, 1.0]]))
    (ax, ay), (bx_, by) = jac[1] - jac[0], jac[2] - jac[0]
    meta.update(h_true=h_true.tolist(), page_pt=list(page_pt), visible_pt=list(box_pt),
                effective_dpi=round(float(72.0 * np.sqrt(abs(ax * by - ay * bx_))), 2))
    return data, meta


# --- jobs ----------------------------------------------------------------------------------


def jobs_for(split: str) -> list[dict]:
    """Every job of a split, in a fixed order (``PROTOCOL["design"]``)."""
    grids = PROTOCOL["grids"][split]
    out: list[dict] = []

    def add(grid: str, base: dict, copies: list[int] | None) -> None:
        k = sum(1 for j in out if j["grid"] == grid)
        job = {"split": split, "grid": grid, "k": k, "renderer": None, "dpi": None, "fmt": None, "position": None,
               "height": None, "chrome": False, "isp": False, "seq": None}
        job.update(base)
        if copies is not None:
            job["seq"] = copies[(k // 6) % len(copies)]
        out.append(job)

    def sub(grid: str, base: dict) -> dict:
        """Renderer, chrome and ISP of the k-th job of a grid."""
        k = sum(1 for j in out if j["grid"] == grid)
        d = dict(base)
        if "renderer" not in d:
            d["renderer"] = MAIN_RENDERERS[k % 3]
        if grid in ("potong", "rendah") and "chrome" not in d:
            d["chrome"] = bool((k // 3) % 2)
        if grid == "foto":
            d["isp"] = bool(k % 2)
        return d

    g = grids["potong"]
    for doc in DOCS:
        for page in PAGES:
            for dpi in g["dpi"]:
                for fmt in g["formats"]:
                    for pos in g["positions"]:
                        for hfrac in g["heights"]:
                            if hfrac == 1.0 and pos != "atas":
                                continue
                            for rep in range(g["reps"]):
                                add("potong", sub("potong", {"doc": doc, "page": page, "dpi": dpi, "fmt": fmt,
                                                             "position": pos, "height": hfrac, "rep": rep}),
                                    g["copies"])
    g = grids["paragraf"]
    for doc in DOCS:
        for page in PAGES:
            for dpi in g["dpi"]:
                for fmt in g["formats"]:
                    for rep in range(g["reps"]):
                        add("paragraf", sub("paragraf", {"doc": doc, "page": page, "dpi": dpi, "fmt": fmt,
                                                         "position": "paragraf", "rep": rep}), g["copies"])
    g = grids["rendah"]
    for doc in DOCS:
        for page in PAGES:
            for renderer in RENDERERS:
                fmts = ["png", "pesan"] if renderer == "poppler_tanpa_aa" else ["png", "pesan", "kecil"]
                for dpi in g["dpi"]:
                    for fmt in fmts:
                        for rep in range(g["reps"]):
                            add("rendah", sub("rendah", {"doc": doc, "page": page, "dpi": dpi, "fmt": fmt,
                                                         "renderer": renderer, "position": "atas", "height": 1.0,
                                                         "rep": rep}), g["copies"])
    g = grids["foto"]
    for doc in DOCS:
        for page in PAGES:
            for pos in g["positions"]:
                for hfrac in (g["heights"] if pos != "paragraf" else [None]):
                    for rep in range(g["reps"]):
                        add("foto", sub("foto", {"doc": doc, "page": page, "position": pos, "height": hfrac,
                                                 "renderer": "foto", "rep": rep}), g["copies"])
    g = grids["induk"]
    for doc in DOCS:
        for page in PAGES:
            for rep in range(g["reps"]):
                for kind in ("potong", "paragraf", "rendah", "foto"):
                    k = sum(1 for j in out if j["grid"] == "induk")
                    base = {"doc": doc, "page": page, "rep": rep, "kind": kind}
                    if kind == "potong":
                        base.update(renderer=MAIN_RENDERERS[k % 3], dpi=CROP_DPI[k % 5], fmt=("png", "pesan")[k % 2],
                                    position=POSITIONS[k % 3], height=HEIGHTS[k % 5], chrome=bool(k % 2))
                    elif kind == "paragraf":
                        base.update(renderer=MAIN_RENDERERS[k % 3], dpi=CROP_DPI[(k + 2) % 5],
                                    fmt=("png", "pesan")[k % 2], position="paragraf")
                    elif kind == "rendah":
                        base.update(renderer=RENDERERS[k % 4], dpi=LOW_DPI[k % 5], fmt=("png", "pesan")[k % 2],
                                    position="atas", height=1.0, chrome=bool(k % 2))
                    else:
                        base.update(renderer="foto", position=(POSITIONS + ("paragraf",))[k % 4],
                                    height=PHOTO_HEIGHTS[k % 4], isp=bool(k % 2))
                        if base["position"] == "paragraf":
                            base["height"] = None
                    add("induk", base, None)
    g = grids["silang"]
    sources = [j for j in out if j["grid"] in ("potong", "paragraf", "rendah", "foto")]
    for src in sources[::g["every"]]:
        k = sum(1 for j in out if j["grid"] == "silang")
        job = dict(src, grid="silang", k=k, source_grid=src["grid"], source_k=src["k"], against=OTHER_DOC[src["doc"]])
        out.append(job)
    return out


def job_key(job: dict) -> str:
    who = f"s{job['seq']:03d}" if job["seq"] is not None else "induk"
    kind = f"_{job['kind']}" if job.get("kind") else ""
    if job["grid"] == "silang":
        kind = f"_{job['source_grid']}{job['source_k']:04d}_lawan_{job['against']}"
    return f"{job['grid']}{kind}_{job['doc']}_p{job['page']}_{job['k']:04d}_{who}"


def source_job(job: dict) -> dict:
    """The job whose evidence a cross-document job reuses (the job itself otherwise)."""
    if job["grid"] != "silang":
        return job
    src = {k: v for k, v in job.items() if k not in ("source_grid", "source_k", "against")}
    src.update(grid=job["source_grid"], k=job["source_k"])
    return src


def expected_copy(job: dict) -> int | None:
    """The copy a correct trace names: the leaked copy; nobody for an unmarked master or for
    evidence of the other document (``silang``)."""
    return None if job["grid"] == "silang" else job["seq"]


def job_rng(job: dict) -> np.random.Generator:
    seed = PROTOCOL["unmarked_seed" if job["seq"] is None else "evidence_seed"][job["split"]]
    return np.random.default_rng([seed, GRID_INDEX[job["grid"]], job["k"]])


def evidence(job: dict) -> tuple[bytes, dict]:
    """The evidence file of a job (cached on disk with its truth)."""
    job = source_job(job)
    path = WORK / "bukti" / job["split"] / f"{job_key(job)}.bin"
    meta_path = path.with_suffix(".json")
    if path.exists() and meta_path.exists():
        return path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
    if job["seq"] is None:
        pdf = (ROOT / "samples" / f"{job['doc']}.pdf").read_bytes()
    else:
        _, manifest, folder = context(job["split"], job["doc"])
        pdf = (folder / "salinan" / manifest.copies[job["seq"] - 1].file).read_bytes()
    kind = job.get("kind") or job["grid"]
    rng = job_rng(job)
    data, meta = photo(pdf, job, rng) if kind == "foto" else screenshot(pdf, dict(job, grid=kind), rng)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return data, meta


# --- tracing -------------------------------------------------------------------------------


def _init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    import cv2

    cv2.setNumThreads(1)


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
            "erasure_flagged": bool(a.erasure.flagged) if a.erasure is not None else None,
            "erasure_z": a.erasure.z if a.erasure is not None else None,
            "contradiction_flagged": bool(a.contradiction.flagged) if a.contradiction is not None else False,
            "contradiction_log10": (round(a.contradiction.log10_bound, 2)
                                    if a.contradiction is not None and np.isfinite(a.contradiction.log10_bound)
                                    else None)}


def _summary_diag(diag: dict, truth: dict, page: int, pts: np.ndarray, tpts: np.ndarray | None = None) -> dict:
    """What each registration stage did, with pose errors against the truth (for the true page;
    ``tpts`` None: evidence of the other document, every pose is wrong)."""
    h_true = np.array(truth["h_true"])
    if tpts is None:
        page = -1
        tpts = np.zeros((0, 2))
    out: dict = {"quad": diag.get("quad") is not None, "outcome": diag.get("outcome"), "candidates": [],
                 "refined": [], "rescue": None}
    for c in diag.get("candidates", []):
        e = pose_error(c["h"], 100.0, h_true, pts)["p95"] if c["page"] == page else None
        out["candidates"].append({"method": c["method"], "page": c["page"] + 1, "score": round(float(c["score"]), 4),
                                  "err_p95": e})
    for r in diag.get("refined", []):
        e = pose_error(r["h"], r["dpi"], h_true, pts)["p95"] if r["page"] == page else None
        out["refined"].append({"method": r["method"], "page": r["page"] + 1, "dpi": r["dpi"],
                               "cc": round(float(r["cc"]), 4), "err_p95": e})
    res = diag.get("rescue")
    if res:
        out["rescue"] = {k: v for k, v in res.items() if k not in ("h", "tries", "page")}
        if res.get("page") is not None:
            out["rescue"]["page"] = res["page"] + 1
            out["rescue"]["err_p95"] = (pose_error(res["h"], res["dpi"], h_true, pts)["p95"]
                                        if res["page"] == page else None)
        out["rescue"]["tries"] = [
            {"origin": t["origin"], "page": t["page"] + 1, "dpi": t["dpi"], "cc": round(float(t["cc"]), 4),
             "agreement": round(float(t["agreement"]), 4), "pixels": t["pixels"],
             "err_p95": pose_error(t["h"], t["dpi"], h_true, pts)["p95"] if t["page"] == page else None,
             "err_text_p95": pose_error(t["h"], t["dpi"], h_true, tpts)["p95"] if t["page"] == page else None}
            for t in res.get("tries", [])]
    return out


def trace_once(gray: np.ndarray, ctx, truth: dict, job: dict, rescue: bool) -> dict:
    """One pass of the production path with the rescue stage on or off."""
    import tapak.decoder.image as image_mod
    from tapak.decoder import rectify

    diag: dict = {}
    original = image_mod.register

    def watched(*a, **k):
        extra = {"rescue": rescue} if _has_rescue() else {}
        reg = rectify.register(*a, diag=diag, **extra, **k)
        diag["final_h"] = reg.h_page_to_img if reg is not None else None
        return reg

    image_mod.register = watched
    t0 = time.perf_counter()
    try:
        obs = image_mod.collect_from_gray(gray, ctx)
    finally:
        image_mod.register = original
    seconds = time.perf_counter() - t0
    page = job["page"] - 1
    h_true = np.array(truth["h_true"])
    pts = visible_points(h_true, tuple(truth["page_pt"]), tuple(truth["image_px"]), tuple(truth["visible_pt"]))
    reg = next((o.meta for o in obs if "correlation" in o.meta), None)
    out: dict = {"registered": reg is not None, "seconds": round(seconds, 2)}
    same_doc = (job.get("against") or job["doc"]) == job["doc"]
    tpts = text_points(context(job["split"], job["doc"])[0].master.layout.pages[page], h_true,
                       tuple(truth["image_px"]), tuple(truth["visible_pt"]))
    if reg is not None:
        h = diag.get("final_h")
        same = h is not None and reg["page"] == page and same_doc
        err = pose_error(h, reg["dpi"], h_true, pts) if same else None
        err_text = pose_error(h, reg["dpi"], h_true, tpts) if same else None
        cls = pose_class(err_text, err, same)
        out["registration"] = {"method": reg["method"], "page": reg["page"] + 1, "dpi": reg["dpi"],
                               "correlation": reg["correlation"], "effective_dpi": reg["effective_dpi"],
                               "pose": err, "pose_text": err_text, "class": cls, "correct": cls == "benar"}
    out["diag"] = _summary_diag(diag, truth, page, pts, tpts if same_doc else None)
    expected = expected_copy(job)
    x = ctx.codewords[expected - 1] if expected is not None else None
    out["bits"] = layar.bit_stats(obs, ctx, x)
    out["accuse"] = verdict(obs, ctx, expected)
    out["n_points"] = int(len(pts))
    out["n_text_points"] = int(len(tpts))
    if ORACLE and same_doc and not out.get("registration", {}).get("correct", False):
        sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
        out["oracle"] = oracle(gray, ctx.master.pdf_bytes, sizes, page, truth, pts)
    return out


def oracle(gray: np.ndarray, pdf: bytes, sizes: list[tuple[float, float]], page: int, truth: dict,
           pts: np.ndarray) -> dict:
    """Every initial-pose stage on the true page on its own (not as a cascade), each refined with
    ECC: which stage could have found the page (diagnosis of failures only)."""
    import cv2

    from tapak.decoder import rectify
    from tapak.decoder.lines import tesseract_homography

    h_true = np.array(truth["h_true"])
    probe = 100.0
    out: dict = {}
    inits: dict = {}
    quad = rectify.detect_page_quad(gray)
    if quad is not None:
        w_pt, h_pt = sizes[page]
        src = rectify.page_corners(w_pt * probe / 72.0, h_pt * probe / 72.0).astype(np.float32)
        inits["kontur"] = cv2.getPerspectiveTransform(src, quad.astype(np.float32)).astype(np.float64)
    inits["fitur"] = rectify.feature_homography(rectify.render_page(pdf, page, probe), gray)
    inits["tesseract"] = tesseract_homography(gray, pdf, page, probe)
    for name, h0 in inits.items():
        if h0 is None:
            out[name] = None
            continue
        w_pt, h_pt = sizes[page]
        eff = rectify.effective_dpi(h0, w_pt * probe / 72.0, h_pt * probe / 72.0, probe)
        dpi = float(np.clip(round(eff / 10) * 10, rectify.DPI_MIN, rectify.DPI_MAX))
        sc = dpi / probe
        h, cc = rectify.ecc_refine(rectify.render_page(pdf, page, dpi), gray, h0 @ np.diag([1 / sc, 1 / sc, 1.0]))
        out[name] = {"init_p95": pose_error(h0, probe, h_true, pts)["p95"], "cc": round(float(cc), 4),
                     "ecc_p95": pose_error(h, dpi, h_true, pts)["p95"]}
    return out


def _has_rescue() -> bool:
    import inspect

    from tapak.decoder import rectify

    return "rescue" in inspect.signature(rectify.register).parameters


def rows_visible(ctx, page: int, box_pt: list[float]) -> int:
    """Text rows of the master page that lie wholly inside the visible box (pt)."""
    x0, y0, x1, y1 = box_pt
    return sum(1 for r in ctx.master.layout.pages[page].rows
               if r.bbox[0] >= x0 - 1 and r.bbox[1] >= y0 - 1 and r.bbox[2] <= x1 + 1 and r.bbox[3] <= y1 + 1)


def trace_job(job: dict) -> dict:
    """Make (or reuse) the evidence of a job and trace it: after, and before when they can differ."""
    from tapak.decoder.rectify import load_gray

    data, truth = evidence(job)
    row = {k: job.get(k) for k in ("split", "grid", "kind", "k", "doc", "page", "renderer", "dpi", "fmt", "position",
                                   "height", "chrome", "isp", "seq", "rep", "source_grid", "source_k", "against")}
    row["truth"] = {k: v for k, v in truth.items() if k != "h_true"}
    row["evidence_sha256"] = hashlib.sha256(data).hexdigest()
    ctx, _, _ = context(job["split"], job.get("against") or job["doc"])
    row["rows_visible"] = rows_visible(ctx, job["page"] - 1, truth["visible_pt"])
    gray = load_gray(data)
    after = trace_once(gray, ctx, truth, job, rescue=True)
    row["sesudah"] = after
    used_rescue = after["diag"].get("rescue") is not None
    row["sebelum"] = trace_once(gray, ctx, truth, job, rescue=False) if (used_rescue and _has_rescue()) else None
    return row


# --- driver --------------------------------------------------------------------------------


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def run_pool(jobs: list[dict], out_path: Path) -> list[dict]:
    """Trace jobs with WORKERS processes; rows are appended as they finish (a rerun skips done jobs)."""
    import multiprocessing as mp

    done = {job_key(r): r for r in _load(out_path)}
    todo = [j for j in jobs if job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            out_path.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(pool.map(trace_job, todo, chunksize=1)):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            a = r["sesudah"]
            print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {job_key(r)}: reg={a['registered']} "
                  f"{a['accuse']['verdict']} {a['seconds']}s", flush=True)
            done[job_key(r)] = r
    return [done[job_key(j)] for j in jobs]


def versions() -> dict:
    """Renderer and library versions (the results depend on them)."""
    v = layar.versions()
    run = subprocess.run(["tesseract", "--version"], capture_output=True, text=True)
    v["tesseract"] = (run.stdout + run.stderr).strip().splitlines()[0] if run.returncode == 0 else None
    return v


def before_outcome(row: dict) -> str | None:
    """Outcome of the stages before the rescue in a traced row."""
    t = row["sebelum"] if row.get("sebelum") is not None else row["sesudah"]
    return t["diag"]["outcome"]


def check_chosen_settings() -> None:
    """Stop unless rectify.py carries the rescue settings chosen on the development set
    (hasil/pilihan.json, written by pilih.py) and no development override is active."""
    from tapak.decoder import rectify

    if os.environ.get("TAPAK_REG_VARIAN"):
        raise SystemExit("TAPAK_REG_VARIAN aktif: set uji hanya dilacak dengan pengaturan di rectify.py")
    path = HASIL / "pilihan.json"
    if not path.exists():
        raise SystemExit("hasil/pilihan.json belum ada: jalankan pilih.py kumpul dan pilih pada set dev lebih dulu")
    chosen = {k: v for k, v in (json.loads(path.read_text(encoding="utf-8")).get("chosen") or {}).items() if k.isupper()}
    now = {k: getattr(rectify, k) for k in chosen}
    if not chosen or any(abs(float(now[k]) - float(chosen[k])) > 1e-9 for k in chosen):
        raise SystemExit(f"pengaturan rectify.py {now} bukan pilihan dev {chosen}; set uji tidak dijalankan")


def decoder_fingerprint() -> dict:
    """Hashes of the decoder sources a run used."""
    files = sorted((ROOT / "tapak" / "decoder").glob("*.py"))
    return {"git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "decoder_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    tb = sub.add_parser("terbit")
    tb.add_argument("--split", choices=("dev", "uji"), required=True)
    lc = sub.add_parser("lacak")
    lc.add_argument("--split", choices=("dev", "uji"), required=True)
    lc.add_argument("--berkas", default=None, help="keluaran JSONL (bawaan hasil/{split}.jsonl)")
    lc.add_argument("--grid", default=None, help="hanya grid ini (dev, penjelajahan)")
    lc.add_argument("--hanya-gagal", default=None,
                    help="dev: hanya gambar yang tahap sebelumnya gagal menurut JSONL ini, ditambah induk dan dokumen lain")
    lc.add_argument("--ulang", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "terbit":
        rows = [issue(args.split, doc) for doc in DOCS]
        HASIL.mkdir(parents=True, exist_ok=True)
        (HASIL / f"terbit_{args.split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
        for r in rows:
            print(json.dumps({k: r[k] for k in ("split", "doc", "shift_slots_per_page")}, ensure_ascii=False))
        return 0
    out = Path(args.berkas) if args.berkas else HASIL / f"{args.split}.jsonl"
    jobs = jobs_for(args.split)
    if args.grid:
        jobs = [j for j in jobs if j["grid"] in args.grid.split(",")]
    if args.hanya_gagal:
        if args.split == "uji":
            raise SystemExit("--hanya-gagal hanya untuk set dev: set uji dilacak utuh")
        failed = {job_key(r) for r in _load(Path(args.hanya_gagal))
                  if (r.get("outcome") or before_outcome(r)) != "terdaftar"}
        jobs = [j for j in jobs if job_key(j) in failed or j["grid"] in ("induk", "silang")]
    if args.split == "uji":
        if out.exists() and not args.ulang and len(_load(out)) >= len(jobs):
            raise SystemExit(f"{out} sudah lengkap: set uji dilacak sekali")
        check_chosen_settings()
        mark = HASIL / "uji_dekoder.json"
        if not mark.exists():
            mark.write_text(json.dumps(dict(decoder_fingerprint(), versions=versions()), indent=2) + "\n",
                            encoding="utf-8")
    run_pool(jobs, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
