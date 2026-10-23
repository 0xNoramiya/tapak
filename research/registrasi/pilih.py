"""Choosing the rescue stage's verification settings on development seeds (research/registrasi).

The rescue stage (``tapak/decoder/rectify.py``, ``rescue_register``) refines several initial poses
and keeps the one that agrees best with the master (``pose_agreement``). Two settings decide
whether that pose is decoded or refused: ``RESCUE_MIN_AGREEMENT`` (the verification threshold)
and ``RESCUE_AMBIGUITY`` (how close a rival pose, on another page or elsewhere on the same page,
may come before the registration counts as ambiguous). Both are chosen here, on the development
set only, by the rule ``ATURAN`` (fixed before ``kumpul`` was first run on the full set), and
written to ``hasil/pilihan.json``; ``ukur.py lacak --split uji`` refuses to start unless
``rectify.py`` carries exactly these values.

``kumpul`` registers every development image (marked copies, unmarked masters and evidence of
the other document) with the production ``register``. Where the earlier stages give no page, the
rescue stage's every try is kept with its pose error against the ground truth; the acceptance
decision is then recomputed for every candidate setting, since the tries do not depend on the
two settings.

    python research/registrasi/pilih.py kumpul     # writes hasil/pilih_dev.jsonl
    python research/registrasi/pilih.py pilih      # writes hasil/pilihan.json
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ukur  # noqa: E402

OUT = Path(os.environ.get("TAPAK_REG_PILIH") or ukur.HASIL / "pilih_dev.jsonl")
CHOICE = ukur.HASIL / "pilihan.json"
WRONG_PX = ukur.WRONG_POSE_PX  # text off by more than this (image px, 95th percentile): a wrong pose
AGREEMENT_GRID = [round(0.30 + 0.05 * i, 2) for i in range(14)]  # 0.30 .. 0.95
AMBIGUITY_GRID = [round(0.05 * i, 2) for i in range(7)]          # 0.00 .. 0.30
ATURAN = ("Pada set dev, untuk setiap gambar yang tahap registrasi sebelumnya tidak menemukan halamannya: tahap "
          "penyelamat memilih percobaan dengan kecocokan tertinggi; pose itu salah bila halaman atau dokumennya "
          "salah, tidak ada kata induk yang terlihat, atau persentil ke-95 galatnya pada titik tengah kata lebih dari "
          f"{WRONG_PX:g} piksel gambar. RESCUE_AMBIGUITY dan "
          "RESCUE_MIN_AGREEMENT dipilih dari kisi 0,00 sampai 0,30 dan 0,30 sampai 0,95 (langkah 0,05): di antara "
          "pasangan yang tidak menerima satu pun pose salah (termasuk induk tanpa tanda dan bukti dokumen lain), "
          "pasangan yang menerima pose benar paling banyak; bila sama, ambang dan margin yang lebih kecil. Lalu "
          "keduanya dinaikkan satu langkah kisi sebagai cadangan.")


def _init() -> None:
    ukur._init()
    apply_variant()


def apply_variant() -> dict:
    """Development only: override rescue settings of rectify.py from $TAPAK_REG_VARIAN (JSON), to
    compare design variants on the development set before they are fixed in code."""
    from tapak.decoder import rectify

    raw = os.environ.get("TAPAK_REG_VARIAN")
    if not raw:
        return {}
    variant = json.loads(raw)
    for name, value in variant.items():
        if not hasattr(rectify, name):
            raise SystemExit(f"pengaturan tidak dikenal: {name}")
        setattr(rectify, name, tuple(tuple(v) for v in value) if isinstance(value, list) and value
                and isinstance(value[0], list) else value)
    return variant


def collect(job: dict) -> dict:
    """Register one development image with the production register and keep every rescue try."""
    from tapak.decoder import rectify
    from tapak.decoder.rectify import load_gray

    data, truth = ukur.evidence(job)
    doc = job.get("against") or job["doc"]
    ctx, _, _ = ukur.context(job["split"], doc)
    gray = load_gray(data)
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    h_true = np.array(truth["h_true"])
    pts = ukur.visible_points(h_true, tuple(truth["page_pt"]), tuple(truth["image_px"]), tuple(truth["visible_pt"]))
    diag: dict = {}
    t0 = time.perf_counter()
    reg = rectify.register(gray, ctx.master.pdf_bytes, sizes, diag=diag)
    seconds = time.perf_counter() - t0
    same_doc = doc == job["doc"]
    page = job["page"] - 1
    src_ctx, _, _ = ukur.context(job["split"], job["doc"])
    tpts = ukur.text_points(src_ctx.master.layout.pages[page], h_true, tuple(truth["image_px"]),
                            tuple(truth["visible_pt"]))

    def err(h, dpi, pg):
        return ukur.pose_error(h, dpi, h_true, pts)["p95"] if (same_doc and pg == page) else None

    def err_text(h, dpi, pg):
        return ukur.pose_error(h, dpi, h_true, tpts)["p95"] if (same_doc and pg == page) else None

    row = {k: job.get(k) for k in ("split", "grid", "kind", "k", "doc", "page", "renderer", "dpi", "fmt", "position",
                                   "height", "chrome", "isp", "seq", "source_grid", "source_k", "against")}
    row.update(key=ukur.job_key(job), outcome=diag["outcome"], seconds=round(seconds, 2),
               effective_dpi=truth.get("effective_dpi"), rows_visible=ukur.rows_visible(ctx, page, truth["visible_pt"])
               if same_doc else None)
    if diag["outcome"] == "terdaftar" and reg is not None:
        row["cascade"] = {"method": reg.method, "page": reg.page + 1, "cc": round(reg.correlation, 4),
                          "err_p95": err(reg.h_page_to_img, reg.dpi, reg.page),
                          "err_text_p95": err_text(reg.h_page_to_img, reg.dpi, reg.page)}
    res = diag.get("rescue")
    if res is not None:
        row["rescue"] = {"mask": res.get("mask"), "outcome": res.get("outcome"),
                         "tries": [{"origin": t["origin"], "page": t["page"] + 1, "dpi": t["dpi"],
                                    "ecc_dpi": t.get("ecc_dpi"), "cc": round(float(t["cc"]), 4),
                                    "sane": t.get("sane"), "h": [round(float(v), 9) for v in np.ravel(t["h"])],
                                    "agreement": round(float(t["agreement"]), 4), "pixels": t["pixels"],
                                    "err_p95": err(t["h"], t["dpi"], t["page"]),
                                    "err_text_p95": err_text(t["h"], t["dpi"], t["page"]),
                                    "centre_pt": centre_pt(t["h"], t["dpi"], res["centre"])}
                                   for t in res.get("tries", [])]}
    return row


def centre_pt(h: np.ndarray, dpi: float, centre: list[float]) -> list[float]:
    """Page point (pt) a pose puts at the centre of the visible page part (for the rival test)."""
    import cv2

    p = cv2.perspectiveTransform(np.array([[centre]], dtype=np.float64), np.linalg.inv(np.asarray(h)))[0, 0] * 72.0 / dpi
    return [round(float(p[0]), 2), round(float(p[1]), 2)]


def decide(tries: list[dict], min_agreement: float, ambiguity: float, distinct_pt: float) -> dict | None:
    """The rescue's acceptance rule (as in rescue_register) for given settings: the accepted try or None."""
    ok = [t for t in tries if t["agreement"] > -1.0]
    if not ok:
        return None
    best = max(ok, key=lambda t: t["agreement"])
    rivals = [t["agreement"] for t in ok if t is not best and (
        t["page"] != best["page"]
        or np.hypot(t["centre_pt"][0] - best["centre_pt"][0], t["centre_pt"][1] - best["centre_pt"][1]) > distinct_pt)]
    if best["agreement"] < min_agreement:
        return None
    if rivals and max(rivals) >= best["agreement"] - ambiguity:
        return None
    return best


