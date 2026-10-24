"""Calibration of the decoder weights per medium (research): measurements behind batasan 12.

The detection bound of ``tapak/tardos/detection.py`` (``read_miss_bound``) is proven under two
conditions on the channel; (C2) asks that, given the weights, a decided bit is wrong with a known
rate, and with the decoder's own LLRs that rate is (1 - w) / 2 only if the LLRs are calibrated.
``research/layar`` found the background weights overconfident in the top bin after JPEG: on
messenger screenshots, bits weighted above 0.95 were wrong 1.8 % at 28 to 48 dpi (0.7 %
promised), 0.9 % at 56 to 84 dpi (0.2 %) and 0.5 % from 96 dpi (0.1 %), PNG 0.1 % (under 0.05 %).
This study measures the calibration of the background weights, and of the shift weights for
comparison, per medium on fresh development seeds, chooses a code-blind correction on those
seeds only (``research/kalibrasi/kandidat.py``, rule ``ATURAN`` committed before any candidate
is scored), and runs the held-out seeds once with the chosen decoder. Nothing here changes an
accusation threshold, eps, an alpha-spending rule or a decision rule, and no decoder ever sees
a recipient's codeword: the codewords are used here only to count wrong bits.

Protocol (fixed here and committed before any run; ``PROTOCOL``):

* Issuances with ``tapak issue --benih-riset SEED --no-registry --canary-domain ""`` (N = 20,
  c = 3, eps = 1e-6, shift scheme geser-v2), fictional sample documents only. Development:
  K1 nota_dinas (13101), K2 surat_telegram (13102), default background profile; K3 nota_dinas
  (13103), K4 surat_telegram (13104), print background profile (``--latar cetak``). Held out:
  U1 nota_dinas (13201), U2 surat_telegram (13202), default profile; U3 nota_dinas (13203), U4
  surat_telegram (13204), print profile. None of these seeds (nor the evidence seeds below) is
  used by research/layar, research/ponsel, research/registrasi, research/deteksi or any other
  study in the repository (they use 2026 and 7100 to 9879).
* Media (evidence is page 1 unless stated):
  - ``pdf``: the forwarded copy itself;
  - ``png``, ``pesan``, ``kecil``: screenshots drawn by real PDF renderers (MuPDF, Poppler Splash,
    Poppler Cairo) at 28 to 150 dpi, made with the unchanged functions of research/layar
    (``render``, ``frame``, ``capture``): lossless PNG; messenger (long side at most 1600 px,
    JPEG quality 68 to 72, then 58 to 62); and drawn at 1.5 times the resolution, scaled down by
    the messenger, then compressed like ``pesan``. Framing alternates over the copies (page
    alone, page in viewer chrome);
  - ``layar_sim``: the screenshot simulator of ``tapak/photos.py`` (render 200 dpi, viewer at
    96 to 150 dpi, long side 1600 px, double JPEG), the screenshots of the README benchmark;
  - ``foto``: a basic phone photo (``photo_jpeg``, view angle 0, 10, 20 or 30 degrees by copy);
  - ``ponsel``: the same scene through the simulated phone ISP (``ISP_PROFILES["ponsel"]``);
  - ``monitor``: a phone photo of the copy on a simulated monitor, with the phone ISP
    (``screen_photo_jpeg``, default ``ScreenParams``);
  - ``cetak``: page 1 or page 2 of a print-profile copy printed on the simulated laser printer
    and photographed (``printed_photo_jpeg``, 10 or 30 degrees by copy), one page per evidence.
* Grids (``GRIDS``): honest single copies through every medium of their issuance; honest
  coalitions of 2 and 3 copies (strategy ``acak``, marking assumption kept, ``tapak.collusion``)
  through ``pdf``, messenger screenshots and ``foto``; the unmarked master through every medium
  (nobody may be named).
* Every evidence is traced through the production path (``collect_file`` for a PDF,
  ``collect_from_gray`` for an image) as the first logged trace with the default stage policy
  (``bertahap-v1``), which runs the erasure, contradiction and reversal checks. The registration
  and the observations of every evidence are kept in the work folder, so candidates of
  ``kandidat.py`` re-decode the background channel from the same registration without
  registering again, and the held-out run is compared with the decoder before this study on
  the same evidence.
* Recorded per evidence (one JSON line): verdict (named at any stage, members, anyone else),
  stage-1 threshold Z, the largest member and non-member score over Z, the false-accusation
  bound of the first name, the three checks, the background decoder's tests, and for honest
  evidence the detection bound of ``read_miss_ceiling`` for the read's fused weights with the
  calibrated ceilings (tempering 1, i.e. (1 - w) / 2 from |L|) and with the contradiction
  check's tempering 0.3, for a coalition of the evidence's size at the stage-1 eps1. For single
  copies, the reliability counts per kind (``latar``: background LLR of every observation;
  ``baris`` and ``kata``: shift rows and word groups; ``gabungan``: fused positions with weight
  above 0) in the weight bins ``W_EDGES``: positions n, wrong k, the calibrated expectation
  E = sum of 1 / (1 + exp |L|) and the sum of w.

Usage, from the repository root (work folder in ``$TAPAK_KALIBRASI_KERJA``, default
``out/riset_kalibrasi``; large, not committed; process pools capped at 3, BLAS and OpenCV at
one thread):

    python research/kalibrasi/ukur.py terbit --split dev
    python research/kalibrasi/ukur.py lacak --split dev
    python research/kalibrasi/kandidat.py nilai --split dev        # candidates, dev only
    python research/kalibrasi/kandidat.py pilih
    python research/kalibrasi/ukur.py terbit --split uji
    python research/kalibrasi/ukur.py lacak --split uji           # once, with the chosen decoder
    python research/kalibrasi/kandidat.py banding --split uji     # before/after on the same evidence
    python research/kalibrasi/ringkas.py --split uji --json
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import pickle  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the working tree's tapak, not an installed copy

WORK = Path(os.environ.get("TAPAK_KALIBRASI_KERJA") or ROOT / "out" / "riset_kalibrasi")
HASIL = ROOT / "research" / "kalibrasi" / "hasil"
WORKERS = 3
EPS = 1e-6
RESOLUTIONS = (28, 32, 40, 48, 56, 64, 72, 84, 96, 120, 150)
RENDERERS = ("mupdf", "poppler", "cairo")
SCREEN_FORMATS = ("png", "pesan", "kecil")
MEDIA = ("pdf", "png", "pesan", "kecil", "layar_sim", "foto", "ponsel", "monitor", "cetak")
FRAMINGS = ("utuh", "bingkai")
PHOTO_ANGLES = (0.0, 10.0, 20.0, 30.0)
PRINT_ANGLES = (10.0, 30.0)
KINDS = ("latar", "baris", "kata", "gabungan")
# Reliability bins on the weight w = tanh(|L| / 2): (0, 0.5], (0.5, 0.8], (0.8, 0.9], (0.9, 0.95],
# (0.95, 0.99], (0.99, 0.999], (0.999, 1]. Stored as |L| edges (exact where w rounds to 1).
W_EDGES = (0.0, 0.5, 0.8, 0.9, 0.95, 0.99, 0.999, 1.0)
L_EDGES = tuple(0.0 if w == 0.0 else (math.inf if w == 1.0 else 2.0 * math.atanh(w)) for w in W_EDGES)
TEMPERINGS = (1.0, 0.3)

# name -> (document, N, research seed, background profile)
ISSUANCES = {
    "K1": ("nota_dinas", 20, 13101, "layar"),
    "K2": ("surat_telegram", 20, 13102, "layar"),
    "K3": ("nota_dinas", 20, 13103, "cetak"),
    "K4": ("surat_telegram", 20, 13104, "cetak"),
    "U1": ("nota_dinas", 20, 13201, "layar"),
    "U2": ("surat_telegram", 20, 13202, "layar"),
    "U3": ("nota_dinas", 20, 13203, "cetak"),
    "U4": ("surat_telegram", 20, 13204, "cetak"),
}
SETS = {"dev": ("K1", "K2", "K3", "K4"), "uji": ("U1", "U2", "U3", "U4")}
SEEDS = {
    "dev": {"bukti": 13111, "koalisi": 13112, "serangan": 13113, "induk": 13119},
    "uji": {"bukti": 13211, "koalisi": 13212, "serangan": 13213, "induk": 13219},
}
# Per split and background profile: which evidence to make (see the module docstring).
GRIDS = {
    "dev": {
        "layar": {
            "pdf": list(range(1, 11)),
            "layar_copies": [3, 11],
            "foto_copies": list(range(1, 13)),          # layar_sim, foto, ponsel, monitor
            "koalisi": {"k": [2, 3], "per_k": 2, "rule": "acak",
                        "media": [("pdf", None, None), ("pesan", "mupdf", 56), ("foto", None, None)]},
            "induk": {"reps": 2, "media": [("pdf", None, None), ("png", "mupdf", 56), ("pesan", "mupdf", 32),
                                           ("pesan", "mupdf", 56), ("pesan", "mupdf", 96), ("layar_sim", None, None),
                                           ("foto", None, None), ("ponsel", None, None), ("monitor", None, None)]},
        },
        "cetak": {"cetak_copies": list(range(1, 11)), "pages": [1, 2], "pdf": list(range(1, 6)),
                  "induk": {"reps": 2, "media": [("cetak", None, None)]}},
    },
    "uji": {
        "layar": {
            "pdf": list(range(1, 21)),
            "layar_copies": [2, 9, 17],
            "foto_copies": list(range(1, 21)),
            "koalisi": {"k": [2, 3], "per_k": 4, "rule": "acak",
                        "media": [("pdf", None, None), ("pesan", "mupdf", 40), ("pesan", "mupdf", 56),
                                  ("pesan", "mupdf", 96), ("foto", None, None)]},
            "induk": {"reps": 3, "media": [("pdf", None, None), ("png", "mupdf", 56), ("pesan", "mupdf", 32),
                                           ("pesan", "mupdf", 56), ("pesan", "mupdf", 96), ("layar_sim", None, None),
                                           ("foto", None, None), ("ponsel", None, None), ("monitor", None, None)]},
        },
        "cetak": {"cetak_copies": list(range(1, 21)), "pages": [1, 2], "pdf": list(range(1, 6)),
                  "induk": {"reps": 3, "media": [("cetak", None, None)]}},
    },
}
PROTOCOL = {
    "n": 20, "c": 3, "eps": EPS, "geser": "v2", "issuances": ISSUANCES, "sets": SETS, "seeds": SEEDS, "grids": GRIDS,
    "media": MEDIA, "resolutions": RESOLUTIONS, "renderers": RENDERERS, "screen_formats": SCREEN_FORMATS,
    "framings": FRAMINGS, "photo_angles": PHOTO_ANGLES, "print_angles": PRINT_ANGLES, "w_edges": W_EDGES,
    "temperings": TEMPERINGS,
    "trace": "pelacakan tercatat ke-1, kebijakan tahap bertahap-v1, jalur produksi (collect_file / collect_from_gray)",
    "generators": ("default_rng([benih bukti atau induk, indeks terbitan, indeks medium, indeks penggambar, dpi, "
                   "indeks format, salinan atau 1000 + ulangan atau 500 + indeks koalisi, halaman])"),
}


# --- issuance ------------------------------------------------------------------------------


def issuance_dir(name: str) -> Path:
    """Work folder of one research issuance."""
    doc, n, seed, latar = ISSUANCES[name]
    return WORK / "terbit" / f"{name}_{doc}_{n}_{seed}_{latar}"


def issue_all(split: str) -> None:
    """Issue every issuance of a split (skips those already there) and record a summary."""
    rows = []
    for name in SETS[split]:
        doc, n, seed, latar = ISSUANCES[name]
        folder = issuance_dir(name)
        if not list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            folder.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
                   "issue", str(ROOT / "samples" / f"{doc}.pdf"), str(ROOT / "samples" / "recipients.csv"),
                   "--no-registry", "--canary-domain", "", "--workers", str(WORKERS), "--geser", "v2",
                   "--latar", latar, "--benih-riset", str(seed)]
            subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
                           capture_output=True)
        ctx, _ = context(name)
        rows.append({"terbitan": name, "dok": doc, "N": n, "benih": seed, "latar": latar,
                     "skema": ctx.manifest.shift_scheme, "m": int(ctx.params.length),
                     "copy_ids_sha256": hashlib.sha256(",".join(c.copy_id for c in ctx.manifest.copies).encode()).hexdigest(),
                     "codewords_sha256": hashlib.sha256(ctx.codewords.tobytes()).hexdigest()})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / f"terbit_{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                                         for r in rows), encoding="utf-8")
    proto = dict(PROTOCOL, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HASIL / "protokol.json").write_text(json.dumps(proto, indent=2, ensure_ascii=False, default=str) + "\n",
                                         encoding="utf-8")


# --- contexts and evidence ------------------------------------------------------------------

_CTX: dict = {}
_LAYAR = None


def layar_module():
    """research/layar/ukur.py, unchanged, with its temporary files in this study's work folder."""
    global _LAYAR
    if _LAYAR is None:
        spec = importlib.util.spec_from_file_location("layar_ukur", ROOT / "research" / "layar" / "ukur.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.WORK = WORK
        _LAYAR = mod
    return _LAYAR


def context(name: str):
    """(trace context, salinan folder) of an issuance, cached per process."""
    if name not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import research_code_secret
        from tapak.marker.issue import IssueManifest

        folder = next(issuance_dir(name).glob("data/dokumen/*/salinan"))
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        doc = ISSUANCES[name][0]
        ctx = load_context((ROOT / "samples" / f"{doc}.pdf").read_bytes(), manifest,
                           research_code_secret(ISSUANCES[name][2]))
        _CTX[name] = (ctx, folder)
    return _CTX[name]


def copy_pdf(name: str, seq: int) -> bytes:
    """Bytes of copy ``seq`` (1-based) of an issuance."""
    ctx, folder = context(name)
    return (folder / ctx.manifest.copies[seq - 1].file).read_bytes()


def members_of(split: str, iss: int, k: int, index: int) -> list[int]:
    """The members of honest coalition ``index`` of size k (copies 1..20)."""
    rng = np.random.default_rng([SEEDS[split]["koalisi"], iss, k, index])
    return sorted(int(s) for s in rng.choice(np.arange(1, 21), size=k, replace=False))


def forged_pdf(job: dict) -> bytes:
    """The PDF an honest coalition leaks (standard strategy, agreeing units untouched)."""
    from tapak.collusion import attack

    ctx, _ = context(job["iss"])
    iss = list(ISSUANCES).index(job["iss"])
    rng = np.random.default_rng([SEEDS[job["split"]]["serangan"], iss, len(job["members"]), job["index"]])
    data, _, _ = attack(ctx.master, [copy_pdf(job["iss"], s) for s in job["members"]], job["rule"], 0.0, rng=rng)
    return data


def source_pdf(job: dict) -> bytes:
    """The PDF the evidence is made from: a copy, a coalition's forgery or the unmarked master."""
    if job["part"] == "induk":
        return (ROOT / "samples" / f"{ISSUANCES[job['iss']][0]}.pdf").read_bytes()
    if job["part"] == "koalisi":
        return forged_pdf(job)
    return copy_pdf(job["iss"], job["seq"])


def job_rng(job: dict) -> np.random.Generator:
    """The evidence generator of a job (``PROTOCOL["generators"]``)."""
    if job["part"] == "induk":
        seed, who = SEEDS[job["split"]]["induk"], 1000 + job["rep"]
    elif job["part"] == "koalisi":
        seed, who = SEEDS[job["split"]]["bukti"], 500 + 10 * len(job["members"]) + job["index"]
    else:
        seed, who = SEEDS[job["split"]]["bukti"], job["seq"]
    renderer = RENDERERS.index(job["renderer"]) if job.get("renderer") else 9
    fmt = SCREEN_FORMATS.index(job["medium"]) if job["medium"] in SCREEN_FORMATS else 9
    return np.random.default_rng([seed, list(ISSUANCES).index(job["iss"]), MEDIA.index(job["medium"]), renderer,
                                  int(job.get("dpi") or 0), fmt, who, int(job.get("page") or 1)])


def _page_image(pdf: bytes, page: int = 0) -> np.ndarray:
    from tapak.marker.render import render_pages

    return render_pages(pdf, 200, [page])[0]


def make_evidence(job: dict) -> tuple[str, bytes, dict]:
    """(file name, bytes, truth) of a job's evidence."""
    from tapak.photos import PhotoParams, PrintParams, ScreenshotParams, photo_jpeg, printed_photo_jpeg, \
        screen_photo_jpeg, screenshot_jpeg
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    pdf = source_pdf(job)
    rng = job_rng(job)
    medium = job["medium"]
    who = job.get("seq") or job.get("rep") or job.get("index") or 0
    if medium == "pdf":
        return "bukti.pdf", pdf, {}
    if medium in SCREEN_FORMATS:
        layar = layar_module()
        spec = {"dpi": job["dpi"], "fmt": medium, "renderer": job["renderer"], "framing": job["framing"]}
        data, meta = layar.capture(pdf, spec, rng)
        return ("bukti.png" if medium == "png" else "bukti.jpg"), data, meta
    if medium == "cetak":
        data, meta = printed_photo_jpeg(pdf, job["page"] - 1, rng, PrintParams(),
                                        PhotoParams(angle_deg=PRINT_ANGLES[who % len(PRINT_ANGLES)], long_side=1600))
        return "bukti.jpg", data, {"angle": PRINT_ANGLES[who % len(PRINT_ANGLES)]}
    page = _page_image(pdf)
    params = PhotoParams(angle_deg=PHOTO_ANGLES[who % len(PHOTO_ANGLES)], long_side=1600)
    if medium == "layar_sim":
        data, meta = screenshot_jpeg(page, rng, ScreenshotParams(render_dpi=200.0, long_side=1600))
        info = {"screen_dpi": meta.get("params", {}).get("screen_dpi")}
    elif medium == "foto":
        data, _ = photo_jpeg(page, rng, params)
        info = {"angle": params.angle_deg}
    elif medium == "ponsel":
        isp_rng = np.random.default_rng(int(rng.integers(2**62)))
        data, _ = photo_jpeg(page, rng, params, isp=ISP_PROFILES["ponsel"], isp_rng=isp_rng)
        info = {"angle": params.angle_deg}
    elif medium == "monitor":
        isp_rng = np.random.default_rng(int(rng.integers(2**62)))
        data, _ = screen_photo_jpeg(page, rng, params, ScreenParams(), isp=ISP_PROFILES["ponsel"], isp_rng=isp_rng,
                                    render_dpi=200.0)
        info = {"angle": params.angle_deg}
    else:
        raise ValueError(medium)
    return "bukti.jpg", data, info


def job_key(job: dict) -> str:
    """A unique, readable name for a job."""
    who = {"salinan": lambda: f"s{job['seq']:02d}", "induk": lambda: f"induk{job['rep']}",
           "koalisi": lambda: f"k{len(job['members'])}_{job['index']}"}[job["part"]]()
    parts = [job["iss"], job["part"], job["medium"]]
    if job.get("renderer"):
        parts += [job["renderer"], str(job["dpi"]), job["framing"]]
    if job.get("page"):
        parts.append(f"h{job['page']}")
    return "_".join(parts + [who])


def evidence(job: dict) -> tuple[str, bytes, dict]:
    """The evidence of a job, cached on disk with its truth."""
    path = WORK / "bukti" / job["split"] / f"{job_key(job)}.bin"
    meta_path = path.with_suffix(".json")
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.pop("_name"), path.read_bytes(), meta
    name, data, meta = make_evidence(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta_path.write_text(json.dumps({"_name": name, **meta}, sort_keys=True, default=str), encoding="utf-8")
    return name, data, meta


# --- jobs ----------------------------------------------------------------------------------


def jobs_for(split: str) -> list[dict]:
    """Every job of a split, in a fixed order."""
    out: list[dict] = []
    for name in SETS[split]:
        latar = ISSUANCES[name][3]
        g = GRIDS[split][latar]
        base = {"split": split, "iss": name}
        if latar == "layar":
            for seq in g["pdf"]:
                out.append({**base, "part": "salinan", "medium": "pdf", "seq": seq})
            for medium in SCREEN_FORMATS:
                for renderer in RENDERERS:
                    for dpi in RESOLUTIONS:
                        for k, seq in enumerate(g["layar_copies"]):
                            out.append({**base, "part": "salinan", "medium": medium, "renderer": renderer, "dpi": dpi,
                                        "framing": FRAMINGS[k % len(FRAMINGS)], "seq": seq})
            for medium in ("layar_sim", "foto", "ponsel", "monitor"):
                for seq in g["foto_copies"]:
                    out.append({**base, "part": "salinan", "medium": medium, "seq": seq})
            kc = g["koalisi"]
            for k in kc["k"]:
                for index in range(kc["per_k"]):
                    members = members_of(split, list(ISSUANCES).index(name), k, index)
                    for medium, renderer, dpi in kc["media"]:
                        job = {**base, "part": "koalisi", "medium": medium, "members": members, "index": index,
                               "rule": kc["rule"]}
                        if renderer:
                            job.update(renderer=renderer, dpi=dpi, framing="utuh")
                        out.append(job)
        else:
            for seq in g["cetak_copies"]:
                for page in g["pages"]:
                    out.append({**base, "part": "salinan", "medium": "cetak", "seq": seq, "page": page})
            for seq in g["pdf"]:
                out.append({**base, "part": "salinan", "medium": "pdf", "seq": seq})
        ind = g["induk"]
        for rep in range(ind["reps"]):
            for medium, renderer, dpi in ind["media"]:
                job = {**base, "part": "induk", "medium": medium, "rep": rep}
                if renderer:
                    job.update(renderer=renderer, dpi=dpi, framing="utuh")
                if medium == "cetak":
                    job["page"] = 1
                out.append(job)
    return out


# --- decoding, accusation and counts ---------------------------------------------------------

_CAUGHT: dict = {}


def _init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    import cv2

    from tapak.decoder import rectify

    cv2.setNumThreads(1)
    rectify._EXACT_CACHE = rectify._ByteBudgetCache(150_000_000)  # three workers on a shared machine
    _watch()


def _watch() -> None:
    """Keep the registration of the production path (no change to it)."""
    import tapak.decoder.image as image_mod

    if getattr(image_mod, "_kalibrasi_watch", False):
        return
    register = image_mod.register

    def register_kept(*a, **k):
        reg = register(*a, **k)
        _CAUGHT["reg"] = reg
        return reg

    image_mod.register = register_kept
    image_mod._kalibrasi_watch = True


def decode(job: dict, name: str, data: bytes) -> tuple[list, dict | None]:
    """Observations of an evidence through the production path, and its registration."""
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.rectify import load_gray
    from tapak.decoder.trace import collect_file

    ctx, _ = context(job["iss"])
    _CAUGHT.clear()
    if name.endswith(".pdf"):
        return collect_file(name, data, ctx)[0], None
    obs = collect_from_gray(load_gray(data), ctx)
    reg = _CAUGHT.get("reg")
    if reg is None:
        return obs, None
    return obs, {"page": int(reg.page), "dpi": float(reg.dpi), "effective_dpi": float(reg.effective_dpi),
                 "h_page_to_img": np.asarray(reg.h_page_to_img, dtype=np.float64).tolist(),
                 "method": reg.method, "correlation": float(reg.correlation)}


def obs_path(job: dict) -> Path:
    """Where the observations and the registration of a job are kept."""
    return WORK / "obs" / job["split"] / f"{job_key(job)}.pkl"


def reliability(llr: np.ndarray, wrong: np.ndarray) -> list[list[float]]:
    """Per weight bin (``W_EDGES``): [n, wrong, calibrated expectation, sum of w], positions with |L| > 0."""
    from scipy.special import expit

    a = np.abs(np.asarray(llr, dtype=np.float64))
    wrong = np.asarray(wrong, dtype=bool)
    out = []
    for lo, hi in zip(L_EDGES[:-1], L_EDGES[1:]):
        sel = (a > lo) & (a <= hi)
        out.append([int(sel.sum()), int(wrong[sel].sum()), round(float(np.sum(expit(-a[sel]))), 5),
                    round(float(np.sum(np.tanh(a[sel] / 2.0))), 4)])
    return out


def kind_counts(obs: list, ctx, x: np.ndarray) -> dict:
    """Reliability counts per kind (module docstring) against the leaked copy's codeword ``x``."""
    from tapak.decoder.fuse import fuse
    from tapak.marker.plan import CHANNEL_SHIFT

    kinds = {s.positions[0]: ("baris" if len(s.ref) == 1 else "kata") for s in ctx.plan.channel(CHANNEL_SHIFT)}
    out: dict = {}
    for kind in ("latar", "baris", "kata"):
        llr, pos = [], []
        for sb in obs:
            if not len(sb):
                continue
            if kind == "latar" and sb.channel == "background":
                sel = np.ones(len(sb), dtype=bool)
            elif kind != "latar" and sb.channel == "shift":
                sel = np.array([kinds.get(int(p)) == kind for p in sb.positions], dtype=bool)
            else:
                continue
            llr.append(sb.llr[sel])
            pos.append(sb.positions[sel])
        if not llr:
            out[kind] = reliability(np.zeros(0), np.zeros(0, dtype=bool))
            continue
        llr_a, pos_a = np.concatenate(llr), np.concatenate(pos)
        out[kind] = reliability(llr_a, (llr_a > 0).astype(np.uint8) != x[pos_a])
    fused = fuse(obs, ctx.params.length)
    seen = fused.weights > 0
    out["gabungan"] = reliability(fused.llr[seen], fused.y[seen] != x[seen])
    return out


def analyse(obs: list, ctx, members: list[int], x: np.ndarray | None) -> dict:
    """Verdict, checks, detection bound and (single copies) reliability counts of one evidence."""
    from tapak.decoder.fuse import fuse
    from tapak.decoder.manipulation import is_manipulation_note
    from tapak.decoder.trace import run_trace
    from tapak.tardos.detection import read_miss_ceiling, tempered_error_rates
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    t0 = time.perf_counter()
    res = run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY))
    seconds = time.perf_counter() - t0
    named = sorted(res.named_seqs)
    stage1 = sorted(c.copy.seq for c in res.accused)
    z = res.threshold.threshold
    finite = bool(math.isfinite(z) and z > 0)
    mem = [c.score for c in res.candidates if c.copy.seq in members]
    oth = [c.score for c in res.candidates if c.copy.seq not in members]
    row: dict = {
        "dituduh": named, "dituduh_tahap1": stage1, "anggota": [s for s in named if s in members],
        "salah": [s for s in named if s not in members], "Z": round(z, 3) if finite else None,
        "eps1": res.threshold.eps1,
        "skor_anggota": round(max(mem) / z, 4) if mem and finite else None,
        "skor_lain": round(max(oth) / z, 4) if oth and finite else None,
        "log10_fa": round(res.accused[0].log10_false_accusation, 3) if res.accused else None,
        "hapus": {"ditandai": bool(res.erasure.flagged), "z": res.erasure.z, "z_semua": res.erasure.z_all},
        "kontradiksi": (None if res.contradiction is None else
                        {"ditandai": bool(res.contradiction.flagged), "log10_batas": res.contradiction.log10_bound,
                         "lengkap": bool(res.contradiction.complete)}),
        "balik": {"ditandai": bool(res.reversal.flagged), "z_pilot": res.reversal.z_pilot,
                  "z_tanda": res.reversal.z_signs},
        "peringatan": sum(1 for n in res.notes if is_manipulation_note(n)),
        "detik_tuduh": round(seconds, 2),
        "latar": [{k: sb.meta.get(k) for k in ("page", "pattern_found", "presence", "decoy_z", "pilot_z", "snr",
                                                "cells_used", "bits_read")}
                  for sb in obs if sb.channel == "background"],
        "terbaca": {},
    }
    for sb in obs:
        row["terbaca"][sb.channel] = row["terbaca"].get(sb.channel, 0) + len(sb)
    fused = fuse(obs, ctx.params.length)
    row["posisi"] = int(np.count_nonzero(fused.weights > 0))
    row["efektif"] = round(float(np.sum(fused.weights ** 2)), 1)
    if members:  # honest evidence: the proven bound for the read's weights, coalition of its size
        bounds = {}
        for tau in TEMPERINGS:
            if row["posisi"] == 0:
                bounds[str(tau)] = 0.0
                continue
            b = read_miss_ceiling(ctx.params, fused.weights, tempered_error_rates(fused.llr, tau),
                                  coalition=len(members), eps1=res.threshold.eps1)
            bounds[str(tau)] = round(min(b.log_bound, 0.0) / math.log(10.0), 4)
        row["log10_batas_deteksi"] = bounds
    if x is not None:
        row["kalibrasi"] = kind_counts(obs, ctx, x)
    return row


