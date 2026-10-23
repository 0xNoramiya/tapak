"""Reversal warning, combined erasure rule and a two-sided score rule (research).

Protocol, seeds, media, rates and analysis fixed and committed before the held-out run, which
runs once. Development seeds ("dev", part ``dev``) serve only to run the pipeline and check it
works; no rate, threshold or rule is chosen from them. Held-out seeds ("uji") are fresh: none
of them was used by ``research/sepakat``, ``research/kontradiksi`` or any other protocol, and dev
and uji are disjoint. Nothing here changes the default accusation rule, a threshold, eps or the
alpha spending; the new warnings never name anyone and never change a score, a threshold or a
verdict. Both sample documents and every recipient are fictional.

What is shipped (``tapak/decoder``), all fixed in code before any run of this protocol:

1. Erasure check, two statistics (``erasure.ERASURE_RULES``): Z under rule "pola" (background
   strengths only from pages where the background decoder found its pattern) and under "semua"
   (every background strength); warning when either is at or below -3.2905, the normal quantile
   of ERASURE_ALARM_RATE / 2 = 5e-4 (calibration factor 1), so the check keeps the rate 1e-3.
2. Reversal check (``reversal.py``), two code-blind statistics: z_pilot, the background
   decoder's pilot sums of every image page added into one Rademacher sum, and z_signs =
   A / sqrt(B) over the fused read, A = sum w (2p - 1)(2y - 1), B = sum w^2 (2p - 1)^2; warning
   "pola tanda terbalik" when either is at or below -REVERSAL_Z = -sqrt(2 ln(2 / 1e-3)) = -3.899
   (rate 1e-3 split 5e-4 each, sub-Gaussian bound exp(-t^2 / 2)).
3. One merged warning under the verdict for the three checks (``manipulation.py``): one primary
   sentence, the causes, the rate, nobody named; in the web page, the CLI, the JSON notes and
   the berita acara. The contradiction check is unchanged (rate 1e-3, tempering 0.3).

Research only, not shipped (``two_sided`` below): the two-sided score rule. Stage 1 of the
default rule names copy j when S_j >= Z(eps1). The two-sided rule splits eps1 between the two
tails: Z2 = Z(eps1 / 2) and copy j is named when S_j >= Z2 or S_j <= -Z2. For an innocent copy
the law of -S under the read y is the law of S under the read 1 - y (U(1 - y, x) = -U(y, x)),
and Z is computed for the worst leaked bit per position, so P(S <= -Z2) <= eps1 / 2 as well and
the false-accusation bound stays eps1 per copy (eps for the document). Later stages are not
changed and not run under the two-sided rule: it is compared at stage 1 only, against the
default stage 1 on the same read.

Issuances (``tapak issue --benih-riset SEED --no-registry --canary-domain ""``, c = 3,
eps = 1e-6; the scheme with ``--geser``, the print profile with ``--latar cetak``):

* dev: P1 nota_dinas N = 20 geser-v2 (9401), P2 surat_telegram N = 20 geser-v1 (9402);
* uji: V1 nota_dinas N = 20 v2 (9601), V2 nota_dinas N = 100 v2 (9602), V3 surat_telegram
  N = 20 v2 (9603), V4 surat_telegram N = 100 v2 (9604), V5 nota_dinas N = 20 v1 (9605), V6
  surat_telegram N = 20 v1 (9606), V7 nota_dinas N = 20 v2 with ``--latar cetak`` (9607), V8 the
  fictional scanned nota_dinas (``samplegen.scanned_sample``, 300 dpi) N = 20 v2 (9608).

Media, as in ``research/kontradiksi`` (its ``evidence``): ``pdf`` the file itself; ``layar`` a
screenshot; ``foto`` a basic phone photo (0, 10, 20 or 30 degrees by index); ``ponsel`` with the
phone ISP; ``monitor`` a phone photo of a simulated monitor; ``cetak1`` page 1 printed and
photographed; ``cetak2`` pages 1 and 2 printed, photographed and traced together. Every
evidence is traced as the first logged trace with the stage policy ``bertahap-v1``
(``run_trace``, which runs every check), except the README benchmark (part ``bench``), traced as
``make bench`` traces it (not logged, ``bertahap-v1``).

Attacks (``tapak.collusion``; members drawn from copies 1 to N; the forgery starts from the
first member; a random member per cell or unit where the copies differ). Honest strategies
obey the marking assumption (``erase_fraction`` 0): ``acak``, ``salin``, ``rata``, ``mayoritas``,
``minoritas``. Knowing coalitions, at the agreeing cells and units:

* ``hapus`` erased (fraction 1); ``balik`` reversed (fraction 1);
* ``balik60`` and ``balik80`` reversed with probability 0.6 and 0.8 per cell and per unit
  (partial reversal; the cells of one position are then partly reversed);
* ``adaptif`` reversed with the smallest fraction r on 0.05, 0.10, ..., 1.00 for which no
  member is named in the PDF trace (bisection with the real decoder and the code secret, as in
  ``research/kontradiksi``: stronger than any real coalition);
* ``acak-sama`` randomized (a random sign per cell, the own or the mirrored position per unit);
* ``buang`` the whole background flattened and the agreeing shift units reversed (the cheapest
  escape of ``research/kontradiksi``); ``buang-acak`` the background flattened and the agreeing
  shift units randomized (a candidate escape from the new statistics);
* ``balik-d4`` ``balik`` with Gaussian noise of 4 gray levels added to every page's background
  image of the PDF (the other cheap escape of ``research/kontradiksi``), PDF only;
* ``balik1`` one copy alone, every mark it can read reversed (the copy given twice);
  ``balik1-buang`` the same with the background flattened (only the shift units mirrored).

Parts.

* ``dev`` (dev, dry run only): P1 and P2, copies 1 to 4 through all seven media (channel seed
  [9411, issuance, copy, medium]), the master through ``pdf``, ``layar`` and ``foto`` (seed
  [9414, issuance, medium]), one coalition per issuance and k = 2, 3 (seed [9412, issuance, k])
  with ``jujur``, ``hapus``, ``balik``, ``balik60``, ``acak-sama``, ``buang`` and ``buang-acak``
  through ``pdf``, ``layar`` and ``foto`` and ``jujur``, ``hapus``, ``balik`` through ``cetak2``
  (channel seed [9413, issuance, k, medium], attack seed [9415, issuance, k, attack]).
* ``jujur`` (uji): V1 to V6, copies 1 to 5 and one coalition per k = 2, 3 and honest strategy
  (members seed [9612, issuance, k, strategy], attack seed [9614, issuance, k, strategy]) through
  all seven media (channel seed [9611, issuance, unit, medium], unit = copy or 100 + 10 k +
  strategy index); the master through ``pdf``, ``layar`` and ``foto`` (seed [9617, issuance,
  medium]); V7 copies 1 to 5 and the coalitions k = 2 ``acak`` and k = 3 ``mayoritas`` through
  ``pdf``, ``cetak1`` and ``cetak2``; V8 copies 1 to 3 through ``pdf``, ``foto`` and ``cetak2``.
* ``sadar`` (uji): V1 to V6, three coalitions per issuance and k = 2, 3 (seed [9622, issuance,
  k]); every attack above except ``balik-d4``, ``balik1`` and ``balik1-buang`` through ``pdf``,
  ``layar`` and ``foto``, ``balik-d4`` through ``pdf``, ``jujur``, ``hapus``, ``balik`` and
  ``adaptif`` through ``cetak2``, and ``balik1`` and ``balik1-buang`` of the first member of every
  k = 2 coalition through ``pdf``, ``layar`` and ``foto`` (channel seed [9623, issuance, k,
  coalition, medium], attack seed [9624, issuance, k, coalition, attack], noise seed [9625,
  issuance, k, coalition]).
* ``cetakprofil`` (uji): V7 (the background reaches the paper), three coalitions per k = 2, 3
  (seed [9632, k]); ``jujur``, ``hapus``, ``balik`` and, for k = 2, ``balik1`` through ``pdf``,
  ``cetak1`` and ``cetak2`` (channel seed [9633, k, coalition, medium], attack seed [9634, k,
  coalition, attack]).
* ``besar`` (uji): V1 to V4, one honest coalition per k = 4, 5, 6 and strategy ``acak``,
  ``mayoritas``, ``minoritas`` (members seed [9627, issuance, k, strategy], attack seed [9628,
  issuance, k, strategy]) through ``pdf`` and ``layar`` (channel seed [9629, issuance, k,
  strategy, medium]); coalitions larger than the bound of the reversal check covers.
* ``bench`` (honest): every image of the README benchmark sets, as ``make bench`` traces them
  (one trace per image, the printed pages 1 and 2 of a copy also together), from the photo sets
  that ``make bench-check`` writes (``--bench DIR``, its ``out/bench-check``).
* ``simetri`` (code level, no evidence): for the two-sided rule, innocent scores against reads
  from coalitions of 2 and 3 (``tapak.tardos.attacks``: random-mix, majority, minority, all-0 and
  erase) with 5 % flips, N = 20, c = 3, a short code
  (m = 300) and eps1 = 1e-2, 2,000 reads per strategy and size (seed [9640, k, strategy]):
  the share of innocent scores at or above Z(eps1) and at or below -Z(eps1), each to be at most
  eps1 (Chernoff bound, not tight).

Recorded per evidence (one JSON line): the default verdict (named at any stage, members among
them, anyone else, stage-1 named, Z, the largest member and non-member score over Z); the
two-sided rule at stage 1 (Z2, Z2 / Z, copies named by the upper and the lower tail, members
and others among them, default stage-1 names lost); the erasure check as shipped (z, z_all,
flagged) and each statistic at the old single threshold -3.0902; the reversal check (z_pilot,
pages, z_signs, positions, flagged) with the pilot z of every page and z_signs of the shift and
background channels alone (diagnostics); the contradiction check; which checks the merged
warning names; positions read per channel; the background tests per page; times.

A false accusation is anyone outside the coalition (or anyone at all, for an unmarked master)
named at any stage; zero is required, under the default rule and under the two-sided rule.

Analysis fixed now. (1) Honest false alarms per medium (parts ``jujur`` and ``bench``; ``besar``
on its own): the erasure check as shipped and each of its statistics at -3.2905, the reversal
check and each of its statistics, the contradiction check, and any warning; the lowest values.
(2) Erased evidence (``sadar`` ``hapus``) flagged per medium: as shipped, "pola" alone and
"semua" alone at -3.0902 (the two old rules), and each statistic at -3.2905. (3) Per attack
and medium (``sadar``, ``cetakprofil``): escapes (no member named), reversal warnings (pilot,
signs, either), erasure warnings, contradiction warnings, any warning, escapes without any
warning, false accusations; the adaptive fraction r. (4) Two-sided rule: per attack and medium,
members named by the default (any stage, stage 1) and by the two-sided rule (upper, lower
tail), false accusations under it; on honest evidence (``jujur``, ``besar``, ``bench``) the
default stage-1 names lost and Z2 / Z (median, largest); part ``simetri``. (5) The time of the
reversal check.

Recommendation on the two-sided rule, fixed now. The README recommends adopting it (as a change
for the maintainers to decide) only if all of these hold on held-out evidence: (a) no false
accusation under it; (b) on the README benchmark it loses no name of the default stage 1;
(c) on the honest traces of ``jujur`` where the default stage 1 names someone it loses a name in
at most 1 % of them; (d) for at least one medium, it names a member in at least half of the
fully reversed traces (``balik``, ``balik1``, ``balik-d4``, ``buang``, ``balik1-buang``) where
the default names nobody. Otherwise the README recommends not adopting it, with the numbers.

Usage (from the repository root; at most 3 worker processes, 1 BLAS thread each; ``--kerja``
is the work folder of the issuances, default ``out/balik``):

    python research/balik/ukur.py terbit dev            # then: terbit uji
    python research/balik/ukur.py dev --out research/balik/hasil/dev.jsonl
    python research/balik/ukur.py jujur --out research/balik/hasil/jujur.jsonl
    python research/balik/ukur.py sadar --out research/balik/hasil/sadar.jsonl
    python research/balik/ukur.py cetakprofil --out research/balik/hasil/cetakprofil.jsonl
    python research/balik/ukur.py besar --out research/balik/hasil/besar.jsonl
    python research/balik/ukur.py bench --bench EXPORT/out/bench-check --out research/balik/hasil/bench.jsonl
    python research/balik/ukur.py simetri --out research/balik/hasil/simetri.jsonl
    python research/balik/ukur.py ringkas research/balik/hasil/*.jsonl
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

_spec = importlib.util.spec_from_file_location("kontradiksi_ukur", ROOT / "research" / "kontradiksi" / "ukur.py")
kontra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kontra)  # its media (``evidence``) and background noise (``degrade_latar``)

WORKERS = 3
EPS = 1e-6
OLD_ERASURE = -3.0902  # the single-statistic threshold before this protocol
MEDIA = ("pdf", "layar", "foto", "ponsel", "monitor", "cetak1", "cetak2")
STANDARD = ("acak", "salin", "rata", "mayoritas", "minoritas")
ATTACKS = ("hapus", "balik", "balik60", "balik80", "adaptif", "acak-sama", "buang", "buang-acak")
DIGITAL = ("pdf", "layar", "foto")
PRINT_ATTACKS = ("jujur", "hapus", "balik", "adaptif")
ONE_COPY = ("balik1", "balik1-buang")
FULL_REVERSAL = ("balik", "balik1", "balik-d4", "buang", "balik1-buang")
ADAPTIVE_GRID = tuple(round(0.05 * i, 2) for i in range(1, 21))
NOISE_SIGMA = 4.0
LARGE = (4, 5, 6)
LARGE_RULES = ("acak", "mayoritas", "minoritas")
DEV_ATTACKS = ("jujur", "hapus", "balik", "balik60", "acak-sama", "buang", "buang-acak")
DEV_PRINT = ("jujur", "hapus", "balik")
SYMMETRY_STRATEGIES = ("random-mix", "majority", "minority", "all-0", "erase")

# name -> (document, N, seed, shift scheme, background profile, master kind)
ISSUANCES = {
    "P1": ("nota_dinas", 20, 9401, "v2", "layar", "teks"),
    "P2": ("surat_telegram", 20, 9402, "v1", "layar", "teks"),
    "V1": ("nota_dinas", 20, 9601, "v2", "layar", "teks"),
    "V2": ("nota_dinas", 100, 9602, "v2", "layar", "teks"),
    "V3": ("surat_telegram", 20, 9603, "v2", "layar", "teks"),
    "V4": ("surat_telegram", 100, 9604, "v2", "layar", "teks"),
    "V5": ("nota_dinas", 20, 9605, "v1", "layar", "teks"),
    "V6": ("surat_telegram", 20, 9606, "v1", "layar", "teks"),
    "V7": ("nota_dinas", 20, 9607, "v2", "cetak", "teks"),
    "V8": ("nota_dinas", 20, 9608, "v2", "layar", "pindaian"),
}
SETS = {"dev": ("P1", "P2"), "uji": ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8")}
SEEDS = {"dev_salinan": 9411, "dev_koalisi": 9412, "dev_kanal": 9413, "dev_induk": 9414, "dev_serangan": 9415,
         "jujur": 9611, "koalisi_jujur": 9612, "serangan_jujur": 9614, "induk": 9617,
         "koalisi_sadar": 9622, "kanal_sadar": 9623, "serangan_sadar": 9624, "derau": 9625,
         "koalisi_besar": 9627, "serangan_besar": 9628, "kanal_besar": 9629,
         "koalisi_cetak": 9632, "kanal_cetak": 9633, "serangan_cetak": 9634, "simetri": 9640}
WORK = [ROOT / "out" / "balik"]  # set by --kerja before any worker starts (passed to workers)
BENCH = [None]


# --- issuance ------------------------------------------------------------------------------


def issuance_dir(name: str) -> Path:
    """Work folder of one research issuance (gitignored)."""
    doc, n, seed, scheme, latar, kind = ISSUANCES[name]
    return WORK[0] / f"{name}_{doc}_{n}_{seed}_{scheme}_{latar}_{kind}"


def master_path(name: str) -> Path:
    """The master PDF of an issuance: the sample, or its fictional scan."""
    doc, *_, kind = ISSUANCES[name]
    if kind == "teks":
        return ROOT / "samples" / f"{doc}.pdf"
    path = WORK[0] / f"{doc}_pindaian.pdf"
    if not path.exists():
        from tapak.samplegen import scanned_sample

        WORK[0].mkdir(parents=True, exist_ok=True)
        path.write_bytes(scanned_sample((ROOT / "samples" / f"{doc}.pdf").read_bytes()))
    return path


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
    """Issue every issuance of a set (skips the ones already there) and check its scheme."""
    from tapak.marker.issue import IssueManifest

    for name in SETS[which]:
        doc, n, seed, scheme, latar, kind = ISSUANCES[name]
        folder = issuance_dir(name)
        if not list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            csv = _recipients_csv(folder, n)
            cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
                   "issue", str(master_path(name)), str(csv), "--no-registry", "--canary-domain", "",
                   "--workers", str(WORKERS), "--geser", scheme, "--latar", latar, "--benih-riset", str(seed)]
            subprocess.run(cmd, check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
        manifest = IssueManifest.from_json(next(folder.glob("data/dokumen/*/salinan/manifest.json"))
                                           .read_text(encoding="utf-8"))
        want = "geser-v2" if scheme == "v2" else "geser-v1"
        got = manifest.shift_scheme or "geser-v1"
        if got != want:
            raise SystemExit(f"{name}: skema {got}, bukan {want}")
        print(f"{name}: {folder.name}, {got}", flush=True)


# --- worker side ---------------------------------------------------------------------------

_CTX: dict[str, tuple] = {}


def _init(work: str, bench: str | None) -> None:
    import cv2

    from tapak.decoder import rectify

    WORK[0], BENCH[0] = Path(work), (Path(bench) if bench else None)
    cv2.setNumThreads(1)
    rectify._EXACT_CACHE = rectify._ByteBudgetCache(150_000_000)  # three workers on a shared machine


def context(name: str):
    """(trace context, salinan folder) of an issuance, cached per process."""
    if name not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.keys import research_code_secret
        from tapak.marker.issue import IssueManifest

        folder = next(issuance_dir(name).glob("data/dokumen/*/salinan"))
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        ctx = load_context(master_path(name).read_bytes(), manifest, research_code_secret(ISSUANCES[name][2]))
        _CTX[name] = (ctx, folder)
    return _CTX[name]


def copy_pdf(name: str, seq: int) -> bytes:
    """Bytes of copy ``seq`` (1-based) of an issuance."""
    ctx, folder = context(name)
    return (folder / ctx.manifest.copies[seq - 1].file).read_bytes()


def members_of(seed: list[int], n: int, k: int) -> list[int]:
    """k distinct copies from 1..n, drawn with ``seed``."""
    rng = np.random.default_rng(seed)
    return sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))


def evidence(ctx, pdf: bytes, medium: str, rng: np.random.Generator, index: int) -> list:
    """Observations of one evidence (``research/kontradiksi``'s media)."""
    return kontra.evidence(ctx, pdf, medium, rng, index)


# --- analysis of one evidence --------------------------------------------------------------


def two_sided(p: np.ndarray, weights: np.ndarray, eps1: float, scores: dict[int, float]) -> dict:
    """The two-sided stage-1 rule (research only): Z2 = Z(eps1 / 2), copies with S >= Z2 (upper
    tail) or S <= -Z2 (lower tail)."""
    from tapak.tardos.accuse import threshold

    z2 = threshold(p, eps1 / 2.0, weights)
    upper = sorted(s for s, v in scores.items() if math.isfinite(z2) and v >= z2)
    lower = sorted(s for s, v in scores.items() if math.isfinite(z2) and v <= -z2)
    return {"Z2": z2, "atas": upper, "bawah": lower}


def _physical_signs(obs: list, ctx) -> dict:
    """z_signs of the shift and the background channel alone (diagnostics)."""
    from tapak.decoder.fuse import fuse_by_physical_channel
    from tapak.decoder.reversal import sign_statistic

    out = {}
    for name, est in fuse_by_physical_channel(obs, ctx.params.length).items():
        z, n = sign_statistic(est, ctx.p)
        out[name] = {"z": None if z is None else round(z, 3), "posisi": n}
    return out


def analyse(obs: list, ctx, members: set[int], spending=None) -> dict:
    """Everything recorded for one evidence (module docstring)."""
    from tapak.decoder.erasure import erasure_statistic
    from tapak.decoder.fuse import fuse
    from tapak.decoder.manipulation import is_manipulation_note
    from tapak.decoder.reversal import reversal_check
    from tapak.decoder.trace import run_trace
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    if spending is None:
        spending = TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY)
    t0 = time.perf_counter()
    res = run_trace(obs, ctx, [], spending)
    t_trace = time.perf_counter() - t0
    fused = fuse(obs, ctx.params.length)
    t1 = time.perf_counter()
    reversal_check(obs, fused, ctx.p)
    t_rev = time.perf_counter() - t1
    named = sorted(res.named_seqs)
    stage1 = sorted(c.copy.seq for c in res.accused)
    z = res.threshold.threshold
    scores = {c.copy.seq: c.score for c in res.candidates}
    mem = [v for s, v in scores.items() if s in members]
    oth = [v for s, v in scores.items() if s not in members]

    def ratio(v: list[float], best=max) -> float | None:
        return round(best(v) / z, 4) if v and math.isfinite(z) and z > 0 else None

    two = two_sided(ctx.p, fused.weights, res.threshold.eps1, scores)
    upper, lower = two["atas"], two["bawah"]
    er, rv, con = res.erasure, res.reversal, res.contradiction
    singles = {}
    for rule in ("pola", "semua"):
        zz, n, _ = erasure_statistic(obs, ctx.p, rule)
        singles[rule] = {"z": None if zz is None else round(zz, 4), "posisi": n,
                         "lama": bool(zz is not None and zz <= OLD_ERASURE)}
    notes = [n for n in res.notes if is_manipulation_note(n)]
    row = {
        "putusan": {"dituduh": named, "anggota": len([s for s in named if s in members]),
                    "salah": [s for s in named if s not in members], "tahap1": stage1,
                    "Z": round(z, 2) if math.isfinite(z) else None,
                    "skor_anggota": ratio(mem), "skor_anggota_min": ratio(mem, min), "skor_lain": ratio(oth),
                    "skor_lain_min": ratio(oth, min)},
        "dua_sisi": {"Z2": round(two["Z2"], 2) if math.isfinite(two["Z2"]) else None,
                     "rasio": round(two["Z2"] / z, 5) if math.isfinite(z) and math.isfinite(two["Z2"]) else None,
                     "atas": upper, "bawah": lower,
                     "anggota_atas": [s for s in upper if s in members],
                     "anggota_bawah": [s for s in lower if s in members],
                     "salah": [s for s in upper + lower if s not in members],
                     "hilang": [s for s in stage1 if s not in upper]},
        "hapus": {"z": er.z, "z_semua": er.z_all, "posisi": er.positions, "posisi_semua": er.positions_all,
                  "ditandai": bool(er.flagged), "tunggal": singles},
        "balik": {"z_pilot": rv.z_pilot, "halaman": rv.pilot_pages, "z_tanda": rv.z_signs, "posisi": rv.positions,
                  "ditandai": bool(rv.flagged), "per_kanal": _physical_signs(obs, ctx)},
        "kontradiksi": None if con is None else {"ditandai": bool(con.flagged), "log10_batas": con.log10_bound,
                                                 "lengkap": con.complete},
        "peringatan": {"ada": bool(notes), "jumlah": len(notes),
                       "balik": bool(rv.flagged), "hapus": bool(er.flagged),
                       "kontradiksi": bool(con is not None and con.flagged)},
        "terbaca": {},
        "latar": [{k: sb.meta.get(k) for k in ("page", "pattern_found", "presence", "decoy_z", "pilot_z", "signal_z")}
                  for sb in obs if sb.channel == "background"],
        "observed": int(np.count_nonzero(fused.weights > 0)),
        "efektif": round(float(np.sum(fused.weights ** 2)), 1),
        "detik_lacak": round(t_trace, 2),
        "detik_balik": round(t_rev, 4),
    }
    for sb in obs:
        row["terbaca"][sb.channel] = row["terbaca"].get(sb.channel, 0) + len(sb)
    return row