def is_wrong(row: dict, t: dict) -> bool:
    """A wrong pose (``ukur.pose_class``): another document or page, no master text visible, or the
    text off by more than WRONG_PX (95th percentile at the word centres)."""
    return t.get("err_text_p95") is None or t["err_text_p95"] > WRONG_PX


def is_right(row: dict, t: dict) -> bool:
    """A correct pose: 95th percentile error over the visible page at most ukur.CORRECT_POSE_PX."""
    return not is_wrong(row, t) and t["err_p95"] is not None and t["err_p95"] <= ukur.CORRECT_POSE_PX


def run_kumpul(only: str | None, controls: bool = True) -> None:
    import multiprocessing as mp

    jobs = ukur.jobs_for("dev")
    if only:
        keep = {r["key"] if "key" in r else ukur.job_key(r) for r in ukur._load(Path(only))
                if (r.get("outcome") or r["sesudah"]["diag"]["outcome"]) != "terdaftar"}
        jobs = [j for j in jobs if ukur.job_key(j) in keep or (controls and j["grid"] in ("induk", "silang"))]
    done = {r["key"]: r for r in ukur._load(OUT)}
    todo = [j for j in jobs if ukur.job_key(j) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool, \
            OUT.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(pool.map(collect, todo, chunksize=1)):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s] {r['key']}: {r['outcome']} "
                  f"{(r.get('rescue') or {}).get('outcome')}", flush=True)


