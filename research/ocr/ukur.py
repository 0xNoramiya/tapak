"""OCR of image evidence for sentence variants and word choice: measurements (research/ocr).

A simulation study. Every image comes from ``tapak.photos`` (basic photo simulator, the phone
ISP and monitor models of ``tapak.ponsel``, the screenshot simulator and the laser printer),
never from a real camera, monitor or printer. The OCR engine is the local Tesseract.

The protocol and every seed are fixed here, before any run (``PROTOCOL``):

* Two fictional masters, ``samples/nota_dinas.pdf`` and ``samples/surat_telegram.pdf``. Each is
  issued with ``tapak issue --benih-riset`` (code secret and copy ids from a public research
  seed, no registry, no canary) to N = 20 recipients (c = 3, eps = 1e-6, default shift scheme
  and default background profile), with every sentence variant of the deterministic phrase
  table approved (``tapak semantic suggest --llm mock``, ``approve --all``) and every word-choice
  point approved (``tapak leksikal scan``, ``review --semua --setujui --ya``): arm ``utama``.
  The held-out split also issues the same masters with the same seeds and no visible-text
  channel (arm ``tanpa``, the default issuance): same copy ids and codewords, so the printed
  photos of both arms share every random number and differ only in the issuance.
* Two disjoint seed sets: ``dev`` chooses the OCR settings (page segmentation, resolution,
  preprocessing) among ``CANDIDATES`` with the rule ``PROTOCOL["choice_rule"]``; ``uji`` is
  generated and traced once, at the end, with the chosen settings (``DEFAULT_OCR`` in
  ``tapak/decoder/ocr.py`` must equal the recorded choice, or the run stops).
* Evidence kinds, one image per (kind, document, copy, page): ``foto`` (basic photo simulator,
  page rendered at 200 dpi, view angle drawn 0 to 30 degrees, 1600 px), ``ponsel`` (the same
  with the phone ISP), ``layar`` (the copy on a simulated monitor, photographed through the
  phone ISP; monitor, distance and angle from ``design``), ``tangkapan`` (screenshot of a PDF
  viewer, 1600 px), ``cetak1600`` and ``cetak4000`` (page printed by the simulated laser printer
  with the default background, which does not reach paper, then photographed at 1600 or 4000
  px). Unmarked masters go through ``foto``, ``cetak1600`` and ``cetak4000``: nobody may be
  accused.
* Traces as ``make bench``: not logged in a registry (all of eps), one stage. Every held-out
  image is decoded once (``collect_from_image``, with OCR) and the same observations are accused
  twice: with the OCR sub-channels and without them. Two-page prints fuse the observations of
  pages 1 and 2 of one copy at one resolution. Verdicts: ``benar`` (exactly the leaked copy),
  ``tidak cukup bukti``, ``salah`` (anyone else; anyone at all for an unmarked master).
* Per OCR sub-channel and page: bits printed on the page, bits read, bits wrong among those
  read (sign of the LLR against the leaked copy's codeword), confident wrong bits (|LLR| >= 4),
  and the OCR time of the page (Tesseract only, one thread).

Data minimization: OCR text never leaves memory. Nothing here writes or prints it; the results
hold counts, ids and times. Process pools are capped at 3 workers, BLAS, OpenCV and Tesseract at
one thread each (shared machine). Issuances, evidence images and observations (LLR arrays) go
to ``out/riset_ocr/`` (large, not committed); the JSON lines quoted in the docs go to
``research/ocr/hasil/``. Usage, from the repository root:

    python research/ocr/ukur.py terbit            # issuances of both splits and arms
    python research/ocr/ukur.py dev               # development grid, all candidates; writes the choice
    python research/ocr/ukur.py uji               # held-out, once, with the chosen settings
    python research/ocr/ukur.py ringkas           # tables for the docs
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

WORK = ROOT / "out" / "riset_ocr"
HASIL = ROOT / "research" / "ocr" / "hasil"
WORKERS = 3
DOCS = ("nota_dinas", "surat_telegram")
KINDS = ("foto", "ponsel", "layar", "tangkapan", "cetak1600", "cetak4000")
CONFIDENT_LLR = 4.0

PROTOCOL: dict = {
    "n": 20, "c": 3, "eps": 1e-6,
    "issue": ("tapak issue --benih-riset BENIH --no-registry --canary-domain '' --workers 3, skema geser dan "
              "profil latar bawaan; arm utama juga --semantic (tabel frasa tiruan, semua varian disetujui) dan "
              "--leksikal (tingkat A, semua titik disetujui)"),
    "benih_riset": {"dev": {"nota_dinas": 7301, "surat_telegram": 7302},
                    "uji": {"nota_dinas": 7401, "surat_telegram": 7402}},
    "evidence_seed": {"dev": 7311, "uji": 7411}, "unmarked_seed": 7499,
    "render_dpi": 200,
    "kinds": {
        "foto": "photo_jpeg(render 200 dpi, PhotoParams()): sudut diundi 0 sampai 30 derajat, 1600 px",
        "ponsel": "foto dengan ISP ponsel (ISP_PROFILES['ponsel'])",
        "layar": "screen_photo_jpeg dengan ScreenParams(monitor, jarak dari design) dan ISP ponsel",
        "tangkapan": "screenshot_jpeg(render 200 dpi, ScreenshotParams(long_side=1600))",
        "cetak1600": "printed_photo_jpeg(PrintParams() laser, PhotoParams(sensor_long_side=2400, long_side=1600))",
        "cetak4000": "printed_photo_jpeg(PrintParams() laser, PhotoParams(sensor_long_side=4000, long_side=4000))",
    },
    "design": ("salinan s: i = s - 1; monitor = [fhd24, qhd27, uhd27, laptop13][i % 4], jarak = [30, 45, 60][(i // 4) % 3] "
               "cm, sudut layar = [0, 10, 20, 30][(i + i // 4) % 4]"),
    "generators": ("default_rng([benih bukti, indeks jenis, indeks dokumen, s (induk: 1000 + ulangan), halaman]); ISP "
                   "default_rng([..., 12]); arm tidak ikut, jadi kedua arm berbagi bilangan acak"),
    "dev": {"copies": list(range(1, 7)), "kinds": list(KINDS), "pages": {"nota_dinas": [1, 2], "surat_telegram": [1]},
            "page_kinds_one_page_only": ["ponsel", "layar"]},
    "uji": {
        "prints": {"kinds": ["cetak1600", "cetak4000"], "copies": list(range(1, 21)),
                   "pages": {"nota_dinas": [1, 2], "surat_telegram": [1, 2]}, "arms": ["utama", "tanpa"]},
        "screen": {"kinds": ["foto", "tangkapan"], "copies": list(range(1, 11)),
                   "pages": {"nota_dinas": [1, 2], "surat_telegram": [1]}},
        "screen_page1": {"kinds": ["ponsel", "layar"], "copies": list(range(1, 11)), "pages": [1]},
        "unmarked": {"kinds": ["foto", "cetak1600", "cetak4000"], "reps": 2,
                     "pages": {"nota_dinas": [1, 2], "surat_telegram": [1]}},
        "two_page": "cetak1600 dan cetak4000, halaman 1 dan 2 salinan yang sama, kedua dokumen, kedua arm",
    },
    "candidates": {
        "psm3": "halaman terektifikasi pada resolusi analisis registrasi, --psm 3",
        "psm4": "sama, --psm 4",
        "psm6": "sama, --psm 6",
        "psm3_300": "gambar bukti dicuplik ulang ke bingkai halaman pada 300 dpi (kubik), --psm 3",
        "psm6_300": "sama, --psm 6",
        "psm3_rata": "halaman terektifikasi dibagi taksiran terang kertas (flatten_illumination), --psm 3",
    },
    "choice_rule": ("skor = bit benar - 5 x bit salah, dijumlahkan atas semua gambar dev (bit OCR yang terbaca, "
                    "dibandingkan dengan kode salinan yang bocor). Kandidat dengan skor tertinggi dipilih; bila skor "
                    "kandidat lain kurang dari 2 % di bawahnya, dipilih yang total waktu OCR-nya paling kecil di antara "
                    "kandidat dalam rentang 2 % itu. Ditetapkan sebelum dev dijalankan."),
    "spending": "tidak dicatat (seluruh eps), satu tahap, seperti make bench",
    "confident_llr": CONFIDENT_LLR,
}


def candidates() -> dict:
    """OCR settings compared on the development seeds."""
    from tapak.decoder.ocr import OcrSettings

    return {"psm3": OcrSettings(psm=3), "psm4": OcrSettings(psm=4), "psm6": OcrSettings(psm=6),
            "psm3_300": OcrSettings(psm=3, dpi=300.0), "psm6_300": OcrSettings(psm=6, dpi=300.0),
            "psm3_rata": OcrSettings(psm=3, flatten=True)}


def design(i: int) -> dict:
    """Monitor, distance and on-screen view angle of copy index i (0-based)."""
    return {"monitor": ["fhd24", "qhd27", "uhd27", "laptop13"][i % 4],
            "distance_cm": float([30, 45, 60][(i // 4) % 3]), "angle": float([0, 10, 20, 30][(i + i // 4) % 4])}


# --- issuance ------------------------------------------------------------------------------


def _tapak(*args: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    run = subprocess.run([sys.executable, "-m", "tapak.cli", *args], cwd=ROOT, env=env, capture_output=True,
                         text=True)
    if run.returncode != 0:
        raise RuntimeError(f"tapak {' '.join(args[:2])} gagal: {run.stderr.strip()[-400:]}")
    return run.stdout


def issuance_dir(split: str, doc: str, arm: str) -> Path:
    return WORK / split / f"{doc}_{arm}"


def issue(split: str, doc: str, arm: str) -> dict:
    """Issue one (split, document, arm) with the CLI, once; returns its summary."""
    folder = issuance_dir(split, doc, arm)
    master = ROOT / "samples" / f"{doc}.pdf"
    seed = PROTOCOL["benih_riset"][split][doc]
    if not list((folder / "data" / "dokumen").glob("*/manifest.json")):
        folder.mkdir(parents=True, exist_ok=True)
        extra: list[str] = []
        if arm == "utama":
            sem, lex = folder / "varian.json", folder / "leksikal.json"
            _tapak("semantic", "suggest", str(master), "-o", str(sem), "--llm", "mock")
            _tapak("semantic", "approve", str(sem), "--all")
            _tapak("leksikal", "scan", str(master), "-o", str(lex))
            _tapak("leksikal", "review", str(lex), "--semua", "--setujui", "--ya")
            extra = ["--semantic", str(sem), "--leksikal", str(lex)]
        _tapak("--data", str(folder / "data"), "--keys", str(folder / "keys"), "issue", str(master),
               str(ROOT / "samples" / "recipients.csv"), "--no-registry", "--canary-domain", "", "--workers",
               str(WORKERS), "--benih-riset", str(seed), *extra)
    ctx, manifest, _ = context(split, doc, arm)
    return {"split": split, "doc": doc, "arm": arm, "benih_riset": seed, "copies": len(manifest.copies),
            "plan_summary": manifest.plan_summary, "shift_scheme": manifest.shift_settings.scheme,
            "copy_ids_sha256": hashlib.sha256(",".join(c.copy_id for c in manifest.copies).encode()).hexdigest(),
            "codewords_sha256": hashlib.sha256(ctx.codewords.tobytes()).hexdigest(),
            "visible_bits_per_page": visible_bits(ctx)}


def visible_bits(ctx) -> dict[str, dict[str, int]]:
    """Semantic and lexical bits printed on each page (1-based)."""
    from tapak.decoder.ocr import page_slots

    out = {}
    for k in range(len(ctx.master.layout.pages)):
        sem, lex = page_slots(ctx, k)
        out[str(k + 1)] = {"semantik": sum(len(s.positions) for s in sem), "leksikal": sum(len(s.positions) for s in lex)}
    return out


# --- worker side ---------------------------------------------------------------------------

_CTX: dict = {}


def _init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    import cv2

    cv2.setNumThreads(1)


def context(split: str, doc: str, arm: str):
    """(trace context, manifest, workspace folder) of an issuance, cached per process."""
    key = (split, doc, arm)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest

        root = issuance_dir(split, doc, arm)
        folder = next((root / "data" / "dokumen").glob("*/manifest.json")).parent
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        secret = load_code_secret(root / "keys" / "code_secret.key")
        _CTX[key] = (load_context((folder / "induk.pdf").read_bytes(), manifest, secret, folder=folder), manifest,
                     folder)
    return _CTX[key]


def evidence(job: dict) -> bytes:
    """The evidence image of a job (cached on disk; the random numbers never depend on the arm)."""
    path = WORK / "bukti" / job["split"] / job["arm"] / f"{job_key(job)}.jpg"
    if path.exists():
        return path.read_bytes()
    from tapak.marker.render import render_pages
    from tapak.photos import (PhotoParams, PrintParams, ScreenshotParams, photo_jpeg, printed_photo_jpeg,
                              screen_photo_jpeg, screenshot_jpeg)
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    split, kind, doc, seq, page = job["split"], job["kind"], job["doc"], job["seq"], job["page"]
    if seq is None:
        pdf = (ROOT / "samples" / f"{doc}.pdf").read_bytes()
        who, seed = 1000 + job["rep"], PROTOCOL["unmarked_seed"]
    else:
        _, manifest, folder = context(split, doc, job["arm"])
        pdf = (folder / "salinan" / manifest.copies[seq - 1].file).read_bytes()
        who, seed = seq, PROTOCOL["evidence_seed"][split]
    base = [seed, KINDS.index(kind), DOCS.index(doc), who, page]
    rng = np.random.default_rng(base)
    if kind.startswith("cetak"):
        res = int(kind[len("cetak"):])
        data, _ = printed_photo_jpeg(pdf, page - 1, rng, PrintParams(),
                                     PhotoParams(sensor_long_side=max(2400, res), long_side=res))
    else:
        img = render_pages(pdf, PROTOCOL["render_dpi"], [page - 1])[0]
        ponsel = ISP_PROFILES["ponsel"]
        if kind == "foto":
            data, _ = photo_jpeg(img, rng, PhotoParams())
        elif kind == "ponsel":
            data, _ = photo_jpeg(img, rng, PhotoParams(), isp=ponsel, isp_rng=np.random.default_rng(base + [12]))
        elif kind == "layar":
            d = design((seq or who) - 1)
            data, _ = screen_photo_jpeg(img, rng, PhotoParams(angle_deg=d["angle"]),
                                        ScreenParams(monitor=d["monitor"], distance_cm=d["distance_cm"]), isp=ponsel,
                                        isp_rng=np.random.default_rng(base + [12]),
                                        render_dpi=float(PROTOCOL["render_dpi"]))
        else:
            data, _ = screenshot_jpeg(img, rng, ScreenshotParams(render_dpi=float(PROTOCOL["render_dpi"]),
                                                                 long_side=1600))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def job_key(job: dict) -> str:
    who = f"s{job['seq']:03d}" if job["seq"] is not None else f"induk{job['rep']}"
    return f"{job['doc']}_{job['kind']}_{who}_p{job['page']}"


def ocr_stats(obs, x: np.ndarray | None, ctx, page: int) -> dict:
    """Per OCR sub-channel: bits printed on the page, read, wrong, confidently wrong; OCR seconds."""
    from tapak.decoder.ocr import page_slots
    from tapak.marker.plan import CHANNEL_LEXICAL_OCR, CHANNEL_SEMANTIC_OCR

    sem, lex = page_slots(ctx, page)
    printed = {CHANNEL_SEMANTIC_OCR: sum(len(s.positions) for s in sem),
               CHANNEL_LEXICAL_OCR: sum(len(s.positions) for s in lex)}
    out: dict = {}
    for name, total in printed.items():
        sb = next((o for o in obs if o.channel == name), None)
        d = {"printed": total, "read": 0, "wrong": None if x is None else 0, "confident_wrong": None if x is None else 0}
        if sb is not None:
            d["read"] = len(sb)
            d["slots_unread"] = int(sb.meta.get("slots_total", 0) or 0) - int(sb.meta.get("slots_read", 0) or 0)
            d["low_confidence"] = int(sb.meta.get("slots_low_confidence", sb.meta.get("points_low_confidence", 0)) or 0)
            if sb.meta.get("ocr_failed"):
                d["ocr_failed"] = True
            if x is not None and len(sb):
                bad = (sb.llr > 0).astype(int) != x[sb.positions]
                d["wrong"] = int(bad.sum())
                d["confident_wrong"] = int((bad & (np.abs(sb.llr) >= CONFIDENT_LLR)).sum())
        out[name] = d
    secs = [o.meta.get("ocr_seconds") for o in obs if o.channel in printed and o.meta.get("ocr_seconds") is not None]
    out["ocr_seconds"] = max(secs) if secs else None
    return out


def dev_job(job: dict) -> dict:
    """Register one development image, then OCR it with every candidate (same registration)."""
    from tapak.decoder.ocr import page_image, read_page_text, recognize
    from tapak.decoder.rectify import load_gray, register

    ctx, _, _ = context(job["split"], job["doc"], job["arm"])
    gray = load_gray(evidence(job))
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    reg = register(gray, ctx.master.pdf_bytes, sizes)
    row = {k: job[k] for k in ("split", "arm", "doc", "kind", "seq", "page")}
    if reg is None:
        return {**row, "registered": False}
    row.update(registered=True, registered_page=reg.page + 1, dpi=reg.dpi, effective_dpi=round(reg.effective_dpi, 1))
    x = ctx.codewords[job["seq"] - 1]
    p = ctx.master.layout.pages[reg.page]
    row["candidates"] = {}
    for name, settings in candidates().items():
        image, dpi = page_image(gray, reg, (p.width, p.height), settings)
        t0 = time.perf_counter()
        text = recognize(image, dpi, settings.psm)
        seconds = round(time.perf_counter() - t0, 2)
        obs = read_page_text(text, reg.page, ctx)
        del text, image
        for sb in obs:
            sb.meta["ocr_seconds"] = seconds
        row["candidates"][name] = ocr_stats(obs, x, ctx, reg.page)
    return row


def save_obs(job: dict, obs) -> None:
    arrays = {}
    for k, sb in enumerate(obs):
        arrays[f"{k}_{sb.channel}_pos"] = sb.positions
        arrays[f"{k}_{sb.channel}_llr"] = sb.llr
    path = WORK / "obs" / job["split"] / job["arm"] / f"{job_key(job)}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def load_obs(job: dict):
    from tapak.decoder.softbits import SoftBits

    data = np.load(WORK / "obs" / job["split"] / job["arm"] / f"{job_key(job)}.npz")
    parts: dict[int, dict] = {}
    for name in data.files:
        k, rest = name.split("_", 1)
        channel, what = rest.rsplit("_", 1)
        parts.setdefault(int(k), {"channel": channel})[what] = data[name]
    return [SoftBits(p["channel"], p["pos"], p["llr"]) for _, p in sorted(parts.items())]


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
            "score_z": round(scores.get(expected, 0.0) / z, 3) if finite and expected is not None else None,
            "max_innocent_z": round(max(innocent) / z, 3) if finite and innocent else None,
            "log10_fa": round(a.accused[0].log10_false_accusation, 2) if a.accused else None}


def uji_job(job: dict) -> dict:
    """Decode one held-out image once (with OCR); accuse with and without the OCR sub-channels."""
    from tapak.decoder.image import collect_from_image
    from tapak.marker.plan import OCR_SUBCHANNELS

    ctx, _, _ = context(job["split"], job["doc"], job["arm"])
    data = evidence(job)
    t0 = time.perf_counter()
    obs = collect_from_image(data, ctx)
    seconds = round(time.perf_counter() - t0, 1)
    save_obs(job, obs)
    row = {k: job[k] for k in ("split", "arm", "doc", "kind", "seq", "page")}
    if job["seq"] is None:
        row["rep"] = job["rep"]
    reg = next((o.meta for o in obs if "correlation" in o.meta), None)
    row["registered_page"] = reg["page"] + 1 if reg else None
    row["effective_dpi"] = round(reg["effective_dpi"], 1) if reg else None
    x = ctx.codewords[job["seq"] - 1] if job["seq"] is not None else None
    row["shift_read"] = sum(len(o) for o in obs if o.channel == "shift")
    row["background_found"] = any(o.meta.get("pattern_found") for o in obs if o.channel == "background")
    row["ocr"] = ocr_stats(obs, x, ctx, reg["page"]) if reg else None
    row["met_ocr"] = verdict(obs, ctx, job["seq"])
    row["tanpa_ocr"] = verdict([o for o in obs if o.channel not in OCR_SUBCHANNELS], ctx, job["seq"])
    row["seconds"] = seconds
    row["evidence_sha256"] = hashlib.sha256(data).hexdigest()
    return row


# --- driver --------------------------------------------------------------------------------


def _pool(fn, jobs: list[dict]) -> list[dict]:
    import multiprocessing as mp

    out = []
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        for r in pool.map(fn, jobs, chunksize=1):
            brief = {k: r.get(k) for k in ("arm", "doc", "kind", "seq", "page")}
            if "met_ocr" in r:
                brief.update(ocr=r["met_ocr"]["verdict"], tanpa=r["tanpa_ocr"]["verdict"])
            print(json.dumps(brief, ensure_ascii=False), flush=True)
            out.append(r)
    return out


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def dev_jobs() -> list[dict]:
    g = PROTOCOL["dev"]
    jobs = []
    for doc in DOCS:
        for seq in g["copies"]:
            for kind in g["kinds"]:
                pages = [1] if kind in g["page_kinds_one_page_only"] else g["pages"][doc]
                for page in pages:
                    jobs.append({"split": "dev", "arm": "utama", "doc": doc, "kind": kind, "seq": seq, "page": page})
    return jobs


def uji_jobs() -> list[dict]:
    g = PROTOCOL["uji"]
    jobs = []
    for arm in g["prints"]["arms"]:
        for doc in DOCS:
            for kind in g["prints"]["kinds"]:
                for seq in g["prints"]["copies"]:
                    for page in g["prints"]["pages"][doc]:
                        jobs.append({"split": "uji", "arm": arm, "doc": doc, "kind": kind, "seq": seq, "page": page})
    for doc in DOCS:
        for kind in g["screen"]["kinds"]:
            for seq in g["screen"]["copies"]:
                for page in g["screen"]["pages"][doc]:
                    jobs.append({"split": "uji", "arm": "utama", "doc": doc, "kind": kind, "seq": seq, "page": page})
        for kind in g["screen_page1"]["kinds"]:
            for seq in g["screen_page1"]["copies"]:
                jobs.append({"split": "uji", "arm": "utama", "doc": doc, "kind": kind, "seq": seq, "page": 1})
        for kind in g["unmarked"]["kinds"]:
            for page in g["unmarked"]["pages"][doc]:
                for rep in range(g["unmarked"]["reps"]):
                    jobs.append({"split": "uji", "arm": "utama", "doc": doc, "kind": kind, "seq": None, "page": page,
                                 "rep": rep})
    return jobs


def choose(rows: list[dict]) -> dict:
    """Apply PROTOCOL['choice_rule'] to the development rows."""
    totals: dict[str, dict] = {}
    for r in rows:
        for name, st in (r.get("candidates") or {}).items():
            t = totals.setdefault(name, {"read": 0, "wrong": 0, "confident_wrong": 0, "printed": 0, "seconds": 0.0,
                                         "pages": 0})
            for ch in ("semantic_ocr", "lexical_ocr"):
                t["read"] += st[ch]["read"]
                t["wrong"] += st[ch]["wrong"] or 0
                t["confident_wrong"] += st[ch]["confident_wrong"] or 0
                t["printed"] += st[ch]["printed"]
            t["seconds"] += st["ocr_seconds"] or 0.0
            t["pages"] += 1
    for t in totals.values():
        t["score"] = (t["read"] - t["wrong"]) - 5 * t["wrong"]
        t["seconds"] = round(t["seconds"], 1)
    best = max(t["score"] for t in totals.values())
    near = [k for k, t in totals.items() if t["score"] >= best - 0.02 * abs(best)]
    chosen = min(near, key=lambda k: (totals[k]["seconds"], k))
    return {"totals": totals, "best_score": best, "within_2_percent": sorted(near), "chosen": chosen,
            "rule": PROTOCOL["choice_rule"]}


def run_terbit() -> None:
    rows = [issue(split, doc, "utama") for split in ("dev", "uji") for doc in DOCS]
    rows += [issue("uji", doc, "tanpa") for doc in DOCS]
    _write(HASIL / "terbit.jsonl", rows)
    proto = dict(PROTOCOL, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HASIL / "protokol.json").write_text(json.dumps(proto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in rows:
        print(json.dumps({k: r[k] for k in ("split", "doc", "arm", "visible_bits_per_page")}, ensure_ascii=False))


def run_dev() -> None:
    rows = _pool(dev_job, dev_jobs())
    _write(HASIL / "dev.jsonl", rows)
    choice = choose(rows)
    (HASIL / "pilihan.json").write_text(json.dumps(choice, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(choice, indent=2, ensure_ascii=False))


def run_uji(again: bool) -> None:
    from tapak.decoder.ocr import DEFAULT_OCR

    out = HASIL / "uji.jsonl"
    if out.exists() and not again:
        raise SystemExit(f"{out} sudah ada: set uji dilacak sekali (pakai --ulang untuk menimpa)")
    choice = json.loads((HASIL / "pilihan.json").read_text(encoding="utf-8"))["chosen"]
    if candidates()[choice] != DEFAULT_OCR:
        raise SystemExit(f"DEFAULT_OCR di tapak/decoder/ocr.py bukan pilihan dev ({choice}); uji tidak dijalankan")
    rows = _pool(uji_job, uji_jobs())
    _write(out, rows)
    two = []
    for arm in PROTOCOL["uji"]["prints"]["arms"]:
        for doc in DOCS:
            ctx, _, _ = context("uji", doc, arm)
            from tapak.marker.plan import OCR_SUBCHANNELS

            for kind in PROTOCOL["uji"]["prints"]["kinds"]:
                for seq in PROTOCOL["uji"]["prints"]["copies"]:
                    obs = []
                    for page in (1, 2):
                        obs += load_obs({"split": "uji", "arm": arm, "doc": doc, "kind": kind, "seq": seq, "page": page})
                    two.append({"split": "uji", "arm": arm, "doc": doc, "kind": kind, "seq": seq,
                                "met_ocr": verdict(obs, ctx, seq),
                                "tanpa_ocr": verdict([o for o in obs if o.channel not in OCR_SUBCHANNELS], ctx, seq)})
    _write(HASIL / "uji_dua_halaman.jsonl", two)


# --- summary -------------------------------------------------------------------------------


def _counts(rows: list[dict], key: str) -> str:
    c = {v: sum(r[key]["verdict"] == v for r in rows) for v in ("benar", "tidak cukup bukti", "salah")}
    return f"{c['benar']} / {c['tidak cukup bukti']} / {c['salah']}"


def _ocr_cells(rows: list[dict]) -> tuple[str, str, str, str]:
    printed = read = wrong = conf = 0
    secs = []
    for r in rows:
        o = r.get("ocr") or {}
        for ch in ("semantic_ocr", "lexical_ocr"):
            if ch in o:
                printed += o[ch]["printed"]
                read += o[ch]["read"]
                wrong += o[ch]["wrong"] or 0
                conf += o[ch]["confident_wrong"] or 0
        if o.get("ocr_seconds") is not None:
            secs.append(o["ocr_seconds"])
    n = max(len(rows), 1)
    ber = f"{100 * wrong / read:.1f} % ({wrong} dari {read})" if read else "-"
    t = f"{np.median(secs):.1f} (maks. {max(secs):.1f})" if secs else "-"
    return f"{read / n:.1f} dari {printed / n:.1f}", ber, str(conf), t


def summarize() -> None:
    rows = _load(HASIL / "uji.jsonl")
    two = _load(HASIL / "uji_dua_halaman.jsonl")
    lines = ["| Bukti (arm utama) | Gambar | Bit OCR terbaca per halaman | Bit salah di antara yang terbaca | "
             "Salah yakin (abs LLR >= 4) | Waktu OCR per halaman, detik (median) | Benar / tcb / salah, dengan OCR | "
             "tanpa OCR |", "|---|---|---|---|---|---|---|---|"]
    summary: dict = {"per_jenis": {}, "dua_halaman": {}, "induk": {}}
    for kind in KINDS:
        for doc in DOCS:
            sel = [r for r in rows if r["arm"] == "utama" and r["kind"] == kind and r["doc"] == doc
                   and r["seq"] is not None]
            for page in sorted({r["page"] for r in sel}):
                s = [r for r in sel if r["page"] == page]
                cells = _ocr_cells(s)
                label = f"{kind}, {doc} hal. {page}"
                lines.append(f"| {label} | {len(s)} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | "
                             f"{_counts(s, 'met_ocr')} | {_counts(s, 'tanpa_ocr')} |")
                summary["per_jenis"][label] = {"gambar": len(s), "bit": cells[0], "galat": cells[1],
                                               "salah_yakin": cells[2], "detik": cells[3],
                                               "dengan_ocr": _counts(s, "met_ocr"), "tanpa_ocr": _counts(s, "tanpa_ocr")}
    lines += ["", "| Cetak dua halaman | arm utama, dengan OCR | arm utama, tanpa OCR | arm tanpa (penerbitan bawaan) |",
              "|---|---|---|---|"]
    for kind in PROTOCOL["uji"]["prints"]["kinds"]:
        for doc in DOCS:
            u = [r for r in two if r["arm"] == "utama" and r["kind"] == kind and r["doc"] == doc]
            t = [r for r in two if r["arm"] == "tanpa" and r["kind"] == kind and r["doc"] == doc]
            lines.append(f"| {kind}, {doc} | {_counts(u, 'met_ocr')} | {_counts(u, 'tanpa_ocr')} | "
                         f"{_counts(t, 'tanpa_ocr')} |")
            summary["dua_halaman"][f"{kind}, {doc}"] = {"dengan_ocr": _counts(u, "met_ocr"),
                                                        "tanpa_ocr": _counts(u, "tanpa_ocr"),
                                                        "arm_tanpa": _counts(t, "tanpa_ocr")}
    lines += ["", "| Cetak satu halaman | arm utama, dengan OCR | arm utama, tanpa OCR | arm tanpa |", "|---|---|---|---|"]
    for kind in PROTOCOL["uji"]["prints"]["kinds"]:
        for doc in DOCS:
            for page in (1, 2):
                u = [r for r in rows if r["arm"] == "utama" and r["kind"] == kind and r["doc"] == doc
                     and r["page"] == page and r["seq"] is not None]
                t = [r for r in rows if r["arm"] == "tanpa" and r["kind"] == kind and r["doc"] == doc
                     and r["page"] == page]
                lines.append(f"| {kind}, {doc} hal. {page} | {_counts(u, 'met_ocr')} | {_counts(u, 'tanpa_ocr')} | "
                             f"{_counts(t, 'tanpa_ocr')} |")
    flips = {"hanya_dengan_ocr": 0, "hanya_tanpa_ocr": 0}
    for r in [r for r in rows if r["arm"] == "utama" and r["seq"] is not None] + [r for r in two if r["arm"] == "utama"]:
        a, b = r["met_ocr"]["verdict"] == "benar", r["tanpa_ocr"]["verdict"] == "benar"
        flips["hanya_dengan_ocr"] += a and not b
        flips["hanya_tanpa_ocr"] += b and not a
    summary["perubahan_putusan"] = flips
    unmarked = [r for r in rows if r["seq"] is None]
    summary["induk"] = {"pelacakan": len(unmarked), "dituduh": sum(bool(r["met_ocr"]["accused"]) for r in unmarked),
                        "bit_ocr_terbaca": sum((r.get("ocr") or {}).get(ch, {}).get("read", 0) for r in unmarked
                                               for ch in ("semantic_ocr", "lexical_ocr"))}
    false = sum(r[k]["verdict"] == "salah" for r in rows + two for k in ("met_ocr", "tanpa_ocr"))
    summary["tuduhan_salah"] = false
    innocent = [r[k]["max_innocent_z"] for r in rows + two for k in ("met_ocr", "tanpa_ocr")
                if r[k]["max_innocent_z"] is not None]
    summary["skor_tak_bersalah_tertinggi_per_Z"] = max(innocent) if innocent else None
    lines += ["", f"Perubahan putusan (gambar dan pasangan arm utama): {flips}",
              f"Induk tanpa tanda: {summary['induk']}", f"Tuduhan salah: {false}",
              f"Skor tak bersalah tertinggi / Z: {summary['skor_tak_bersalah_tertinggi_per_Z']}"]
    print("\n".join(lines))
    (HASIL / "ringkas_uji.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("terbit")
    sub.add_parser("dev")
    u = sub.add_parser("uji")
    u.add_argument("--ulang", action="store_true", help="timpa hasil uji yang sudah ada")
    sub.add_parser("ringkas")
    args = ap.parse_args(argv)
    if args.cmd == "terbit":
        run_terbit()
    elif args.cmd == "dev":
        run_dev()
    elif args.cmd == "uji":
        run_uji(args.ulang)
    else:
        summarize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
