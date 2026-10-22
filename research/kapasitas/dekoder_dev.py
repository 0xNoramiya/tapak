"""Decoder study for geser-v2 on development evidence only (``ukur.py`` dev seeds).

Regenerates some dev printed photos of v2 copies (same random numbers as ``ukur.py dev``),
saves the measured group displacements, then compares decoder variants on them. Every variant
is code-blind; the codewords are used only afterwards, to count errors and score the leaked
copy. Variants of the word part (rows are decoded as in production):

* ``d1``, ``d2``: row nuisance of degree 1 (offset, slope) or 2 (plus curvature) per row;
* ``veld``: first a smooth displacement field over the page, a polynomial of degree 3 in the
  page coordinates fitted to every measured group (the random signs average out), is
  subtracted; then degree 1 per row. The field takes the bow left by rectification without
  spending a degree of freedom of every row on it.

Output: ``hasil/dekoder_dev.jsonl``.

    PYTHONPATH=. python research/kapasitas/dekoder_dev.py simpan   # displacements (slow)
    PYTHONPATH=. python research/kapasitas/dekoder_dev.py banding  # decoder variants (fast)
"""

from __future__ import annotations

import json
import sys

import numpy as np

import ukur

OUT = ukur.WORK / "disp_dev"
VARIANTS = ("d1", "d2", "veld2", "veld3", "prod1", "prod2", "prod3")


def jobs() -> list[dict]:
    """Nota dinas, pages 1 and 2 at 1600 px (laser and inkjet) and page 1 at 4000 px (laser)."""
    g = ukur.PROTOCOL["dev"]
    out = []
    for prn, res, pages in (("laser", 1600, (1, 2)), ("inkjet", 1600, (1, 2)), ("laser", 4000, (1,))):
        for seq in g["copies"]:
            for page in pages:
                out.append({"phase": "dev", "kind": "cetak", "variant": "v2", "doc": "nota_dinas", "n": 100,
                            "printer": prn, "res": res, "seqs": [seq], "page": page})
    return out


def save() -> None:
    from tapak.decoder.trace import collect_file

    ukur._init()
    OUT.mkdir(parents=True, exist_ok=True)
    for job in jobs():
        path = OUT / (ukur.job_key(job).replace("|", "__") + ".json")
        if path.exists():
            continue
        name, data, _ = ukur.make_evidence(job)
        ctx, _, _ = ukur.context("dev", job["doc"], 100, "v2")
        disps: list = []
        with ukur.capture_displacements(disps):
            collect_file(name, data, ctx)
        disp = disps[0] if disps else {}
        path.write_text(json.dumps({"job": job, "disp": [[list(k), float(v[0]), float(v[1])] for k, v in disp.items()]}))
        print(path.name, len(disp), flush=True)


def field_residual(units_by_row: dict, degree: int = 3) -> dict:
    """Subtract a polynomial field of ``degree`` in (x, y) fitted to all groups of the page
    (robust: refitted twice without groups beyond 3 MAD)."""
    pts = [(x, y, d) for (y, units) in units_by_row.items() for (_, _, x, d) in units]
    if len(pts) < 20:
        return units_by_row
    xs, ys, ds = (np.array(v) for v in zip(*pts))
    xn, yn = (xs - xs.mean()) / (np.ptp(xs) or 1.0), (ys - ys.mean()) / (np.ptp(ys) or 1.0)
    terms = [xn**i * yn**j for i in range(degree + 1) for j in range(degree + 1 - i)]
    a = np.stack(terms, axis=1)
    keep = np.ones(len(ds), dtype=bool)
    for _ in range(3):
        coef, *_ = np.linalg.lstsq(a[keep], ds[keep], rcond=None)
        r = ds - a @ coef
        mad = 1.4826 * float(np.median(np.abs(r[keep] - np.median(r[keep])))) or 1e-9
        keep = np.abs(r) <= 3 * mad + 1e-12
    fit = a @ coef
    out, k = {}, 0
    for y, units in units_by_row.items():
        out[y] = [(q, w, x, d - fit[k + i]) for i, (q, w, x, d) in enumerate(units)]
        k += len(units)
    return out