def run_pilih() -> dict:
    from tapak.decoder import rectify

    rows = [r for r in ukur._load(OUT) if r.get("rescue")]
    distinct = rectify.RESCUE_DISTINCT_PT
    table = []
    for amb in AMBIGUITY_GRID:
        for thr in AGREEMENT_GRID:
            acc = [(r, decide(r["rescue"]["tries"], thr, amb, distinct)) for r in rows]
            acc = [(r, t) for r, t in acc if t is not None]
            wrong = sum(is_wrong(r, t) for r, t in acc)
            right = sum(not is_wrong(r, t) for r, t in acc)
            precise = sum(is_right(r, t) for r, t in acc)
            table.append({"ambiguity": amb, "min_agreement": thr, "accepted": len(acc), "wrong": wrong, "right": right,
                          "precise": precise})
    safe = [c for c in table if c["wrong"] == 0]
    best = max(safe, key=lambda c: (c["right"], -c["min_agreement"], -c["ambiguity"])) if safe else None
    chosen = None
    if best is not None:
        chosen = {"RESCUE_MIN_AGREEMENT": round(min(best["min_agreement"] + 0.05, 0.95), 2),
                  "RESCUE_AMBIGUITY": round(best["ambiguity"] + 0.05, 2)}
        at = [(r, decide(r["rescue"]["tries"], chosen["RESCUE_MIN_AGREEMENT"], chosen["RESCUE_AMBIGUITY"], distinct))
              for r in rows]
        chosen["dev_at_choice"] = {"accepted": sum(t is not None for _, t in at),
                                   "wrong": sum(t is not None and is_wrong(r, t) for r, t in at),
                                   "right": sum(t is not None and not is_wrong(r, t) for r, t in at),
                                   "precise": sum(t is not None and is_right(r, t) for r, t in at)}
    out = {"rule": ATURAN, "rows_with_rescue": len(rows), "best_safe": best, "chosen": chosen, "table": table,
           "rectify_now": {"RESCUE_MIN_AGREEMENT": rectify.RESCUE_MIN_AGREEMENT,
                           "RESCUE_AMBIGUITY": rectify.RESCUE_AMBIGUITY}}
    CHOICE.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("rows_with_rescue", "best_safe", "chosen", "rectify_now")}, indent=1))
    return out


def compare(paths: list[Path]) -> list[dict]:
    """Design variants on the same development images (one kumpul file each, written with
    $TAPAK_REG_VARIAN): per variant, the class of the best try (benar, kasar, salah, none) on the
    images the rescue ran on, split into marked copies of the right document and the rest
    (unmarked masters, the other document), and the median seconds per registration."""
    out = []
    for path in paths:
        rows = [r for r in ukur._load(path) if r.get("rescue")]
        tally: dict = {}
        for r in rows:
            group = "salinan" if r["grid"] not in ("induk", "silang") else r["grid"]
            ok = [t for t in r["rescue"]["tries"] if t["agreement"] > -1.0]
            if not ok:
                cls = "tanpa_pose"
            else:
                best = max(ok, key=lambda t: t["agreement"])
                cls = "salah" if is_wrong(r, best) else ("benar" if is_right(r, best) else "kasar")
            tally.setdefault(group, {}).setdefault(cls, 0)
            tally[group][cls] += 1
        secs = [r["seconds"] for r in rows]
        out.append({"file": path.name, "rows_with_rescue": len(rows), "best_try": tally,
                    "median_seconds": round(float(np.median(secs)), 1) if secs else None})
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kumpul")
    k.add_argument("--hanya-gagal", default=None, help="JSONL lama: hanya gambar yang tahap sebelumnya gagal (penjelajahan)")
    k.add_argument("--tanpa-kontrol", action="store_true", help="dengan --hanya-gagal: tanpa induk dan dokumen lain")
    sub.add_parser("pilih")
    b = sub.add_parser("banding")
    b.add_argument("berkas", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "kumpul":
        run_kumpul(args.hanya_gagal, controls=not args.tanpa_kontrol)
    elif args.cmd == "banding":
        compare([Path(p) for p in args.berkas])
    else:
        run_pilih()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