# --- forgeries -----------------------------------------------------------------------------


def _flatten(plan) -> None:
    for lv in plan.levels.values():
        lv[:] = 0.0


def forge(ctx, pdfs: list[bytes], attack_name: str, rng_seed: list[int], fraction: float | None = None,
          noise_seed: list[int] | None = None) -> tuple[bytes, dict]:
    """A forged PDF of the coalition ``pdfs`` (first member first) for one attack name."""
    from tapak.collusion import attack, forge_copy

    rng = np.random.default_rng(rng_seed)
    if attack_name in STANDARD:  # honest coalition: agreeing units untouched
        data, _, plan = attack(ctx.master, pdfs, attack_name, 0.0, rng=rng)
        return data, plan.counts
    if attack_name in ("buang", "buang-acak", "balik1-buang"):
        if attack_name == "balik1-buang":
            pdfs = [pdfs[0], pdfs[0]]
        neutralize = "acak" if attack_name == "buang-acak" else "balik"
        _, _, plan = attack(ctx.master, pdfs, "acak", 1.0, rng=rng, neutralize=neutralize)
        _flatten(plan)
        return forge_copy(ctx.master, pdfs, plan), plan.counts
    if attack_name == "balik1":
        pdfs = [pdfs[0], pdfs[0]]
    neutralize = {"hapus": "hapus", "balik": "balik", "balik60": "balik", "balik80": "balik", "adaptif": "balik",
                  "acak-sama": "acak", "balik1": "balik", "balik-d4": "balik"}[attack_name]
    frac = {"balik60": 0.6, "balik80": 0.8}.get(attack_name, 1.0) if fraction is None else fraction
    data, _, plan = attack(ctx.master, pdfs, "acak", frac, rng=rng, neutralize=neutralize)
    if attack_name == "balik-d4":
        data = kontra.degrade_latar(data, NOISE_SIGMA, np.random.default_rng(noise_seed))
    return data, plan.counts


