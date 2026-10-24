"""Calibration of the word-group weights on image evidence (research): the held-out run.

``kandidat.py`` chose a word model of ``ch_shift.WORD_MODELS`` on the evidence of research/kalibrasi
(both of its splits). This script issues four fresh documents, makes fresh evidence of them and
traces it once through the production path with the chosen model; then it decodes the same
registrations again with the decoder before this study (``gauss``) and accuses the same way, so
before and after are paired (``banding``).

Protocol (fixed here and committed before the held-out issuances are made):

* Issuances (``tapak issue --benih-riset``, N = 20, c = 3, eps = 1e-6, geser v2, fictional
  samples only): G1 nota_dinas 13401 and G2 surat_telegram 13402 with the default background
  profile, G3 nota_dinas 13403 and G4 surat_telegram 13404 with the print profile. Evidence seeds
  13411 (copies), 13412 (coalitions), 13413 (their forgery), 13419 (unmarked master). No study in
  the repository uses these seeds.
* Media and evidence: research/kalibrasi's functions unchanged (``ukur.make_evidence``), with
  the grid ``GRIDS["geser"]``: per default-profile issuance the forwarded PDF of 5 copies;
  screenshots of copies 4 and 15 by the three real renderers at 28, 40, 56, 84 and 120 dpi as
  PNG, messenger and drawn-small captures (framing alternating); the screenshot simulator and
  the three phone-photo media for all 20 copies; honest coalitions of 2 and 3 (3 each, strategy
  ``acak``) through PDF, messenger at 40 and 84 dpi and phone photo; the unmarked master twice
  through every medium. Per print-profile issuance: page 1 and page 2 of all 20 copies printed
  and photographed, 3 forwarded PDFs and the master printed twice.
* Recorded per evidence as research/kalibrasi (``ukur.analyse``): verdict, scores, bound, the
  three checks, the detection bound and the reliability counts per kind (``kata`` and
  ``gabungan`` included), with the chosen model and with ``gauss`` on the same registration.

Usage (work folder ``$TAPAK_GESER_KERJA``, default out/riset_geser; at most 3 processes):

    python research/geser/ukur.py terbit
    python research/geser/ukur.py lacak                 # once, with the chosen model
    python research/geser/ringkas.py --json
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "research" / "kalibrasi"):  # research/geser is the script folder
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import ukur as kal  # noqa: E402  research/kalibrasi/ukur.py

WORK = Path(os.environ.get("TAPAK_GESER_KERJA") or ROOT / "out" / "riset_geser")
HASIL = ROOT / "research" / "geser" / "hasil"
SPLIT = "geser"
ISSUANCES = {
    "G1": ("nota_dinas", 20, 13401, "layar"),
    "G2": ("surat_telegram", 20, 13402, "layar"),
    "G3": ("nota_dinas", 20, 13403, "cetak"),
    "G4": ("surat_telegram", 20, 13404, "cetak"),
}
SEEDS = {"bukti": 13411, "koalisi": 13412, "serangan": 13413, "induk": 13419}
RESOLUTIONS = (28, 40, 56, 84, 120)
GRID = {
    "layar": {
        "pdf": list(range(1, 6)),
        "layar_copies": [4, 15],
        "foto_copies": list(range(1, 21)),
        "koalisi": {"k": [2, 3], "per_k": 3, "rule": "acak",
                    "media": [("pdf", None, None), ("pesan", "mupdf", 40), ("pesan", "mupdf", 84), ("foto", None, None)]},
        "induk": {"reps": 2, "media": [("pdf", None, None), ("png", "mupdf", 56), ("pesan", "mupdf", 40),
                                       ("pesan", "mupdf", 84), ("layar_sim", None, None), ("foto", None, None),
                                       ("ponsel", None, None), ("monitor", None, None)]},
    },
    "cetak": {"cetak_copies": list(range(1, 21)), "pages": [1, 2], "pdf": list(range(1, 4)),
              "induk": {"reps": 2, "media": [("cetak", None, None)]}},
}
PROTOCOL = {"issuances": ISSUANCES, "seeds": SEEDS, "resolutions": RESOLUTIONS, "grid": GRID,
            "media": kal.MEDIA, "w_edges": kal.W_EDGES,
            "trace": "pelacakan tercatat ke-1, kebijakan tahap bertahap-v1, jalur produksi, model kata pilihan",
            "banding": "registrasi yang sama didekode ulang dengan gauss (dekoder sebelum studi ini)"}


def configure() -> None:
    """Point research/kalibrasi's functions at this study's issuances, seeds, grid and folders."""
    kal.WORK = WORK
    kal.ISSUANCES = {**kal.ISSUANCES, **ISSUANCES}
    kal.SETS = {**kal.SETS, SPLIT: tuple(ISSUANCES)}
    kal.SEEDS = {**kal.SEEDS, SPLIT: SEEDS}
    kal.GRIDS = {**kal.GRIDS, SPLIT: GRID}
    kal.RESOLUTIONS = RESOLUTIONS


configure()


def chosen_model() -> str:
    """The model of ``hasil/pilihan.json``; the run stops unless it is the shipped default."""
    from tapak.decoder import ch_shift

    path = HASIL / "pilihan.json"
    if not path.exists():
        raise SystemExit("hasil/pilihan.json belum ada: jalankan kandidat.py pilih lebih dulu")
    chosen = json.loads(path.read_text(encoding="utf-8"))["dipilih"]
    if chosen != ch_shift.IMAGE_WORD_MODEL:
        raise SystemExit(f"model kata pohon kerja ({ch_shift.IMAGE_WORD_MODEL}) bukan pilihan dev ({chosen})")
    return chosen


def issue() -> None:
    kal.issue_all(SPLIT)
    rows = kal._load(kal.HASIL / f"terbit_{SPLIT}.jsonl")
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / "terbit.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                                        encoding="utf-8")
    (kal.HASIL / f"terbit_{SPLIT}.jsonl").unlink(missing_ok=True)  # kept here, not in research/kalibrasi
    (HASIL / "protokol.json").write_text(json.dumps(
        dict(PROTOCOL, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _kandidat():
    """research/geser/kandidat.py under its own module name (research/kalibrasi has a kandidat.py too)."""
    import importlib.util

    if "geser_kandidat" not in sys.modules:
        spec = importlib.util.spec_from_file_location("geser_kandidat", ROOT / "research" / "geser" / "kandidat.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["geser_kandidat"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["geser_kandidat"]


def trace_job(job: dict) -> dict:
    """One evidence: traced with the chosen model, then its registration decoded with gauss."""
    kandidat = _kandidat()
    row = kal.trace_job(job)
    if row.get("registrasi"):
        ctx, _ = kal.context(job["iss"])
        with kal.obs_path(job).open("rb") as fh:
            stored = pickle.load(fh)
        members = job["members"] if job["part"] == "koalisi" else [job["seq"]] if job["part"] == "salinan" else []
        x = ctx.codewords[job["seq"] - 1].astype(np.uint8) if job["part"] == "salinan" else None
        before = kandidat.redecoded(job, stored, ("gauss",))["gauss"]
        row["sebelum"] = kal.analyse(before, ctx, members, x)
    return row


def run() -> None:
    import multiprocessing as mp

    model = chosen_model()
    out = HASIL / "uji.jsonl"
    jobs = kal.jobs_for(SPLIT)
    mark = HASIL / "uji_dekoder.json"
    if not mark.exists():
        files = sorted((ROOT / "tapak" / "decoder").glob("*.py")) + sorted((ROOT / "tapak" / "tardos").glob("*.py"))
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        mark.write_text(json.dumps({"git_head": head, "model_kata": model,
                                    "sha256": {f"{f.parent.name}/{f.name}": hashlib.sha256(f.read_bytes()).hexdigest()
                                               for f in files}}, indent=2) + "\n", encoding="utf-8")
    done = {r["key"] for r in kal._load(out)}
    todo = [j for j in jobs if kal.job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa (model {model})", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=kal.WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(pool.map(trace_job, todo, chunksize=1)):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {r['key']}: dituduh {r['dituduh']} "
                  f"(sebelum {(r.get('sebelum') or {}).get('dituduh')}) peringatan {r['peringatan']}", flush=True)


def _init() -> None:
    configure()
    kal._init()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("perintah", choices=("terbit", "lacak", "tugas"))
    args = ap.parse_args(argv)
    if args.perintah == "terbit":
        issue()
    elif args.perintah == "lacak":
        run()
    else:
        from collections import Counter

        jobs = kal.jobs_for(SPLIT)
        print(len(jobs), dict(Counter((j["part"], j["medium"]) for j in jobs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
