"""Word-group models of the shift decoder for image evidence, chosen on development evidence.

Development evidence: every image evidence of research/kalibrasi, both its development and its
held-out split (both were measured and reported there; neither is held out here). Each keeps
its registration, so this script measures the word groups again on the same rectified page
(``ch_shift.measure_image``, with the match quality of every group), decodes channel 1 with
every candidate of ``ch_shift.WORD_MODELS`` through the production code
(``decode_displacements(..., word_model=...)``), puts that output in place of the stored shift
output and accuses exactly as research/kalibrasi does (``ukur.analyse``). PDF evidence is decoded
as before by every candidate (the word models apply to image evidence only).

Why these candidates (prototype on the same evidence, ``README.md``): on photos and prints the
standardized word-group residual had a kurtosis of 7 to 9 and 1.5 to 1.8 times the variance the
decoder assumed, mostly in groups whose template matched poorly; below about 44 dpi the measured
shift was 0.55 to 0.7 of the mark. A fitted per-evidence gain made calibration worse (not
identifiable with hidden signs) and was dropped.

The rule ``ATURAN`` was written after the prototype had scored the word-group calibration of
rounds 1 to 3 on this evidence, and before any verdict, warning or fused calibration of a
candidate was computed. The held-out evidence of ``ukur.py`` is new and is traced once.

Usage (work folder: ``$TAPAK_GESER_KERJA``, default out/riset_geser; research/kalibrasi's work
folder ``$TAPAK_KALIBRASI_KERJA`` must hold its issuances, evidence and observations):

    python research/geser/kandidat.py nilai              # every candidate on every development evidence
    python research/geser/kandidat.py pilih              # the rule: hasil/pilihan.json
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "research" / "kalibrasi"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import ukur as kal  # noqa: E402  research/kalibrasi/ukur.py: evidence, contexts, analyse

WORK = Path(os.environ.get("TAPAK_GESER_KERJA") or ROOT / "out" / "riset_geser")
HASIL = ROOT / "research" / "geser" / "hasil"
WORKERS = 3
CANDIDATES = ("gauss", "t3_redam", "t3_redam_puncak", "t3_redam_puncak05", "t4_redam_puncak", "t2_redam_puncak")
BASE = "gauss"
ATURAN = {
    "1_tanpa_tuduhan_salah": "tidak ada tuduhan salah di pelacakan dev mana pun (salinan, koalisi jujur, induk tanpa tanda)",
    "2_tanpa_putusan_hilang": ("setiap salinan dev yang disebut dekoder sekarang (gauss) tetap disebut, dan setiap "
                               "koalisi dev tidak kehilangan anggota yang disebut (tahap mana pun)"),
    "3_tanpa_peringatan_baru": ("tidak ada pelacakan jujur dev tanpa peringatan dengan gauss yang mendapat peringatan "
                                "(pola penghapusan, bacaan jelas tanpa nama, atau pola tanda terbalik) dengan kandidat"),
    "4_kalibrasi": ("sel terlalu yakin: kelas medium (kalibrasi/kandidat.py medium_class) x kelompok bobot W_EDGES "
                    "dengan P(Poisson(E) >= k) < 1e-4, dihitung untuk kelompok kata (kata) dan bacaan gabungan "
                    "(gabungan) salinan dev"),
    "5_pilihan": ("di antara kandidat yang lolos 1 sampai 3 dan punya lebih sedikit sel kata terlalu yakin daripada "
                  "gauss: sel terlalu yakin kata + gabungan paling sedikit; seri: galat kalibrasi kata terkecil, lalu "
                  "lebih banyak putusan benar; tidak ada: dekoder tetap gauss"),
    "level_poisson": 1e-4,
}


def _kandidat_module():
    """research/kalibrasi/kandidat.py (calibration table and Poisson rule), loaded once."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("kal_kandidat", ROOT / "research" / "kalibrasi" / "kandidat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dev_jobs() -> list[dict]:
    """Every evidence of research/kalibrasi (both splits) with stored observations."""
    return [j for split in ("dev", "uji") for j in kal.jobs_for(split) if kal.obs_path(j).exists()]