def _members_named(pdf: bytes, ctx, members: set[int]) -> bool:
    from tapak.decoder.trace import collect_file, run_trace
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    obs = collect_file("bukti.pdf", pdf, ctx)[0]
    res = run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY))
    return bool(res.named_seqs & members)


def adaptive(ctx, pdfs: list[bytes], members: set[int], rng_seed: list[int]) -> tuple[bytes, dict, float]:
    """The smallest reversed fraction on ADAPTIVE_GRID with no member named in the PDF trace."""
    lo, hi = -1, len(ADAPTIVE_GRID) - 1
    cache: dict[int, tuple[bytes, dict]] = {}
    while hi - lo > 1:
        mid = (lo + hi) // 2
        cache[mid] = forge(ctx, pdfs, "adaptif", rng_seed, ADAPTIVE_GRID[mid])
        if _members_named(cache[mid][0], ctx, members):
            lo = mid
        else:
            hi = mid
    if hi not in cache:
        cache[hi] = forge(ctx, pdfs, "adaptif", rng_seed, ADAPTIVE_GRID[hi])
    return cache[hi][0], cache[hi][1], ADAPTIVE_GRID[hi]


# --- jobs ----------------------------------------------------------------------------------


def _base(part: str, name: str) -> dict:
    doc, n, seed, scheme, latar, kind = ISSUANCES[name]
    return {"bagian": part, "terbitan": name, "dok": doc, "N": n, "benih": seed, "skema": scheme,
            "latar_profil": latar, "induk": kind}


