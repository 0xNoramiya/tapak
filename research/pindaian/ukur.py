"""Measurements behind the scanned-master numbers in docs/keamanan.md (batasan 8).

The protocol and every seed are fixed here, before any run (``PROTOCOL``). Both masters are
fictional: the text sample ``samples/nota_dinas.pdf`` and its synthetic 300 dpi scan
(``tapak.samplegen.scanned_sample``, gray JPEG pages with skew, paper tone and noise, the
"CONTOH SINTETIS - BUKAN DOKUMEN ASLI" footer in every page image). Copy ids come from a
seeded generator, so every copy, photo and screenshot is reproduced exactly.

Per master, N = 20 copies (c = 3, eps = 1e-6) are issued, then traced the way ``make bench``
does (a trace that is not logged, all of eps):

* ``pdf``: every copy PDF itself;
* ``tangkapan_layar``: one screenshot of page 1 per copy (``tapak.photos``, 96 to 150 dpi);
* ``foto``: one synthetic phone photo of page 1 per copy, view angle 0, 10, 20 or 30 degrees;
* ``tanpa_latar``: the simulator has no printer model, so, as for batasan 3, a print is
  stood in for by a copy rendered without its background pattern: photos of pages 1 and 2 of
  copies 1 to 6, traced one page alone and both pages together;
* ``kolusi_c3``: five coalitions of three copies: a page 1 image made of the top third of
  copy A, the middle third of B and the bottom third of C (150 dpi, JPEG twice), as the c = 2
  composite in tests/test_image_decoder.py;
* ``resolusi`` (scan only): the same scan at 150, 200 and 300 dpi, 6 copies each (the
  200 dpi minimum lifted for this measurement only), copy PDFs and photos of page 1;
* ``visibilitas``: displacement of every moved word group of the scanned copies, measured
  from the copy images, and crops of master, copy and amplified difference at 100 %.

Verdicts: ``benar`` (exactly the leaked copy), ``tidak cukup bukti`` (nobody), ``salah``
(anyone else). Per channel: positions read and bit error rate against the leaked copy's
codeword (sign of the LLR). Process pools are capped at 3 (shared machine).

Issued copies go to ``out/riset_pindaian/`` (large, not committed); the JSON lines quoted in
the docs go to ``research/pindaian/hasil/`` and the crops to ``research/pindaian/potongan/``.
Usage (from the repository root; the scan is generated here):

    python research/pindaian/ukur.py semua --out research/pindaian/hasil
    python research/pindaian/ukur.py resolusi --out research/pindaian/hasil
    python research/pindaian/ukur.py visibilitas --out research/pindaian/hasil
    python research/pindaian/ukur.py ringkas      # the tables quoted in the docs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORKERS = 3
PROTOCOL = {
    "n": 20, "c": 3, "eps": 1e-6,
    "secret": "sha256('TAPAK-riset-pindaian-v1')",
    "copy_id_seed": 20261022,
    "scan": {"dpi": 300, "seed": 2026},
    "screenshot_seed": 31, "photo_seed": 32, "print_seed": 33, "coalition_seed": 34,
    "photo_angles": [0, 10, 20, 30], "print_copies": [1, 2, 3, 4, 5, 6], "print_angle": 15,
    "coalitions": 5, "composite_dpi": 150, "composite_jpeg": [75, 65],
    "resolution_dpis": [150, 200, 300], "resolution_copies": 6, "resolution_angle": 15, "resolution_seed": 35,
    "render_dpi": 200,
    "spending": "tidak dicatat (seluruh eps), seperti make bench",
}
SECRET = hashlib.sha256(b"TAPAK-riset-pindaian-v1").digest()


def _recipients(n: int):
    from tapak.marker.issue import read_recipients

    return read_recipients(ROOT / "samples" / "recipients.csv")[:n]


def _masters(work: Path, dpis: tuple[int, ...] = ()) -> dict[str, Path]:
    from tapak.samplegen import scanned_sample

    work.mkdir(parents=True, exist_ok=True)
    text = ROOT / "samples" / "nota_dinas.pdf"
    out = {"teks": text}
    scan = work / "nota_dinas_pindaian.pdf"
    scan.write_bytes(scanned_sample(text.read_bytes(), dpi=PROTOCOL["scan"]["dpi"], seed=PROTOCOL["scan"]["seed"]))
    out["pindaian"] = scan
    for dpi in dpis:
        p = work / f"nota_dinas_pindaian_{dpi}.pdf"
        p.write_bytes(scanned_sample(text.read_bytes(), dpi=dpi, seed=PROTOCOL["scan"]["seed"]))
        out[f"pindaian_{dpi}"] = p
    return out


def _issue(master: Path, out: Path, n: int, seed: int):
    """Issue n copies with seeded copy ids (secrets.token_hex patched for this call only)."""
    import tapak.marker.issue as issue_mod
    from tapak.marker.issue import IssueSettings, issue

    rng = np.random.default_rng(seed)
    real = issue_mod.secrets.token_hex
    issue_mod.secrets.token_hex = lambda k: rng.bytes(k).hex()  # type: ignore[assignment]
    try:
        t0 = time.perf_counter()
        manifest = issue(master, _recipients(n), out, SECRET,
                         IssueSettings(c=PROTOCOL["c"], eps=PROTOCOL["eps"], workers=WORKERS, n_max=n), issuer="riset")
        return manifest, time.perf_counter() - t0
    finally:
        issue_mod.secrets.token_hex = real


# --- worker side ---------------------------------------------------------------------------

_CTX: dict[str, object] = {}


def _init(jobs_root: str) -> None:
    import os

    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    _CTX["root"] = jobs_root


def _context(key: str):
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

        folder = Path(_CTX["root"]) / key  # type: ignore[arg-type]
        manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        master = (folder / "induk.pdf").read_bytes()
        _CTX[key] = (load_context(master, manifest, SECRET), manifest, folder)
    return _CTX[key]


def _channel_stats(obs, x: np.ndarray | None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for sb in obs:
        if not len(sb):
            continue
        d = out.setdefault(sb.channel, {"read": 0, "errors": 0})
        d["read"] += int(len(sb))
        if x is not None:
            d["errors"] += int(np.sum((sb.llr > 0) != (x[sb.positions] == 1)))
    return out


def _verdict(accused: list[int], expected: list[int]) -> str:
    if not accused:
        return "tidak cukup bukti"
    if set(accused) <= set(expected):
        return "benar" if len(expected) == 1 else "koalisi"
    return "salah"


def _copy_render(folder: Path, manifest, seq: int, page: int, dpi: int, shift_only: bool = False) -> np.ndarray:
    from tapak.marker.render import render_pages

    copy = manifest.copies[seq - 1]
    if not shift_only:
        return render_pages((folder / "salinan" / copy.file).read_bytes(), dpi, [page])[0]
    from tapak.marker.issue import IssueSettings, build_document_plan, document_grids, marks_for_codeword
    from tapak.marker.master import load_master
    from tapak.marker.raster import prepare_scans
    from tapak.marker.render import render_copy
    from tapak.tardos.code import derive_bias, derive_codeword

    master = load_master((folder / "induk.pdf").read_bytes())
    prepare_scans(master)
    params = manifest.tardos_params
    settings = IssueSettings(c=params.c, eps=params.eps, n_max=params.n_max)
    plan = build_document_plan(master, params, SECRET, tuple(manifest.channels), set(), settings.background)
    x = derive_codeword(SECRET, master.doc_hash, copy.copy_id, derive_bias(SECRET, master.doc_hash, params))
    marks, _ = marks_for_codeword(master, plan, x, settings, document_grids(master, SECRET, settings.background))
    marks.page_hooks, marks.scan_patterns = [], {}  # no background pattern: what a printer leaves
    return render_pages(render_copy(master, marks), dpi, [page])[0]


def _job(job: dict) -> dict:
    """Make one piece of evidence, trace it, return the verdict and channel statistics."""
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import collect_file, run_trace
    from tapak.photos import PhotoParams, ScreenshotParams, encode_jpeg, decode_jpeg, photo_jpeg, screenshot_jpeg

    ctx, manifest, folder = _context(job["master"])
    kind, seqs = job["kind"], job["seqs"]
    t0 = time.perf_counter()
    rdpi = PROTOCOL["render_dpi"]
    obs, notes = [], []
    if kind == "pdf":
        c = manifest.copies[seqs[0] - 1]
        obs, notes = collect_file(c.file, (folder / "salinan" / c.file).read_bytes(), ctx)
    elif kind == "tangkapan_layar":
        page = _copy_render(folder, manifest, seqs[0], 0, rdpi)
        data, _ = screenshot_jpeg(page, np.random.default_rng([PROTOCOL["screenshot_seed"], seqs[0]]),
                                  ScreenshotParams(render_dpi=float(rdpi)))
        obs = collect_from_image(data, ctx)
    elif kind in ("foto", "foto_resolusi"):
        page = _copy_render(folder, manifest, seqs[0], 0, rdpi)
        angle = float(job["angle"])
        seed = PROTOCOL["photo_seed"] if kind == "foto" else PROTOCOL["resolution_seed"]
        data, _ = photo_jpeg(page, np.random.default_rng([seed, seqs[0]]), PhotoParams(angle_deg=angle))
        obs = collect_from_image(data, ctx)
    elif kind == "tanpa_latar":
        for page_no in job["pages"]:
            page = _copy_render(folder, manifest, seqs[0], page_no, rdpi, shift_only=True)
            data, _ = photo_jpeg(page, np.random.default_rng([PROTOCOL["print_seed"], seqs[0], page_no]),
                                 PhotoParams(angle_deg=float(PROTOCOL["print_angle"])))
            obs += collect_from_image(data, ctx)
    elif kind == "kolusi_c3":
        dpi = PROTOCOL["composite_dpi"]
        parts = [_copy_render(folder, manifest, s, 0, dpi) for s in seqs]
        h = parts[0].shape[0]
        cuts = [0, h // 3, 2 * h // 3, h]
        composite = np.vstack([parts[i][cuts[i]:cuts[i + 1]] for i in range(3)])
        canvas = np.full((composite.shape[0] + 60, composite.shape[1] + 60), 80, np.uint8)
        canvas[30:-30, 30:-30] = composite
        q1, q2 = PROTOCOL["composite_jpeg"]
        data = encode_jpeg(decode_jpeg(encode_jpeg(canvas, q1)), q2)
        obs = collect_from_image(data, ctx)
    result = run_trace(obs, ctx, notes)
    accused = [c.copy.seq for c in result.accused]
    x = ctx.codewords[seqs[0] - 1] if len(seqs) == 1 else None
    best = result.accused[0].log10_false_accusation if result.accused else None
    return {"master": job["master"], "kind": kind, "seqs": seqs, "angle": job.get("angle"),
            "pages": job.get("pages"), "accused": accused, "verdict": _verdict(accused, seqs),
            "log10_fa_best": best, "positions_observed": int(result.threshold.n_observed),
            "channels": _channel_stats(obs, x), "seconds": round(time.perf_counter() - t0, 1),
            "warnings": list(ctx.warnings)}


def _run_jobs(jobs: list[dict], root: Path) -> list[dict]:
    import multiprocessing as mp

    ctx = mp.get_context("forkserver")
    out = []
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=ctx, initializer=_init, initargs=(str(root),)) as pool:
        for r in pool.map(_job, jobs):
            print(json.dumps({k: r[k] for k in ("master", "kind", "seqs", "verdict", "accused", "seconds")}),
                  flush=True)
            out.append(r)
    return out


def _workspace(root: Path, key: str, master: Path, n: int, seed: int) -> dict:
    folder = root / key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "induk.pdf").write_bytes(master.read_bytes())
    manifest, seconds = _issue(folder / "induk.pdf", folder / "salinan", n, seed)
    sizes = [(folder / "salinan" / c.file).stat().st_size for c in manifest.copies]
    return {"master": key, "issue_seconds": round(seconds, 1), "copies": n,
            "master_bytes": master.stat().st_size, "copy_bytes_mean": int(np.mean(sizes)),
            "copy_bytes_max": int(max(sizes)), "plan_summary": manifest.plan_summary,
            "scan": manifest.scan, "gate": manifest.gate}


WORK = ROOT / "out" / "riset_pindaian"  # issued copies (large, not committed)


def run_all(out: Path) -> None:
    work = WORK
    masters = _masters(work)
    n = PROTOCOL["n"]
    issued = [_workspace(work, key, path, n, PROTOCOL["copy_id_seed"]) for key, path in masters.items()]
    rng = np.random.default_rng(PROTOCOL["coalition_seed"])
    coalitions = [sorted(int(v) for v in rng.choice(np.arange(1, n + 1), 3, replace=False))
                  for _ in range(PROTOCOL["coalitions"])]
    jobs = []
    for key in masters:
        jobs += [{"master": key, "kind": "pdf", "seqs": [s]} for s in range(1, n + 1)]
        jobs += [{"master": key, "kind": "tangkapan_layar", "seqs": [s]} for s in range(1, n + 1)]
        jobs += [{"master": key, "kind": "foto", "seqs": [s], "angle": PROTOCOL["photo_angles"][s % 4]}
                 for s in range(1, n + 1)]
        for s in PROTOCOL["print_copies"]:
            jobs += [{"master": key, "kind": "tanpa_latar", "seqs": [s], "pages": [0]},
                     {"master": key, "kind": "tanpa_latar", "seqs": [s], "pages": [0, 1]}]
        jobs += [{"master": key, "kind": "kolusi_c3", "seqs": c} for c in coalitions]
    rows = _run_jobs(jobs, work)
    _write(out / "terbit.jsonl", issued)
    _write(out / "lacak.jsonl", rows)


def run_resolution(out: Path) -> None:
    import tapak.marker.raster as raster

    work = WORK / "resolusi"
    dpis = tuple(PROTOCOL["resolution_dpis"])
    masters = {k: v for k, v in _masters(work, dpis).items() if k.startswith("pindaian_")}
    raster.MIN_SCAN_DPI = 100.0  # this measurement only: find out what happens below 200 dpi
    n = PROTOCOL["resolution_copies"]
    issued = [_workspace(work, key, path, n, PROTOCOL["copy_id_seed"]) for key, path in masters.items()]
    jobs = []
    for key in masters:
        jobs += [{"master": key, "kind": "pdf", "seqs": [s]} for s in range(1, n + 1)]
        jobs += [{"master": key, "kind": "foto_resolusi", "seqs": [s], "angle": PROTOCOL["resolution_angle"]}
                 for s in range(1, n + 1)]
    rows = _run_jobs(jobs, work)
    _write(out / "resolusi_terbit.jsonl", issued)
    _write(out / "resolusi_lacak.jsonl", rows)


def run_visibility(out: Path) -> None:
    """Moved-group displacement of scanned copies (from the copy images) and crops."""
    import cv2
    import pymupdf

    from tapak.marker.issue import IssueManifest
    from tapak.marker.master import load_master
    from tapak.marker.pdf_shift import MM_TO_PT
    from tapak.marker.raster import decode_scan_image, detect_scans, prepare_scans, scan_image

    folder = WORK / "pindaian"
    manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
    master = load_master((folder / "induk.pdf").read_bytes())
    prepare_scans(master)
    rows_out = []
    per_copy: dict[int, dict] = {}
    for c in manifest.copies[:6]:
        with pymupdf.open(folder / "salinan" / c.file) as doc:
            for k, scan in master.scans.items():
                img = scan_image(master, k).astype(np.float64)
                cimg = decode_scan_image(doc, detect_scans(doc)[k]).astype(np.float64)
                kx, ky = scan.scale
                ink_m, ink_c = np.clip(220.0 - img, 0, None), np.clip(220.0 - cimg, 0, None)
                for row in master.shift_layout.pages[k].rows:
                    for g in row.groups:
                        x0, y0 = int(g.bbox[0] * kx) - 4, int(g.bbox[1] * ky) - 4
                        x1, y1 = int(np.ceil(g.bbox[2] * kx)) + 4, int(np.ceil(g.bbox[3] * ky)) + 4
                        a, b = ink_m[y0:y1, x0:x1], ink_c[y0:y1, x0:x1]
                        if a.sum() <= 0 or b.sum() <= 0:
                            continue
                        ys, xs = np.indices(a.shape)
                        dx = ((b * xs).sum() / b.sum() - (a * xs).sum() / a.sum()) / kx / MM_TO_PT
                        dy = ((b * ys).sum() / b.sum() - (a * ys).sum() / a.sum()) / ky / MM_TO_PT
                        per_copy.setdefault(c.seq, {})[g.id] = (dx, dy)
    seqs = sorted(per_copy)
    pair_max = 0.0
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            a, b = per_copy[seqs[i]], per_copy[seqs[j]]
            for gid in a.keys() & b.keys():
                pair_max = max(pair_max, abs(a[gid][0] - b[gid][0]), abs(a[gid][1] - b[gid][1]))
    allv = np.array([v for d in per_copy.values() for v in d.values()])
    # Planned offsets of the same groups, to separate the centroid measurement error from the marks.
    from tapak.marker.issue import IssueSettings, build_document_plan, marks_for_codeword
    from tapak.tardos.code import derive_bias, derive_codeword

    params = manifest.tardos_params
    plan = build_document_plan(master, params, SECRET, ("shift",), set())
    p = derive_bias(SECRET, master.doc_hash, params)
    errs = []
    for c in manifest.copies[:6]:
        marks, _ = marks_for_codeword(master, plan, derive_codeword(SECRET, master.doc_hash, c.copy_id, p),
                                      IssueSettings(channels=("shift",)))
        for gid, (dx, dy) in per_copy[c.seq].items():
            want_dx = marks.group_dx.get(gid, 0.0) / MM_TO_PT
            want_dy = marks.row_dy.get((gid[0], gid[1]), 0.0) / MM_TO_PT
            errs.append((dx - want_dx, dy - want_dy))
    e = np.abs(np.array(errs))
    rows_out.append({"copies": len(seqs), "groups": int(len(allv)), "abs_dx_mm_max": float(np.abs(allv[:, 0]).max()),
                     "abs_dy_mm_max": float(np.abs(allv[:, 1]).max()), "pairwise_mm_max": pair_max,
                     "planned_mm": manifest.shift_mm,
                     "measurement_error_mm": {"rms": float(np.sqrt(np.mean(e ** 2))),
                                              "p99": float(np.percentile(e, 99)), "max": float(e.max())},
                     "groups_error_over_0.01mm": int(np.sum(e.max(axis=1) > 0.01))})
    # Crops at 100 %: master, copy, difference x20 around three moved groups of copy 1.
    crops = out.parent / "potongan"
    crops.mkdir(parents=True, exist_ok=True)
    c = manifest.copies[0]
    with pymupdf.open(folder / "salinan" / c.file) as doc:
        img = scan_image(master, 0)
        cimg = decode_scan_image(doc, detect_scans(doc)[0])
    kx, ky = master.scans[0].scale
    moved = [g for g, v in per_copy[c.seq].items() if g[0] == 0 and abs(v[0]) > 0.02]
    for n_crop, gid in enumerate(moved[:3]):
        g = master.shift_layout.pages[0].rows[gid[1]].groups[gid[2]]
        x0, y0 = int(g.bbox[0] * kx) - 40, int(g.bbox[1] * ky) - 30
        x1, y1 = int(g.bbox[2] * kx) + 40, int(g.bbox[3] * ky) + 30
        a, b = img[y0:y1, x0:x1], cimg[y0:y1, x0:x1]
        d = np.clip(128 + 20 * (b.astype(int) - a.astype(int)), 0, 255).astype(np.uint8)
        cv2.imwrite(str(crops / f"kata{n_crop + 1}_induk.png"), a)
        cv2.imwrite(str(crops / f"kata{n_crop + 1}_salinan.png"), b)
        cv2.imwrite(str(crops / f"kata{n_crop + 1}_selisih_x20.png"), d)
        up = lambda z: cv2.resize(z, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)  # noqa: E731
        cv2.imwrite(str(crops / f"kata{n_crop + 1}_perbesar4x.png"), np.vstack([up(a[25:65, 30:130]), up(b[25:65, 30:130])]))
    _write(out / "visibilitas.jsonl", rows_out)


def summarize(out: Path) -> None:
    """Print the tables quoted in the docs from the JSON lines in ``out``."""
    for name in ("terbit.jsonl", "resolusi_terbit.jsonl"):
        path = out / name
        if path.exists():
            for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
                print(f"{r['master']:<14} terbit {r['copies']} salinan {r['issue_seconds']} s; induk "
                      f"{r['master_bytes'] / 1e6:.2f} MB, salinan rata-rata {r['copy_bytes_mean'] / 1e6:.2f} MB, "
                      f"terbesar {r['copy_bytes_max'] / 1e6:.2f} MB; rencana "
                      + ", ".join(f"{k} {v['positions']}" for k, v in r["plan_summary"].items()))
    for name in ("lacak.jsonl", "resolusi_lacak.jsonl"):
        path = out / name
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            sub = r["kind"] if r["kind"] != "tanpa_latar" else f"tanpa_latar {len(r['pages'])} hal"
            groups.setdefault((r["master"], sub), []).append(r)
        for (master, kind), rs in groups.items():
            count: dict[str, int] = {}
            for r in rs:
                count[r["verdict"]] = count.get(r["verdict"], 0) + 1
            ch: dict[str, list[float]] = {}
            for r in rs:
                for c, d in r["channels"].items():
                    ch.setdefault(c, [0, 0, 0])
                    ch[c][0] += d["read"]
                    ch[c][1] += d["errors"]
                    ch[c][2] += 1
            single = all(len(r["seqs"]) == 1 for r in rs)  # no single codeword to compare a composite with
            chan = "; ".join(f"{c}: {v[0] / len(rs):.0f} posisi/bukti, galat "
                             + (f"{100 * v[1] / max(v[0], 1):.2f} %" if single else "-")
                             for c, v in sorted(ch.items()))
            extra = ""
            if kind == "kolusi_c3":
                caught = [len(set(r["accused"]) & set(r["seqs"])) for r in rs]
                innocent = sum(len(set(r["accused"]) - set(r["seqs"])) for r in rs)
                extra = f" anggota tertangkap {caught}, tak bersalah dituduh {innocent}"
            secs = np.mean([r["seconds"] for r in rs])
            print(f"{master:<14} {kind:<20} n={len(rs):>2} " + ", ".join(f"{k} {v}" for k, v in sorted(count.items()))
                  + f" | {chan} | {secs:.0f} s/bukti{extra}")


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pengukuran induk hasil pindai")
    ap.add_argument("bagian", choices=["semua", "resolusi", "visibilitas", "ringkas"])
    ap.add_argument("--out", default=str(ROOT / "research" / "pindaian" / "hasil"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.bagian == "ringkas":
        summarize(out)
        return 0
    (out / "protokol.json").write_text(json.dumps(PROTOCOL, indent=2), encoding="utf-8")
    {"semua": run_all, "resolusi": run_resolution, "visibilitas": run_visibility}[args.bagian](out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
