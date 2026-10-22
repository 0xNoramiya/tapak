"""Review checks of the OCR path on fresh seeds: a reproduction and adversarial images (research/ocr).

A simulation study like ``ukur.py``. The protocol and every seed are fixed here before any run:

* issuance: ``samples/nota_dinas.pdf`` and ``samples/surat_telegram.pdf``, ``tapak issue --benih-riset``
  7801 and 7802 (fresh: ``ukur.py`` used 7301, 7302, 7401, 7402), N = 20, no registry, every
  sentence variant of the mock phrase table and every tier-A word-choice point approved (as arm
  ``utama`` of ``ukur.py``); evidence seed 7811 (``ukur.py``: 7311, 7411, 7499);
* ``ulang`` (reproduction): ``cetak1600`` copies 1 to 8, page 1 of both documents, and ``foto``
  copies 1 to 4, page 1 of the nota dinas, generated as in ``ukur.py``;
* ``lawan`` (adversarial, nota dinas page 1, copies 1 to 6 each): ``kecil1000`` and ``kecil800``
  (photo long side 1000 or 800 px), ``buram`` (lens blur 2.5 to 3.5 px), ``jpeg10`` (both JPEG
  compressions at quality 8 to 12), ``cetak1000`` (printed copy photographed at 1000 px),
  ``terbalik`` (photo turned 180 degrees), ``potong`` (photo cropped into the page by up to 35 %),
  ``timpa`` (the other form of every word-choice point typed over the printed one, no white-out),
  ``palsu`` (the same over a white-out: a forgery, the forged forms are expected to be read),
  ``lain`` (page 1 of the surat telegram copy traced against the nota dinas), ``halaman`` (a photo
  of page 2 registered as usual, its OCR text then read against the slots of page 1 on purpose);
* per image: printed bits of the found page, bits read, wrong (sign of the LLR against the
  photographed copy's codeword), confidently wrong (|LLR| >= 4), slots outside the image, OCR
  seconds; verdicts with and without the OCR sub-channels (all of eps, one stage).

Data minimization as in ``ukur.py``: OCR text never leaves memory; results hold counts and times.
Process pools are capped at 3 workers, BLAS, OpenCV and Tesseract at one thread. Usage, from the
repository root:

    python research/ocr/tinjau.py terbit     # issuances (out/riset_ocr/tinjau/)
    python research/ocr/tinjau.py ulang      # reproduction; writes hasil/tinjau_ulang.jsonl
    python research/ocr/tinjau.py lawan      # adversarial images; writes hasil/tinjau_lawan.jsonl
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

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

WORK = ROOT / "out" / "riset_ocr" / "tinjau"
HASIL = ROOT / "research" / "ocr" / "hasil"
WORKERS = 3
SEEDS = {"nota_dinas": 7801, "surat_telegram": 7802}
EVIDENCE_SEED = 7811
CONFIDENT_LLR = 4.0
KINDS = ("foto", "cetak1600", "kecil1000", "kecil800", "buram", "jpeg10", "cetak1000", "terbalik", "potong",
         "timpa", "palsu", "lain", "halaman")


def _tapak(*args: str) -> None:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    run = subprocess.run([sys.executable, "-m", "tapak.cli", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"tapak {' '.join(args[:2])} gagal: {run.stderr.strip()[-400:]}")


def issue(doc: str) -> None:
    """Issue one document once (all variants and word-choice points approved)."""
    folder = WORK / doc
    if list((folder / "data" / "dokumen").glob("*/manifest.json")):
        return
    folder.mkdir(parents=True, exist_ok=True)
    master = ROOT / "samples" / f"{doc}.pdf"
    sem, lex = folder / "varian.json", folder / "leksikal.json"
    _tapak("semantic", "suggest", str(master), "-o", str(sem), "--llm", "mock")
    _tapak("semantic", "approve", str(sem), "--all")
    _tapak("leksikal", "scan", str(master), "-o", str(lex))
    _tapak("leksikal", "review", str(lex), "--semua", "--setujui", "--ya")
    _tapak("--data", str(folder / "data"), "--keys", str(folder / "keys"), "issue", str(master),
           str(ROOT / "samples" / "recipients.csv"), "--no-registry", "--canary-domain", "", "--workers",
           str(WORKERS), "--benih-riset", str(SEEDS[doc]), "--semantic", str(sem), "--leksikal", str(lex))


_CTX: dict = {}


def context(doc: str):
    """(trace context, manifest, workspace folder) of an issuance, cached per process."""
    if doc not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest

        root = WORK / doc
        folder = next((root / "data" / "dokumen").glob("*/manifest.json")).parent
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        secret = load_code_secret(root / "keys" / "code_secret.key")
        _CTX[doc] = (load_context((folder / "induk.pdf").read_bytes(), manifest, secret, folder=folder), manifest,
                     folder)
    return _CTX[doc]


def overlay(pdf: bytes, ctx, page: int, whiteout: bool) -> bytes:
    """Type the other form of every word-choice point of ``page`` over the printed form."""
    import pymupdf

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pg = doc[page]
    rows = ctx.master.layout.pages[page].rows
    for pt in ctx.lexical.carrying():
        if pt.page != page:
            continue
        hit = next(((k, r) for k, form in enumerate(pt.forms) for r in pg.search_for(form.strip())
                    if abs(r.y1 - rows[pt.row].baseline) < 8), None)
        if hit is None:
            continue
        k, r = hit
        other = pt.forms[(k + 1) % len(pt.forms)].strip()
        if whiteout:
            pg.draw_rect(r, color=(1, 1, 1), fill=(1, 1, 1))
        size = max(6.0, 0.85 * (r.y1 - r.y0))
        pg.insert_text((r.x0, r.y1 - 0.22 * (r.y1 - r.y0)), other, fontsize=size,
                       fontname="tiro" if whiteout else "helv")
    return doc.tobytes()


def evidence(job: dict) -> bytes:
    """The evidence image of a job (cached on disk)."""
    path = WORK / "bukti" / f"{job['doc']}_{job['kind']}_s{job['seq']:03d}_p{job['page']}.jpg"
    if path.exists():
        return path.read_bytes()
    import cv2

    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, PrintParams, photo_jpeg, printed_photo_jpeg

    doc, kind, seq, page = job["doc"], job["kind"], job["seq"], job["page"]
    ctx, manifest, folder = context(doc)
    src_manifest, src_folder = (context("surat_telegram")[1:] if kind == "lain" else (manifest, folder))
    pdf = (src_folder / "salinan" / src_manifest.copies[seq - 1].file).read_bytes()
    rng = np.random.default_rng([EVIDENCE_SEED, KINDS.index(kind), seq, page])
    if kind in ("timpa", "palsu"):
        pdf = overlay(pdf, ctx, page - 1, whiteout=kind == "palsu")
    if kind.startswith("cetak"):
        res = int(kind[len("cetak"):])
        data, _ = printed_photo_jpeg(pdf, page - 1, rng, PrintParams(),
                                     PhotoParams(sensor_long_side=max(2400, res), long_side=res))
    else:
        params = {"kecil1000": PhotoParams(long_side=1000), "kecil800": PhotoParams(long_side=800),
                  "buram": PhotoParams(blur_sigma=(2.5, 3.5)),
                  "jpeg10": PhotoParams(jpeg_quality_1=(8, 12), jpeg_quality_2=(8, 12)),
                  "potong": PhotoParams(crop_into_page=True, crop_into_max_frac=0.35)}.get(kind, PhotoParams())
        data, _ = photo_jpeg(render_pages(pdf, 200, [page - 1])[0], rng, params)
        if kind == "terbalik":
            arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            ok, enc = cv2.imencode(".jpg", cv2.rotate(arr, cv2.ROTATE_180), [cv2.IMWRITE_JPEG_QUALITY, 90])
            data = enc.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def ocr_stats(obs, x: np.ndarray | None, ctx, page: int | None) -> dict:
    """Bits printed on the found page, read, wrong, confidently wrong; slots outside; OCR seconds."""
    from tapak.decoder.ocr import page_slots
    from tapak.marker.plan import OCR_SUBCHANNELS

    out: dict = {"printed": None, "read": 0, "wrong": 0, "confident_wrong": 0, "outside": 0, "ocr_seconds": None}
    if page is not None:
        sem, lex = page_slots(ctx, page)
        out["printed"] = sum(len(s.positions) for s in sem + lex)
    for sb in obs:
        if sb.channel not in OCR_SUBCHANNELS:
            continue
        out["read"] += len(sb)
        out["outside"] += int(sb.meta.get("slots_outside_image", 0) or 0)
        out["ocr_seconds"] = sb.meta.get("ocr_seconds", out["ocr_seconds"])
        if x is not None and len(sb):
            bad = (sb.llr > 0).astype(int) != x[sb.positions]
            out["wrong"] += int(bad.sum())
            out["confident_wrong"] += int((bad & (np.abs(sb.llr) >= CONFIDENT_LLR)).sum())
    return out


def verdict(obs, ctx, expected: int | None) -> str:
    """'benar', 'tidak cukup bukti' or 'salah' (anyone else, or anyone when nobody leaked)."""
    from tapak.decoder.trace import run_trace

    accused = sorted(c.copy.seq for c in run_trace(obs, ctx).accused)
    if not accused:
        return "tidak cukup bukti"
    return "benar" if expected is not None and accused == [expected] else "salah"


def run_job(job: dict) -> dict:
    """Decode one image (with OCR) and accuse with and without the OCR sub-channels."""
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.ocr import page_image, read_page_text, recognize
    from tapak.decoder.rectify import load_gray, register
    from tapak.marker.plan import OCR_SUBCHANNELS

    ctx, _, _ = context(job["doc"])
    row = dict(job)
    x = ctx.codewords[job["seq"] - 1]
    if job["kind"] == "halaman":
        gray = load_gray(evidence(dict(job, kind="foto", page=2)))
        reg = register(gray, ctx.master.pdf_bytes, [(p.width, p.height) for p in ctx.master.layout.pages])
        row["registered_page"] = reg.page + 1 if reg else None
        if reg is not None:
            p = ctx.master.layout.pages[reg.page]
            image, dpi = page_image(gray, reg, (p.width, p.height))
            text = recognize(image, dpi)
            obs = read_page_text(text, 0, ctx)  # the slots of page 1, on purpose
            del text, image
            row["ocr"] = ocr_stats(obs, x, ctx, None)
        return row
    data = evidence(job)
    t0 = time.perf_counter()
    obs = collect_from_image(data, ctx)
    row["seconds"] = round(time.perf_counter() - t0, 1)
    reg = next((o.meta for o in obs if "correlation" in o.meta), None)
    row["registered_page"] = reg["page"] + 1 if reg else None
    row["effective_dpi"] = round(reg["effective_dpi"], 1) if reg else None
    expected = None if job["kind"] == "lain" else job["seq"]
    row["ocr"] = ocr_stats(obs, x if expected else None, ctx, reg["page"] if reg else None)
    row["met_ocr"] = verdict(obs, ctx, expected)
    row["tanpa_ocr"] = verdict([o for o in obs if o.channel not in OCR_SUBCHANNELS], ctx, expected)
    return row


def jobs(which: str) -> list[dict]:
    if which == "ulang":
        out = [{"doc": d, "kind": "cetak1600", "seq": s, "page": 1} for d in SEEDS for s in range(1, 9)]
        return out + [{"doc": "nota_dinas", "kind": "foto", "seq": s, "page": 1} for s in range(1, 5)]
    return [{"doc": "nota_dinas", "kind": k, "seq": s, "page": 1} for k in KINDS[2:] for s in range(1, 7)]


def _init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    import cv2

    cv2.setNumThreads(1)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "terbit":
        for doc in SEEDS:
            issue(doc)
        return
    if which not in ("ulang", "lawan"):
        raise SystemExit("pakai: tinjau.py terbit | ulang | lawan")
    import multiprocessing as mp

    rows = []
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        for r in pool.map(run_job, jobs(which), chunksize=1):
            print(json.dumps(r, ensure_ascii=False), flush=True)
            rows.append(r)
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / f"tinjau_{which}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    main()