def _media(name: str) -> tuple[str, ...]:
    if name == "V7":
        return ("pdf", "cetak1", "cetak2")
    if name == "V8":
        return ("pdf", "foto", "cetak2")
    return MEDIA


def dev_job(job: tuple) -> list[dict]:
    """Part dev: one honest copy, the master, or one coalition with the dev attacks."""
    name, iss, what = job
    ctx, _ = context(name)
    rows = []
    if what == "induk":
        for mi, medium in enumerate(DIGITAL):
            obs = evidence(ctx, ctx.master.pdf_bytes, medium, np.random.default_rng([SEEDS["dev_induk"], iss, mi]), mi)
            rows.append({**_base("dev", name), "unit": "induk", "kanal": medium, **analyse(obs, ctx, set())})
        return rows
    if isinstance(what, int):
        pdf = copy_pdf(name, what)
        for mi, medium in enumerate(MEDIA):
            obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["dev_salinan"], iss, what, mi]), what)
            rows.append({**_base("dev", name), "unit": "salinan", "salinan": what, "kanal": medium,
                         **analyse(obs, ctx, {what})})
        return rows
    k = what[1]
    members = members_of([SEEDS["dev_koalisi"], iss, k], ctx.params.n_max, k)
    pdfs = [copy_pdf(name, s) for s in members]
    forged = {"jujur": pdfs[0]}
    for ai, att in enumerate(DEV_ATTACKS[1:]):
        forged[att] = forge(ctx, pdfs, att, [SEEDS["dev_serangan"], iss, k, ai])[0]
    for mi, medium in enumerate(DIGITAL + ("cetak2",)):
        for att, data in forged.items():
            if medium == "cetak2" and att not in DEV_PRINT:
                continue
            obs = evidence(ctx, data, medium, np.random.default_rng([SEEDS["dev_kanal"], iss, k, mi]), k)
            rows.append({**_base("dev", name), "unit": "koalisi", "k": k, "koalisi": members, "serangan": att,
                         "kanal": medium, **analyse(obs, ctx, set(members))})
    return rows


