"""Photos of part of a page at low resolution: the footprint try of the rescue stage, before and after.

research/registrasi left partial phone photos almost untouched: they were taken at 4000 px and
cropped, so the feature stage (SIFT) already found nearly all of them. A leaker who photographs
the whole page and crops one part afterwards keeps far fewer pixels: at a third of a 1600 px
photo, the middle 40 % of a page is about 300 x 200 pixels (35 to 45 dpi). There SIFT still finds
the page to within a pixel, but the ECC refinement drifted off that pose (research notes in
``README.md``), and the rescue stage refused the evidence. ``rectify.rescue_register`` now also
refines a tilted initial pose against the master cut to its footprint (``RESCUE_FOOTPRINT``).

Evidence (``PROTOCOL``): the honest phone photos of research/kalibrasi (``foto`` and ``ponsel``,
one per copy, the whole page at 1600 px; synthetic), cropped by the leaker to the whole page, the
top 30 %, the middle 40 %, the bottom 40 % (of the page height, full width) or one paragraph,
scaled by 1, 0.5 or 0.35 and sent through a messenger (JPEG quality 58 to 62). The true pose of
every crop is the stored registration of the whole photo (each of them named its copy) through
the crop and the scale. Development: issuances K1 and K2 of research/kalibrasi; held out: U1
and U2 (photos the rescue change was not designed on). One crop in four is also registered
against the other document of its split (``silang``): any registration there is a wrong pose.

Every crop is registered once with the production code. When the rescue stage runs, its tries
are kept; the outcome before this change is the decision of ``rectify.rescue_decision`` on the
same tries without the footprint ones (every other try is computed exactly as before), so before
and after are paired on the same evidence. Pose classes and errors as research/registrasi
(``pose_class``). Held out only: every registered crop is traced (all of eps, one stage) after,
and before when that registration differs.

Usage (work folders: ``$TAPAK_KALIBRASI_KERJA`` with research/kalibrasi's evidence and
observations; ``$TAPAK_FOTOPOTONG_KERJA``, default out/riset_fotopotong):

    python research/fotopotong/ukur.py jalan --split dev
    python research/fotopotong/ukur.py jalan --split uji       # once
    python research/fotopotong/ukur.py ringkas --split uji
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"
os.environ.setdefault("TAPAK_WORKERS", "1")  # one rescue thread per process: three processes share the machine

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "research" / "kalibrasi"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import ukur as kal  # noqa: E402  research/kalibrasi/ukur.py: photos and contexts

HASIL = ROOT / "research" / "fotopotong" / "hasil"
WORK = Path(os.environ.get("TAPAK_FOTOPOTONG_KERJA") or ROOT / "out" / "riset_fotopotong")
WORKERS = 3
CROPS = {"utuh": (0.0, 1.0), "atas30": (0.08, 0.38), "tengah40": (0.30, 0.70), "bawah40": (0.55, 0.95),
         "paragraf": None}
SCALES = (1.0, 0.5, 0.35)
SPLITS = {"dev": ("K1", "K2"), "uji": ("U1", "U2")}
OTHER = {"K1": "K2", "K2": "K1", "U1": "U2", "U2": "U1"}
MEDIA = ("foto", "ponsel")
SEED = 14001
PROTOCOL = {"crops": {k: v for k, v in CROPS.items()}, "scales": SCALES, "splits": SPLITS, "media": MEDIA,
            "silang": "satu dari setiap empat potongan (urutan tugas), terhadap dokumen lain dari split yang sama",
            "jpeg": "mutu 58 sampai 62 (default_rng([SEED, indeks tugas]))", "seed": SEED,
            "lacak": "set uji saja: semua potongan yang diregistrasi, seluruh eps, satu tahap"}


def _reg():
    """research/registrasi/ukur.py (pose classes and errors), loaded under its own name."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("reg_ukur", ROOT / "research" / "registrasi" / "ukur.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jobs_for(split: str) -> list[dict]:
    """Every crop of a split, in a fixed order."""
    out = []
    for iss in SPLITS[split]:
        kal_split = "dev" if split == "dev" else "uji"
        for job in kal.jobs_for(kal_split):
            if job["iss"] != iss or job["part"] != "salinan" or job["medium"] not in MEDIA:
                continue
            for crop in CROPS:
                for scale in SCALES:
                    out.append({"split": split, "src": job, "crop": crop, "scale": scale, "against": iss})
    for i, job in enumerate(list(out)):
        if i % 4 == 0:
            out.append(dict(job, against=OTHER[job["src"]["iss"]]))
    return out


def job_key(job: dict) -> str:
    return f"{kal.job_key(job['src'])}_{job['crop']}_{job['scale']}_vs{job['against']}"


