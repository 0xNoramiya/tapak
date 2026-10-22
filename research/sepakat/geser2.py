"""Shift scheme geser-v2: the erasure check on honest evidence and the knowing coalition (research).

Protocol, seeds and analysis fixed and committed before any run. Nothing here chooses a
threshold or changes a decoder: the erasure threshold stays z = -3.0902 (``erasure.ERASURE_Z``),
and no accusation threshold, eps or decision rule is touched. The results only state what the
check and the attack do on geser-v2 issuances, the default of a new issuance since
``research/kapasitas``. Both sample documents are fictional.

Issuances (``tapak issue --geser v2 --benih-riset``, no registry, no canary, c = 3,
eps = 1e-6; every manifest is checked to record ``shift_scheme: geser-v2``): nota_dinas
N = 20 (7801) and N = 100 (7802), surat_telegram N = 20 (7803) and N = 100 (7804); for the
honest part also four more with N = 20: nota_dinas 7805 and 7807, surat_telegram 7806 and 7808.
Seeds used before (7101 to 7241, 7301, 7302, 7401, 7601 to 7651, 2026) are not reused.

Part ``jujur`` (honest behaviour of the erasure check; the shift strengths now come from the
geser-v2 row decoder, ``ch_shift.joint_strengths``): copies 1 to 10 of all eight issuances
through ``pdf``, ``layar``, ``foto`` and ``cetak`` exactly as ``ukur.evidence`` (page 1 for
the screen channels; pages 1 and 2 printed on the simulated laser printer, photographed and
traced together), seed [7841, issuance, copy, channel]; and the unmarked master of each
through ``pdf``, ``layar`` and ``foto`` (seed [7851, issuance, channel]). Each evidence is
traced as the first logged trace, single-stage and staged (``ukur.verdicts``).

Part ``serang`` (a slice of the held-out attack protocol of ``ukur.py``, on geser-v2): the four
issuances 7801 to 7804, coalitions of k = 2, 3 and 4 copies, 3 per issuance and k (seed
[7811, issuance, k]) from copies 1 to N, so 36 coalitions; the forgery starts from the
coalition's first copy, erase_fraction 1, a random member at disagreeing units (rule
``acak``); the coalition assumes geser-v2 (``tapak.collusion``: every word group is a data
unit, agreeing groups go back to their master position estimated row by row from the word
gaps, ``row_signs``). Configurations:

* ``jujur``: copy 1 itself (the paired honest control);
* ``semua/hapus``: agreeing background cells and shift units erased (``semua/acak`` of
  ``ukur.py``);
* ``geser/hapus``: only the agreeing shift units erased (``geser/acak`` of ``ukur.py``);
* ``semua/balik``: agreeing background cells negated and agreeing shift units mirrored about
  their master position (``balik.py``).

Channels ``pdf``, ``layar`` and ``foto`` for every configuration; ``cetak`` (pages 1 and 2)
for ``jujur``, ``semua/hapus`` and ``semua/balik`` (the default background does not reach the
paper, so ``geser/hapus`` equals ``semua/hapus`` there). Channel randomness seed [7821,
issuance, k, coalition, channel]; attack randomness seed [7831, issuance, k, coalition,
configuration]. Every evidence is traced as the first logged trace, single-stage and staged.

Part ``bench`` (honest, after ``make photos photos-cetak photos-ponsel photos-layar`` in this
checkout): every image of the README benchmark sets (one trace per image, the printed pages 1
and 2 of a copy also together), with the erasure check.

Part ``tipografi`` (deterministic, no seed): how many geser-v2 word-group signs ONE copy
reveals through its word gaps (``tapak.collusion.shift_units`` on that copy alone, scheme
geser-v2) and how many of them are right, over copies 1 to 20 of issuances 7801 and 7803.

Recorded per evidence (one JSON line): ``ukur.record`` (positions read, signed weight sums at
agreeing and disagreeing positions per channel, both verdicts, the erasure statistic for the
three strength choices), the shipped check (``balik.check``: z, flagged, positions), the
measured units per physical channel, and the attack plan's counts.

Analysis fixed now: (1) per configuration and channel: escapes (no coalition member named,
single-stage and staged), warnings (flagged by the shipped check), the share of agreeing marks
neutralized per channel (1 - signed weight sum at agreeing positions of the attacked evidence /
the same in the paired honest evidence, mean and range over the coalitions with a positive
honest sum), and every false accusation (anyone outside the coalition named at any stage;
zero required); (2) honest false alarms (z <= -3.0902) per channel, for the masters and in
total; the mean and spread of honest Z per issuance and channel, and the between-issuance
spread of those means after removing the within-issuance part (as ``balik.summary``);
(3) false alarms on the benchmark sets per medium; (4) the typography tally.

Usage (from the repository root; at most 3 worker processes, 1 BLAS thread each):

    python research/sepakat/geser2.py terbit
    python research/sepakat/geser2.py jujur --out research/sepakat/hasil/geser2_jujur.jsonl
    python research/sepakat/geser2.py serang --out research/sepakat/hasil/geser2_serang.jsonl
    python research/sepakat/geser2.py bench --out research/sepakat/hasil/geser2_bench.jsonl
    python research/sepakat/geser2.py tipografi --out research/sepakat/hasil/geser2_tipografi.jsonl
    python research/sepakat/geser2.py ringkas research/sepakat/hasil/geser2_*.jsonl
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

import balik  # noqa: E402
import ukur  # noqa: E402

SCHEME = "geser-v2"
ATTACK_ISSUANCES = [("nota_dinas", 20, 7801), ("nota_dinas", 100, 7802), ("surat_telegram", 20, 7803),
                    ("surat_telegram", 100, 7804)]
HONEST_ISSUANCES = ATTACK_ISSUANCES + [("nota_dinas", 20, 7805), ("surat_telegram", 20, 7806),
                                       ("nota_dinas", 20, 7807), ("surat_telegram", 20, 7808)]
SEEDS = {"koalisi": 7811, "kanal": 7821, "serangan": 7831, "jujur": 7841, "induk": 7851}
KS = (2, 3, 4)
COALITIONS = 3
COPIES = 10
CONFIGS = ("semua/hapus", "geser/hapus", "semua/balik")
SCOPE = {"semua": ("latar", "geser"), "geser": ("geser",)}
ATTACK_CHANNELS = ("pdf", "layar", "foto")
PRINT_CONFIGS = ("jujur", "semua/hapus", "semua/balik")
HONEST_CHANNELS = ("pdf", "layar", "foto", "cetak")
TYPOGRAPHY = (("nota_dinas", 20, 7801), ("surat_telegram", 20, 7803))
ERASURE_THRESHOLD = -3.0902
# The README benchmark sets as the Makefile writes them (default locations).
BENCH_DATA = ROOT / "out" / "photos"
BENCH_SETS = {"layar": ROOT / "samples" / "photos", "cetak": ROOT / "samples" / "photos-cetak",
              "ponsel": ROOT / "samples" / "photos-ponsel", "fotolayar": ROOT / "samples" / "photos-layar"}


def issue_all() -> None:
    """Issue every issuance of this protocol with geser-v2 (skips the ones already there)."""
    from tapak.marker.issue import IssueManifest

    for doc, n, seed in HONEST_ISSUANCES:
        folder = ukur.issuance_dir(doc, n, seed)
        if not list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            csv = ukur._recipients_csv(folder, n)
            cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
                   "issue", str(ROOT / "samples" / f"{doc}.pdf"), str(csv), "--no-registry", "--canary-domain", "",
                   "--workers", str(ukur.WORKERS), "--geser", "v2", "--benih-riset", str(seed)]
            subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
        path = next(folder.glob("data/dokumen/*/salinan/manifest.json"))
        scheme = IssueManifest.from_json(path.read_text(encoding="utf-8")).shift_scheme
        if scheme != SCHEME:
            raise SystemExit(f"{folder.name}: skema geser {scheme!r}, bukan {SCHEME}")
        print(f"{folder.name}: {SCHEME}", flush=True)


def _measured(obs) -> dict[str, int]:
    """Units with a strength per physical channel (what the erasure check reads)."""
    from tapak.marker.plan import PHYSICAL_CHANNEL

    out: dict[str, int] = {}
    for sb in obs:
        if sb.strengths is not None and len(sb.strengths):
            name = PHYSICAL_CHANNEL.get(sb.channel, sb.channel)
            out[name] = out.get(name, 0) + len(sb.strengths)
    return out


def _forge(ctx, pdfs: list[bytes], config: str, rng: np.random.Generator) -> tuple[bytes, dict]:
    from tapak.collusion import attack

    scope, how = config.split("/")
    data, view, plan = attack(ctx.master, pdfs, "acak", 1.0, SCOPE[scope], rng, neutralize=how, scheme=SCHEME)
    if view.scheme != SCHEME:
        raise RuntimeError("koalisi tidak memakai skema geser-v2")
    return data, plan.counts


def attack_job(job: tuple) -> list[dict]:
    """Every configuration and the honest control of one coalition through one channel group."""
    iss, (doc, n, seed), k, ci, members, channels = job
    ctx, _ = ukur.context(doc, n, seed)
    pdfs = [ukur.copy_pdf(doc, n, seed, s) for s in members]
    x = ctx.codewords[[s - 1 for s in members]].astype(np.int64)
    agree = np.all(x == x[:1], axis=0)
    forged: dict[str, tuple[bytes, dict]] = {"jujur": (pdfs[0], {})}
    for cfg_i, name in enumerate(CONFIGS):
        if "cetak" in channels and name not in PRINT_CONFIGS:
            continue
        forged[name] = _forge(ctx, pdfs, name, np.random.default_rng([SEEDS["serangan"], iss, k, ci, cfg_i]))
    rows = []
    for channel in channels:
        ch_i = HONEST_CHANNELS.index(channel)
        for name, (data, counts) in forged.items():
            t0 = time.perf_counter()
            rng = np.random.default_rng([SEEDS["kanal"], iss, k, ci, ch_i])
            obs, _ = ukur.evidence(ctx, data, channel, rng, ci)
            row = {"bagian": "serangan", "dok": doc, "N": n, "benih": seed, "k": k, "koalisi_ke": ci,
                   "koalisi": members, "serangan": name, "kanal": channel, "rencana": counts}
            row.update(ukur.record(obs, ctx, members, x[0], agree))
            row["periksa"] = balik.check(obs, ctx)
            row["unit"] = _measured(obs)
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
        row["periksa"] = balik.check(obs, ctx)
        row["unit"] = _measured(obs)
        row["detik"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
    return rows


_BENCH: dict[str, object] = {}


def bench_job(job: tuple) -> list[dict]:
    """One image (or the printed pages 1 and 2 of a copy) of the README benchmark sets."""
    from tapak.decoder.trace import collect_file, load_context
    from tapak.keys import research_code_secret
    from tapak.marker.issue import IssueManifest

    medium, folder, files, seq = job
    if "ctx" not in _BENCH:
        issued = next((BENCH_DATA / "data" / "dokumen").glob("*/salinan"))
        manifest = IssueManifest.from_json((issued / "manifest.json").read_text(encoding="utf-8"))
        if manifest.shift_scheme != SCHEME:
            raise RuntimeError("penerbitan benchmark bukan geser-v2")
        _BENCH["ctx"] = load_context((ROOT / "samples" / "nota_dinas.pdf").read_bytes(), manifest,
                                     research_code_secret(2026))
    ctx = _BENCH["ctx"]
    obs = []
    for f in files:
        o, _ = collect_file(f, (Path(folder) / f).read_bytes(), ctx)
        obs += o
    x = ctx.codewords[seq - 1].astype(np.int64)
    row = {"bagian": "bench", "medium": medium, "berkas": files, "salinan": seq}
    row.update(ukur.record(obs, ctx, [seq], x, np.ones(x.size, dtype=bool)))
    row["periksa"] = balik.check(obs, ctx)
    row["unit"] = _measured(obs)
    return [row]


def attack_jobs() -> list[tuple]:
    """The coalitions of every attack issuance and size, from the fixed seed; digital and print."""
    jobs = []
    for iss, spec in enumerate(ATTACK_ISSUANCES):
        n = spec[1]
        for k in KS:
            rng = np.random.default_rng([SEEDS["koalisi"], iss, k])
            for ci in range(COALITIONS):
                members = sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
                jobs.append((iss, spec, k, ci, members, ATTACK_CHANNELS))
                jobs.append((iss, spec, k, ci, members, ("cetak",)))
    return jobs


def honest_jobs() -> list[tuple]:
    """Copies 1 to COPIES and the master (0) of every honest issuance."""
    return [(iss, spec, seq) for iss, spec in enumerate(HONEST_ISSUANCES) for seq in range(0, COPIES + 1)]


def bench_jobs() -> list[tuple]:
    """Every image of the benchmark sets, and every printed copy's pages 1 and 2 together."""
    jobs = []
    for medium, folder in BENCH_SETS.items():
        truth = folder / "truth.json"
        if not truth.exists():
            raise SystemExit(f"{folder} belum ada: jalankan make photos photos-cetak photos-ponsel photos-layar")
        items = json.loads(truth.read_text(encoding="utf-8"))["items"]
        jobs += [(medium, str(folder), [it["file"]], it["seq"]) for it in items]
        if medium == "cetak":
            pairs: dict[tuple, dict] = {}
            for it in items:
                index = it["file"].rsplit("_", 1)[-1].split(".")[0]
                pairs.setdefault((it["seq"], it["angle"], index), {})[it["page"]] = it["file"]
            jobs += [("cetak2", str(folder), [d[p] for p in sorted(d)], key[0]) for key, d in pairs.items()
                     if len(d) == 2]
    return jobs


