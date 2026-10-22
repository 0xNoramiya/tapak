"""Review of the erasure check: reversal instead of erasure, and honest evidence from fresh seeds.

Protocol, seeds and analysis fixed and committed before any run. Nothing here chooses a
threshold or changes the decoder; the results only correct what the documentation claims.

Question 1 (``serang``). A coalition that knows the erasure check can neutralize the agreeing
marks by reversing them instead of erasing them (``tapak.collusion``, ``neutralize="balik"``:
background cell level negated, data unit mirrored about its master position). Every unit then
reads as clearly as in an honest copy, so the check (which looks at how clearly units are
read) should not fire, while the agreeing positions now count against the coalition. Fresh
issuances (``tapak issue --benih-riset``, no registry, no canary, c = 3, eps = 1e-6):
nota_dinas N = 20 (7601) and N = 100 (7602), surat_telegram N = 20 (7603) and N = 100 (7604).
Coalitions of k = 2, 3, 4 copies, 3 per issuance and k (seed [7611, issuance, k]), from
copies 1 to N; the forgery starts from the coalition's first copy. Configurations (random
member at disagreeing units, ``rule="acak"``, erase_fraction 1):

* ``jujur``: copy 1 itself (paired honest control);
* ``semua/hapus``: the attack of ``ukur.py`` (``semua/acak`` there): agreeing background cells
  and shift units erased;
* ``semua/balik``: agreeing background cells and shift units reversed;
* ``buang/balik``: the whole background flattened (every cell at the base level, as a
  coalition that drops the pattern image), agreeing shift units reversed;
* ``buang/hapus``: the whole background flattened, agreeing shift units erased.

Channels ``pdf``, ``layar`` (screenshot of page 1) and ``foto`` (phone photo of page 1 on a
screen), exactly as ``ukur.evidence``; channel randomness seed [7621, issuance, k, coalition,
channel]; attack randomness seed [7631, issuance, k, coalition, configuration]. Every
evidence is traced as the first logged trace, single-stage and staged (``ukur.verdicts``).

Question 2 (``jujur``). False alarms of the erasure check on honest evidence from seeds never
used before, and how far one document's honest Z sits from 0. Issuances 7601 to 7604 above
and four more with N = 20: nota_dinas 7605 and 7607, surat_telegram 7606 and 7608. Copies 1
to 10 of each through ``pdf``, ``layar``, ``foto`` and ``cetak`` (pages 1 and 2 printed and
photographed), seed [7641, issuance, copy, channel]; and the unmarked master of each through
``pdf``, ``layar`` and ``foto`` (seed [7651, issuance, channel]).

Recorded per evidence (one JSON line): everything ``ukur.record`` records, the shipped
check (``erasure_check``: z, flagged, positions) and, as a measurement only, the alignment of
the read bits with the bias vector, per physical channel and fused:
A = sum_i w_i (2 y_i - 1)(2 p_i - 1) and B = sum_i w_i^2 (2 p_i - 1)^2 over the fused
estimate (w, y) the accusation uses. For honest evidence whose read errors are independent
of the code with error rate at most 1/2, E[A] >= 0, so A / sqrt(B) far below 0 cannot come
from an honest copy (Hoeffding: P(A <= -t sqrt(B)) <= exp(-t^2 / 2)); A / B is about 1 for a
calibrated honest read.

Analysis fixed now: (1) per configuration and channel, escapes (nobody in the coalition named,
single-stage and staged), flagged by the shipped check, and every false accusation (zero
required); (2) honest false alarms per channel and in total, the mean and spread of honest Z
per issuance and channel, and the between-issuance spread of those means after removing the
within-issuance part; (3) A / sqrt(B) and A / B per configuration and channel. Seeds used
before (7101 to 7241, 7301, 7302, 7401) are not reused.

    python research/sepakat/balik.py terbit
    python research/sepakat/balik.py serang --out research/sepakat/hasil/balik_serang.jsonl
    python research/sepakat/balik.py jujur --out research/sepakat/hasil/balik_jujur.jsonl
    python research/sepakat/balik.py ringkas research/sepakat/hasil/balik_*.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import ukur  # noqa: E402

ATTACK_ISSUANCES = [("nota_dinas", 20, 7601), ("nota_dinas", 100, 7602), ("surat_telegram", 20, 7603),
                    ("surat_telegram", 100, 7604)]
HONEST_ISSUANCES = ATTACK_ISSUANCES + [("nota_dinas", 20, 7605), ("surat_telegram", 20, 7606),
                                       ("nota_dinas", 20, 7607), ("surat_telegram", 20, 7608)]
SEEDS = {"koalisi": 7611, "kanal": 7621, "serangan": 7631, "jujur": 7641, "induk": 7651}
KS = (2, 3, 4)
COALITIONS = 3
COPIES = 10
CONFIGS = ("semua/hapus", "semua/balik", "buang/balik", "buang/hapus")
ATTACK_CHANNELS = ("pdf", "layar", "foto")
HONEST_CHANNELS = ("pdf", "layar", "foto", "cetak")


def issue_all() -> None:
    """Issue every issuance of this protocol (skips the ones already there)."""
    for doc, n, seed in HONEST_ISSUANCES:
        folder = ukur.issuance_dir(doc, n, seed)
        if list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            print(f"{folder.name}: sudah ada", flush=True)
            continue
        csv = ukur._recipients_csv(folder, n)
        cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
               "issue", str(ROOT / "samples" / f"{doc}.pdf"), str(csv), "--no-registry", "--canary-domain", "",
               "--workers", str(ukur.WORKERS), "--benih-riset", str(seed)]
        subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})


def alignment(obs, ctx) -> dict[str, list[float]]:
    """[positions, A, B] of the fused estimate and of every physical channel (see the docstring)."""
    from tapak.decoder.fuse import fuse, fuse_by_physical_channel

    m = ctx.params.length
    e = 2.0 * np.asarray(ctx.p, dtype=np.float64) - 1.0
    out = {}
    parts = {"gabung": fuse(obs, m), **fuse_by_physical_channel(obs, m)}
    for name, f in parts.items():
        w = np.asarray(f.weights, dtype=np.float64)
        s = 2.0 * np.asarray(f.y, dtype=np.float64) - 1.0
        out[name] = [int(np.count_nonzero(w)), round(float(np.sum(w * s * e)), 3), round(float(np.sum((w * e) ** 2)), 3)]
    return out


def check(obs, ctx) -> dict:
    """The shipped erasure check of one evidence."""
    from tapak.decoder.erasure import erasure_check

    c = erasure_check(obs, ctx.p)
    return {"z": c.z, "ditandai": bool(c.flagged), "posisi": c.positions}


def _forge(ctx, pdfs: list[bytes], config: str, rng: np.random.Generator) -> tuple[bytes, dict]:
    from tapak.collusion import attack, forge_copy

    scope, how = config.split("/")
    channels = ("latar", "geser") if scope == "semua" else ("geser",)
    data, _, plan = attack(ctx.master, pdfs, "acak", 1.0, channels, rng, neutralize=how)
    if scope == "buang":
        for lv in plan.levels.values():
            lv[:] = 0.0
        data = forge_copy(ctx.master, pdfs, plan)
    return data, plan.counts


def attack_job(job: tuple) -> list[dict]:
    """Every configuration and the honest control of one coalition through the three channels."""
    iss, (doc, n, seed), k, ci, members = job
    ctx, _ = ukur.context(doc, n, seed)
    pdfs = [ukur.copy_pdf(doc, n, seed, s) for s in members]
    x = ctx.codewords[[s - 1 for s in members]].astype(np.int64)
    agree = np.all(x == x[:1], axis=0)
    forged: dict[str, tuple[bytes, dict]] = {"jujur": (pdfs[0], {})}
    for cfg_i, name in enumerate(CONFIGS):
        forged[name] = _forge(ctx, pdfs, name, np.random.default_rng([SEEDS["serangan"], iss, k, ci, cfg_i]))
    rows = []
    for ch_i, channel in enumerate(ATTACK_CHANNELS):
        for name, (data, counts) in forged.items():
            t0 = time.perf_counter()
            rng = np.random.default_rng([SEEDS["kanal"], iss, k, ci, ch_i])
            obs, _ = ukur.evidence(ctx, data, channel, rng, ci)
            row = {"bagian": "serangan", "dok": doc, "N": n, "benih": seed, "k": k, "koalisi_ke": ci,
                   "koalisi": members, "serangan": name, "kanal": channel, "rencana": counts}
            row.update(ukur.record(obs, ctx, members, x[0], agree))
            row["periksa"] = check(obs, ctx)
            row["selaras"] = alignment(obs, ctx)
            row["detik"] = round(time.perf_counter() - t0, 1)
            rows.append(row)
    return rows


def honest_job(job: tuple) -> list[dict]:
    """One honest copy (seq >= 1) or the unmarked master (seq 0) through the channels."""
    iss, (doc, n, seed), seq = job
    ctx, _ = ukur.context(doc, n, seed)
    if seq == 0:
        pdf, channels = ctx.master.pdf_bytes, ATTACK_CHANNELS
        x = np.zeros(ctx.params.length, dtype=np.int64)
    else:
        pdf, channels = ukur.copy_pdf(doc, n, seed, seq), HONEST_CHANNELS
        x = ctx.codewords[seq - 1].astype(np.int64)
    rows = []
    for ch_i, channel in enumerate(channels):
        t0 = time.perf_counter()
        seeds = [SEEDS["induk"], iss, ch_i] if seq == 0 else [SEEDS["jujur"], iss, seq, ch_i]
        obs, _ = ukur.evidence(ctx, pdf, channel, np.random.default_rng(seeds), seq)
        row = {"bagian": "induk" if seq == 0 else "jujur", "dok": doc, "N": n, "benih": seed, "salinan": seq,
               "kanal": channel}
        if seq:
            row.update(ukur.record(obs, ctx, [seq], x, np.ones(x.size, dtype=bool)))
        else:
            row["putusan"] = ukur.verdicts(obs, ctx, set())
        row["periksa"] = check(obs, ctx)
        row["selaras"] = alignment(obs, ctx)
        row["detik"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
    return rows


def attack_jobs() -> list[tuple]:
    """The coalitions of every attack issuance and size, from the fixed seed."""
    jobs = []
    for iss, spec in enumerate(ATTACK_ISSUANCES):
        n = spec[1]
        for k in KS:
            rng = np.random.default_rng([SEEDS["koalisi"], iss, k])
            for ci in range(COALITIONS):
                members = sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
                jobs.append((iss, spec, k, ci, members))
    return jobs


def honest_jobs() -> list[tuple]:
    """Copies 1 to COPIES and the master (0) of every honest issuance."""
    return [(iss, spec, seq) for iss, spec in enumerate(HONEST_ISSUANCES) for seq in range(0, COPIES + 1)]


# --- summary -------------------------------------------------------------------------------


def _escaped(row: dict, stage: str) -> bool:
    return row["putusan"][stage]["anggota"] == 0


def summary(paths: list[str]) -> int:
    """Tables of the analysis fixed in the module docstring."""
    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    wrong = [(r.get("serangan", r["bagian"]), r["kanal"], r["putusan"][s]["salah"]) for r in rows
             for s in ("satu", "bertahap") if r["putusan"][s]["salah"]]
    print(f"tuduhan salah: {len(wrong)} dari {2 * len(rows)} pelacakan {wrong[:5]}")
    attack = [r for r in rows if r["bagian"] == "serangan"]
    if attack:
        print("\nserangan: lolos satu tahap / lolos bertahap / ditandai, dari n; median A/sqrt(B) dan A/B (gabung)")
        cells: dict[tuple, list[dict]] = defaultdict(list)
        for r in attack:
            cells[(r["serangan"], r["kanal"])].append(r)
        for (cfg, ch), rs in sorted(cells.items()):
            s = [r["selaras"]["gabung"] for r in rs]
            zs = [x[1] / math.sqrt(x[2]) for x in s if x[2] > 0]
            ratio = [x[1] / x[2] for x in s if x[2] > 0]
            named = sum(r["putusan"]["satu"]["anggota"] > 0 for r in rs)
            print(f"  {cfg:12s} {ch:6s} lolos {sum(_escaped(r, 'satu') for r in rs):3d} / "
                  f"{sum(_escaped(r, 'bertahap') for r in rs):3d} / ditandai {sum(r['periksa']['ditandai'] for r in rs):3d}"
                  f" dari {len(rs)} (disebut {named}); z median {np.median([r['periksa']['z'] for r in rs if r['periksa']['z'] is not None] or [np.nan]):6.2f};"
                  f" A/sqrt(B) median {np.median(zs) if zs else float('nan'):7.2f} maks {max(zs) if zs else float('nan'):7.2f};"
                  f" A/B median {np.median(ratio) if ratio else float('nan'):5.2f}")
    honest = [r for r in rows if r["bagian"] == "jujur"]
    if honest:
        print("\njujur: ditandai / diperiksa per kanal; Z rata-rata per penerbitan (sd di dalam)")
        by_ch: dict[str, list[dict]] = defaultdict(list)
        for r in honest:
            by_ch[r["kanal"]].append(r)
        total = flagged = 0
        for ch, rs in sorted(by_ch.items()):
            zs = [r["periksa"]["z"] for r in rs if r["periksa"]["z"] is not None]
            f = sum(r["periksa"]["ditandai"] for r in rs)
            total += len(zs)
            flagged += f
            groups: dict[int, list[float]] = defaultdict(list)
            for r in rs:
                if r["periksa"]["z"] is not None:
                    groups[r["benih"]].append(r["periksa"]["z"])
            means = [float(np.mean(v)) for v in groups.values()]
            within = float(np.mean([np.var(v, ddof=1) for v in groups.values() if len(v) > 1]))
            size = float(np.mean([len(v) for v in groups.values()]))
            between = max(0.0, float(np.var(means, ddof=1)) - within / size) if len(means) > 1 else float("nan")
            al = [r["selaras"]["gabung"] for r in rs if r["selaras"]["gabung"][2] > 0]
            print(f"  {ch:6s} ditandai {f} dari {len(zs)}; sd Z {np.std(zs, ddof=1):.2f}; min Z {min(zs):.2f}; "
                  f"rata-rata per penerbitan {', '.join(f'{m:+.2f}' for m in means)}; sd di dalam {math.sqrt(within):.2f}; "
                  f"sd antarpenerbitan {math.sqrt(between):.2f}; A/sqrt(B) min {min(a[1] / math.sqrt(a[2]) for a in al):.1f}; "
                  f"A/B min {min(a[1] / a[2] for a in al):.2f} median {np.median([a[1] / a[2] for a in al]):.2f}")
        print(f"  total ditandai {flagged} dari {total}")
    master = [r for r in rows if r["bagian"] == "induk"]
    if master:
        print("\ninduk tanpa tanda: z per kanal, ditandai, disebut")
        for r in master:
            print(f"  {r['dok']} {r['benih']} {r['kanal']}: z {r['periksa']['z']} ditandai {r['periksa']['ditandai']} "
                  f"disebut {r['putusan']['satu']['dituduh']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "serang", "jujur", "ringkas"])
    ap.add_argument("paths", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.bagian == "terbit":
        issue_all()
    elif args.bagian == "serang":
        ukur._run(attack_job, attack_jobs(), args.out)
    elif args.bagian == "jujur":
        ukur._run(honest_job, honest_jobs(), args.out)
    else:
        return summary(args.paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
