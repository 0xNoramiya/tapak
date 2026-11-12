"""Real paper shapes replayed on simulated copies whose recipient is known (docs/keamanan.md
batasan 10).

The real photos (``ukur.py``) show the unmarked master, so they cannot say whether a mark is
read from a real sheet. They do give the shape each sheet had under the camera: the fine field
of every registered photo (``hasil/medan.json``; no mark is in it, the sheets carried none).
Here that shape is put on simulated printed copies: the page is printed by the simulated laser
printer (``tapak.photos``), its content is displaced by the field, and the sheet is photographed
by the simulated phone. What is real is the geometry (curl, cockle, creases, the lens of the
phone that took the photo); printer, camera noise and light stay simulated.

Nothing is chosen here: it measures the decoder as it is on three issuances of the same copies
(``PROTOCOL["variants"]``), the three the team was given to print. The protocol was fixed
before the run. Photos of the same sheet in the same state are near duplicates
(``hasil/geser.json``), so each state gives one field.

A second round (``PROTOCOL2``, fixed after the first round's result and before its own run)
asks two things the first left open: whether the print profile still names the copy on smaller
photos (1600 px as a messaging app sends them, 2400 px), and how large a geser-v2 word shift
would have to be on real paper. Shifts above the issuance limit (0.025 mm) exist in this study
only: the limits of ``pdf_shift`` are lifted inside this script, nothing is issued that way.

Issued copies and photos go to ``out/riset_fotoasli/`` (not committed); rows to ``hasil/``.
Process pools are capped at 3, BLAS and OpenCV at one thread per worker (shared machine).
Usage, from the repository root:

    PYTHONPATH=. python research/fotoasli/putar.py jalan [--putaran 2]
    PYTHONPATH=. python research/fotoasli/putar.py ringkas [--putaran 2]
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORK = ROOT / "out" / "riset_fotoasli"
HASIL = Path(__file__).resolve().parent / "hasil"
WORKERS = 3
DOCS = ("nota_dinas", "surat_telegram")
FLAT = "datar"

PROTOCOL: dict = {
    "c": 3, "eps": 1e-6, "n": 20,
    "spending": "not logged (all of eps), one stage, as in make bench",
    "secret": "sha256('TAPAK-riset-fotoasli-putar-v1')", "copy_id_seed": 61201, "evidence_seed": 61211,
    "variants": {"v2": ["geser-v2", "layar"], "v2_cetak": ["geser-v2", "cetak"], "v1": ["geser-v1", "layar"]},
    "pages": [["surat_telegram", 1], ["nota_dinas", 1]],
    "fields": ["miring/175559", "miring/180124", "basah/G_3332", "kusut/G_3339"],
    "seqs": [3, 11],
    "res": 4000,  # long side (px): about 250 dpi on the page, as the iPhone photos gave
    "printer": "laser (tapak.photos.PrintParams())",
}
PROTOCOL2: dict = {
    **{k: PROTOCOL[k] for k in ("c", "eps", "n", "spending", "secret", "copy_id_seed", "pages", "fields", "seqs", "printer")},
    "evidence_seed": 61212,
    "variants": {"v2_cetak": ["geser-v2", "cetak"], "v2_050": ["geser-v2", "layar", 0.05],
                 "v2_100": ["geser-v2", "layar", 0.10], "v2_150": ["geser-v2", "layar", 0.15]},
    "grid": {"v2_cetak": [1600, 2400], "v2_050": [4000], "v2_100": [4000], "v2_150": [4000]},  # long sides (px)
    "word_shift": "third entry of a variant: geser-v2 word shift in mm (rows keep 0.05 mm); study only",
}
ROUNDS = {1: PROTOCOL, 2: PROTOCOL2}
SECRET = hashlib.sha256(b"TAPAK-riset-fotoasli-putar-v1").digest()


def _lift_limits() -> None:
    """Allow the larger word shifts of round 2 (in this process only)."""
    from tapak.marker import pdf_shift

    pdf_shift.MAX_SHIFT_MM = max(pdf_shift.MAX_SHIFT_MM, 0.2)
    pdf_shift.V2_MAX_WORD_SHIFT_MM = max(pdf_shift.V2_MAX_WORD_SHIFT_MM, 0.2)


def variant_spec(variant: str) -> list:
    return {**PROTOCOL["variants"], **PROTOCOL2["variants"]}[variant]


def issuance_dir(variant: str, doc: str) -> Path:
    return WORK / variant / doc


def ensure_issued(variant: str, doc: str) -> None:
    """Issue 20 copies of ``doc`` under ``variant`` (the same copy ids for every variant). Once."""
    from tapak.marker.background import background_profile
    from tapak.marker.issue import IssueSettings, Recipient, issue
    from tapak.marker.pdf_shift import ShiftSettings

    folder = issuance_dir(variant, doc)
    if (folder / "salinan" / "manifest.json").exists():
        return
    scheme, profile, *word_mm = variant_spec(variant)
    _lift_limits()
    shift = ShiftSettings(word_mm=word_mm[0], row_mm=0.05, scheme=scheme) if word_mm else ShiftSettings.for_scheme(scheme)
    n = PROTOCOL["n"]
    rng = np.random.default_rng([PROTOCOL["copy_id_seed"], DOCS.index(doc)])
    people = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i:03d}", "Jabatan Uji", "Satuan Uji") for i in range(1, n + 1)]
    settings = IssueSettings(c=PROTOCOL["c"], eps=PROTOCOL["eps"], n_max=n, workers=WORKERS, canary_domain=None,
                             shift=shift, background=background_profile(profile))
    issue(ROOT / "samples" / f"{doc}.pdf", people, folder / "salinan", SECRET, settings,
          issuer="riset-fotoasli", copy_ids=[rng.bytes(8).hex() for _ in range(n)])


_CTX: dict = {}
_FIELDS: dict = {}


def context(variant: str, doc: str):
    if (variant, doc) not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

        _lift_limits()
        folder = issuance_dir(variant, doc) / "salinan"
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        ctx = load_context((ROOT / "samples" / f"{doc}.pdf").read_bytes(), manifest, SECRET)
        _CTX[(variant, doc)] = (ctx, manifest, folder)
    return _CTX[(variant, doc)]


def bend_sheet(sheet: np.ndarray, name: str) -> np.ndarray:
    """The printed sheet with its content displaced by the field ``name``: content of page
    point p shows at p + d(p) (to first order: the sheet at q shows page q - d(q))."""
    import cv2

    from tapak.decoder.rectify import Bend

    if not _FIELDS:
        _FIELDS.update(json.loads((HASIL / "medan.json").read_text(encoding="utf-8")))
    f = _FIELDS[name]
    d = Bend(np.array(f["field"], dtype=np.float32), tuple(f["page_size"])).pixels((sheet.shape[1], sheet.shape[0]))
    ys, xs = np.mgrid[0:sheet.shape[0], 0:sheet.shape[1]].astype(np.float32)
    return cv2.remap(sheet, xs - d[..., 0], ys - d[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def make_evidence(job: dict) -> tuple[bytes, dict]:
    """The photo of a job. Its random numbers depend on the document, page, copy and field only,
    so the three variants of a copy are printed and photographed alike."""
    from tapak.photos import PhotoParams, PrintParams, photo_jpeg, print_layers, print_page

    doc, page, seq = job["doc"], job["page"], job["seq"]
    fields = [FLAT] + PROTOCOL["fields"]
    res = job.get("res", PROTOCOL["res"])
    seed = [PROTOCOL["evidence_seed"], DOCS.index(doc), page, seq, fields.index(job["field"])]
    if "res" in job:  # round 2: its own photos, one per resolution
        seed = [PROTOCOL2["evidence_seed"], *seed[1:], res]
    rng = np.random.default_rng(seed)
    _, manifest, folder = context(job["variant"], doc)
    pdf = (folder / manifest.copies[seq - 1].file).read_bytes()
    prm = PrintParams()
    text, tint = print_layers(pdf, page - 1, prm.device_dpi)
    sheet, _ = print_page(text, tint, rng, prm)
    del text, tint
    if job["field"] != FLAT:
        sheet = bend_sheet(sheet, job["field"])
    data, meta = photo_jpeg(sheet, rng, PhotoParams(sensor_long_side=max(2400, res), long_side=res))
    return data, {"view_angle": round(meta["view_angle_deg"], 1)}


def _stats(obs, ctx, x: np.ndarray) -> dict:
    """Positions read and wrong bits: word groups and rows of the shift channel, background."""
    from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

    kinds = {s.positions[0]: ("kata" if len(s.ref) == 2 else "baris") for s in ctx.plan.channel(CHANNEL_SHIFT)}
    out = {k: {"read": 0, "errors": 0} for k in ("kata", "baris", "latar")}
    for sb in obs:
        if sb.channel not in (CHANNEL_SHIFT, CHANNEL_BACKGROUND):
            continue
        for q, v in zip(sb.positions, sb.llr):
            d = out["latar" if sb.channel == CHANNEL_BACKGROUND else kinds[int(q)]]
            d["read"] += 1
            d["errors"] += int((v > 0) != (x[int(q)] == 1))
    return out


def run_job(job: dict) -> dict:
    import cv2

    cv2.setNumThreads(1)
    from tapak.decoder import rectify
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.trace import run_trace

    t0 = time.time()
    try:
        ctx, _, _ = context(job["variant"], job["doc"])
        data, meta = make_evidence(job)
        obs = collect_from_gray(rectify.load_gray(data), ctx, read_text=False)
        a = run_trace(obs, ctx)
        accused = sorted(c.copy.seq for c in a.accused)
        z = a.threshold.threshold
        scores = {c.copy.seq: c.score for c in a.candidates}
        ok = bool(np.isfinite(z) and z > 0)
        reg = next((sb.meta for sb in obs if "method" in sb.meta), {})
        return {**job, **meta,
                "verdict": "tidak cukup bukti" if not accused else ("benar" if accused == [job["seq"]] else "salah"),
                "accused": accused, "n_observed": int(a.threshold.n_observed),
                "score_z": round(scores.get(job["seq"], 0.0) / z, 3) if ok else None,
                "max_innocent_z": round(max(s for k, s in scores.items() if k != job["seq"]) / z, 3) if ok else None,
                "channels": _stats(obs, ctx, ctx.codewords[job["seq"] - 1]),
                "sigma_pt": next((sb.meta.get("sigma_pt") for sb in obs if sb.channel == "shift" and len(sb)), None),
                "registered": bool(reg), "method": reg.get("method"), "correlation": reg.get("correlation"),
                "eff_dpi": reg.get("effective_dpi"), "seconds": round(time.time() - t0, 1)}
    except Exception:  # noqa: BLE001 - a failed job is a row, not a lost run
        return {**job, "error": traceback.format_exc()}


def jobs(rnd: int) -> list[dict]:
    base = [{"doc": doc, "page": page, "seq": seq, "field": f}
            for doc, page in PROTOCOL["pages"] for seq in PROTOCOL["seqs"] for f in [FLAT] + PROTOCOL["fields"]]
    if rnd == 1:
        return [{"variant": v, **b} for b in base for v in PROTOCOL["variants"]]
    return [{"variant": v, **b, "res": res} for b in base for v, sizes in PROTOCOL2["grid"].items() for res in sizes]


def _name(rnd: int, stem: str) -> Path:
    return HASIL / (f"{stem}.json" if rnd == 1 else f"{stem}{rnd}.json")


def run(rnd: int) -> None:
    HASIL.mkdir(parents=True, exist_ok=True)
    for variant in ROUNDS[rnd]["variants"]:
        for doc in {d for d, _ in PROTOCOL["pages"]}:
            ensure_issued(variant, doc)
    path = _name(rnd, "putar").with_suffix(".jsonl")
    key = lambda r: json.dumps([r.get(k) for k in ("variant", "doc", "page", "seq", "field", "res")])  # noqa: E731
    done = {key(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    todo = [j for j in jobs(rnd) if key(j) not in done]
    _name(rnd, "protokol_putar").write_text(json.dumps(ROUNDS[rnd], indent=1) + "\n", encoding="utf-8")
    print(f"{len(todo)} pekerjaan ({len(done)} sudah ada)", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool, path.open("a", encoding="utf-8") as out:
        for n, fut in enumerate(as_completed([pool.submit(run_job, j) for j in todo]), 1):
            row = fut.result()
            out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")
            out.flush()
            note = row["error"].splitlines()[-1] if "error" in row else f"{row['verdict']} {row['channels']}"
            print(f"[{n}/{len(todo)}] {row['variant']} {row['doc']} s{row['seq']} {row['field']}: {note}", flush=True)


def summarize(rnd: int) -> None:
    rows = [json.loads(line) for line in _name(rnd, "putar").with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    bad = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    out: dict = {"jobs": len(rows), "errors": len(bad), "cells": {}}
    sizes = sorted({r.get("res", PROTOCOL["res"]) for r in rows})
    for variant, res in [(v, x) for v in ROUNDS[rnd]["variants"] for x in sizes]:
        for kind, pick in (("datar", lambda r: r["field"] == FLAT), ("lembar sungguhan", lambda r: r["field"] != FLAT)):
            cell = [r for r in rows if r["variant"] == variant and r.get("res", PROTOCOL["res"]) == res and pick(r)]
            if not cell:
                continue
            ch = {k: [sum(r["channels"][k]["read"] for r in cell), sum(r["channels"][k]["errors"] for r in cell)]
                  for k in ("kata", "baris", "latar")}
            out["cells"][f"{variant} {res} px | {kind}"] = {
                "n": len(cell), "benar": sum(r["verdict"] == "benar" for r in cell),
                "salah": sum(r["verdict"] == "salah" for r in cell), "registered": sum(r["registered"] for r in cell),
                "wrong_bit_share": {k: (round(e / n, 3) if n else None) for k, (n, e) in ch.items()},
                "bits_read_per_photo": {k: round(n / len(cell)) for k, (n, _) in ch.items()},
                "by_field": {f: [sum(r["verdict"] == "benar" for r in cell if r["field"] == f),
                                 sum(r["field"] == f for r in cell)] for f in sorted({r["field"] for r in cell})}}
    _name(rnd, "ringkas_putar").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, c in out["cells"].items():
        print(f"{name:30s} benar {c['benar']}/{c['n']} salah {c['salah']} terdaftar {c['registered']} "
              f"bit salah {c['wrong_bit_share']} per foto {c['bits_read_per_photo']} {c['by_field']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cmd", choices=("jalan", "ringkas"))
    parser.add_argument("--putaran", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    run(args.putaran) if args.cmd == "jalan" else summarize(args.putaran)


if __name__ == "__main__":
    main()