def typography_rows() -> list[dict]:
    """Part ``tipografi``: signs one geser-v2 copy reveals through its own word gaps."""
    from tapak.collusion import copy_displacements, shift_units
    from tapak.marker.layout import extract_layout

    rows = []
    for doc, n, seed in TYPOGRAPHY:
        ctx, _ = ukur.context(doc, n, seed)
        tally = {"kata": [0, 0, 0], "baris": [0, 0, 0]}  # units, decided, right
        for seq in range(1, n + 1):
            pdf = ukur.copy_pdf(doc, n, seed, seq)
            units, _ = shift_units([extract_layout(pdf)], scheme=SCHEME)
            disp = copy_displacements(pdf, ctx.master)
            for u in units:
                row = ctx.master.layout.pages[u.ref[0]].rows[u.ref[1]]
                if u.kind == "kata":
                    true = float(np.mean([disp[row.words[i].id][0] for i in row.groups[u.ref[2]].word_indices]))
                else:
                    true = float(np.median([disp[w.id][1] for w in row.words]))
                t = tally[u.kind]
                t[0] += 1
                if u.typographic is not None:
                    t[1] += 1
                    t[2] += int(abs(true - u.typographic) < 1e-3)
        rows.append({"bagian": "tipografi", "dok": doc, "N": n, "benih": seed, "salinan": n,
                     "kata": tally["kata"], "baris": tally["baris"]})
    return rows


