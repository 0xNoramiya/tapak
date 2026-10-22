"""How the background-decoder change was chosen: candidates on the development seeds only.

Every development image of ``ukur.py`` is registered once and cached (rectified page, valid
mask, exact template, shift soft bits); each candidate then re-decodes only the background
channel and runs the unchanged fusion and accusation. The ``base`` candidate reproduced all
500 verdicts and background read counts of ``ukur.py lacak --split pengembangan --dekoder
lama`` exactly. The held-out seeds (``uji``) are never touched here.

Candidates (all use the evidence alone, never a keyed sign or a codeword):

* ``notch``: remove narrowband periodic components (moire) from the paper modulation, tile
  by tile (``ch_background.suppress_periodic``; peak factor ``NOTCH_K``, radius ``NOTCH_R``);
* ``flat``: count locally featureless pixels (high-pass energy below ``FLAT_FRAC`` of the
  page median, as clipped paper looks after tone mapping) with the saturated ones when
  assigning strata, extending the clipping weights to texture loss;
* ``halo``: mask bright outliers as well as dark ones (|modulation| above ``HALO``);
* ``nh2``: ``notch`` first, then ``halo`` on the filtered modulation, then ``notch`` again.

Selection rule, stated after the first three candidates and the small grid were seen but
before the last candidate (``nh2``) was evaluated: no verdict lost against ``base`` in any
condition, no accusation of an unmarked master, better margins (median z, smallest score over
threshold, per-image bit errors) where the images are affected. ``nh2`` with the defaults was
chosen and is the decoder of this tree.

Usage (from the repository root, after ``ukur.py buat --split pengembangan``):

    python research/ponsel/kandidat.py cache
    python research/ponsel/kandidat.py nilai base,notch,flat,halo,nh2,notch+halo
    NOTCH_R=2 TAG=_r2 python research/ponsel/kandidat.py nilai notch     # likewise _k4, _k9, _h05
    python research/ponsel/kandidat.py ringkas                           # research/ponsel/hasil
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ukur  # noqa: E402

CACHE = ukur.WORK / "cache" / "pengembangan"
OUT = ukur.WORK / "kandidat"
FLAT_FRAC = float(os.environ.get("FLAT_FRAC", "0.15"))
HALO = float(os.environ.get("HALO", "0.08"))
NOTCH_K = float(os.environ.get("NOTCH_K", "6"))
NOTCH_R = int(os.environ.get("NOTCH_R", "1"))


def cache_path(job: dict) -> Path:
    return CACHE / ukur._evidence_path(job).relative_to(ukur.WORK / "bukti" / "pengembangan").with_suffix(".npz")


def build(job: dict) -> bool:
    from tapak.decoder.ch_shift import decode_displacements, measure_image, template_boxes
    from tapak.decoder.rectify import load_gray, register, render_page_exact

    out = cache_path(job)
    if out.exists():
        return True
    ctx, _, _ = ukur._context(job["doc"])
    gray = load_gray(ukur._evidence_path(job).read_bytes())
    reg = register(gray, ctx.master.pdf_bytes, [(p.width, p.height) for p in ctx.master.layout.pages])
    out.parent.mkdir(parents=True, exist_ok=True)
    if reg is None:
        np.savez_compressed(out, registered=False)
        return False
    template = render_page_exact(ctx.master.pdf_bytes, reg.page, reg.dpi,
                                 boxes=template_boxes(ctx.master, reg.page, reg.dpi))
    disp = measure_image(reg.rectified, reg.valid, template, ctx.master, reg.page, reg.dpi)
    sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
    np.savez_compressed(out, registered=True, page=reg.page, dpi=reg.dpi, rect=reg.rectified.astype(np.float32),
                        valid=reg.valid, shift_pos=sb.positions, shift_llr=sb.llr)
    return True


def decode_variant(rectified, valid, master_render, dpi, grid, slots, bias, opts: set[str]):
    """The background decoder of commit ukur.PROTOCOL['base_commit'] with the candidate steps."""
    import cv2

    import tapak.decoder.ch_background as bg
    from tapak.decoder.softbits import SoftBits
    from tapak.marker.plan import CHANNEL_BACKGROUND
    from tapak.tardos.code import uniform_stream

    def notch(m, u):
        return bg.suppress_periodic(m, u, peak=NOTCH_K, radius=NOTCH_R)

    page_slots = [s for s in slots if s.page == grid.page and s.channel == CHANNEL_BACKGROUND]
    usable = valid & ~bg.ink_mask(master_render) & (rectified > 20)
    sigma_px = 3.0 * grid.cell_pt * dpi / 72.0
    mod = bg.relative_modulation(rectified, usable, sigma_px)
    if "nh2" in opts:
        mod, _ = notch(mod, usable)
        opts = opts | {"halo", "notch"}
    outliers = (np.abs(mod) > HALO) if "halo" in opts else (mod < -0.08)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    usable &= ~cv2.dilate((usable & outliers).astype(np.uint8), k).astype(bool)
    mod = bg.relative_modulation(rectified, usable, sigma_px)
    bins = 0
    if "notch" in opts:
        mod, bins = notch(mod, usable)
    means, frac = bg.cell_means(mod, usable, grid, dpi)
    sel = (frac >= bg.MIN_VALID_FRACTION) & (grid.cell_bit >= 0)
    bits = grid.cell_bit[sel]
    contrib = (grid.pn * means)[sel]
    weight = frac[sel]
    den = np.bincount(bits, weights=weight, minlength=grid.n_bits)
    seen = den > 0
    t = np.where(seen, np.bincount(bits, weights=contrib * weight, minlength=grid.n_bits) / np.maximum(den, 1e-12), 0)
    decoy = np.where(uniform_stream(grid.key, f"bg-decoy|{grid.page}".encode(), grid.n_cells) < 0.5,
                     -1.0, 1.0).reshape(grid.ny, grid.nx)
    t_decoy = np.where(seen, np.bincount(bits, weights=(decoy * grid.pn * means)[sel] * weight,
                                         minlength=grid.n_bits) / np.maximum(den, 1e-12), 0.0)
    noise2 = float(np.median(t_decoy[seen] ** 2)) if seen.any() else 0.0
    sigma = float(np.sqrt(noise2 / 0.4549)) if noise2 > 0 else 1.0
    z_decoy = bg.pattern_z(t[seen], t_decoy[seen], sigma) if noise2 > 0 else 0.0
    if "flat" in opts:
        img = rectified.astype(np.float32)
        r = img - cv2.GaussianBlur(img, (0, 0), 1.0)
        energy = cv2.GaussianBlur(r * r, (0, 0), 2.0)
        paper = usable & (img < bg.SAT_LEVEL)
        ref = float(np.median(energy[paper])) if paper.any() else 0.0
        featureless = (img >= bg.SAT_LEVEL) | (energy < FLAT_FRAC * ref)
        own, _ = bg.cell_means(featureless.astype(np.float64), usable, grid, dpi)
        w = (frac >= bg.MIN_VALID_FRACTION).astype(np.float64)
        num_s = cv2.GaussianBlur(own * w, (0, 0), bg.SAT_SMOOTH_CELLS)
        den_s = cv2.GaussianBlur(w, (0, 0), bg.SAT_SMOOTH_CELLS)
        share = np.where(den_s > 1e-9, num_s / np.maximum(den_s, 1e-9), own)
    else:
        share = bg.saturated_share(rectified, usable, grid, dpi, frac)
    n_strata = len(bg.SAT_EDGES)
    stratum = bg.saturation_strata(share[sel])
    u = bg._clip_by_stratum(contrib, stratum, n_strata)
    e_bit = np.zeros(grid.n_bits)
    for s in page_slots:
        e_bit[s.ref[0]] = (2.0 * float(bias[s.positions[0]]) - 1.0) * (1 - 2 * s.whiten[0])
    e = e_bit[bits]
    z_pilot = bg.pilot_z(u, e)
    gain, var = bg.stratum_gains(u, e, stratum, n_strata, weight)
    found = (z_decoy >= bg.SIGNAL_Z or z_pilot >= bg.SIGNAL_Z) and bool(np.any(gain > 0))
    info = np.bincount(bits, weights=(gain ** 2 / var)[stratum] * weight, minlength=grid.n_bits)
    llr = np.bincount(bits, weights=(2.0 * gain / var)[stratum] * weight * u, minlength=grid.n_bits)
    pos, val = [], []
    if found:
        for s in page_slots:
            if info[s.ref[0]] > 0:
                pos.append(s.positions[0])
                val.append(llr[s.ref[0]] * (1 - 2 * s.whiten[0]))
    meta = {"signal_z": max(z_decoy, z_pilot), "pattern_found": bool(found), "periodic_bins": bins}
    return SoftBits(CHANNEL_BACKGROUND, np.array(pos, dtype=np.int64), np.array(val), meta)


def evaluate(task: tuple[dict, str]) -> dict:
    job, variant = task
    from tapak.decoder.rectify import render_page
    from tapak.decoder.softbits import SoftBits
    from tapak.decoder.trace import run_trace
    from tapak.marker.background import page_grids
    from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

    ctx, _, _ = ukur._context(job["doc"])
    z = np.load(cache_path(job))
    obs = []
    if bool(z["registered"]):
        page, dpi = int(z["page"]), float(z["dpi"])
        master = render_page(ctx.master.pdf_bytes, page, dpi)
        grid = page_grids([(p.width, p.height) for p in ctx.master.layout.pages], ctx.key, ctx.background)[page]
        slots = ctx.plan.channel(CHANNEL_BACKGROUND)
        opts = set() if variant == "base" else set(variant.split("+"))  # base: the old decoder's steps
        sb = decode_variant(z["rect"], z["valid"], master, dpi, grid, slots, ctx.p, opts)
        obs = [SoftBits(CHANNEL_SHIFT, z["shift_pos"], z["shift_llr"], {}), sb]
    res = run_trace(obs, ctx)
    accused = [c.copy.seq for c in res.accused]
    exp = job["seq"]
    if exp is None:
        verdict = "salah" if accused else "tidak cukup bukti"
    else:
        verdict = "tidak cukup bukti" if not accused else "benar" if accused == [exp] else "salah"
    thr = float(res.threshold.threshold)
    scores = {c.copy.seq: float(c.score) for c in res.candidates}
    row = {"doc": job["doc"], "seq": exp, "cond": job["cond"], "variant": variant, "verdict": verdict,
           "score_ratio": scores[exp] / thr if exp in scores and thr > 0 else None,
           "max_innocent_ratio": max((s for q, s in scores.items() if q != exp), default=0.0) / thr if thr > 0 else None}
    if job["seq"] is None:
        row["master_image"] = job["master_image"]
    for o in obs:
        if o.channel == CHANNEL_BACKGROUND:
            row.update(z=float(o.meta["signal_z"]), bg_read=int(len(o)), periodic_bins=o.meta["periodic_bins"])
            if exp is not None and len(o):
                row["bg_err"] = int(np.sum((o.llr > 0) != (ctx.codewords[exp - 1][o.positions] == 1)))
    return row


def _pool(fn, tasks):
    import multiprocessing as mp

    with ProcessPoolExecutor(ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=ukur._init,
                             initargs=(None,)) as pool:
        return list(pool.map(fn, tasks, chunksize=4))


def summarize() -> list[dict]:
    """One row per candidate and condition, from out/riset_ponsel/kandidat/*.jsonl."""
    out = []
    for path in sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for cond in sorted({r["cond"] + (":induk" if r["seq"] is None else "") for r in rows}):
            sel = [r for r in rows if r["cond"] + (":induk" if r["seq"] is None else "") == cond]
            ratios = [r["score_ratio"] for r in sel if r.get("score_ratio") is not None]
            per = [r["bg_err"] / r["bg_read"] for r in sel if r.get("bg_read") and "bg_err" in r]
            out.append({"kandidat": path.stem, "kondisi": cond, "n": len(sel),
                        **{v: sum(r["verdict"] == v for r in sel) for v in ("benar", "tidak cukup bukti", "salah")},
                        "z_median": round(float(np.median([r.get("z", 0.0) for r in sel])), 2),
                        "skor_per_ambang_median": round(float(np.median(ratios)), 3) if ratios else None,
                        "skor_per_ambang_min": round(min(ratios), 3) if ratios else None,
                        "galat_latar_median": round(float(np.median(per)), 4) if per else None,
                        "skor_tak_bersalah_maks": round(max(r["max_innocent_ratio"] or 0 for r in sel), 3)})
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("cache", "nilai", "ringkas"):
        print(__doc__)
        return 2
    if argv[0] == "cache":
        _pool(build, ukur.jobs_for("pengembangan"))
    elif argv[0] == "nilai":
        variants = argv[1].split(",")
        jobs = ukur.jobs_for("pengembangan")
        rows = _pool(evaluate, [(j, v) for v in variants for j in jobs])
        OUT.mkdir(parents=True, exist_ok=True)
        tag = os.environ.get("TAG", "")
        for v in variants:
            ukur._write(OUT / f"{v}{tag}.jsonl", [r for r in rows if r["variant"] == v])
    else:
        rows = summarize()
        ukur._write(ukur.RESULTS / "pengembangan_kandidat.jsonl", rows)
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
