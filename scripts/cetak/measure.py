"""Print, photograph and trace issued copies with the production decoder; tabulate the results.

    python -m scripts.cetak.measure trials --profile layar --seqs 1-20 --pages 0,1 --long 1600,4000
    python -m scripts.cetak.measure composites --profile cetak --coalitions 16 --pages 0,1 --long 1600
    python -m scripts.cetak.measure report

Trials: copy s, page p, long side L: the page is printed (tapak.photos.print_page, laser
preset unless --printer says otherwise) and photographed (all photo parameters drawn from
their defaults, sensor at least 2400 px, WhatsApp long side L), with a random generator that
depends only on (s, p, L, repetition), so every decoder and profile sees the same print and
photo. The photo is decoded by tapak.decoder.image.collect_from_gray (the production path);
``--template supersampled`` swaps the exact master template of the shift decoder for the
supersampled render it replaced, for paired comparisons.

Composites (c = 3 cut-and-paste on paper): three copies are cut into bands at the white
space nearest 1/3 and 2/3 of the text block (top from member 1, middle from 2, bottom from
3), printed as one sheet and photographed. Coalitions are drawn from copies 1 to 20 with the
fixed seed 31337.

Verdict: the production rule (tapak.decoder.trace.run_trace: fused LLRs, Chernoff threshold
from the bias vector and the decoder weights only, eps1 = eps / N), over all 100 copies. A
trace "names correctly" when exactly the true copy is accused. "2 pages" fuses pages 1 and 2
of the same copy and long side. Nothing is tuned: the decoder, the thresholds and the seeds
are fixed before any result is seen.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import time
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace

import numpy as np

from scripts.cetak.common import OUT, TEST_SEQS, context, copy_pdf

PRINTERS = ("laser", "inkjet", "laser_85lpi", "laser_cut245", "laser_fit97")


def printer(name: str):
    """Print settings by name: the laser and inkjet presets and three laser variations."""
    from tapak.photos import INKJET, PrintParams

    laser = PrintParams()
    return {"laser": laser, "inkjet": INKJET, "laser_85lpi": replace(laser, screen_lpi=85.0),
            "laser_cut245": replace(laser, white_cutoff=245.0), "laser_fit97": replace(laser, fit_scale=0.97)}[name]


def _use_template(kind: str) -> None:
    import tapak.decoder.image as image
    from tapak.decoder import rectify

    if kind == "supersampled":  # the shift decoder's template before exact templates
        image.render_page_exact = lambda pdf, page, dpi: rectify.render_page(pdf, page, dpi)
    else:
        image.render_page_exact = rectify.render_page_exact


def _decode(gray: np.ndarray, profile: str) -> tuple[dict, dict]:
    from tapak.decoder.image import collect_from_gray

    ctx = context(profile)
    rec: dict = {}
    arrays: dict[str, np.ndarray] = {}
    for sb in collect_from_gray(gray, ctx):
        arrays[f"{sb.channel}_pos"] = sb.positions
        arrays[f"{sb.channel}_llr"] = sb.llr
        rec[sb.channel] = {k: v for k, v in sb.meta.items() if isinstance(v, (int, float, str, bool, type(None)))}
    return rec, arrays


def _save(path, rec: dict, arrays: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, meta=np.array(json.dumps(rec)), **arrays)


def trial_path(profile, template, prn, seq, page, long_side, rep):
    """Result file of one trial."""
    return OUT / "results" / f"{profile}__{template}__{prn}" / f"s{seq:03d}_p{page}_L{long_side}_r{rep}.npz"


def trial(job: tuple) -> dict:
    """Print, photograph and decode one page of one copy."""
    profile, template, prn, seq, page, long_side, rep = job
    path = trial_path(*job)
    if path.exists():
        return {"job": job, "skipped": True}
    from tapak.decoder.rectify import load_gray
    from tapak.photos import PhotoParams, printed_photo_jpeg

    _use_template(template)
    t0 = time.perf_counter()
    rng = np.random.default_rng([2026, seq, page, long_side, rep])
    photo = PhotoParams(sensor_long_side=max(2400, long_side), long_side=long_side)
    data, meta = printed_photo_jpeg(copy_pdf(profile, seq), page, rng, printer(prn), photo)
    t_sim = time.perf_counter() - t0
    rec, arrays = _decode(load_gray(data), profile)
    rec.update(job=list(job), t_sim=t_sim, t_total=time.perf_counter() - t0, view_angle=meta["view_angle_deg"],
               clipped=meta["params"].get("highlight_clip_frac"))
    _save(path, rec, arrays)
    return {"job": job, "t": round(rec["t_total"], 1)}


def coalitions(k: int) -> list[tuple[int, int, int]]:
    """The first k coalitions of three copies out of 1 to 20 (seed fixed before any result)."""
    rng = np.random.default_rng(31337)
    return [tuple(int(s) for s in sorted(rng.choice(np.arange(1, 21), 3, replace=False))) for _ in range(k)]


def cut_rows(ctx, page: int, dpi: int) -> list[int]:
    """Device rows of the two cuts: the white space between text rows nearest 1/3 and 2/3."""
    boxes = sorted((r.bbox[1], r.bbox[3]) for r in ctx.master.layout.pages[page].rows)
    top, bottom = boxes[0][0], boxes[-1][1]
    gaps = [0.5 * (boxes[i][1] + boxes[i + 1][0]) for i in range(len(boxes) - 1) if boxes[i][1] < boxes[i + 1][0]]
    cuts = [min(gaps, key=lambda g: abs(g - (top + f * (bottom - top)))) for f in (1 / 3, 2 / 3)]
    return [int(round(c * dpi / 72.0)) for c in cuts]


def composite_path(profile, template, prn, coal, page, long_side):
    """Result file of one composite page."""
    tag = "-".join(f"{s:03d}" for s in coal)
    return OUT / "composites" / f"{profile}__{template}__{prn}" / f"c{tag}_p{page}_L{long_side}.npz"


def composite(job: tuple) -> dict:
    """Cut three copies together, print the sheet, photograph and decode it."""
    profile, template, prn, coal, page, long_side = job
    path = composite_path(*job)
    if path.exists():
        return {"job": job, "skipped": True}
    from tapak.decoder.rectify import load_gray
    from tapak.photos import PhotoParams, photo_jpeg, print_layers, print_page

    _use_template(template)
    t0 = time.perf_counter()
    prm = printer(prn)
    layers = [print_layers(copy_pdf(profile, s), page, prm.device_dpi) for s in coal]
    c1, c2 = cut_rows(context(profile), page, prm.device_dpi)
    text = np.vstack([layers[0][0][:c1], layers[1][0][c1:c2], layers[2][0][c2:]])
    background = np.vstack([layers[0][1][:c1], layers[1][1][c1:c2], layers[2][1][c2:]])
    del layers
    rng = np.random.default_rng([4242, *coal, page, long_side])
    sheet, _ = print_page(text, background, rng, prm)
    del text, background
    data, meta = photo_jpeg(sheet, rng, PhotoParams(sensor_long_side=max(2400, long_side), long_side=long_side))
    rec, arrays = _decode(load_gray(data), profile)
    rec.update(job=[profile, template, prn, list(coal), page, long_side], cuts=[c1, c2],
               t_total=time.perf_counter() - t0, view_angle=meta["view_angle_deg"])
    _save(path, rec, arrays)
    return {"job": job, "t": round(rec["t_total"], 1)}


def _range(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def _run(fn, jobs: list, workers: int, profile: str) -> None:
    print(f"{len(jobs)} jobs", flush=True)
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                             initializer=context, initargs=(profile,)) as pool:
        futs = {pool.submit(fn, j): j for j in jobs}
        for k, f in enumerate(as_completed(futs), 1):
            try:
                print(f"[{k}/{len(jobs)} {time.perf_counter() - t0:.0f}s] {f.result()}", flush=True)
            except Exception:  # noqa: BLE001 (report and continue with the other jobs)
                print(f"FAILED {futs[f]}\n{traceback.format_exc()}", flush=True)


# --- report --------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95 % interval of a proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load(folder) -> list[dict]:
    """All result files of one folder, with their soft bits."""
    from tapak.decoder.softbits import SoftBits

    out = []
    for f in sorted(folder.glob("*.npz")):
        z = np.load(f)
        rec = json.loads(str(z["meta"]))
        rec["sb"] = {k[:-4]: SoftBits(k[:-4], z[k], z[f"{k[:-4]}_llr"]) for k in z.files if k.endswith("_pos")}
        out.append(rec)
    return out


def verdict(ctx, sbs: list, guilty: list[int]) -> dict:
    """Production verdict over all copies, plus score / Z of the guilty and the largest innocent."""
    from tapak.decoder.fuse import fuse
    from tapak.decoder.trace import run_trace
    from tapak.tardos.accuse import scores, threshold

    sbs = [s for s in sbs if len(s)]
    att = run_trace(sbs, ctx)
    accused = {c.copy.seq for c in att.accused}
    est = fuse(sbs, ctx.params.length)
    z = threshold(ctx.p, ctx.params.eps1, est.weights)
    s = scores(ctx.codewords, est.y, ctx.p, est.weights) if est.n_observed else np.zeros(len(ctx.codewords))
    if math.isfinite(z) and {int(i) + 1 for i in np.nonzero(s >= z)[0]} != accused:
        raise RuntimeError("fused scores disagree with run_trace")
    idx = [g - 1 for g in guilty]
    ratio = s / z if math.isfinite(z) and z > 0 else np.zeros_like(s)
    return {"caught": len(accused & set(guilty)), "fa": len(accused - set(guilty)), "none": not accused,
            "ratios": [float(ratio[i]) for i in idx], "inno": float(np.delete(ratio, idx).max()),
            "top_is_guilty": bool(np.argmax(s) in idx), "n": int(est.n_observed)}


def channel_stats(ctx, recs: list[dict], ch: str) -> dict:
    """Readable positions and bit errors of one channel against the true codewords."""
    n_read, errs, tot, per_trace, found = [], 0, 0, [], 0
    for r in recs:
        sb = r["sb"].get(ch)
        n_read.append(len(sb) if sb is not None else 0)
        if sb is not None and len(sb):
            x = ctx.codewords[r["job"][3] - 1]
            e = int(np.sum((sb.llr > 0) != (x[sb.positions] == 1)))
            errs, tot, found = errs + e, tot + len(sb), found + 1
            per_trace.append(e / len(sb))
    return {"traces": len(recs), "with_bits": found, "read_mean": float(np.mean(n_read)) if n_read else 0.0,
            "ber": errs / tot if tot else None, "bits": tot,
            "ber_median": float(np.median(per_trace)) if per_trace else None,
            "ber_max": float(np.max(per_trace)) if per_trace else None}


def _lone(rows: list[dict]) -> dict:
    n = len(rows)
    ok = sum(r["caught"] == 1 and r["fa"] == 0 for r in rows)
    ratios = [r["ratios"][0] for r in rows]
    return {"n": n, "named": ok, "wilson": wilson(ok, n), "insufficient": sum(r["none"] for r in rows),
            "wrong": sum(r["fa"] > 0 for r in rows), "top_is_true": sum(r["top_is_guilty"] for r in rows),
            "ratio_median": float(np.median(ratios)), "ratio_min": float(np.min(ratios)),
            "ratio_max": float(np.max(ratios)), "innocent_max": max(r["inno"] for r in rows),
            "positions_median": float(np.median([r["n"] for r in rows]))}


def report() -> dict:
    """Tables of every result folder (printed and returned)."""
    summary: dict = {}
    for folder in sorted((OUT / "results").glob("*__*__*")):
        profile, template, prn = folder.name.split("__")
        ctx = context(profile)
        recs = load(folder)
        for long_side in sorted({r["job"][5] for r in recs}):
            rl = [r for r in recs if r["job"][5] == long_side]
            key = f"{profile}/{template}/{prn}/L{long_side}"
            out = summary.setdefault(key, {})
            for page in sorted({r["job"][4] for r in rl}):
                rp = [r for r in rl if r["job"][4] == page]
                for ch in ("shift", "background"):
                    out[f"p{page + 1} {ch}"] = channel_stats(ctx, rp, ch)
                out[f"p{page + 1} background found"] = sum(
                    bool(r.get("background", {}).get("pattern_found")) for r in rp)
            for chans in (["shift"], ["background"], ["shift", "background"]):
                label = "+".join(chans)
                one = [verdict(ctx, [r["sb"][c] for c in chans if c in r["sb"]], [r["job"][3]]) for r in rl]
                out[f"1 page {label}"] = _lone(one)
                pairs = defaultdict(list)
                for r in rl:
                    pairs[(r["job"][3], r["job"][6])].append(r)
                two = [verdict(ctx, [x["sb"][c] for x in pr for c in chans if c in x["sb"]], [seq])
                       for (seq, _), pr in pairs.items() if len(pr) == 2]
                if two:
                    out[f"2 pages {label}"] = _lone(two)
    for folder in sorted((OUT / "composites").glob("*__*__*")):
        profile, template, prn = folder.name.split("__")
        ctx = context(profile)
        recs = load(folder)
        for long_side in sorted({r["job"][5] for r in recs}):
            rl = [r for r in recs if r["job"][5] == long_side]
            out = summary.setdefault(f"composite {profile}/{template}/{prn}/L{long_side}", {})
            by_coal = defaultdict(list)
            for r in rl:
                by_coal[tuple(r["job"][3])].append(r)
            for chans in (["background"], ["shift", "background"]):
                label = "+".join(chans)
                one = [verdict(ctx, [r["sb"][c] for c in chans if c in r["sb"]], list(r["job"][3])) for r in rl]
                two = [verdict(ctx, [x["sb"][c] for x in rr for c in chans if c in x["sb"]], list(coal))
                       for coal, rr in by_coal.items() if len(rr) == 2]
                for pages, rows in (("1 page", one), ("2 pages", two)):
                    if rows:
                        out[f"{pages} {label}"] = {
                            "n": len(rows), "innocents_named": sum(r["fa"] for r in rows),
                            "at_least_one": sum(r["caught"] >= 1 for r in rows),
                            "all_three": sum(r["caught"] == 3 for r in rows),
                            "member_ratio_median": float(np.median([x for r in rows for x in r["ratios"]])),
                            "innocent_max": max(r["inno"] for r in rows)}
            out["background found"] = sum(bool(r.get("background", {}).get("pattern_found")) for r in rl)
    for key, out in summary.items():
        print(f"\n=== {key}")
        for k, v in out.items():
            print(f"  {k}: {json.dumps(v, default=float)}")
    return summary


def main() -> None:
    """Command line: trials, composites or report."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=["trials", "composites", "report"])
    ap.add_argument("--profile", choices=["layar", "cetak"], default="layar")
    ap.add_argument("--template", choices=["exact", "supersampled"], default="exact")
    ap.add_argument("--printer", choices=PRINTERS, default="laser")
    ap.add_argument("--seqs", default="1-20")
    ap.add_argument("--pages", default="0,1")
    ap.add_argument("--long", default="1600,4000")
    ap.add_argument("--reps", default="0")
    ap.add_argument("--coalitions", type=int, default=16)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--json", default=None, help="write the report to this file")
    args = ap.parse_args()
    if args.what == "report":
        summary = report()
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=1, default=float)
        return
    context(args.profile)  # issue once, before the workers start
    if args.what == "trials":
        jobs = [(args.profile, args.template, args.printer, s, p, L, r) for s in _range(args.seqs)
                for p in _range(args.pages) for L in _range(args.long) for r in _range(args.reps)
                if s in TEST_SEQS]
        _run(trial, [j for j in jobs if not trial_path(*j).exists()], args.workers, args.profile)
    else:
        jobs = [(args.profile, args.template, args.printer, c, p, L) for c in coalitions(args.coalitions)
                for p in _range(args.pages) for L in _range(args.long)]
        _run(composite, [j for j in jobs if not composite_path(*j).exists()], args.workers, args.profile)


if __name__ == "__main__":
    main()