# --- summary -------------------------------------------------------------------------------


def _escaped(row: dict, stage: str) -> bool:
    return row["putusan"][stage]["anggota"] == 0


def _neutralized(rows: list[dict]) -> dict[tuple, dict[str, list[float]]]:
    """Per (configuration, channel): 1 - attacked / honest signed weight at agreeing positions."""
    honest = {(r["benih"], r["k"], r["koalisi_ke"], r["kanal"]): r for r in rows
              if r["bagian"] == "serangan" and r["serangan"] == "jujur"}
    out: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["bagian"] != "serangan" or r["serangan"] == "jujur":
            continue
        h = honest.get((r["benih"], r["k"], r["koalisi_ke"], r["kanal"]))
        for ch in ("shift", "background"):
            base = h["sama"][ch][1] if h else 0.0
            if base > 0:
                out[(r["serangan"], r["kanal"])][ch].append(1.0 - r["sama"][ch][1] / base)
    return out


def _z_spread(rs: list[dict]) -> str:
    """Alarms, spread of Z, per-issuance means and the within / between-issuance spread."""
    zs = [r["periksa"]["z"] for r in rs if r["periksa"]["z"] is not None]
    if not zs:
        return "tanpa Z"
    flagged = sum(r["periksa"]["ditandai"] for r in rs)
    groups: dict[int, list[float]] = defaultdict(list)
    for r in rs:
        if r["periksa"]["z"] is not None:
            groups[r.get("benih", 0)].append(r["periksa"]["z"])
    means = [float(np.mean(v)) for v in groups.values()]
    inner = [np.var(v, ddof=1) for v in groups.values() if len(v) > 1]
    within = float(np.mean(inner)) if inner else float("nan")
    size = float(np.mean([len(v) for v in groups.values()]))
    between = (max(0.0, float(np.var(means, ddof=1)) - within / size)
               if len(means) > 1 and math.isfinite(within) else float("nan"))
    sd = np.std(zs, ddof=1) if len(zs) > 1 else float("nan")
    return (f"ditandai {flagged} dari {len(zs)}; rata-rata Z {np.mean(zs):+.2f}, sd {sd:.2f}, min {min(zs):.2f}; "
            f"rata-rata per penerbitan {min(means):+.2f} sampai {max(means):+.2f}; sd di dalam "
            f"{math.sqrt(within) if math.isfinite(within) else float('nan'):.2f}; sd antarpenerbitan "
            f"{math.sqrt(between) if math.isfinite(between) else float('nan'):.2f}")


