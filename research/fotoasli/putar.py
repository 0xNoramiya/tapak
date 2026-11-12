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

Issued copies and photos go to ``out/riset_fotoasli/`` (not committed); rows to ``hasil/``.
Process pools are capped at 3, BLAS and OpenCV at one thread per worker (shared machine).
Usage, from the repository root:

    PYTHONPATH=. python research/fotoasli/putar.py jalan
    PYTHONPATH=. python research/fotoasli/putar.py ringkas
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
SECRET = hashlib.sha256(b"TAPAK-riset-fotoasli-putar-v1").digest()


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
    scheme, profile = PROTOCOL["variants"][variant]
    n = PROTOCOL["n"]
    rng = np.random.default_rng([PROTOCOL["copy_id_seed"], DOCS.index(doc)])
    people = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i:03d}", "Jabatan Uji", "Satuan Uji") for i in range(1, n + 1)]
    settings = IssueSettings(c=PROTOCOL["c"], eps=PROTOCOL["eps"], n_max=n, workers=WORKERS, canary_domain=None,
                             shift=ShiftSettings.for_scheme(scheme), background=background_profile(profile))
    issue(ROOT / "samples" / f"{doc}.pdf", people, folder / "salinan", SECRET, settings,
          issuer="riset-fotoasli", copy_ids=[rng.bytes(8).hex() for _ in range(n)])


_CTX: dict = {}
_FIELDS: dict = {}


def context(variant: str, doc: str):
    if (variant, doc) not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

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
    rng = np.random.default_rng([PROTOCOL["evidence_seed"], DOCS.index(doc), page, seq, fields.index(job["field"])])
    _, manifest, folder = context(job["variant"], doc)
    pdf = (folder / manifest.copies[seq - 1].file).read_bytes()
    prm = PrintParams()
    text, tint = print_layers(pdf, page - 1, prm.device_dpi)
    sheet, _ = print_page(text, tint, rng, prm)
    del text, tint
    if job["field"] != FLAT:
        sheet = bend_sheet(sheet, job["field"])
    res = PROTOCOL["res"]
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


def jobs() -> list[dict]:
    return [{"variant": v, "doc": doc, "page": page, "seq": seq, "field": f}
            for doc, page in PROTOCOL["pages"] for seq in PROTOCOL["seqs"]
            for f in [FLAT] + PROTOCOL["fields"] for v in PROTOCOL["variants"]]


def run() -> None:
    HASIL.mkdir(parents=True, exist_ok=True)
    for variant in PROTOCOL["variants"]:
        for doc in {d for d, _ in PROTOCOL["pages"]}:
            ensure_issued(variant, doc)
    path = HASIL / "putar.jsonl"
    key = lambda r: json.dumps([r[k] for k in ("variant", "doc", "page", "seq", "field")])  # noqa: E731
    done = {key(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    todo = [j for j in jobs() if key(j) not in done]
    (HASIL / "protokol_putar.json").write_text(json.dumps(PROTOCOL, indent=1) + "\n", encoding="utf-8")
    print(f"{len(todo)} pekerjaan ({len(done)} sudah ada)", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool, path.open("a", encoding="utf-8") as out:
        for n, fut in enumerate(as_completed([pool.submit(run_job, j) for j in todo]), 1):
            row = fut.result()
            out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")
            out.flush()
            note = row["error"].splitlines()[-1] if "error" in row else f"{row['verdict']} {row['channels']}"
            print(f"[{n}/{len(todo)}] {row['variant']} {row['doc']} s{row['seq']} {row['field']}: {note}", flush=True)


def summarize() -> None:
    rows = [json.loads(line) for line in (HASIL / "putar.jsonl").read_text(encoding="utf-8").splitlines()]
    bad = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    out: dict = {"jobs": len(rows), "errors": len(bad), "cells": {}}
    for variant in PROTOCOL["variants"]:
        for kind, pick in (("datar", lambda r: r["field"] == FLAT), ("lembar sungguhan", lambda r: r["field"] != FLAT)):
            cell = [r for r in rows if r["variant"] == variant and pick(r)]
            if not cell:
                continue
            ch = {k: [sum(r["channels"][k]["read"] for r in cell), sum(r["channels"][k]["errors"] for r in cell)]
                  for k in ("kata", "baris", "latar")}
            out["cells"][f"{variant} | {kind}"] = {
                "n": len(cell), "benar": sum(r["verdict"] == "benar" for r in cell),
                "salah": sum(r["verdict"] == "salah" for r in cell), "registered": sum(r["registered"] for r in cell),
                "wrong_bit_share": {k: (round(e / n, 3) if n else None) for k, (n, e) in ch.items()},
                "bits_read_per_photo": {k: round(n / len(cell)) for k, (n, _) in ch.items()},
                "by_field": {f: [sum(r["verdict"] == "benar" for r in cell if r["field"] == f),
                                 sum(r["field"] == f for r in cell)] for f in sorted({r["field"] for r in cell})}}
    (HASIL / "ringkas_putar.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, c in out["cells"].items():
        print(f"{name:30s} benar {c['benar']}/{c['n']} salah {c['salah']} terdaftar {c['registered']} "
              f"bit salah {c['wrong_bit_share']} per foto {c['bits_read_per_photo']} {c['by_field']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cmd", choices=("jalan", "ringkas"))
    args = parser.parse_args()
    run() if args.cmd == "jalan" else summarize()


if __name__ == "__main__":
    main()