def jujur_job(job: tuple) -> list[dict]:
    """Part jujur: one honest unit (a copy, an honest coalition, or the master) through its media."""
    name, iss, unit = job
    ctx, _ = context(name)
    n = ctx.params.n_max
    rows = []
    if unit == "induk":
        for mi, medium in enumerate(DIGITAL):
            obs = evidence(ctx, ctx.master.pdf_bytes, medium, np.random.default_rng([SEEDS["induk"], iss, mi]), mi)
            rows.append({**_base("jujur", name), "unit": "induk", "kanal": medium, **analyse(obs, ctx, set())})
        return rows
    if isinstance(unit, int):
        members, pdf, label, uid = [unit], copy_pdf(name, unit), "salinan", unit
    else:
        k, rule = unit
        si = STANDARD.index(rule)
        members = members_of([SEEDS["koalisi_jujur"], iss, k, si], n, k)
        pdf, _ = forge(ctx, [copy_pdf(name, s) for s in members], rule, [SEEDS["serangan_jujur"], iss, k, si])
        label, uid = f"koalisi/{rule}", 100 + 10 * k + si
    for medium in _media(name):
        obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["jujur"], iss, uid, MEDIA.index(medium)]), uid)
        rows.append({**_base("jujur", name), "unit": label, "k": len(members), "koalisi": members, "kanal": medium,
                     **analyse(obs, ctx, set(members))})
    return rows