def summary(paths: list[str]) -> int:
    """Tables of the analysis fixed in the module docstring."""
    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    traced = [r for r in rows if "putusan" in r]
    wrong = [(r.get("serangan", r["bagian"]), r.get("kanal", r.get("medium")), r["putusan"][s]["salah"])
             for r in traced for s in ("satu", "bertahap") if r["putusan"][s]["salah"]]
    print(f"tuduhan salah: {len(wrong)} dari {2 * len(traced)} pelacakan {wrong[:5]}")
    attack = [r for r in rows if r["bagian"] == "serangan"]
    if attack:
        neut = _neutralized(rows)
        print("\nserangan: lolos satu tahap / bertahap / ditandai dari n; dinetralkan geser, latar (rata-rata, rentang)")
        cells: dict[tuple, list[dict]] = defaultdict(list)
        for r in attack:
            cells[(r["serangan"], r["kanal"])].append(r)
        for (cfg, ch), rs in sorted(cells.items()):
            parts = []
            for name in ("shift", "background"):
                v = neut.get((cfg, ch), {}).get(name, [])
                parts.append(f"{np.mean(v):.2f} ({min(v):.2f}..{max(v):.2f})" if v else "-")
            zs = [r["periksa"]["z"] for r in rs if r["periksa"]["z"] is not None]
            print(f"  {cfg:12s} {ch:6s} lolos {sum(_escaped(r, 'satu') for r in rs):3d} / "
                  f"{sum(_escaped(r, 'bertahap') for r in rs):3d} / ditandai "
                  f"{sum(r['periksa']['ditandai'] for r in rs):3d} dari {len(rs)}; z median "
                  f"{np.median(zs) if zs else float('nan'):6.2f}; dinetralkan geser {parts[0]}, latar {parts[1]}")
        plans = [r["rencana"] for r in attack if r["serangan"] == "semua/hapus" and r["kanal"] == "pdf"]
        if plans:
            same = sum(p["unit_sama"] for p in plans)
            print(f"  semua/hapus, unit geser sama yang dinetralkan menurut rencana: "
                  f"{sum(p['unit_sama_dinetralkan'] for p in plans)} dari {same} "
                  f"({sum(p['unit_sama_tanpa_taksiran'] for p in plans)} tanpa taksiran)")
    honest = [r for r in rows if r["bagian"] == "jujur"]
    if honest:
        print("\njujur per kanal:")
        by_ch: dict[str, list[dict]] = defaultdict(list)
        for r in honest:
            by_ch[r["kanal"]].append(r)
        for ch, rs in sorted(by_ch.items()):
            named = sum(r["putusan"]["satu"]["anggota"] > 0 for r in rs)
            print(f"  {ch:6s} disebut benar {named} dari {len(rs)}; {_z_spread(rs)}")
        print(f"  semua: {_z_spread(honest)}")
    master = [r for r in rows if r["bagian"] == "induk"]
    if master:
        zs = [r["periksa"]["z"] for r in master]
        print(f"\ninduk tanpa tanda: ditandai {sum(r['periksa']['ditandai'] for r in master)} dari {len(master)}; "
              f"z {min(z for z in zs if z is not None):.2f} sampai {max(z for z in zs if z is not None):.2f}; "
              f"disebut {sum(bool(r['putusan']['satu']['dituduh']) for r in master)}")
    bench = [r for r in rows if r["bagian"] == "bench"]
    if bench:
        print("\nbenchmark README per medium:")
        by_m: dict[str, list[dict]] = defaultdict(list)
        for r in bench:
            by_m[r["medium"]].append(r)
        for m, rs in sorted(by_m.items()):
            zs = [r["periksa"]["z"] for r in rs if r["periksa"]["z"] is not None]
            low = min(zs) if zs else float("nan")
            print(f"  {m:9s} ditandai {sum(r['periksa']['ditandai'] for r in rs)} dari {len(rs)} "
                  f"(diperiksa {len(zs)}); z terendah {low:.2f}")
    for r in rows:
        if r["bagian"] == "tipografi":
            k, b = r["kata"], r["baris"]
            print(f"\ntipografi {r['dok']} {r['benih']} ({r['salinan']} salinan): kelompok kata {k[1]} dari {k[0]} "
                  f"diputuskan, {k[2]} benar; baris {b[1]} dari {b[0]}, {b[2]} benar")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "jujur", "serang", "bench", "tipografi", "ringkas"])
    ap.add_argument("paths", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.bagian == "terbit":
        issue_all()
    elif args.bagian == "jujur":
        ukur._run(honest_job, honest_jobs(), args.out)
    elif args.bagian == "serang":
        ukur._run(attack_job, attack_jobs(), args.out)
    elif args.bagian == "bench":
        ukur._run(bench_job, bench_jobs(), args.out)
    elif args.bagian == "tipografi":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as fh:
            for row in typography_rows():
                fh.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)
    else:
        return summary(args.paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
