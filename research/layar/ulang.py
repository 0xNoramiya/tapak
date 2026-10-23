"""Review check of the screenshot study: the floors again, on research seeds never used before.

Added in review, after the held-out run; it changes nothing in the study and makes no decoder
choice. The protocol functions of ``ukur.py`` are used unchanged (real renderers, captures,
tracing through ``collect_from_gray``) with a third split ``rev`` whose seeds are new:
nota_dinas 7901, surat_telegram 7902, evidence seed 7911, unmarked seed 7999. Scheme geser-v2
only, copies 4 and 13 of each document (utuh and bingkai alternate), the four renderers, every
resolution and format of the ``utama`` and ``tanpa_aa`` grids (4 images per cell, the held-out set
has 12), and the unmarked masters at 32, 56, 96 and 150 dpi. The shift channel of every trace is
then decoded again from the kept displacements with the Gaussian rows (the decoder before the
study) for a paired before/after count, as ``kandidat.py nilai`` does for the held-out set.

    python research/layar/ulang.py terbit     # issuances under $TAPAK_LAYAR_KERJA/rev
    python research/layar/ulang.py lacak      # writes hasil/ulang.jsonl.gz
    python research/layar/ulang.py banding    # writes hasil/ulang_kandidat.jsonl.gz
    python research/layar/ulang.py ringkas    # writes hasil/ringkas_ulang.json
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_v] = "1"

import gzip  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ukur  # noqa: E402

SPLIT = "rev"
ROWS = ukur.HASIL / "ulang.jsonl.gz"
PAIRED = ukur.HASIL / "ulang_kandidat.jsonl.gz"
RES = list(ukur.RESOLUTIONS)


def patch() -> None:
    """Add the review split to the protocol (in every process; it is not part of PROTOCOL)."""
    p = ukur.PROTOCOL
    p["benih_riset"][SPLIT] = {"nota_dinas": 7901, "surat_telegram": 7902}
    p["evidence_seed"][SPLIT] = 7911
    p["unmarked_seed"][SPLIT] = 7999
    p["grids"][SPLIT] = {
        "utama": {"renderers": list(ukur.MAIN_RENDERERS), "resolutions": RES, "formats": list(ukur.FORMATS),
                  "copies": {"v2": [4, 13]}, "framings": ["utuh", "bingkai"]},
        "tanpa_aa": {"renderers": ["poppler_tanpa_aa"], "resolutions": RES, "formats": ["png", "pesan"],
                     "copies": {"v2": [4, 13]}, "framings": ["utuh", "bingkai"]},
        "induk": {"renderers": list(ukur.MAIN_RENDERERS), "resolutions": [32, 56, 96, 150], "formats": ["png", "pesan"],
                  "reps": 1, "framings": ["utuh"]},
    }
    ukur.SCHEMES = ("v2",)  # unmarked masters are traced against the v2 issuance only


def _init() -> None:
    patch()
    ukur._init()


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    with gzip.GzipFile(path, "wb", mtime=0) as fh:
        fh.write(text.encode("utf-8"))


def run_lacak() -> None:
    import multiprocessing as mp

    jobs = ukur.jobs_for(SPLIT)
    done = {ukur.job_key(r): r for r in _read(ROWS)}
    todo = [j for j in jobs if ukur.job_key(j) not in done]
    print(f"{len(jobs)} pekerjaan, {len(todo)} tersisa", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        for i, r in enumerate(pool.map(ukur.trace_job, todo, chunksize=1)):
            done[ukur.job_key(r)] = r
            if i % 20 == 0:
                print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {ukur.job_key(r)}", flush=True)
    _write(ROWS, [done[ukur.job_key(j)] for j in jobs])


def run_banding() -> None:
    import multiprocessing as mp

    import kandidat

    rows = _read(ROWS)
    with ProcessPoolExecutor(max_workers=ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        out = list(pool.map(kandidat.evaluate, [(r, ["sekarang", "kisi_baris3"], "kisi_baris3") for r in rows],
                            chunksize=4))
    _write(PAIRED, out)


def run_ringkas() -> dict:
    """Floors and the numbers the review quotes (hasil/ringkas_ulang.json)."""
    import tempfile

    from ringkas import paired, summarize

    with tempfile.TemporaryDirectory() as tmp:
        plain = Path(tmp) / "ulang.jsonl"
        plain.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _read(ROWS)), encoding="utf-8")
        out = summarize("dev", plain)  # the split name only labels the tables (no partial viewports here)
    rows = _read(ROWS)
    whole = [(r, t) for r in rows if r["seq"] is not None for t in r["traces"]]
    named = [t["accuse"]["semua"] for _, t in whole if t["accuse"]["semua"]["verdict"] == "benar"]
    out["review"] = {
        "seeds": ukur.PROTOCOL["benih_riset"][SPLIT], "evidence_seed": ukur.PROTOCOL["evidence_seed"][SPLIT],
        "misses_registered": sum(t["registered"] and t["accuse"]["semua"]["verdict"] != "benar" for _, t in whole),
        "misses_unregistered": sum(not t["registered"] for _, t in whole),
        "min_score_z_named": min(a["score_z"] for a in named),
        "max_log10_fa_named": max(a["log10_fa"] for a in named),
        "paired": paired(SPLIT, path=PAIRED),
    }
    (ukur.HASIL / "ringkas_ulang.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main() -> int:
    patch()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "terbit":
        for doc in ukur.DOCS:
            print(json.dumps(ukur.issue(SPLIT, doc, "v2"), ensure_ascii=False), flush=True)
    elif cmd == "lacak":
        run_lacak()
    elif cmd == "banding":
        run_banding()
    elif cmd == "ringkas":
        run_ringkas()
    else:
        raise SystemExit("pakai: ulang.py terbit | lacak | banding | ringkas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