def sadar_job(job: tuple) -> list[dict]:
    """Part sadar: one knowing coalition, every attack, its media."""
    name, iss, k, ci, members = job
    ctx, _ = context(name)
    pdfs = [copy_pdf(name, s) for s in members]
    forged: dict[str, tuple[bytes, dict, float | None]] = {"jujur": (pdfs[0], {}, None)}
    for ai, att in enumerate(ATTACKS + ("balik-d4",) + ONE_COPY):
        if att in ONE_COPY and k != 2:
            continue
        seed = [SEEDS["serangan_sadar"], iss, k, ci, ai]
        if att == "adaptif":
            forged[att] = adaptive(ctx, pdfs, set(members), seed)
        else:
            data, counts = forge(ctx, pdfs, att, seed, noise_seed=[SEEDS["derau"], iss, k, ci])
            forged[att] = (data, counts, None)
    rows = []
    for mi, medium in enumerate(DIGITAL + ("cetak2",)):
        for att, (data, counts, frac) in forged.items():
            if medium == "cetak2" and att not in PRINT_ATTACKS:
                continue
            if att == "balik-d4" and medium != "pdf":
                continue
            group = {members[0]} if att in ONE_COPY else set(members)
            obs = evidence(ctx, data, medium, np.random.default_rng([SEEDS["kanal_sadar"], iss, k, ci, mi]), ci)
            rows.append({**_base("sadar", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": att,
                         "r": frac, "rencana": counts, "kanal": medium, **analyse(obs, ctx, group)})
    return rows


def cetakprofil_job(job: tuple) -> list[dict]:
    """Part cetakprofil: one coalition of V7 (print profile) through pdf, cetak1 and cetak2."""
    name, k, ci, members = job
    ctx, _ = context(name)
    pdfs = [copy_pdf(name, s) for s in members]
    forged = {"jujur": pdfs[0]}
    for ai, att in enumerate(("hapus", "balik", "balik1")):
        if att == "balik1" and k != 2:
            continue
        forged[att] = forge(ctx, pdfs, att, [SEEDS["serangan_cetak"], k, ci, ai])[0]
    rows = []
    for mi, medium in enumerate(("pdf", "cetak1", "cetak2")):
        for att, data in forged.items():
            group = {members[0]} if att == "balik1" else set(members)
            obs = evidence(ctx, data, medium, np.random.default_rng([SEEDS["kanal_cetak"], k, ci, mi]), ci)
            rows.append({**_base("cetakprofil", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": att,
                         "kanal": medium, **analyse(obs, ctx, group)})
    return rows


def besar_job(job: tuple) -> list[dict]:
    """Part besar: one honest coalition larger than three through pdf and layar."""
    name, iss, k, rule = job
    ctx, _ = context(name)
    si = LARGE_RULES.index(rule)
    members = members_of([SEEDS["koalisi_besar"], iss, k, si], ctx.params.n_max, k)
    pdf, _ = forge(ctx, [copy_pdf(name, s) for s in members], rule, [SEEDS["serangan_besar"], iss, k, si])
    rows = []
    for mi, medium in enumerate(("pdf", "layar")):
        obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["kanal_besar"], iss, k, si, mi]), si)
        rows.append({**_base("besar", name), "k": k, "koalisi": members, "aturan": rule, "kanal": medium,
                     **analyse(obs, ctx, set(members))})
    return rows


_BENCH: dict[str, object] = {}

BENCH_SETS = {"layar": "photos", "cetak": "photos-cetak", "ponsel": "photos-ponsel", "fotolayar": "photos-layar"}


def bench_job(job: tuple) -> list[dict]:
    """Part bench: one image (or the printed pages 1 and 2 of a copy) of the README benchmark."""
    from tapak.decoder.trace import collect_file, load_context
    from tapak.keys import research_code_secret
    from tapak.marker.issue import IssueManifest
    from tapak.service import TRACE_STAGE_POLICY
    from tapak.tardos.spending import TraceSpending

    medium, folder, files, seq = job
    if "ctx" not in _BENCH:
        issued = next((BENCH[0] / "data" / "dokumen").glob("*/salinan"))
        manifest = IssueManifest.from_json((issued / "manifest.json").read_text(encoding="utf-8"))
        _BENCH["ctx"] = load_context((ROOT / "samples" / "nota_dinas.pdf").read_bytes(), manifest,
                                     research_code_secret(2026))
    ctx = _BENCH["ctx"]
    obs = []
    for f in files:
        obs += collect_file(f, (Path(folder) / f).read_bytes(), ctx)[0]
    spending = TraceSpending.unlogged(EPS, TRACE_STAGE_POLICY)
    return [{"bagian": "bench", "medium": medium, "kanal": medium, "berkas": files, "salinan": seq,
             **analyse(obs, ctx, {seq}, spending)}]


def simetri_job(job: tuple) -> list[dict]:
    """Part simetri: innocent scores against coalition reads, both tails of Z(eps1)."""
    from tapak.tardos.accuse import scores, threshold
    from tapak.tardos.attacks import STRATEGIES, add_channel_noise
    from tapak.tardos.code import random_code
    from tapak.tardos.params import TardosParams

    k, strategy = job
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    m, eps1, reads = 300, 1e-2, 2000
    rng = np.random.default_rng([SEEDS["simetri"], k, SYMMETRY_STRATEGIES.index(strategy)])
    hi = lo = total = 0
    for _ in range(reads):
        p, x = random_code(params, params.n_max, rng, m)
        y, w = STRATEGIES[strategy](x[:k], rng)
        y, w = add_channel_noise(y, w, rng, ber=0.05)
        z = threshold(p, eps1, w)
        s = scores(x[k:], y, p, w)
        hi += int(np.sum(s >= z))
        lo += int(np.sum(s <= -z))
        total += s.size
    return [{"bagian": "simetri", "k": k, "strategi": strategy, "m": m, "eps1": eps1, "skor": total,
             "atas": hi, "bawah": lo}]


def dev_jobs() -> list[tuple]:
    jobs = []
    for i, name in enumerate(SETS["dev"]):
        jobs += [(name, i, s) for s in range(1, 5)] + [(name, i, "induk")] + [(name, i, ("koalisi", k)) for k in (2, 3)]
    return jobs


def jujur_jobs() -> list[tuple]:
    jobs = []
    for i, name in enumerate(SETS["uji"]):
        if name == "V7":
            jobs += [(name, i, s) for s in range(1, 6)] + [(name, i, (2, "acak")), (name, i, (3, "mayoritas"))]
            continue
        if name == "V8":
            jobs += [(name, i, s) for s in range(1, 4)]
            continue
        jobs += [(name, i, s) for s in range(1, 6)]
        jobs += [(name, i, (k, rule)) for k in (2, 3) for rule in STANDARD]
        jobs.append((name, i, "induk"))
    return jobs


def sadar_jobs() -> list[tuple]:
    jobs = []
    for name in ("V1", "V2", "V3", "V4", "V5", "V6"):
        i = SETS["uji"].index(name)
        n = ISSUANCES[name][1]
        for k in (2, 3):
            rng = np.random.default_rng([SEEDS["koalisi_sadar"], i, k])
            for ci in range(3):
                members = sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
                jobs.append((name, i, k, ci, members))
    return jobs


def cetakprofil_jobs() -> list[tuple]:
    jobs = []
    for k in (2, 3):
        rng = np.random.default_rng([SEEDS["koalisi_cetak"], k])
        for ci in range(3):
            jobs.append(("V7", k, ci, sorted(int(s) for s in rng.choice(np.arange(1, 21), size=k, replace=False))))
    return jobs


def besar_jobs() -> list[tuple]:
    return [(name, SETS["uji"].index(name), k, rule) for name in ("V1", "V2", "V3", "V4") for k in LARGE
            for rule in LARGE_RULES]