def measured(job: dict, stored: dict):
    """(displacements, match quality, pixel grid, registration meta) of an image evidence from its
    stored registration, cached in the work folder."""
    from tapak.decoder.ch_shift import PixelGrid, measure_image, template_boxes
    from tapak.decoder.rectify import load_gray, render_page_exact, warp_to_page

    reg = stored["reg"]
    grid = PixelGrid(np.asarray(reg["h_page_to_img"]), reg["dpi"], reg["effective_dpi"])
    meta = {"page": reg["page"], "dpi": reg["dpi"], "correlation": round(reg["correlation"], 4),
            "method": reg["method"], "effective_dpi": round(reg["effective_dpi"], 1)}
    cache = WORK / "ukuran" / job["split"] / f"{kal.job_key(job)}.pkl"
    if cache.exists():
        with cache.open("rb") as fh:
            disp, quality = pickle.load(fh)
        return disp, quality, grid, meta
    ctx, _ = kal.context(job["iss"])
    _, data, _ = kal.evidence(job)
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    page, dpi = reg["page"], reg["dpi"]
    size = (int(round(sizes[page][0] * dpi / 72.0)), int(round(sizes[page][1] * dpi / 72.0)))
    rect, valid = warp_to_page(load_gray(data), grid.h_page_to_img, size)
    template = render_page_exact(ctx.master.pdf_bytes, page, dpi, boxes=template_boxes(ctx.master, page, dpi))
    quality: dict = {}
    disp = measure_image(rect, valid, template, ctx.master, page, dpi, quality=quality)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("wb") as fh:
        pickle.dump((disp, quality), fh)
    return disp, quality, grid, meta


def redecoded(job: dict, stored: dict, names: tuple[str, ...]) -> dict[str, list]:
    """Observations of an evidence with channel 1 decoded again by every word model in ``names``."""
    from tapak.decoder.ch_shift import decode_displacements

    obs = stored["obs"]
    index = [i for i, sb in enumerate(obs) if sb.channel == "shift"]
    if stored["reg"] is None or not index:
        return {name: obs for name in names}
    ctx, _ = kal.context(job["iss"])
    disp, quality, grid, meta = measured(job, stored)
    out = {}
    for name in names:
        sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded, grid=grid, quality=quality,
                                  word_model=name)
        sb.meta.update(meta)
        new = list(obs)
        new[index[0]] = sb
        out[name] = new
    return out


def same_soft_bits(a, b) -> bool:
    return bool(np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr))


def nilai_job(job: dict) -> list[dict]:
    """Every candidate on one development evidence (and whether gauss reproduces the stored output)."""
    ctx, _ = kal.context(job["iss"])
    with kal.obs_path(job).open("rb") as fh:
        stored = pickle.load(fh)
    members = job["members"] if job["part"] == "koalisi" else [job["seq"]] if job["part"] == "salinan" else []
    x = ctx.codewords[job["seq"] - 1].astype(np.uint8) if job["part"] == "salinan" else None
    t0 = time.perf_counter()
    variants = redecoded(job, stored, CANDIDATES)
    old = next((sb for sb in stored["obs"] if sb.channel == "shift"), None)
    new = next((sb for sb in variants[BASE] if sb.channel == "shift"), None)
    rows = []
    for name in CANDIDATES:
        row = {"key": kal.job_key(job), "kandidat": name,
               **{k: job.get(k) for k in ("split", "iss", "part", "medium", "renderer", "dpi", "framing", "seq",
                                          "page", "rep", "members", "index")}}
        row.update(kal.analyse(variants[name], ctx, members, x))
        rows.append(row)
    rows[0]["gauss_sama"] = old is None or (new is not None and same_soft_bits(old, new))
    rows[0]["detik"] = round(time.perf_counter() - t0, 1)
    return rows


def _init() -> None:
    kal._init()