def crop_box(ctx, crop: str) -> tuple[float, float, float, float]:
    """The crop's box on page 1 in points."""
    page = ctx.master.layout.pages[0]
    if CROPS[crop] is not None:
        a, b = CROPS[crop]
        return 0.0, a * page.height, page.width, b * page.height
    rows = page.rows
    mid = len(rows) // 2
    part = rows[mid:mid + 4]
    return (min(r.bbox[0] for r in part) - 6.0, part[0].bbox[1] - 6.0, max(r.bbox[2] for r in part) + 6.0,
            part[-1].bbox[3] + 6.0)


def make_crop(job: dict, index: int) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float, float]]:
    """(gray image as sent, true page-points-to-image map, visible box in points) of a job."""
    import cv2

    from tapak.decoder.rectify import load_gray
    from tapak.photos import encode_jpeg

    R = _reg()
    src = job["src"]
    with kal.obs_path(src).open("rb") as fh:
        reg = pickle.load(fh)["reg"]
    ctx, _ = kal.context(src["iss"])
    _, data, _ = kal.evidence(src)
    gray = load_gray(data)
    h_full = np.asarray(reg["h_page_to_img"]) @ R.pt_to_px(reg["dpi"])  # page points -> photo pixels
    box = crop_box(ctx, job["crop"])
    x0, y0, x1, y1 = box
    corners = R.apply(h_full, np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]))
    ix0, iy0 = (max(0, int(np.floor(v))) for v in corners.min(axis=0))
    ix1, iy1 = int(np.ceil(corners[:, 0].max())), int(np.ceil(corners[:, 1].max()))
    ix1, iy1 = min(ix1, gray.shape[1]), min(iy1, gray.shape[0])
    sub = gray[iy0:iy1, ix0:ix1]
    s = job["scale"]
    if s != 1.0:
        sub = cv2.resize(sub, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng([SEED, index])
    img = load_gray(encode_jpeg(np.clip(sub, 0, 255).astype(np.uint8), int(rng.integers(58, 63))))
    crop_map = np.array([[s, 0, 0.5 * s - 0.5], [0, s, 0.5 * s - 0.5], [0, 0, 1.0]]) @ R._shift(-ix0, -iy0)
    return img, crop_map @ h_full, box


def pose_of(R, ctx, h, dpi, page: int, h_true, box, image_px) -> dict:
    """Pose class and errors of a registration (page, homography at dpi) against the truth."""
    pts = R.visible_points(h_true, (ctx.master.layout.pages[0].width, ctx.master.layout.pages[0].height),
                           image_px, box)
    tpts = R.text_points(ctx.master.layout.pages[0], h_true, image_px, box)
    same = page == 0
    err_all = R.pose_error(h, dpi, h_true, pts) if same else None
    err_text = R.pose_error(h, dpi, h_true, tpts) if same and len(tpts) else None
    return {"class": R.pose_class(err_text, err_all, same), "err_p95": (err_all or {}).get("p95"),
            "err_text_p95": (err_text or {}).get("p95")}


def run_job(item: tuple[int, dict]) -> dict:
    """Register one crop (and trace it on the held-out split)."""
    from tapak.decoder import rectify

    index, job = item
    R = _reg()
    img, h_true, box = make_crop(job, index)
    ctx, _ = kal.context(job["against"])
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    wrong_doc = job["against"] != job["src"]["iss"]
    diag: dict = {}
    t0 = time.perf_counter()
    reg = rectify.register(img, ctx.master.pdf_bytes, sizes, diag=diag)
    seconds = time.perf_counter() - t0
    row = {"key": job_key(job), "split": job["split"], "crop": job["crop"], "scale": job["scale"],
           "medium": job["src"]["medium"], "seq": job["src"]["seq"], "iss": job["src"]["iss"],
           "against": job["against"], "silang": wrong_doc, "image_px": list(img.shape[::-1]),
           "detik": round(seconds, 2), "tahap_awal": diag.get("outcome"), "jejak_dicoba": False}
    image_px = (img.shape[1], img.shape[0])

    def describe(page, h, dpi):
        if wrong_doc:
            return {"class": "salah", "err_p95": None, "err_text_p95": None}
        return pose_of(R, ctx, h, dpi, page, h_true, box, image_px)

    after = None if reg is None else {"page": reg.page, "method": reg.method, **describe(reg.page, reg.h_page_to_img, reg.dpi)}
    before = after
    before_try = None
    rescue = diag.get("rescue")
    if rescue is not None:
        tries = rescue.get("tries", [])
        row["jejak_dicoba"] = any(t["origin"].endswith(":jejak") for t in tries)
        old = [t for t in tries if not t["origin"].endswith(":jejak")]
        centre = np.array([[rescue["centre"]]], dtype=np.float64)
        best, outcome, _ = rectify.rescue_decision(old, centre)
        before_try = best if outcome == "terdaftar" else None
        before = None if outcome != "terdaftar" else {"page": best["page"], "method": f"penyelamat:{best['origin']}",
                                                         **describe(best["page"], best["h"], best["dpi"])}
        row["penyelamat"] = {"sesudah": rescue.get("outcome"), "sebelum": outcome,
                             "jejak": [{"origin": t["origin"], "agreement": round(t["agreement"], 4), "sane": t["sane"]}
                                       for t in tries if t["origin"].endswith(":jejak")]}
    row["sebelum"], row["sesudah"] = before, after
    if job["split"] == "uji":
        if reg is not None:
            row["lacak_sesudah"] = trace_with(img, ctx, reg, job)
        if before is not None and after is not None and before.get("method") == after.get("method"):
            row["lacak_sebelum"] = row["lacak_sesudah"]
        elif before is not None:  # a different registration before: decoded from that try's pose
            row["lacak_sebelum"] = trace_with(img, ctx, registration_from(img, sizes, before_try) if before_try
                                              else reg, job)
    return row


def registration_from(img: np.ndarray, sizes, t: dict):
    """The Registration the rescue stage makes from one of its tries (no viewer chrome on photos)."""
    from tapak.decoder.rectify import Registration, effective_dpi, warp_to_page

    page, h, dpi = t["page"], np.asarray(t["h"]), t["dpi"]
    size = (int(round(sizes[page][0] * dpi / 72.0)), int(round(sizes[page][1] * dpi / 72.0)))
    rect, valid = warp_to_page(img, h, size)
    return Registration(page=page, dpi=dpi, h_page_to_img=h, correlation=t["cc"], method=f"penyelamat:{t['origin']}",
                        rectified=rect, valid=valid, effective_dpi=effective_dpi(h, size[0], size[1], dpi))


def trace_with(img: np.ndarray, ctx, reg, job: dict) -> dict:
    """Verdict of a crop decoded with a given registration (no registration again)."""
    import tapak.decoder.image as image_mod

    R = _reg()
    real = image_mod.register
    image_mod.register = lambda *a, **k: reg
    try:
        obs = image_mod.collect_from_gray(img, ctx)
    finally:
        image_mod.register = real
    expected = None if job["against"] != job["src"]["iss"] else job["src"]["seq"]
    return R.verdict(obs, ctx, expected)


def _init() -> None:
    kal._init()


def run(split: str) -> None:
    import multiprocessing as mp

    out = HASIL / f"{split}.jsonl"
    HASIL.mkdir(parents=True, exist_ok=True)
    if split == "uji" and not (HASIL / "uji_kode.json").exists():
        files = sorted((ROOT / "tapak" / "decoder").glob("*.py"))
        (HASIL / "uji_kode.json").write_text(json.dumps(
            {"protokol": PROTOCOL, "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}},
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    done = set()
    if out.exists():
        done = {json.loads(x)["key"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()}
    jobs = [(i, j) for i, j in enumerate(jobs_for(split)) if job_key(j) not in done]
    print(f"{len(done)} selesai, {len(jobs)} tersisa", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for k, row in enumerate(pool.map(run_job, jobs, chunksize=1)):
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            if (k + 1) % 25 == 0 or k + 1 == len(jobs):
                print(f"[{k + 1}/{len(jobs)} {time.time() - t0:.0f}s]", flush=True)


def summary(split: str) -> dict:
    rows = [json.loads(x) for x in (HASIL / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    out: dict = {"split": split, "potongan": len(rows)}
    for when in ("sebelum", "sesudah"):
        own = [r for r in rows if not r["silang"]]
        c = Counter()
        for r in own:
            reg = r[when]
            key = (r["crop"], r["scale"])
            c[key + ("n",)] += 1
            if reg is not None:
                c[key + ("ditemukan",)] += 1
                c[key + (reg["class"],)] += 1
        table = {}
        for crop in CROPS:
            for scale in SCALES:
                k = (crop, scale)
                table[f"{crop}|{scale}"] = {f: c[k + (f,)] for f in ("n", "ditemukan", "benar", "kasar", "salah")}
        out[when] = {"tabel": table,
                     "pose_salah": sum(1 for r in rows if r[when] is not None and r[when]["class"] == "salah"),
                     "silang_diterima": sum(1 for r in rows if r["silang"] and r[when] is not None)}
        if split == "uji":
            lacak = [r.get(f"lacak_{when}") for r in rows]
            out[when]["disebut"] = sum(1 for r, v in zip(rows, lacak) if v and v["verdict"] == "benar" and not r["silang"])
            out[when]["tuduhan_salah"] = sum(1 for v in lacak if v and v["verdict"] == "salah")
    jejak = [r for r in rows if r["jejak_dicoba"]]
    out["jejak_dicoba"] = len(jejak)
    out["detik"] = {"median": float(np.median([r["detik"] for r in rows])),
                    "p95": float(np.percentile([r["detik"] for r in rows], 95))}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("perintah", choices=("jalan", "ringkas"))
    ap.add_argument("--split", choices=("dev", "uji"), required=True)
    args = ap.parse_args(argv)
    if args.perintah == "jalan":
        run(args.split)
    else:
        res = summary(args.split)
        (HASIL / f"ringkas_{args.split}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
        print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