def bench_jobs() -> list[tuple]:
    """Every image of the benchmark sets, and every printed copy's pages 1 and 2 together."""
    if BENCH[0] is None:
        raise SystemExit("bagian bench memerlukan --bench (folder out/bench-check dari make bench-check)")
    jobs = []
    for medium, sub in BENCH_SETS.items():
        folder = BENCH[0] / sub
        truth = folder / "truth.json"
        if not truth.exists():
            raise SystemExit(f"{folder} belum ada: jalankan make bench-check")
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


def simetri_jobs() -> list[tuple]:
    return [(k, s) for k in (2, 3) for s in SYMMETRY_STRATEGIES]


PARTS = {"dev": (dev_job, dev_jobs), "jujur": (jujur_job, jujur_jobs), "sadar": (sadar_job, sadar_jobs),
         "cetakprofil": (cetakprofil_job, cetakprofil_jobs), "besar": (besar_job, besar_jobs),
         "bench": (bench_job, bench_jobs), "simetri": (simetri_job, simetri_jobs)}


def _job(item: tuple) -> list[dict]:
    part, job = item
    return PARTS[part][0](tuple(job) if isinstance(job, list) else job)


def _run(part: str, out: Path) -> None:
    """Run every job of a part not yet in ``out`` (a job is done when one of its rows is there)."""
    import multiprocessing as mp

    fn, make = PARTS[part]
    jobs = make()
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line:
                done.add(json.loads(line)["job"])
    todo = [j for j in jobs if json.dumps(j) not in done]
    print(f"{part}: {len(todo)} dari {len(jobs)} tugas", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    init_args = (str(WORK[0]), str(BENCH[0]) if BENCH[0] else None)
    with out.open("a", encoding="utf-8") as fh, ProcessPoolExecutor(WORKERS, mp_context=mp.get_context("spawn"),
                                                                    initializer=_init, initargs=init_args) as pool:
        for job, rows in zip(todo, pool.map(_job, [(part, j) for j in todo])):
            for r in rows:
                fh.write(json.dumps({"job": json.dumps(job), **r}) + "\n")
            fh.flush()
            print(f"{len(rows)} baris, {job}", flush=True)


# --- summary -------------------------------------------------------------------------------


def _any(r: dict) -> bool:
    return bool(r["peringatan"]["ada"])


def _medium(r: dict) -> str:
    return r["kanal"]


def _honest_table(rows: list[dict], title: str) -> None:
    print(f"\n{title}: per medium n; hapus kirim / pola@-3,29 / semua@-3,29; balik kirim / pilot / tanda; "
          "kontradiksi; salah satu; z terendah (pola, semua, pilot, tanda)")
    from tapak.decoder.erasure import ERASURE_Z
    from tapak.decoder.reversal import REVERSAL_Z

    cells = defaultdict(list)
    for r in rows:
        cells[(r.get("unit") == "induk", _medium(r))].append(r)
    for (master, medium), rs in sorted(cells.items()):
        def low(vals):
            vals = [v for v in vals if v is not None]
            return round(min(vals), 2) if vals else None
        zp = [r["hapus"]["z"] for r in rs]
        zs = [r["hapus"]["z_semua"] for r in rs]
        pil = [r["balik"]["z_pilot"] for r in rs]
        sig = [r["balik"]["z_tanda"] for r in rs]
        print(f"  {'induk ' if master else ''}{medium:9s} {len(rs):4d}; "
              f"{sum(r['hapus']['ditandai'] for r in rs)} / {sum(v is not None and v <= -ERASURE_Z for v in zp)} / "
              f"{sum(v is not None and v <= -ERASURE_Z for v in zs)}; "
              f"{sum(r['balik']['ditandai'] for r in rs)} / {sum(v is not None and v <= -REVERSAL_Z for v in pil)} / "
              f"{sum(v is not None and v <= -REVERSAL_Z for v in sig)}; "
              f"{sum(r['peringatan']['kontradiksi'] for r in rs)}; {sum(map(_any, rs))}; "
              f"({low(zp)}, {low(zs)}, {low(pil)}, {low(sig)})")


def summary(paths: list[str]) -> int:
    """Tables of the analysis fixed in the module docstring."""
    from tapak.decoder.erasure import ERASURE_Z
    from tapak.decoder.reversal import REVERSAL_Z

    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    by = defaultdict(list)
    for r in rows:
        by[r["bagian"]].append(r)
    traced = [r for r in rows if "putusan" in r]
    wrong = [(r["bagian"], r.get("terbitan"), r.get("serangan", r.get("unit")), r["kanal"], r["putusan"]["salah"])
             for r in traced if r["putusan"]["salah"]]
    wrong2 = [(r["bagian"], r.get("serangan", r.get("unit")), r["kanal"], r["dua_sisi"]["salah"])
              for r in traced if r["dua_sisi"]["salah"]]
    print(f"tuduhan salah (aturan bawaan): {len(wrong)} dari {len(traced)} pelacakan {wrong[:5]}")
    print(f"tuduhan salah (aturan dua sisi, tahap 1): {len(wrong2)} {wrong2[:5]}")
    for part in ("dev", "jujur", "bench", "besar"):
        honest = [r for r in by.get(part, []) if r.get("unit") != "koalisi" and r.get("serangan") in (None, "jujur")]
        if part == "dev":
            honest = [r for r in by.get(part, []) if r.get("unit") in ("salinan", "induk")
                      or r.get("serangan") == "jujur"]
        if honest:
            _honest_table(honest, f"(1) jujur, bagian {part}")
    if by.get("besar"):
        print("\n(1b) besar per k dan aturan: peringatan balik / hapus / kontradiksi / bukti; z tanda terendah")
        cells = defaultdict(list)
        for r in by["besar"]:
            cells[(r["k"], r["aturan"])].append(r)
        for key, rs in sorted(cells.items()):
            sig = [r["balik"]["z_tanda"] for r in rs if r["balik"]["z_tanda"] is not None]
            print(f"  k {key[0]} {key[1]:10s} {sum(r['balik']['ditandai'] for r in rs)} / "
                  f"{sum(r['hapus']['ditandai'] for r in rs)} / {sum(r['peringatan']['kontradiksi'] for r in rs)} / "
                  f"{len(rs)}; {min(sig) if sig else None}")
    attacked = by.get("sadar", []) + by.get("dev", []) + by.get("cetakprofil", [])
    erased = [r for r in attacked if r.get("serangan") == "hapus"]
    if erased:
        print("\n(2) bukti hapus ditandai: kirim / pola lama (-3,09) / semua lama / pola@-3,29 / semua@-3,29 / n")
        for part in ("dev", "sadar", "cetakprofil"):
            for medium in MEDIA:
                rs = [r for r in erased if r["bagian"] == part and _medium(r) == medium]
                if not rs:
                    continue
                print(f"  {part:11s} {medium:7s} {sum(r['hapus']['ditandai'] for r in rs)} / "
                      f"{sum(r['hapus']['tunggal']['pola']['lama'] for r in rs)} / "
                      f"{sum(r['hapus']['tunggal']['semua']['lama'] for r in rs)} / "
                      f"{sum(r['hapus']['z'] is not None and r['hapus']['z'] <= -ERASURE_Z for r in rs)} / "
                      f"{sum(r['hapus']['z_semua'] is not None and r['hapus']['z_semua'] <= -ERASURE_Z for r in rs)}"
                      f" / {len(rs)}")
        for part in ("dev", "sadar"):
            rs = [r for r in erased if r["bagian"] == part]
            if rs:
                print(f"  {part} jumlah: kirim {sum(r['hapus']['ditandai'] for r in rs)}, pola lama "
                      f"{sum(r['hapus']['tunggal']['pola']['lama'] for r in rs)}, semua lama "
                      f"{sum(r['hapus']['tunggal']['semua']['lama'] for r in rs)}, dari {len(rs)}")
    if attacked:
        print("\n(3) per serangan dan medium: lolos / balik (pilot, tanda) / hapus / kontradiksi / salah satu / "
              "lolos tanpa peringatan / n; salah; z pilot dan z tanda median")
        cells = defaultdict(list)
        for r in attacked:
            if r.get("serangan"):
                cells[(r["bagian"], r["serangan"], _medium(r))].append(r)
        for (part, att, medium), rs in sorted(cells.items()):
            esc = [r for r in rs if r["putusan"]["anggota"] == 0]
            pil = [r["balik"]["z_pilot"] for r in rs if r["balik"]["z_pilot"] is not None]
            sig = [r["balik"]["z_tanda"] for r in rs if r["balik"]["z_tanda"] is not None]
            extra = ""
            if att == "adaptif" and rs[0].get("r") is not None:
                extra = f"; r {min(r['r'] for r in rs)}..{max(r['r'] for r in rs)}"
            print(f"  {part:11s} {att:12s} {medium:7s} {len(esc):3d} / {sum(r['balik']['ditandai'] for r in rs):3d} "
                  f"({sum(v <= -REVERSAL_Z for v in pil)}, {sum(v <= -REVERSAL_Z for v in sig)}) / "
                  f"{sum(r['hapus']['ditandai'] for r in rs):3d} / {sum(r['peringatan']['kontradiksi'] for r in rs):3d}"
                  f" / {sum(map(_any, rs)):3d} / {sum(not _any(r) for r in esc):3d} / {len(rs):3d}; "
                  f"{sum(bool(r['putusan']['salah']) for r in rs)}; "
                  f"{np.median(pil) if pil else None} {np.median(sig) if sig else None}{extra}")
        print("\n(4) dua sisi per serangan dan medium: anggota disebut bawaan (tahap mana pun) / bawaan tahap 1 / "
              "dua sisi atas / dua sisi bawah / dua sisi salah satu / disebut dua sisi saat bawaan tidak / n")
        for (part, att, medium), rs in sorted(cells.items()):
            d_any = sum(r["putusan"]["anggota"] > 0 for r in rs)
            d1 = sum(any(s in r["koalisi"] for s in r["putusan"]["tahap1"]) for r in rs)
            up = sum(bool(r["dua_sisi"]["anggota_atas"]) for r in rs)
            dn = sum(bool(r["dua_sisi"]["anggota_bawah"]) for r in rs)
            either = sum(bool(r["dua_sisi"]["anggota_atas"] or r["dua_sisi"]["anggota_bawah"]) for r in rs)
            gain = sum(bool(r["dua_sisi"]["anggota_atas"] or r["dua_sisi"]["anggota_bawah"])
                       and r["putusan"]["anggota"] == 0 for r in rs)
            print(f"  {part:11s} {att:12s} {medium:7s} {d_any:3d} / {d1:3d} / {up:3d} / {dn:3d} / {either:3d} / "
                  f"{gain:3d} / {len(rs):3d}")
    for part in ("jujur", "bench", "besar"):
        rs = by.get(part, [])
        if not rs:
            continue
        named1 = [r for r in rs if r["putusan"]["tahap1"]]
        lost = [r for r in named1 if r["dua_sisi"]["hilang"]]
        ratios = [r["dua_sisi"]["rasio"] for r in rs if r["dua_sisi"]["rasio"] is not None]
        print(f"\n(4b) dua sisi, bagian {part}: nama tahap 1 hilang pada {len(lost)} dari {len(named1)} pelacakan yang "
              f"menyebut nama; Z2/Z median {np.median(ratios):.4f}, terbesar {max(ratios):.4f}; "
              f"bawah {sum(bool(r['dua_sisi']['bawah']) for r in rs)}")
        per = defaultdict(lambda: [0, 0])
        for r in named1:
            per[_medium(r)][0] += bool(r["dua_sisi"]["hilang"])
            per[_medium(r)][1] += 1
        print("  per medium (hilang / menyebut nama): " + ", ".join(f"{m} {a}/{b}" for m, (a, b) in sorted(per.items())))
    sym = by.get("simetri", [])
    if sym:
        print("\n(4c) simetri: skor tak bersalah >= Z / <= -Z dari n (eps1 = 0,01)")
        for r in sym:
            print(f"  k {r['k']} {r['strategi']:10s} {r['atas']} / {r['bawah']} dari {r['skor']} "
                  f"({r['atas'] / r['skor']:.2e}, {r['bawah'] / r['skor']:.2e})")
    if traced:
        t = np.array([r["detik_balik"] for r in traced])
        print(f"\n(5) waktu pemeriksaan pola tanda terbalik: median {np.median(t) * 1000:.1f} ms, persentil 95 "
              f"{np.percentile(t, 95) * 1000:.1f} ms ({len(t)} bukti); pelacakan median "
              f"{np.median([r['detik_lacak'] for r in traced]):.1f} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "ringkas", *PARTS])
    ap.add_argument("paths", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--kerja", type=Path, default=ROOT / "out" / "balik", help="folder kerja penerbitan riset")
    ap.add_argument("--bench", type=Path, default=None, help="folder out/bench-check dari make bench-check")
    args = ap.parse_args(argv)
    WORK[0] = args.kerja.resolve()
    BENCH[0] = args.bench.resolve() if args.bench else None
    if args.bagian == "terbit":
        issue_all(args.paths[0])
    elif args.bagian == "ringkas":
        return summary(args.paths)
    else:
        _run(args.bagian, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