def run_nilai() -> None:
    import multiprocessing as mp

    out = HASIL / "dev_kandidat.jsonl.gz"
    done = set()
    if out.exists():
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            done = {json.loads(line)["key"] for line in fh if line.strip()}
    todo = [j for j in dev_jobs() if kal.job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    HASIL.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            gzip.open(out, "at", encoding="utf-8") as fh:
        for i, rows in enumerate(pool.map(nilai_job, todo, chunksize=1)):
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            if (i + 1) % 25 == 0 or i + 1 == len(todo):
                print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s]", flush=True)


def _warned(r: dict) -> bool:
    return bool(r["hapus"]["ditandai"] or (r["kontradiksi"] or {}).get("ditandai") or r["balik"]["ditandai"])


def choose(rows: list[dict]) -> dict:
    """Apply ATURAN to the re-decoded development rows of every candidate."""
    kk = _kandidat_module()
    by_cand: dict[str, dict[str, dict]] = {n: {} for n in CANDIDATES}
    for r in rows:
        by_cand[r["kandidat"]][r["key"]] = r
    base = by_cand[BASE]
    report = {}
    for name in CANDIDATES:
        rs = list(by_cand[name].values())
        if len(rs) != len(base):
            raise SystemExit(f"{name}: {len(rs)} baris, {len(base)} diharapkan")
        wrong = [r["key"] for r in rs if r["salah"]]
        lost = [r["key"] for r in rs if r["part"] in ("salinan", "koalisi")
                and len(r["anggota"]) < len(base[r["key"]]["anggota"])]
        gained = [r["key"] for r in rs if r["part"] in ("salinan", "koalisi")
                  and len(r["anggota"]) > len(base[r["key"]]["anggota"])]
        new_warn = [r["key"] for r in rs if r["part"] in ("salinan", "koalisi", "induk") and _warned(r)
                    and not _warned(base[r["key"]])]
        cells = {}
        for kind in ("kata", "gabungan"):
            _, err, fails = kk.calibration_verdict(kk.calibration_table(rs, kind))
            cells[kind] = {"gagal": len(fails), "galat": round(err, 6), "sel": fails[:60]}
        right = sum(1 for r in rs if r["part"] == "salinan" and r["anggota"])
        report[name] = {"tuduhan_salah": wrong, "putusan_hilang": lost, "putusan_bertambah": gained,
                        "peringatan_baru": new_warn, "kalibrasi": cells, "benar": right,
                        "lolos_1_3": not wrong and not lost and not new_warn}
    base_cells = report[BASE]["kalibrasi"]["kata"]["gagal"]
    eligible = [n for n in CANDIDATES if n != BASE and report[n]["lolos_1_3"]
                and report[n]["kalibrasi"]["kata"]["gagal"] < base_cells]
    chosen = BASE
    if eligible:
        chosen = min(eligible, key=lambda n: (report[n]["kalibrasi"]["kata"]["gagal"]
                                              + report[n]["kalibrasi"]["gabungan"]["gagal"],
                                              report[n]["kalibrasi"]["kata"]["galat"], -report[n]["benar"]))
    return {"aturan": ATURAN, "kandidat": report, "dipilih": chosen}


def run_pilih() -> None:
    with gzip.open(HASIL / "dev_kandidat.jsonl.gz", "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    bad = [r["key"] for r in rows if r["kandidat"] == BASE and not r.get("gauss_sama", True)]
    print(f"gauss mengulang keluaran tersimpan: {len(rows) // len(CANDIDATES) - len(bad)} bukti, berbeda {len(bad)}")
    res = choose(rows)
    (HASIL / "pilihan.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, r in res["kandidat"].items():
        k, g = r["kalibrasi"]["kata"], r["kalibrasi"]["gabungan"]
        print(f"{name}: lolos 1-3 {r['lolos_1_3']} (salah {len(r['tuduhan_salah'])}, hilang {len(r['putusan_hilang'])}, "
              f"bertambah {len(r['putusan_bertambah'])}, peringatan baru {len(r['peringatan_baru'])}); sel kata "
              f"{k['gagal']} gabungan {g['gagal']}; galat kata {k['galat']}; benar {r['benar']}")
    print("dipilih:", res["dipilih"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("perintah", choices=("nilai", "pilih"))
    args = ap.parse_args(argv)
    run_nilai() if args.perintah == "nilai" else run_pilih()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
