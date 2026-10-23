"""Review check outside the protocol: one fresh seed (9301) for honest prints and screen photos,
and the cheapest escapes from both manipulation checks.

Run after the held-out parts, with nothing in the code changed. Issuance F1: the fictional
nota_dinas, N = 20, geser-v2, default background, ``tapak issue --benih-riset 9301``.

* ``jujur``: copies 1 to 10 and three standard coalitions (2 ``acak``, 3 ``mayoritas``, 2
  ``rata``; members seed [9302, k, strategy], attack seed [9303, k, strategy]) through
  ``cetak1``, ``cetak2`` and ``monitor`` (channel seed [9304, unit, medium]).
* ``serang``: one coalition of two (seed [9305, 0]) and its first member alone. ``buang``: the
  background flattened and the agreeing shift units mirrored (``buang1``: the same with the
  first copy alone, so every unit counts as agreeing); ``balik``: agreeing marks reversed
  (``balik1``: one copy reversing every mark it can read); each through the PDF itself, a
  screenshot, a lossless PNG render, or Gaussian noise of 2 to 4 gray levels on the background
  image; ``jujur``: the first member through the same.

Usage (from the repository root; 3 worker processes, 1 BLAS thread each):

    python research/kontradiksi/tinjau.py terbit
    python research/kontradiksi/tinjau.py jujur --out research/kontradiksi/hasil/tinjau/jujur.jsonl
    python research/kontradiksi/tinjau.py serang --out research/kontradiksi/hasil/tinjau/serang.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import ukur  # noqa: E402

ukur.ISSUANCES["F1"] = ("nota_dinas", 20, 9301, "v2", "layar", "teks")
ukur.SETS["tinjau"] = ("F1",)
KEYS = ("putusan", "kontradiksi", "batas_penuh", "observed", "efektif", "hapus", "terbaca")


def honest_job(job: tuple) -> dict:
    """One honest unit (a copy or a standard coalition) through one medium."""
    kind, unit, medium = job
    ctx, _ = ukur.context("F1")
    if kind == "salinan":
        members, pdf, uid = [unit], ukur.copy_pdf("F1", unit), unit
    else:
        k, rule = unit
        si = ukur.STANDARD.index(rule)
        members = ukur.members_of([9302, k, si], ctx.params.n_max, k)
        pdf, _ = ukur._forge(ctx, [ukur.copy_pdf("F1", s) for s in members], rule, [9303, k, si])
        uid = 100 + 10 * k + si
    obs = ukur.evidence(ctx, pdf, medium, np.random.default_rng([9304, uid, ukur.MEDIA.index(medium)]), uid)
    row = ukur.analyse(obs, ctx, set(members))
    return {"jenis": kind, "unit": str(unit), "koalisi": members, "kanal": medium, **{k: row[k] for k in KEYS}}


def attack_job(job: tuple) -> dict:
    """One escape attempt (see the module docstring) through one medium."""
    from tapak.decoder.trace import collect_file

    name, medium = job
    ctx, _ = ukur.context("F1")
    members = ukur.members_of([9305, 0], ctx.params.n_max, 2)
    pdfs = [ukur.copy_pdf("F1", s) for s in members]
    group = set(members)
    if name == "buang1":
        pdf, _ = ukur._forge(ctx, [pdfs[0], pdfs[0]], "buang", [9306, 1])
        group = {members[0]}
    elif name == "buang":
        pdf, _ = ukur._forge(ctx, pdfs, "buang", [9306, 2])
    elif name == "balik1":
        pdf, _ = ukur._forge(ctx, [pdfs[0], pdfs[0]], "balik1", [9306, 3])
        group = {members[0]}
    elif name == "balik":
        pdf, _ = ukur._forge(ctx, pdfs, "balik", [9306, 4])
    elif name == "jujur":
        pdf, group = pdfs[0], {members[0]}
    else:
        raise ValueError(name)
    if medium.startswith("derau"):
        data = ukur.degrade_latar(pdf, float(medium[5:]), np.random.default_rng([9307, len(name)]))
        obs = collect_file("bukti.pdf", data, ctx)[0]
    elif medium == "png":
        fname, data = ukur.degrade_raster(pdf, "png", np.random.default_rng([9308]), 0)
        obs = collect_file(fname, data, ctx)[0]
    else:
        obs = ukur.evidence(ctx, pdf, medium, np.random.default_rng([9309, ukur.MEDIA.index(medium)]), 0)
    row = ukur.analyse(obs, ctx, group)
    return {"serangan": name, "kanal": medium, "anggota": sorted(group), **{k: row[k] for k in KEYS}}


def jobs(part: str) -> list[tuple]:
    """The fixed job list of a part."""
    if part == "jujur":
        out = [("salinan", s, m) for s in range(1, 11) for m in ("cetak1", "cetak2", "monitor")]
        return out + [("koalisi", (k, r), m) for k, r in ((2, "acak"), (3, "mayoritas"), (2, "rata"))
                      for m in ("cetak1", "cetak2", "monitor")]
    out = [(a, m) for a in ("jujur", "buang", "buang1") for m in ("pdf", "layar")]
    out += [("balik", m) for m in ("pdf", "png", "derau2", "derau3", "derau4")]
    out += [("balik1", m) for m in ("pdf", "png", "derau3", "derau4")]
    return out + [("jujur", m) for m in ("png", "derau3", "derau4")]


def main(argv: list[str] | None = None) -> int:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "jujur", "serang"])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.bagian == "terbit":
        ukur.issue_all("tinjau")
        return 0
    fn = honest_job if args.bagian == "jujur" else attack_job
    todo = jobs(args.bagian)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
            ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=ukur._init) as pool:
        for job, row in zip(todo, pool.map(fn, todo)):
            fh.write(json.dumps({"job": str(job), **row}) + "\n")
            fh.flush()
            con = row["kontradiksi"]
            print(job, "disebut", row["putusan"]["dituduh"], "kontradiksi", con and con["ditandai"],
                  "log10 B", row["batas_penuh"]["0.3"], "posisi", row["observed"],
                  "hapus", row["hapus"]["pola"]["ditandai"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