def word_softbits(ctx, disp, variant: str):
    from tapak.decoder.ch_shift import decode_displacements, joint_measurements, joint_word_llrs
    from tapak.decoder.softbits import SoftBits

    delta = ctx.shift.word_pt
    if variant.startswith("prod"):  # the production decoder (iterated page field), word part only
        rounds = int(variant[4:] or 3)
        import tapak.decoder.ch_shift as ch

        ch.FIELD_ROUNDS, old = rounds, ch.FIELD_ROUNDS
        try:
            sb = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded, field_degree=3)
        finally:
            ch.FIELD_ROUNDS = old
        words = {s.positions[0] for s in ctx.plan.channel("shift") if len(s.ref) == 2}
        keep = np.isin(sb.positions, list(words))
        return SoftBits("shift", sb.positions[keep], sb.llr[keep]), sb.meta["sigma_pt"].get("kata", 0.0)
    degree = 2 if variant == "d2" else (0 if variant.endswith("_d0") else 1)
    rows, _ = joint_measurements(ctx.master, ctx.plan, disp, delta, degree)
    if variant.startswith("veld"):
        fdeg = int(variant[4]) if len(variant) > 4 and variant[4].isdigit() else 3
        layout = ctx.master.shift_layout
        ymap = {}
        for s in ctx.plan.channel("shift"):
            if len(s.ref) == 2:
                ymap[s.positions[0]] = layout.pages[s.page].rows[s.ref[0]].baseline
        by_row = {ymap[r[0][0]]: r for r in rows}
        rows = list(field_residual(by_row, fdeg).values())
    llrs, sigma = joint_word_llrs([(np.array([u[2] for u in r]), np.array([u[3] for u in r])) for r in rows],
                                  delta, floor=0.05 * delta, degree=degree)
    pos, llr = [], []
    for units, rl in zip(rows, llrs):
        for (q, w, _, _), v in zip(units, rl):
            if abs(v) > 1e-6:
                pos.append(q)
                llr.append(v * (1 - 2 * w))
    return SoftBits("shift", np.array(pos, dtype=np.int64), np.array(llr)), sigma


def compare() -> None:
    from tapak.decoder.ch_shift import decode_displacements
    from tapak.decoder.softbits import SoftBits
    from tapak.decoder.trace import run_trace
    from tapak.marker.pdf_shift import MM_TO_PT

    out = []
    for path in sorted(OUT.glob("*.json")):
        rec = json.loads(path.read_text())
        job = rec["job"]
        ctx, _, _ = ukur.context("dev", job["doc"], 100, "v2")
        disp = {tuple(k): (dx, dy) for k, dx, dy in rec["disp"]}
        x = ctx.codewords[job["seqs"][0] - 1]
        rows_pos = {s.positions[0] for s in ctx.plan.channel("shift") if len(s.ref) == 1}
        prod = decode_displacements(ctx.master, ctx.plan, disp, ctx.shift, ctx.excluded)
        keep = np.isin(prod.positions, list(rows_pos))
        row_sb = SoftBits("shift", prod.positions[keep], prod.llr[keep])
        res = {"job": ukur.job_key(job)}
        for variant in VARIANTS:
            sb, sigma = word_softbits(ctx, disp, variant)
            both = SoftBits.concat("shift", [sb, row_sb])
            a = run_trace([both], ctx)
            score = next(c.score for c in a.candidates if c.copy.seq == job["seqs"][0]) / a.threshold.threshold
            w = np.tanh(np.abs(sb.llr) / 2)
            right = (sb.llr > 0) == (x[sb.positions] == 1)
            res[variant] = {"read": int(len(sb)), "ber": round(float(np.mean(~right)), 3),
                            "eff": round(float(np.sum(w * np.where(right, 1, -1))), 1),
                            "score_z": round(score, 3), "sigma_um": round(sigma / MM_TO_PT * 1000, 1),
                            "named": [c.copy.seq for c in a.accused]}
        out.append(res)
        print(json.dumps(res), flush=True)
    (ukur.HASIL / "dekoder_dev.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    for variant in VARIANTS:
        for tag in ("laser|1600", "inkjet|1600", "laser|4000"):
            sel = [r[variant] for r in out if tag in r["job"]]
            if sel:
                print(variant, tag, "score median %.3f" % np.median([s["score_z"] for s in sel]),
                      "named", sum(1 for s in sel if s["named"]), "/", len(sel),
                      "eff median %.1f" % np.median([s["eff"] for s in sel]))


if __name__ == "__main__":
    {"simpan": save, "banding": compare}[sys.argv[1]]()