def trace_job(job: dict) -> dict:
    """One job: make (or reuse) its evidence, decode it, keep the observations, accuse."""
    ctx, _ = context(job["iss"])
    name, data, truth = evidence(job)
    t0 = time.perf_counter()
    obs, reg = decode(job, name, data)
    seconds = time.perf_counter() - t0
    path = obs_path(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump({"obs": obs, "reg": reg, "name": name}, fh)
    members = (job["members"] if job["part"] == "koalisi" else [job["seq"]] if job["part"] == "salinan" else [])
    x = ctx.codewords[job["seq"] - 1].astype(np.uint8) if job["part"] == "salinan" else None
    row = {k: job.get(k) for k in ("split", "iss", "part", "medium", "renderer", "dpi", "framing", "seq", "page", "rep",
                                   "members", "index", "rule")}
    row.update(key=job_key(job), truth=truth, evidence_sha256=hashlib.sha256(data).hexdigest(),
               registrasi=None if reg is None else {k: reg[k] for k in ("page", "dpi", "effective_dpi", "method",
                                                                          "correlation")},
               detik_dekode=round(seconds, 2))
    row.update(analyse(obs, ctx, members, x))
    return row


# --- driver --------------------------------------------------------------------------------


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def run_lacak(split: str, again: bool) -> None:
    """Trace every job of a split not yet recorded (the held-out set once, with the chosen decoder)."""
    import multiprocessing as mp

    out = HASIL / f"{split}.jsonl"
    jobs = jobs_for(split)
    if split == "uji":
        if out.exists() and not again and len(_load(out)) >= len(jobs):
            raise SystemExit(f"{out} sudah lengkap: set uji dilacak sekali")
        check_chosen_decoder()
        mark = HASIL / "uji_dekoder.json"
        if not mark.exists():
            mark.write_text(json.dumps(decoder_fingerprint(), indent=2) + "\n", encoding="utf-8")
    done = {r["key"] for r in _load(out)}
    todo = [j for j in jobs if job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(pool.map(trace_job, todo, chunksize=1)):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {r['key']}: dituduh {r['dituduh']} "
                  f"peringatan {r['peringatan']}", flush=True)


def check_chosen_decoder() -> None:
    """Stop unless the working tree's background decoder is the development choice (hasil/pilihan.json)."""
    from tapak.decoder import ch_background

    path = HASIL / "pilihan.json"
    if not path.exists():
        raise SystemExit("hasil/pilihan.json belum ada: jalankan kandidat.py pilih pada set dev lebih dulu")
    chosen = json.loads(path.read_text(encoding="utf-8"))["dipilih"]
    shipped = getattr(ch_background, "NOISE_MODEL", "sekarang")
    if chosen is None or chosen != shipped:
        raise SystemExit(f"dekoder pohon kerja ({shipped}) bukan pilihan dev ({chosen}); set uji tidak dijalankan")


def decoder_fingerprint() -> dict:
    """Hashes of the decoder sources the held-out run used (written before the run)."""
    files = sorted((ROOT / "tapak" / "decoder").glob("*.py")) + sorted((ROOT / "tapak" / "tardos").glob("*.py"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"git_head": head, "sha256": {f"{f.parent.name}/{f.name}": hashlib.sha256(f.read_bytes()).hexdigest()
                                         for f in files}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    tb = sub.add_parser("terbit")
    tb.add_argument("--split", choices=("dev", "uji"), required=True)
    lc = sub.add_parser("lacak")
    lc.add_argument("--split", choices=("dev", "uji"), required=True)
    lc.add_argument("--ulang", action="store_true")
    jb = sub.add_parser("tugas")
    jb.add_argument("--split", choices=("dev", "uji"), required=True)
    args = ap.parse_args(argv)
    if args.cmd == "terbit":
        issue_all(args.split)
    elif args.cmd == "lacak":
        run_lacak(args.split, args.ulang)
    else:
        jobs = jobs_for(args.split)
        from collections import Counter

        print(len(jobs), dict(Counter((j["part"], j["medium"]) for j in jobs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
