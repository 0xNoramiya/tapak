"""Agreement-targeted erasure on real channels, and the decoder's erasure check (research).

The protocol below, every seed and the decision rules were fixed and committed before any
held-out run. Development seeds ("dev") serve every choice; held-out seeds ("uji") are run
once at the end. Both sample documents are fictional.

Issuances (``tapak issue --benih-riset``, no registry, no canary, c = 3, eps = 1e-6):

* dev: nota_dinas N = 20 (benih 7101), surat_telegram N = 20 (benih 7102);
* uji: nota_dinas N = 20 (7201), nota_dinas N = 100 (7202), surat_telegram N = 20 (7203),
  surat_telegram N = 100 (7204).

N = 20 uses ``samples/recipients.csv``; N = 100 a list of 100 fictitious recipients written
by this script (``penerima100.csv`` in the issuance folder).

Attack (``tapak.collusion``): coalitions of k = 2, 3 and 4 distinct copies drawn from copies
1 to N (``coalitions`` per issuance and k: dev 3, uji 5; seed [koalisi, issuance, k]). The
forgery starts from the coalition's first copy ("copy 1"). Configurations, each with
erase_fraction 1 (every agreeing unit the coalition can neutralize is neutralized):

* ``semua/acak``: agreeing background cells and shift units neutralized; at disagreeing units
  a random member per unit (per cell for the background);
* ``latar/acak``, ``geser/acak``: only the background, or only the shifts, neutralized;
* ``semua/salin``: as semua, copy 1 kept at disagreeing units;
* ``semua/rata``: as semua, the average of the copies at disagreeing units (with two copies
  this erases them too: nothing marked is left except agreeing shift units without a
  typographic estimate).

Channels for every configuration and for copy 1 itself (``jujur``, the paired honest
control, same channel randomness):

* ``pdf``: the forged PDF traced as a forwarded file;
* ``layar``: a screenshot of page 1 (``tapak.photos.screenshot_jpeg``, render 200 dpi,
  long side 1600, JPEG twice);
* ``foto``: a phone photo of page 1 shown on screen (``photo_jpeg``, view angle 0, 10, 20,
  30 degrees by coalition index, long side 1600);
* ``cetak``: pages 1 and 2 printed on the simulated laser printer and photographed
  (``printed_photo_jpeg``, angle 10 or 30 by coalition index, 1600 px), traced together;
  only for jujur, semua/acak and semua/salin (the default background does not survive print,
  so the other configurations equal these on paper).

Channel randomness: seed [kanal, issuance, k, coalition, channel]; attack randomness: seed
[serangan, issuance, k, coalition, configuration]. Seeds: dev koalisi 7111, kanal 7121,
serangan 7131, jujur 7141; uji 7211, 7221, 7231, 7241.

Every evidence is traced as the first logged trace of the document (eps share
eps * 6 / pi^2), once single-stage and once with the stage policy ``bertahap-v1``. Recorded
per evidence (one JSON line): positions read per channel, whether the background pattern was
found, at positions where all k coalition codewords agree and where they disagree the number
read and the sum of w * (+1 if the read bit equals the coalition's (copy 1's) bit, else -1)
per channel, the verdict of both accusations (copies named at every stage, coalition members
among them, anyone else), the largest member and non-member score over Z, and the erasure
statistic for three strength choices (``gabung``: every measure; ``mutlak``: background
|despread mean| and shifts; ``energi``: background cell energy and shifts). A wrong
accusation is anyone outside the coalition named at any stage; zero is required and every
one is reported. "Neutralized" agreeing positions per channel = 1 - (signed weight sum at
agreeing positions in the attacked evidence) / (the same in the paired honest evidence).

Honest calibration of the erasure check (``jujur``): copies 1 to 20 of both dev issuances
through pdf, layar, foto and cetak (seed [jujur, issuance, copy, channel]), plus the dev
honest controls above. Rules fixed now: (1) the strength choice is the one with the highest
detection rate over the dev targeted attacks (semua/acak, latar/acak, geser/acak,
semua/salin; every channel), "gabung" on a tie; (2) the alarm threshold is
-3.0902 * max(1, s) with s the sample standard deviation of Z for that choice over all dev
honest evidence, rounded up to two decimals (3.0902 is the standard normal quantile for the
alarm rate 1e-3, fixed before measuring); the held-out false alarms are counted on the uji
honest controls and on the README benchmark sets if present (``make photos``,
``make photos-cetak``, rebuilt in ``out/sepakat/bench``).

Defense decision rule (part 3, ``samaran.py``), fixed now: the masking scheme becomes the
default for new issuances only if (a) on every benchmark set (README screen photos and
screenshots; printed photos, one page and two pages) its correct count is within 1 of
today's, (b) it passes visibility (S-CIELAB at 35 cm, mean <= 0.75 and 95th percentile
<= 2.0 on screen and on the simulated laser print, the values of a plain gray raster one
level deep; and the 0.10 mm bound between any two copies), and (c) it cuts the escape rate of
semua/acak on the uji pdf, layar and foto channels by at least half and by at least 25
percentage points. If it meets (b) and (c) but not (a) it is opt-in; otherwise it is dropped.
Old manifests decode exactly as today in every case.

Decisions taken on the development seeds, recorded before the held-out run:

* the background energy strength leaves out cells whose saturated share is 0.5 or more
  (``ch_background.ENERGY_MAX_SHARE``; chosen on one dev photo with 65 % clipped paper, where
  it raised the rank correlation with q of the attacked photo from -0.087 to -0.127);
* strength choice: ``gabung`` (dev detection over the targeted attacks 0.619 for gabung and
  for energi, 0.579 for mutlak; the tie goes to gabung by the rule above);
* calibration: s = 0.996 over 232 dev honest evidence, so the factor is 1 and the alarm
  threshold stays -3.0902 (``erasure.ERASURE_CALIBRATION`` = 1.0);
* observed on dev, not a choice: honest strengths share part of their pattern across copies
  of one document (rank correlation of the position scores between two honest copies 0.22
  for pdf, 0.12 for layar, nota dinas), so for one document Z is centred on an offset of a
  few tenths rather than on 0; the alarm rate 1e-3 holds on average over the code draw.

Part ``tipografi`` was added after the protocol commit; it is deterministic (no seed).

Usage (from the repository root; at most 3 worker processes, 1 BLAS thread each):

    python research/sepakat/ukur.py terbit dev            # or uji
    python research/sepakat/ukur.py serang dev --out research/sepakat/hasil/serang_dev.jsonl
    python research/sepakat/ukur.py jujur dev --out research/sepakat/hasil/jujur_dev.jsonl
    python research/sepakat/ukur.py serang uji --out research/sepakat/hasil/serang_uji.jsonl
    python research/sepakat/ukur.py bench --out research/sepakat/hasil/bench.jsonl
    python research/sepakat/ukur.py tipografi uji --out research/sepakat/hasil/tipografi.jsonl
    python research/sepakat/ukur.py ringkas research/sepakat/hasil/*.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

OUT = ROOT / "out" / "sepakat"
# The README benchmark rebuilt here: make photos photos-cetak bench PHOTO_DATA=out/sepakat/bench
# PHOTO_SET=out/sepakat/bench/photos PHOTO_SET_CETAK=out/sepakat/bench/photos-cetak (benih riset 2026).
BENCH = OUT / "bench"
WORKERS = 3
EPS = 1e-6
C = 3
KS = (2, 3, 4)
ISSUANCES = {
    "dev": [("nota_dinas", 20, 7101), ("surat_telegram", 20, 7102)],
    "uji": [("nota_dinas", 20, 7201), ("nota_dinas", 100, 7202), ("surat_telegram", 20, 7203),
            ("surat_telegram", 100, 7204)],
}
SEEDS = {
    "dev": {"koalisi": 7111, "kanal": 7121, "serangan": 7131, "jujur": 7141},
    "uji": {"koalisi": 7211, "kanal": 7221, "serangan": 7231, "jujur": 7241},
}
COALITIONS = {"dev": 3, "uji": 5}
CONFIGS = [("semua", "acak"), ("latar", "acak"), ("geser", "acak"), ("semua", "salin"), ("semua", "rata")]
ATTACK_CHANNELS = {"semua": ("latar", "geser"), "latar": ("latar",), "geser": ("geser",)}
CHANNELS = ("pdf", "layar", "foto", "cetak")
PRINT_CONFIGS = {"jujur", "semua/acak", "semua/salin"}
TARGETED = ("semua/acak", "latar/acak", "geser/acak", "semua/salin")
PHOTO_ANGLES = (0.0, 10.0, 20.0, 30.0)
PRINT_ANGLES = (10.0, 30.0)
STRENGTH_CHOICES = ("gabung", "mutlak", "energi")
PROTOCOL = {
    "eps": EPS, "c": C, "k": list(KS), "issuances": ISSUANCES, "seeds": SEEDS, "coalitions": COALITIONS,
    "configs": ["/".join(c) for c in CONFIGS], "erase_fraction": 1.0, "channels": list(CHANNELS),
    "print_configs": sorted(PRINT_CONFIGS), "photo_angles": PHOTO_ANGLES, "print_angles": PRINT_ANGLES,
    "long_side": 1600, "render_dpi": 200, "spending": "pelacakan tercatat ke-1; satu tahap dan bertahap-v1",
    "alarm_rate": 1e-3, "z_quantile": 3.0902,
}


# --- issuance ------------------------------------------------------------------------------


def issuance_dir(doc: str, n: int, seed: int) -> Path:
    """Work folder of one research issuance."""
    return OUT / f"{doc}_{n}_{seed}"


def _recipients_csv(folder: Path, n: int) -> Path:
    if n == 20:
        return ROOT / "samples" / "recipients.csv"
    path = folder / "penerima100.csv"
    lines = ["recipient_id,nama,jabatan,satuan"]
    lines += [f"R{i:03d},Penerima Fiktif {i:03d},Jabatan Contoh,Satuan Uji" for i in range(1, n + 1)]
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def issue_all(which: str) -> None:
    """Issue every research issuance of a set (skips the ones already there)."""
    for doc, n, seed in ISSUANCES[which]:
        folder = issuance_dir(doc, n, seed)
        if list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            print(f"{folder.name}: sudah ada", flush=True)
            continue
        csv = _recipients_csv(folder, n)
        cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
               "issue", str(ROOT / "samples" / f"{doc}.pdf"), str(csv), "--no-registry", "--canary-domain", "",
               "--workers", str(WORKERS), "--benih-riset", str(seed)]
        subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})


# --- worker side ---------------------------------------------------------------------------

_CTX: dict[tuple, object] = {}


def _init() -> None:
    from tapak.decoder import rectify

    rectify._EXACT_CACHE = rectify._ByteBudgetCache(150_000_000)  # three workers on a shared machine


def context(doc: str, n: int, seed: int):
    """(trace context, salinan folder) of an issuance, cached per process."""
    key = (doc, n, seed)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import research_code_secret
        from tapak.marker.issue import IssueManifest

        folder = next(issuance_dir(doc, n, seed).glob("data/dokumen/*/salinan"))
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        ctx = load_context((ROOT / "samples" / f"{doc}.pdf").read_bytes(), manifest, research_code_secret(seed))
        _CTX[key] = (ctx, folder)
    return _CTX[key]


def copy_pdf(doc: str, n: int, seed: int, seq: int) -> bytes:
    """Bytes of copy ``seq`` (1-based) of an issuance."""
    ctx, folder = context(doc, n, seed)
    return (folder / ctx.manifest.copies[seq - 1].file).read_bytes()


def coalitions(which: str, iss: int, n: int, k: int) -> list[list[int]]:
    """The coalitions (copy numbers) of an issuance and size, from the fixed seed."""
    rng = np.random.default_rng([SEEDS[which]["koalisi"], iss, k])
    return [sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
            for _ in range(COALITIONS[which])]


def evidence(ctx, pdf: bytes, channel: str, rng: np.random.Generator, index: int):
    """(observations, notes) of one evidence made from ``pdf`` through ``channel``."""
    from tapak.decoder.trace import collect_file
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, PrintParams, ScreenshotParams, photo_jpeg, printed_photo_jpeg, screenshot_jpeg

    if channel == "pdf":
        return collect_file("bukti.pdf", pdf, ctx)
    if channel == "cetak":
        obs, notes = [], []
        angle = PRINT_ANGLES[index % len(PRINT_ANGLES)]
        for page in range(min(2, len(ctx.master.layout.pages))):
            data, _ = printed_photo_jpeg(pdf, page, rng, PrintParams(), PhotoParams(angle_deg=angle, long_side=1600))
            o, n = collect_file(f"cetak_h{page + 1}.jpg", data, ctx)
            obs += o
            notes += n
        return obs, notes
    page = render_pages(pdf, 200, [0])[0]
    if channel == "layar":
        data, _ = screenshot_jpeg(page, rng, ScreenshotParams(render_dpi=200.0, long_side=1600))
    elif channel == "foto":
        data, _ = photo_jpeg(page, rng, PhotoParams(angle_deg=PHOTO_ANGLES[index % len(PHOTO_ANGLES)], long_side=1600))
    else:
        raise ValueError(channel)
    return collect_file("bukti.jpg", data, ctx)


def _signed(obs, channel: str, m: int, x: np.ndarray, sel: np.ndarray) -> list[float]:
    """[positions read, sum of w * (+1 right / -1 wrong)] of one channel over positions ``sel``."""
    llr = np.zeros(m)
    for sb in obs:
        if sb.channel == channel and len(sb):
            np.add.at(llr, sb.positions, sb.llr)
    read = sel & (llr != 0)
    w = np.tanh(np.abs(llr) / 2.0)
    sign = np.where((llr > 0) == (x == 1), 1.0, -1.0)
    return [int(read.sum()), round(float(np.sum((w * sign)[read])), 3)]


def strength_variants(obs, p: np.ndarray) -> dict[str, float | None]:
    """The erasure statistic for the three strength choices (``STRENGTH_CHOICES``)."""
    from dataclasses import replace

    from tapak.decoder.erasure import ERASURE_MIN_POSITIONS, agreement_score, erasure_z, position_scores
    from tapak.decoder.softbits import Strengths

    out: dict[str, float | None] = {}
    for choice in STRENGTH_CHOICES:
        sliced = []
        for sb in obs:
            st = sb.strengths
            if st is not None and sb.channel == "background" and choice != "gabung":
                col = 0 if choice == "mutlak" else 1
                st = Strengths(st.positions, st.values[:, col])
            sliced.append(replace(sb, strengths=st))
        pos, scores, _ = position_scores(sliced, p.size)
        out[choice] = (round(erasure_z(scores, agreement_score(p)[pos]), 3)
                       if pos.size >= ERASURE_MIN_POSITIONS else None)
    out["n"] = int(pos.size)
    return out


def verdicts(obs, ctx, members: set[int]) -> dict[str, dict]:
    """Single-stage and staged accusation of one evidence (first logged trace)."""
    from tapak.decoder.trace import run_trace
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    out = {}
    for name, policy in (("satu", None), ("bertahap", DEFAULT_STAGE_POLICY)):
        res = run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, policy))
        z = res.threshold.threshold
        named = sorted(res.named_seqs)
        stage1 = sorted(c.copy.seq for c in res.accused)
        mem = [c.score for c in res.candidates if c.copy.seq in members]
        oth = [c.score for c in res.candidates if c.copy.seq not in members]
        ratio = (lambda v: round(max(v) / z, 4) if v and math.isfinite(z) and z > 0 else None)
        out[name] = {"dituduh": named, "tahap1": stage1, "anggota": len([s for s in named if s in members]),
                     "salah": [s for s in named if s not in members], "Z": round(z, 2) if math.isfinite(z) else None,
                     "terbaca": res.threshold.n_observed, "efektif": round(res.threshold.effective_positions, 1),
                     "skor_anggota": ratio(mem), "skor_lain": ratio(oth),
                     "tahap": [[st.stage, sorted(c.copy.seq for c in st.accused)] for st in res.stages]}
    return out


def record(obs, ctx, members: list[int], x_ref: np.ndarray, agree: np.ndarray) -> dict:
    """Everything recorded for one evidence (see the module docstring)."""
    m = ctx.params.length
    row = {
        "geser": sum(len(sb) for sb in obs if sb.channel == "shift"),
        "latar": sum(len(sb) for sb in obs if sb.channel == "background"),
        "pola_latar": [sb.meta.get("pattern_found") for sb in obs if sb.channel == "background"],
        "sama": {ch: _signed(obs, ch, m, x_ref, agree) for ch in ("shift", "background")},
        "beda": {ch: _signed(obs, ch, m, x_ref, ~agree) for ch in ("shift", "background")},
        "putusan": verdicts(obs, ctx, set(members)),
        "hapus": strength_variants(obs, ctx.p),
    }
    return row


def attack_job(job: tuple) -> list[dict]:
    """All configurations and the honest control of one coalition through one channel group."""
    from tapak.collusion import attack

    which, iss, (doc, n, seed), k, ci, members, channels = job
    ctx, _ = context(doc, n, seed)
    pdfs = [copy_pdf(doc, n, seed, s) for s in members]
    x = ctx.codewords[[s - 1 for s in members]].astype(np.int64)
    agree = np.all(x == x[:1], axis=0)
    forged: dict[str, tuple[bytes, dict]] = {"jujur": (pdfs[0], {})}
    for cfg_i, (chans, rule) in enumerate(CONFIGS):
        name = f"{chans}/{rule}"
        if not any(ch != "cetak" or name in PRINT_CONFIGS for ch in channels):
            continue
        rng = np.random.default_rng([SEEDS[which]["serangan"], iss, k, ci, cfg_i])
        data, _, plan = attack(ctx.master, pdfs, rule, 1.0, ATTACK_CHANNELS[chans], rng)
        forged[name] = (data, plan.counts)
    rows = []
    for channel in channels:
        ch_i = CHANNELS.index(channel)
        for name, (data, counts) in forged.items():
            if channel == "cetak" and name not in PRINT_CONFIGS:
                continue
            t0 = time.perf_counter()
            rng = np.random.default_rng([SEEDS[which]["kanal"], iss, k, ci, ch_i])
            obs, _ = evidence(ctx, data, channel, rng, ci)
            row = {"bagian": "serangan", "set": which, "dok": doc, "N": n, "benih": seed, "k": k, "koalisi_ke": ci,
                   "koalisi": members, "serangan": name, "kanal": channel, "rencana": counts}
            row.update(record(obs, ctx, members, x[0], agree))
            row["detik"] = round(time.perf_counter() - t0, 1)
            rows.append(row)
    return rows


def honest_job(job: tuple) -> list[dict]:
    """One honest copy through every channel (calibration of the erasure check)."""
    which, iss, (doc, n, seed), seq = job
    ctx, _ = context(doc, n, seed)
    pdf = copy_pdf(doc, n, seed, seq)
    x = ctx.codewords[seq - 1].astype(np.int64)
    agree = np.ones(x.size, dtype=bool)
    rows = []
    for ch_i, channel in enumerate(CHANNELS):
        t0 = time.perf_counter()
        rng = np.random.default_rng([SEEDS[which]["jujur"], iss, seq, ch_i])
        obs, _ = evidence(ctx, pdf, channel, rng, seq)
        row = {"bagian": "jujur", "set": which, "dok": doc, "N": n, "benih": seed, "salinan": seq, "kanal": channel}
        row.update(record(obs, ctx, [seq], x, agree))
        row["detik"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
    return rows


def bench_job(job: tuple) -> list[dict]:
    """One image (or a print pair) of the README benchmark sets, traced with the erasure check."""
    from tapak.decoder.trace import collect_file
    from tapak.keys import research_code_secret

    folder, files, seq, kind = job
    key = ("bench",)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

        issued = next((BENCH / "data" / "dokumen").glob("*/salinan"))
        manifest = IssueManifest.from_json((issued / "manifest.json").read_text(encoding="utf-8"))
        _CTX[key] = load_context((ROOT / "samples" / "nota_dinas.pdf").read_bytes(), manifest,
                                 research_code_secret(2026))
    ctx = _CTX[key]
    obs = []
    for f in files:
        o, _ = collect_file(f, (Path(folder) / f).read_bytes(), ctx)
        obs += o
    x = ctx.codewords[seq - 1].astype(np.int64)
    row = {"bagian": "bench", "berkas": files, "salinan": seq, "jenis": kind}
    row.update(record(obs, ctx, [seq], x, np.ones(x.size, dtype=bool)))
    return [row]


def typography_rows(which: str) -> list[dict]:
    """Part ``tipografi`` (added after the protocol commit; deterministic, no seed): how many
    shift bits ONE copy reveals through its own gaps (``tapak.collusion.shift_units`` on a
    single copy), and how many of those are right, per document over all copies of a set."""
    from tapak.collusion import copy_displacements, shift_units
    from tapak.marker.layout import extract_layout

    rows = []
    for doc, n, seed in ISSUANCES[which]:
        ctx, _ = context(doc, n, seed)
        tally = {"kata": [0, 0, 0], "baris": [0, 0, 0]}  # units, decided, right
        for seq in range(1, n + 1):
            pdf = copy_pdf(doc, n, seed, seq)
            units, _ = shift_units([extract_layout(pdf)])
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
        rows.append({"bagian": "tipografi", "set": which, "dok": doc, "N": n, "benih": seed, "salinan": n,
                     "kata": tally["kata"], "baris": tally["baris"]})
    return rows


def _run(fn, jobs: list, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    with out.open("a", encoding="utf-8") as fh, ProcessPoolExecutor(WORKERS, mp_context=ctx, initializer=_init) as pool:
        for rows in pool.map(fn, jobs):
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"{len(rows)} baris, {rows[0].get('dok', '')} {rows[0].get('kanal', '')}", flush=True)


def attack_jobs(which: str) -> list[tuple]:
    """Jobs of the attack grid, grouped by issuance (warm caches): digital channels and print."""
    jobs = []
    for iss, spec in enumerate(ISSUANCES[which]):
        doc, n, seed = spec
        for k in KS:
            for ci, members in enumerate(coalitions(which, iss, n, k)):
                jobs.append((which, iss, spec, k, ci, members, ("pdf", "layar", "foto")))
                jobs.append((which, iss, spec, k, ci, members, ("cetak",)))
    return jobs


def honest_jobs(which: str) -> list[tuple]:
    """Copies 1 to 20 of every issuance of the set."""
    return [(which, iss, spec, seq) for iss, spec in enumerate(ISSUANCES[which]) for seq in range(1, 21)]


def bench_jobs() -> list[tuple]:
    """Every screen image and every print pair of the README benchmark sets (if present)."""
    jobs = []
    for name in ("photos", "photos-cetak"):
        folder = BENCH / name
        if not (folder / "truth.json").exists():
            continue
        items = json.loads((folder / "truth.json").read_text(encoding="utf-8"))["items"]
        if name == "photos":
            jobs += [(str(folder), [it["file"]], it["seq"], it["kind"]) for it in items]
        else:
            pairs: dict[tuple, dict] = {}
            for it in items:
                index = it["file"].rsplit("_", 1)[-1].split(".")[0]
                pairs.setdefault((it["seq"], it["angle"], index), {})[it["page"]] = it["file"]
            jobs += [(str(folder), [d[p] for p in sorted(d)], key[0], "cetak") for key, d in pairs.items()]
    return jobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "serang", "jujur", "bench", "tipografi", "ringkas"])
    ap.add_argument("set", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.bagian == "terbit":
        issue_all(args.set[0])
    elif args.bagian == "serang":
        _run(attack_job, attack_jobs(args.set[0]), args.out)
    elif args.bagian == "jujur":
        _run(honest_job, honest_jobs(args.set[0]), args.out)
    elif args.bagian == "bench":
        _run(bench_job, bench_jobs(), args.out)
    elif args.bagian == "tipografi":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as fh:
            for row in typography_rows(args.set[0]):
                fh.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ringkas import main as summary

        return summary(args.set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
