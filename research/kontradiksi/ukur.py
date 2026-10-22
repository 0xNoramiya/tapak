"""Contradiction check (a clear read that names nobody) and the erasure check on prints (research).

Protocol, seeds, media, decision rules and analysis fixed and committed before any run.
Development seeds ("dev") serve the two choices below; held-out seeds ("uji") are run once,
after the choices are written into the code and committed. Nothing here changes an accusation
threshold, eps, an alpha-spending rule or a decision rule; ERASURE_Z stays -3.0902. Both sample
documents and every recipient are fictional.

The check (``tapak/decoder/contradiction.py``). After the accusation (all stages), when nobody
is named, B = max over c' = 1..c of ``detection.read_miss_ceiling`` for the fused weights, rate
ceilings ``tempered_error_rates(L, tau)`` of the fused LLRs and the stage-1 eps1 the trace used;
warning when B <= CONTRADICTION_RATE. The rate is fixed now at 1e-3 (the erasure check's rate)
and the boxes at 64. Under (C1) and (C2) with rates at most the ceilings, an honest read raises
the warning with probability at most 1e-3.

Choice 1, the tempering factor tau (CONTRADICTION_TEMPERING), on dev only. Part ``kalibrasi``
reads honest single copies; for every position with weight > 0 the fused decision is compared
with the copy's codeword. Per medium and per bin of the fused |L| (edges 0.25, 1, 2, 3, 4, 6, 8,
12, infinity) it counts positions, wrong decisions k and, for every tau on the grid 1.0, 0.9,
..., 0.1, the expected count E(tau) = sum of 1 / (1 + exp(tau |L|)). Rule: tau is the largest
grid value for which every (medium, bin) with E(tau) > 0 or k > 0 has P(Poisson(E(tau)) >= k) >=
0.01; 0.1 if none passes.

Choice 2, the erasure check's background rule (``erasure.SILENT_BACKGROUND_RULE``), on dev
only. Background strengths count only from pages where the background decoder saw its pattern;
two readings fixed now: "pola" (its own decision ``pattern_found``) and "uji" (a presence test
passed, ``presence``). Rule: the reading that flags more dev erased evidence (part
``hapus-dev``, all four media together) wins, provided its dev honest alarms (parts
``kalibrasi`` and ``hapus-dev``, honest evidence) are not more than the other's; on a tie, or if
the reading with more flags has more honest alarms, "pola".

Issuances (``tapak issue --benih-riset SEED --no-registry --canary-domain ""``, c = 3, eps =
1e-6; the scheme with ``--geser``, the print profile with ``--latar cetak``). Seeds used by
earlier research (7101 to 8951 and 2026) are not reused.

* dev: D1 nota_dinas N = 20 geser-v2 (9101), D2 surat_telegram N = 20 geser-v2 (9102), D3
  nota_dinas N = 20 geser-v1 (9103);
* uji: U1 nota_dinas N = 20 v2 (9201), U2 nota_dinas N = 100 v2 (9202), U3 surat_telegram N = 20
  v2 (9203), U4 surat_telegram N = 100 v2 (9204), U5 nota_dinas N = 20 v1 (9205), U6
  surat_telegram N = 20 v1 (9206), U7 nota_dinas N = 20 v2 with ``--latar cetak`` (9207), U8 the
  fictional scanned nota_dinas (``samplegen.scanned_sample``, 300 dpi) N = 20 v2 (9208).

Media (every image long side 1600 px; page 1 unless stated):
``pdf`` the file itself; ``layar`` a screenshot (``screenshot_jpeg``, render 200 dpi);
``foto`` a basic phone photo of the page (``photo_jpeg``, view angle 0, 10, 20 or 30 degrees by
index); ``ponsel`` the same with the phone ISP (``ISP_PROFILES["ponsel"]``); ``monitor`` a phone
photo of the copy on a simulated monitor with the phone ISP (``screen_photo_jpeg``, default
``ScreenParams``); ``cetak1`` page 1 printed on the simulated laser printer and photographed
(10 or 30 degrees by index); ``cetak2`` pages 1 and 2 printed, photographed and traced together.

Every evidence is traced as the first logged trace with the stage policy ``bertahap-v1``, the
default of a recorded trace (``run_trace``, which runs both checks). Recorded per evidence (one
JSON line): the verdict (copies named at any stage, coalition members among them, anyone else,
stage-1 Z and the largest member and non-member score over Z), positions read per channel, the
background decoder's tests per page, the shipped contradiction check (flagged, bound, complete)
and its time on its own, the full bound B (every c', no early stop) at the shipped tau and at
tau = 1, the sum of squared weights, and the erasure statistic under the shipped rule, under
"semua" (every background strength, the check as it was) and under the other reading. A false
accusation is anyone outside the coalition (or anyone at all, for an unmarked master) named at
any stage; zero is required and every one is reported.

Coalitions (``tapak.collusion``; members drawn from copies 1 to N with the stated seed; the
forgery starts from the first member). Standard strategies, obeying the marking assumption
(no agreeing unit touched, ``erase_fraction`` 0): ``acak`` (a random member per cell or unit),
``salin`` (the first member), ``rata`` (the average, which erases disagreeing units of two
copies and weakens them for three), ``mayoritas``, ``minoritas``. Knowing coalitions (random
member at disagreeing units, ``erase_fraction`` 1 unless stated): ``hapus`` (agreeing marks
erased), ``balik`` (reversed), ``acak`` (randomized: a random sign per cell, the own or the
mirrored position per data unit), ``adaptif`` (reversed with the smallest fraction r on the grid
0.05, 0.10, ..., 1.00 for which no member is named in the PDF trace, found by bisection with the
real decoder and the code secret: a coalition stronger than any real one), ``buang`` (the whole
background flattened and the agreeing shift units reversed), and ``balik1`` (one copy alone,
every mark it can read reversed: the attack with the copy given twice).

Part ``kalibrasi`` (dev): copies 1 to 10 of D1, D2 and D3 through all seven media (seed [9111,
issuance, copy, medium]) with the calibration counts; and the unmarked master of each through
``pdf``, ``layar`` and ``foto`` (seed [9114, issuance, medium]).

Part ``hapus-dev`` (dev): D1, D2 and D3, coalitions of k = 2 and 3, two per issuance and k (seed
[9112, issuance, k]); ``jujur`` (the first member) and ``hapus`` through ``pdf``, ``layar``,
``foto`` and ``cetak2`` (channel seed [9113, issuance, k, coalition, medium], attack seed [9115,
issuance, k, coalition]).

Part ``jujur`` (3a, uji): U1 to U6: copies 1 to 5 and one coalition per k = 2, 3 and standard
strategy (members seed [9212, issuance, k, strategy], attack seed [9214, issuance, k, strategy])
through all seven media (channel seed [9211, issuance, unit, medium], unit = copy, or 100 + 10 k
+ strategy index); the unmarked master through ``pdf``, ``layar`` and ``foto`` (seed [9217,
issuance, medium]). U7: copies 1 to 5 and coalitions k = 2 ``acak`` and k = 3 ``mayoritas``
through ``pdf``, ``cetak1`` and ``cetak2``. U8: copies 1 to 3 and coalitions k = 2 ``acak`` and
k = 3 ``mayoritas`` through ``pdf``, ``foto`` and ``cetak2``.

Part ``sadar`` (3b, uji): U1 to U6, coalitions of k = 2 and 3, three per issuance and k (seed
[9222, issuance, k]); ``jujur``, ``hapus``, ``balik``, ``acak``, ``adaptif`` and ``buang``
through ``pdf``, ``layar`` and ``foto``, and ``jujur``, ``hapus``, ``balik`` and ``adaptif``
through ``cetak2`` (channel seed [9223, issuance, k, coalition, medium], attack seed [9224,
issuance, k, coalition, attack]); ``balik1`` of the first member of every k = 2 coalition
through ``pdf``, ``layar`` and ``foto``.

Part ``lawan`` (3c, uji): U1 to U4, coalitions k = 2 and 3, two per issuance and k (the first
two of part ``sadar``), attacks ``balik`` and ``adaptif`` (same forgeries as part ``sadar``)
and the paired honest first member, each through two ladders of code-independent degradation:
``latar`` (the PDF stays a PDF; Gaussian noise of sigma 0, 1, 2, 3, 4, 6, 8 and 12 gray levels
added to every page's background image, then the background removed; seed [9225, issuance, k,
coalition, level]) and ``raster`` (page 1 rendered at 200 dpi: lossless PNG, JPEG quality 90,
70, 50 with a Gaussian blur of 1 px, 1200 px long side with JPEG 60, then the ``foto`` medium;
seed [9226, issuance, k, coalition, level]). Analysis: per attack and ladder, the first level at
which the warning stops, and there the positions read, the sum of squared weights, whether the
coalition is named and whether the honest copy at the same level is named.

Part ``besar`` (3d, uji): U1 to U4, honest coalitions of k = 4, 5 and 6 (c + 1 to c + 3), one per
issuance, k and standard strategy (members seed [9227, issuance, k, strategy], attack seed
[9228, issuance, k, strategy]) through ``pdf``, ``layar`` and ``foto`` (channel seed [9229,
issuance, k, strategy, medium]).

Analysis fixed now: (1) part ``jujur``: per medium, the warnings, the evidence where nobody is
named, the smallest B among those, and the per-issuance count of warnings and of evidence;
masters likewise; erasure alarms per medium under the shipped rule (the honest false-alarm rate
of part 4) and under "semua"; (2) part ``sadar``: per attack and medium, escapes (no member
named), contradiction warnings, erasure warnings, warning of either kind, and false accusations;
the adaptive fraction r; (3) part ``lawan``: as stated above; (4) part ``besar``: per k and
medium, warnings, evidence where nobody is named, and members named; (5) part 4: erased prints
(``sadar`` ``hapus`` ``cetak2``) flagged under the shipped rule and under "semua", and the same
for the other media; (6) the cost of the check: median and 95th percentile of its time per
evidence, all evidence and those where nobody is named.

Usage (from the repository root; at most 3 worker processes, 1 BLAS thread each):

    python research/kontradiksi/ukur.py terbit dev            # then: terbit uji
    python research/kontradiksi/ukur.py kalibrasi --out research/kontradiksi/hasil/kalibrasi.jsonl
    python research/kontradiksi/ukur.py hapus-dev --out research/kontradiksi/hasil/hapus_dev.jsonl
    python research/kontradiksi/ukur.py pilih research/kontradiksi/hasil/kalibrasi.jsonl \\
        research/kontradiksi/hasil/hapus_dev.jsonl
    python research/kontradiksi/ukur.py jujur --out research/kontradiksi/hasil/jujur.jsonl
    python research/kontradiksi/ukur.py sadar --out research/kontradiksi/hasil/sadar.jsonl
    python research/kontradiksi/ukur.py lawan --out research/kontradiksi/hasil/lawan.jsonl
    python research/kontradiksi/ukur.py besar --out research/kontradiksi/hasil/besar.jsonl
    python research/kontradiksi/ukur.py ringkas research/kontradiksi/hasil/*.jsonl
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
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

OUT = ROOT / "out" / "kontradiksi"
WORKERS = 3
EPS = 1e-6
RATE = 1e-3
ERASURE_THRESHOLD = -3.0902
TAU_GRID = tuple(round(1.0 - 0.1 * i, 1) for i in range(10))
L_EDGES = (0.25, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, math.inf)
POISSON_LEVEL = 0.01
MEDIA = ("pdf", "layar", "foto", "ponsel", "monitor", "cetak1", "cetak2")
PHOTO_ANGLES = (0.0, 10.0, 20.0, 30.0)
PRINT_ANGLES = (10.0, 30.0)
STANDARD = ("acak", "salin", "rata", "mayoritas", "minoritas")
KNOWING = ("hapus", "balik", "acak", "adaptif", "buang")
PRINT_ATTACKS = ("jujur", "hapus", "balik", "adaptif")
ADAPTIVE_GRID = tuple(round(0.05 * i, 2) for i in range(1, 21))
NOISE_LEVELS = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, "buang")
RASTER_LEVELS = ("png", "jpeg90", "jpeg70", "blur1-jpeg50", "1200-jpeg60", "foto")

# name -> (document, N, seed, shift scheme, background profile, master kind)
ISSUANCES = {
    "D1": ("nota_dinas", 20, 9101, "v2", "layar", "teks"),
    "D2": ("surat_telegram", 20, 9102, "v2", "layar", "teks"),
    "D3": ("nota_dinas", 20, 9103, "v1", "layar", "teks"),
    "U1": ("nota_dinas", 20, 9201, "v2", "layar", "teks"),
    "U2": ("nota_dinas", 100, 9202, "v2", "layar", "teks"),
    "U3": ("surat_telegram", 20, 9203, "v2", "layar", "teks"),
    "U4": ("surat_telegram", 100, 9204, "v2", "layar", "teks"),
    "U5": ("nota_dinas", 20, 9205, "v1", "layar", "teks"),
    "U6": ("surat_telegram", 20, 9206, "v1", "layar", "teks"),
    "U7": ("nota_dinas", 20, 9207, "v2", "cetak", "teks"),
    "U8": ("nota_dinas", 20, 9208, "v2", "layar", "pindaian"),
}
SETS = {"dev": ("D1", "D2", "D3"), "uji": ("U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8")}
SEEDS = {"kalibrasi": 9111, "koalisi_dev": 9112, "kanal_dev": 9113, "induk_dev": 9114, "serangan_dev": 9115,
         "jujur": 9211, "koalisi_jujur": 9212, "serangan_jujur": 9214, "induk": 9217,
         "koalisi_sadar": 9222, "kanal_sadar": 9223, "serangan_sadar": 9224, "lawan_latar": 9225,
         "lawan_raster": 9226, "koalisi_besar": 9227, "serangan_besar": 9228, "kanal_besar": 9229}
PROTOCOL = {"eps": EPS, "c": 3, "rate": RATE, "boxes": 64, "tau_grid": TAU_GRID, "L_edges": L_EDGES,
            "poisson_level": POISSON_LEVEL, "media": MEDIA, "issuances": ISSUANCES, "seeds": SEEDS,
            "standard": STANDARD, "knowing": KNOWING, "adaptive_grid": ADAPTIVE_GRID,
            "noise_levels": NOISE_LEVELS, "raster_levels": RASTER_LEVELS,
            "spending": "pelacakan tercatat ke-1, bertahap-v1"}


# --- issuance ------------------------------------------------------------------------------


def issuance_dir(name: str) -> Path:
    """Work folder of one research issuance (gitignored)."""
    doc, n, seed, scheme, latar, kind = ISSUANCES[name]
    return OUT / f"{name}_{doc}_{n}_{seed}_{scheme}_{latar}_{kind}"


def master_path(name: str) -> Path:
    """The master PDF of an issuance: the sample, or its fictional scan."""
    doc, *_, kind = ISSUANCES[name]
    if kind == "teks":
        return ROOT / "samples" / f"{doc}.pdf"
    path = OUT / f"{doc}_pindaian.pdf"
    if not path.exists():
        from tapak.samplegen import scanned_sample

        OUT.mkdir(parents=True, exist_ok=True)
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
        if manifest.shift_scheme != want:
            raise SystemExit(f"{name}: skema {manifest.shift_scheme}, bukan {want}")
        print(f"{name}: {folder.name}, {manifest.shift_scheme}", flush=True)


# --- worker side ---------------------------------------------------------------------------

_CTX: dict[str, tuple] = {}


def _init() -> None:
    from tapak.decoder import rectify

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


def _page_image(pdf: bytes, page: int = 0) -> np.ndarray:
    from tapak.marker.render import render_pages

    return render_pages(pdf, 200, [page])[0]


def evidence(ctx, pdf: bytes, medium: str, rng: np.random.Generator, index: int) -> list:
    """Observations of one evidence made from ``pdf`` through ``medium`` (see the docstring)."""
    from tapak.decoder.trace import collect_file
    from tapak.photos import PhotoParams, PrintParams, ScreenshotParams, photo_jpeg, printed_photo_jpeg, \
        screen_photo_jpeg, screenshot_jpeg
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    if medium == "pdf":
        return collect_file("bukti.pdf", pdf, ctx)[0]
    if medium in ("cetak1", "cetak2"):
        obs = []
        angle = PRINT_ANGLES[index % len(PRINT_ANGLES)]
        for page in range(min(1 if medium == "cetak1" else 2, len(ctx.master.layout.pages))):
            data, _ = printed_photo_jpeg(pdf, page, rng, PrintParams(), PhotoParams(angle_deg=angle, long_side=1600))
            obs += collect_file(f"cetak_h{page + 1}.jpg", data, ctx)[0]
        return obs
    page = _page_image(pdf)
    params = PhotoParams(angle_deg=PHOTO_ANGLES[index % len(PHOTO_ANGLES)], long_side=1600)
    if medium == "layar":
        data, _ = screenshot_jpeg(page, rng, ScreenshotParams(render_dpi=200.0, long_side=1600))
    elif medium == "foto":
        data, _ = photo_jpeg(page, rng, params)
    elif medium == "ponsel":
        isp_rng = np.random.default_rng(int(rng.integers(2**62)))
        data, _ = photo_jpeg(page, rng, params, isp=ISP_PROFILES["ponsel"], isp_rng=isp_rng)
    elif medium == "monitor":
        isp_rng = np.random.default_rng(int(rng.integers(2**62)))
        data, _ = screen_photo_jpeg(page, rng, params, ScreenParams(), isp=ISP_PROFILES["ponsel"], isp_rng=isp_rng,
                                    render_dpi=200.0)
    else:
        raise ValueError(medium)
    return collect_file("bukti.jpg", data, ctx)[0]


def _hist(llr: np.ndarray, w: np.ndarray, wrong: np.ndarray) -> list[list[float]]:
    """Per |L| bin: [positions, wrong, expected wrong for every tau of TAU_GRID]."""
    from scipy.special import expit

    a = np.abs(llr)
    out = []
    for lo, hi in zip(L_EDGES[:-1], L_EDGES[1:]):
        sel = (w > 0) & (a >= lo) & (a < hi)
        row = [int(sel.sum()), int(wrong[sel].sum())]
        row += [round(float(np.sum(expit(-tau * a[sel]))), 4) for tau in TAU_GRID]
        out.append(row)
    return out


def _other_rule(rule: str) -> str:
    return "uji" if rule == "pola" else "pola"


def analyse(obs: list, ctx, members: set[int], x_ref: np.ndarray | None = None) -> dict:
    """Everything recorded for one evidence (module docstring). ``x_ref``: the codeword of a
    single copy, for the calibration counts."""
    from tapak.decoder.contradiction import CONTRADICTION_TEMPERING, contradiction_check
    from tapak.decoder.erasure import SILENT_BACKGROUND_RULE, erasure_check
    from tapak.decoder.fuse import fuse
    from tapak.decoder.trace import run_trace
    from tapak.tardos.detection import proven_read_miss_ceiling, tempered_error_rates
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    m = ctx.params.length
    t0 = time.perf_counter()
    res = run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY))
    t_trace = time.perf_counter() - t0
    fused = fuse(obs, m)
    eps1 = res.threshold.eps1
    t1 = time.perf_counter()
    alone = contradiction_check(fused, ctx.params, eps1, False)  # the cost, also when someone is named
    t_check = time.perf_counter() - t1
    named = sorted(res.named_seqs)
    z = res.threshold.threshold
    mem = [c.score for c in res.candidates if c.copy.seq in members]
    oth = [c.score for c in res.candidates if c.copy.seq not in members]

    def ratio(v: list[float]) -> float | None:
        return round(max(v) / z, 4) if v and math.isfinite(z) and z > 0 else None

    full = {}
    for tau in sorted({CONTRADICTION_TEMPERING, 1.0}):
        b = proven_read_miss_ceiling(ctx.params, fused.weights, tempered_error_rates(fused.llr, tau), eps1=eps1)
        full[str(tau)] = round(math.log10(b), 3) if b > 0 else None
    erasure = {}
    for rule in (SILENT_BACKGROUND_RULE, "semua", _other_rule(SILENT_BACKGROUND_RULE)):
        e = erasure_check(obs, ctx.p, rule)
        erasure[rule] = {"z": e.z, "ditandai": bool(e.flagged), "posisi": e.positions}
    con = res.contradiction
    row = {
        "putusan": {"dituduh": named, "anggota": len([s for s in named if s in members]),
                    "salah": [s for s in named if s not in members], "Z": round(z, 2) if math.isfinite(z) else None,
                    "skor_anggota": ratio(mem), "skor_lain": ratio(oth)},
        "terbaca": {sb.channel: 0 for sb in obs},
        "latar": [{k: sb.meta.get(k) for k in ("page", "pattern_found", "presence", "decoy_z", "pilot_z", "signal_z")}
                  for sb in obs if sb.channel == "background"],
        "kontradiksi": None if con is None else {"ditandai": bool(con.flagged), "log10_batas": con.log10_bound,
                                                 "lengkap": con.complete},
        "batas_penuh": full,
        "tau": CONTRADICTION_TEMPERING,
        "aturan_latar": SILENT_BACKGROUND_RULE,
        "observed": int(np.count_nonzero(fused.weights > 0)),
        "efektif": round(float(np.sum(fused.weights ** 2)), 1),
        "hapus": erasure,
        "catatan_peringatan": sum(1 for n in res.notes if n.startswith(("pola penghapusan", "bukti terbaca jelas"))),
        "detik_lacak": round(t_trace, 2),
        "detik_periksa": round(t_check, 3),
        "periksa_lengkap": None if alone is None else bool(alone.complete),
    }
    for sb in obs:
        row["terbaca"][sb.channel] += len(sb)
    if x_ref is not None:
        w = fused.weights
        wrong = (fused.y != x_ref) & (w > 0)
        row["kalibrasi"] = _hist(fused.llr, w, wrong)
    return row


def _forge(ctx, pdfs: list[bytes], attack_name: str, rng_seed: list[int], fraction: float = 1.0) -> tuple[bytes, dict]:
    """A forged PDF of the coalition ``pdfs`` (first member first) for one attack name."""
    from tapak.collusion import attack, forge_copy

    rng = np.random.default_rng(rng_seed)
    if attack_name in STANDARD:  # honest coalition: agreeing units untouched
        data, _, plan = attack(ctx.master, pdfs, attack_name, 0.0, rng=rng)
        return data, plan.counts
    if attack_name == "buang":
        data, _, plan = attack(ctx.master, pdfs, "acak", 1.0, rng=rng, neutralize="balik")
        for lv in plan.levels.values():
            lv[:] = 0.0
        return forge_copy(ctx.master, pdfs, plan), plan.counts
    neutralize = {"hapus": "hapus", "balik": "balik", "adaptif": "balik", "acak": "acak", "balik1": "balik"}[attack_name]
    data, _, plan = attack(ctx.master, pdfs, "acak", fraction, rng=rng, neutralize=neutralize)
    return data, plan.counts


def _members_named(pdf: bytes, ctx, members: set[int]) -> bool:
    from tapak.decoder.trace import collect_file, run_trace
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    obs = collect_file("bukti.pdf", pdf, ctx)[0]
    res = run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY))
    return bool(res.named_seqs & members)


def adaptive(ctx, pdfs: list[bytes], members: set[int], rng_seed: list[int]) -> tuple[bytes, dict, float]:
    """The smallest reversed fraction on ADAPTIVE_GRID with no member named in the PDF trace."""
    lo, hi = -1, len(ADAPTIVE_GRID) - 1  # the last grid value reverses everything
    cache: dict[int, bytes] = {}
    counts: dict = {}
    while hi - lo > 1:
        mid = (lo + hi) // 2
        data, counts = _forge(ctx, pdfs, "adaptif", rng_seed, ADAPTIVE_GRID[mid])
        cache[mid] = data
        if _members_named(data, ctx, members):
            lo = mid
        else:
            hi = mid
    if hi not in cache:
        cache[hi], counts = _forge(ctx, pdfs, "adaptif", rng_seed, ADAPTIVE_GRID[hi])
    return cache[hi], counts, ADAPTIVE_GRID[hi]


def _replace_backgrounds(pdf: bytes, change) -> bytes:
    """The PDF with every page's background image (its largest image) replaced by change(img)."""
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for page in doc:
            best = None
            for info in page.get_images(full=True):
                area = max((r.width * r.height for r in page.get_image_rects(info[0])), default=0.0)
                if best is None or area > best[0]:
                    best = (area, info[0])
            if best is None:
                continue
            pix = pymupdf.Pixmap(doc, best[1])
            if pix.n - pix.alpha != 1:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0]
            new = np.ascontiguousarray(change(img.astype(np.float64)).clip(0, 255).round().astype(np.uint8))
            page.replace_image(best[1], pixmap=pymupdf.Pixmap(pymupdf.csGRAY, new.shape[1], new.shape[0],
                                                                new.tobytes(), False))
        return doc.tobytes(garbage=3, deflate=True)


def degrade_latar(pdf: bytes, level, rng: np.random.Generator) -> bytes:
    """Ladder ``latar``: Gaussian noise of ``level`` gray levels on the background, or removed."""
    if level == "buang":
        return _replace_backgrounds(pdf, lambda img: np.full_like(img, float(np.median(img))))
    if level == 0:
        return pdf
    return _replace_backgrounds(pdf, lambda img: img + rng.normal(0.0, float(level), img.shape))


def degrade_raster(pdf: bytes, level: str, rng: np.random.Generator, index: int) -> tuple[str, bytes]:
    """Ladder ``raster``: page 1 as an image file (name, bytes)."""
    import cv2

    from tapak.photos import PhotoParams, encode_jpeg, photo_jpeg

    page = _page_image(pdf)
    if level == "png":
        return "bukti.png", cv2.imencode(".png", page.clip(0, 255).astype(np.uint8))[1].tobytes()
    if level.startswith("jpeg"):
        return "bukti.jpg", encode_jpeg(page, int(level[4:]))
    if level == "blur1-jpeg50":
        return "bukti.jpg", encode_jpeg(cv2.GaussianBlur(page.astype(np.float32), (0, 0), 1.0), 50)
    if level == "1200-jpeg60":
        h, w = page.shape
        s = 1200 / max(h, w)
        small = cv2.resize(page.astype(np.float32), (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        return "bukti.jpg", encode_jpeg(small, 60)
    if level == "foto":
        data, _ = photo_jpeg(page, rng, PhotoParams(angle_deg=PHOTO_ANGLES[index % len(PHOTO_ANGLES)], long_side=1600))
        return "bukti.jpg", data
    raise ValueError(level)


# --- jobs ----------------------------------------------------------------------------------


def _base(part: str, name: str) -> dict:
    doc, n, seed, scheme, latar, kind = ISSUANCES[name]
    return {"bagian": part, "terbitan": name, "dok": doc, "N": n, "benih": seed, "skema": scheme, "latar_profil": latar,
            "induk": kind}


def _media(name: str) -> tuple[str, ...]:
    if name == "U7":
        return ("pdf", "cetak1", "cetak2")
    if name == "U8":
        return ("pdf", "foto", "cetak2")
    return MEDIA


def kalibrasi_job(job: tuple) -> list[dict]:
    """Part kalibrasi: one honest copy (seq >= 1) or the master (seq 0) through its media."""
    name, iss, seq = job
    ctx, _ = context(name)
    rows = []
    if seq == 0:
        pdf = ctx.master.pdf_bytes
        for mi, medium in enumerate(("pdf", "layar", "foto")):
            obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["induk_dev"], iss, mi]), mi)
            rows.append({**_base("kalibrasi", name), "unit": "induk", "kanal": medium, **analyse(obs, ctx, set())})
        return rows
    pdf = copy_pdf(name, seq)
    x = ctx.codewords[seq - 1].astype(np.uint8)
    for mi, medium in enumerate(MEDIA):
        obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["kalibrasi"], iss, seq, mi]), seq)
        rows.append({**_base("kalibrasi", name), "unit": "salinan", "salinan": seq, "kanal": medium,
                     **analyse(obs, ctx, {seq}, x)})
    return rows


def hapus_dev_job(job: tuple) -> list[dict]:
    """Part hapus-dev: one coalition, honest first member and erased forgery, four media."""
    name, iss, k, ci, members = job
    ctx, _ = context(name)
    pdfs = [copy_pdf(name, s) for s in members]
    forged = {"jujur": pdfs[0], "hapus": _forge(ctx, pdfs, "hapus", [SEEDS["serangan_dev"], iss, k, ci])[0]}
    rows = []
    for mi, medium in enumerate(("pdf", "layar", "foto", "cetak2")):
        for att, data in forged.items():
            obs = evidence(ctx, data, medium, np.random.default_rng([SEEDS["kanal_dev"], iss, k, ci, mi]), ci)
            rows.append({**_base("hapus-dev", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": att,
                         "kanal": medium, **analyse(obs, ctx, set(members))})
    return rows


def jujur_job(job: tuple) -> list[dict]:
    """Part jujur: one honest unit (a copy, a standard coalition, or the master) through its media."""
    name, iss, unit = job
    ctx, _ = context(name)
    n = ctx.params.n_max
    rows = []
    if unit == "induk":
        for mi, medium in enumerate(("pdf", "layar", "foto")):
            obs = evidence(ctx, ctx.master.pdf_bytes, medium, np.random.default_rng([SEEDS["induk"], iss, mi]), mi)
            rows.append({**_base("jujur", name), "unit": "induk", "kanal": medium, **analyse(obs, ctx, set())})
        return rows
    if isinstance(unit, int):
        members, pdf, label, uid = [unit], copy_pdf(name, unit), "salinan", unit
        x = ctx.codewords[unit - 1].astype(np.uint8)
    else:
        k, rule = unit
        si = STANDARD.index(rule)
        members = members_of([SEEDS["koalisi_jujur"], iss, k, si], n, k)
        pdf, _ = _forge(ctx, [copy_pdf(name, s) for s in members], rule, [SEEDS["serangan_jujur"], iss, k, si])
        label, uid, x = f"koalisi/{rule}", 100 + 10 * k + si, None
    for mi, medium in enumerate(_media(name)):
        obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["jujur"], iss, uid, MEDIA.index(medium)]), uid)
        rows.append({**_base("jujur", name), "unit": label, "k": len(members), "koalisi": members, "kanal": medium,
                     **analyse(obs, ctx, set(members), x)})
    return rows


def sadar_job(job: tuple) -> list[dict]:
    """Part sadar: one knowing coalition, every attack, its media."""
    name, iss, k, ci, members = job
    ctx, _ = context(name)
    pdfs = [copy_pdf(name, s) for s in members]
    forged: dict[str, tuple[bytes, dict, float | None]] = {"jujur": (pdfs[0], {}, None)}
    for ai, att in enumerate(KNOWING):
        seed = [SEEDS["serangan_sadar"], iss, k, ci, ai]
        if att == "adaptif":
            forged[att] = adaptive(ctx, pdfs, set(members), seed)
        else:
            data, counts = _forge(ctx, pdfs, att, seed)
            forged[att] = (data, counts, None)
    if k == 2:
        data, counts = _forge(ctx, [pdfs[0], pdfs[0]], "balik1", [SEEDS["serangan_sadar"], iss, k, ci, 9])
        forged["balik1"] = (data, counts, None)
    rows = []
    for mi, medium in enumerate(("pdf", "layar", "foto", "cetak2")):
        for att, (data, counts, frac) in forged.items():
            if medium == "cetak2" and att not in PRINT_ATTACKS:
                continue
            group = {members[0]} if att == "balik1" else set(members)
            obs = evidence(ctx, data, medium, np.random.default_rng([SEEDS["kanal_sadar"], iss, k, ci, mi]), ci)
            rows.append({**_base("sadar", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": att,
                         "r": frac, "rencana": counts, "kanal": medium, **analyse(obs, ctx, group)})
    return rows


def lawan_job(job: tuple) -> list[dict]:
    """Part lawan: one coalition's balik and adaptif forgeries and its honest first member, both ladders."""
    name, iss, k, ci, members = job
    from tapak.decoder.trace import collect_file

    ctx, _ = context(name)
    pdfs = [copy_pdf(name, s) for s in members]
    sources = {"jujur": pdfs[0],
               "balik": _forge(ctx, pdfs, "balik", [SEEDS["serangan_sadar"], iss, k, ci, KNOWING.index("balik")])[0],
               "adaptif": adaptive(ctx, pdfs, set(members),
                                   [SEEDS["serangan_sadar"], iss, k, ci, KNOWING.index("adaptif")])[0]}
    rows = []
    for li, level in enumerate(NOISE_LEVELS):
        for src, pdf in sources.items():
            data = degrade_latar(pdf, level, np.random.default_rng([SEEDS["lawan_latar"], iss, k, ci, li]))
            obs = collect_file("bukti.pdf", data, ctx)[0]
            rows.append({**_base("lawan", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": src,
                         "tangga": "latar", "tingkat": str(level), "urut": li, **analyse(obs, ctx, set(members))})
    for li, level in enumerate(RASTER_LEVELS):
        for src, pdf in sources.items():
            fname, data = degrade_raster(pdf, level, np.random.default_rng([SEEDS["lawan_raster"], iss, k, ci, li]), ci)
            obs = collect_file(fname, data, ctx)[0]
            rows.append({**_base("lawan", name), "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": src,
                         "tangga": "raster", "tingkat": level, "urut": li, **analyse(obs, ctx, set(members))})
    return rows


def besar_job(job: tuple) -> list[dict]:
    """Part besar: one honest coalition larger than c through pdf, layar and foto."""
    name, iss, k, rule = job
    ctx, _ = context(name)
    si = STANDARD.index(rule)
    members = members_of([SEEDS["koalisi_besar"], iss, k, si], ctx.params.n_max, k)
    pdf, _ = _forge(ctx, [copy_pdf(name, s) for s in members], rule, [SEEDS["serangan_besar"], iss, k, si])
    rows = []
    for mi, medium in enumerate(("pdf", "layar", "foto")):
        obs = evidence(ctx, pdf, medium, np.random.default_rng([SEEDS["kanal_besar"], iss, k, si, mi]), si)
        rows.append({**_base("besar", name), "k": k, "koalisi": members, "aturan": rule, "kanal": medium,
                     **analyse(obs, ctx, set(members))})
    return rows


def kalibrasi_jobs() -> list[tuple]:
    return [(name, i, seq) for i, name in enumerate(SETS["dev"]) for seq in range(0, 11)]


def hapus_dev_jobs() -> list[tuple]:
    jobs = []
    for i, name in enumerate(SETS["dev"]):
        n = ISSUANCES[name][1]
        for k in (2, 3):
            rng = np.random.default_rng([SEEDS["koalisi_dev"], i, k])
            for ci in range(2):
                members = sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
                jobs.append((name, i, k, ci, members))
    return jobs


def jujur_jobs() -> list[tuple]:
    jobs = []
    for i, name in enumerate(SETS["uji"]):
        if name in ("U7", "U8"):
            copies = range(1, 6) if name == "U7" else range(1, 4)
            jobs += [(name, i, s) for s in copies] + [(name, i, (2, "acak")), (name, i, (3, "mayoritas"))]
            continue
        jobs += [(name, i, s) for s in range(1, 6)]
        jobs += [(name, i, (k, rule)) for k in (2, 3) for rule in STANDARD]
        jobs.append((name, i, "induk"))
    return jobs


def _knowing_coalitions(names: tuple[str, ...], per: int) -> list[tuple]:
    jobs = []
    for name in names:
        i = SETS["uji"].index(name)
        n = ISSUANCES[name][1]
        for k in (2, 3):
            rng = np.random.default_rng([SEEDS["koalisi_sadar"], i, k])
            for ci in range(3):
                members = sorted(int(s) for s in rng.choice(np.arange(1, n + 1), size=k, replace=False))
                if ci < per:
                    jobs.append((name, i, k, ci, members))
    return jobs


def sadar_jobs() -> list[tuple]:
    return _knowing_coalitions(("U1", "U2", "U3", "U4", "U5", "U6"), 3)


def lawan_jobs() -> list[tuple]:
    return _knowing_coalitions(("U1", "U2", "U3", "U4"), 2)


def besar_jobs() -> list[tuple]:
    return [(name, SETS["uji"].index(name), k, rule) for name in ("U1", "U2", "U3", "U4") for k in (4, 5, 6)
            for rule in STANDARD]


PARTS = {"kalibrasi": (kalibrasi_job, kalibrasi_jobs), "hapus-dev": (hapus_dev_job, hapus_dev_jobs),
         "jujur": (jujur_job, jujur_jobs), "sadar": (sadar_job, sadar_jobs), "lawan": (lawan_job, lawan_jobs),
         "besar": (besar_job, besar_jobs)}


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
    with out.open("a", encoding="utf-8") as fh, ProcessPoolExecutor(WORKERS, mp_context=mp.get_context("spawn"),
                                                                    initializer=_init) as pool:
        for job, rows in zip(todo, pool.map(_job, [(part, j) for j in todo])):
            for r in rows:
                fh.write(json.dumps({"job": json.dumps(job), **r}) + "\n")
            fh.flush()
            print(f"{len(rows)} baris, {job}", flush=True)


def _job(item: tuple) -> list[dict]:
    part, job = item
    return PARTS[part][0](tuple(job) if isinstance(job, list) else job)


# --- decisions on dev ------------------------------------------------------------------------


def choose(paths: list[str]) -> dict:
    """The two dev choices, by the rules of the module docstring."""
    from scipy.stats import poisson

    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    cal: dict[str, np.ndarray] = {}
    for r in rows:
        if r["bagian"] == "kalibrasi" and "kalibrasi" in r:
            cal.setdefault(r["kanal"], np.zeros((len(L_EDGES) - 1, 2 + len(TAU_GRID))))
            cal[r["kanal"]] += np.array(r["kalibrasi"], dtype=np.float64)
    passing = []
    detail = {}
    for ti, tau in enumerate(TAU_GRID):
        worst = 1.0
        for medium, h in cal.items():
            for b in range(h.shape[0]):
                k, e = h[b, 1], h[b, 2 + ti]
                if e > 0 or k > 0:
                    pv = float(poisson.sf(k - 1, e)) if e > 0 else 0.0
                    worst = min(worst, pv)
        detail[str(tau)] = worst
        if worst >= POISSON_LEVEL:
            passing.append(tau)
    tau = max(passing) if passing else 0.1
    honest = [r for r in rows if r.get("unit") in ("salinan", "induk") or r.get("serangan") == "jujur"]
    erased = [r for r in rows if r.get("serangan") == "hapus"]
    score = {}
    for rule in ("pola", "uji"):
        score[rule] = (sum(r["hapus"][rule]["ditandai"] for r in erased), sum(r["hapus"][rule]["ditandai"] for r in honest))
    a, b = score["pola"], score["uji"]
    rule = "uji" if (b[0] > a[0] and b[1] <= a[1]) else "pola"
    return {"tau": tau, "tau_p_terburuk": detail, "aturan_latar": rule, "aturan_skor": score,
            "kalibrasi": {m: h.tolist() for m, h in cal.items()}, "n_jujur": len(honest), "n_hapus": len(erased)}


# --- summary -------------------------------------------------------------------------------


def _warned(r: dict) -> bool:
    return bool(r["kontradiksi"] and r["kontradiksi"]["ditandai"])


def _erasure(r: dict, rule: str | None = None) -> bool:
    return bool(r["hapus"][rule or r["aturan_latar"]]["ditandai"])


def _wrong(rows: list[dict]) -> list:
    return [(r["bagian"], r["terbitan"], r.get("serangan", r.get("unit")), r["kanal"], r["putusan"]["salah"])
            for r in rows if r["putusan"]["salah"]]


def summary(paths: list[str]) -> int:
    """Tables of the analysis fixed in the module docstring."""
    rows = [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines() if line]
    by = defaultdict(list)
    for r in rows:
        by[r["bagian"]].append(r)
    wrong = _wrong(rows)
    print(f"tuduhan salah: {len(wrong)} dari {len(rows)} pelacakan {wrong[:5]}")
    honest = by.get("jujur", [])
    if honest:
        print("\n(1) jujur per medium: peringatan kontradiksi / tanpa nama / bukti; B terkecil tanpa nama; "
              "alarm hapus aturan kini / semua")
        cells = defaultdict(list)
        for r in honest:
            cells[(r["unit"] == "induk", r["kanal"])].append(r)
        for (master, medium), rs in sorted(cells.items()):
            silent = [r for r in rs if not r["putusan"]["dituduh"]]
            bmin = min((r["kontradiksi"]["log10_batas"] for r in silent if r["kontradiksi"]), default=None)
            print(f"  {'induk ' if master else ''}{medium:8s} {sum(map(_warned, rs)):3d} / {len(silent):3d} / "
                  f"{len(rs):3d}; log10 B terkecil {bmin}; hapus {sum(_erasure(r) for r in rs)} / "
                  f"{sum(_erasure(r, 'semua') for r in rs)}")
        per_iss = defaultdict(lambda: [0, 0, 0])
        for r in honest:
            c = per_iss[r["terbitan"]]
            c[0] += _warned(r)
            c[1] += not r["putusan"]["dituduh"]
            c[2] += 1
        print("  per terbitan (peringatan / tanpa nama / bukti): "
              + ", ".join(f"{k} {v[0]}/{v[1]}/{v[2]}" for k, v in sorted(per_iss.items())))
        units = defaultdict(lambda: [0, 0, 0])
        for r in honest:
            u = units[r["unit"]]
            u[0] += _warned(r)
            u[1] += not r["putusan"]["dituduh"]
            u[2] += 1
        print("  per unit: " + ", ".join(f"{k} {v[0]}/{v[1]}/{v[2]}" for k, v in sorted(units.items())))
    knowing = by.get("sadar", [])
    if knowing:
        print("\n(2) sadar: lolos / kontradiksi / hapus / salah satu / dari n; per skema")
        cells = defaultdict(list)
        for r in knowing:
            cells[(r["skema"], r["serangan"], r["kanal"])].append(r)
        for (scheme, att, medium), rs in sorted(cells.items()):
            esc = sum(r["putusan"]["anggota"] == 0 for r in rs)
            con = sum(map(_warned, rs))
            era = sum(_erasure(r) for r in rs)
            either = sum(_warned(r) or _erasure(r) for r in rs)
            extra = ""
            if att == "adaptif":
                extra = f"; r median {np.median([r['r'] for r in rs]):.2f} ({min(r['r'] for r in rs)}..{max(r['r'] for r in rs)})"
            print(f"  {scheme} {att:8s} {medium:7s} {esc:3d} / {con:3d} / {era:3d} / {either:3d} / {len(rs):3d}"
                  f"; hapus semua {sum(_erasure(r, 'semua') for r in rs)}{extra}")
    counter = by.get("lawan", [])
    if counter:
        print("\n(3) lawan: tingkat pertama tanpa peringatan; di sana posisi, sum w^2, anggota disebut, jujur disebut")
        grouped = defaultdict(dict)
        for r in counter:
            grouped[(r["terbitan"], r["k"], r["koalisi_ke"], r["tangga"])][(r["serangan"], r["urut"])] = r
        stats = defaultdict(list)
        for (iss, k, ci, ladder), cell in sorted(grouped.items()):
            levels = sorted({u for (_, u) in cell})
            for att in ("balik", "adaptif"):
                first = next((u for u in levels if (att, u) in cell and not _warned(cell[(att, u)])), None)
                warned0 = _warned(cell[(att, levels[0])]) if (att, levels[0]) in cell else None
                if first is None:
                    stats[(att, ladder)].append(("tidak berhenti", warned0, None, None, None, None))
                    continue
                r, h = cell[(att, first)], cell.get(("jujur", first))
                stats[(att, ladder)].append((r["tingkat"], warned0, r["observed"], r["efektif"],
                                             r["putusan"]["anggota"] > 0, bool(h and h["putusan"]["anggota"] > 0)))
        for (att, ladder), vals in sorted(stats.items()):
            print(f"  {att:8s} {ladder:7s} n {len(vals)}; peringatan di tingkat 0: {sum(bool(v[1]) for v in vals)}")
            for v in vals:
                print(f"     berhenti di {v[0]}: posisi {v[2]}, sum w^2 {v[3]}, anggota disebut {v[4]}, jujur disebut {v[5]}")
    large = by.get("besar", [])
    if large:
        print("\n(4) besar: peringatan / tanpa anggota disebut / bukti; anggota disebut rata-rata")
        cells = defaultdict(list)
        for r in large:
            cells[(r["k"], r["kanal"])].append(r)
        for (k, medium), rs in sorted(cells.items()):
            print(f"  k {k} {medium:6s} {sum(map(_warned, rs)):3d} / {sum(r['putusan']['anggota'] == 0 for r in rs):3d}"
                  f" / {len(rs):3d}; anggota {np.mean([r['putusan']['anggota'] for r in rs]):.2f}")
    if knowing:
        print("\n(5) bagian 4: bukti hapus ditandai, aturan kini / semua / lainnya")
        for medium in ("pdf", "layar", "foto", "cetak2"):
            rs = [r for r in knowing if r["serangan"] == "hapus" and r["kanal"] == medium]
            if rs:
                rule = rs[0]["aturan_latar"]
                print(f"  {medium:7s} {sum(_erasure(r) for r in rs)} / {sum(_erasure(r, 'semua') for r in rs)} / "
                      f"{sum(_erasure(r, _other_rule(rule)) for r in rs)} dari {len(rs)}")
    if rows:
        t = np.array([r["detik_periksa"] for r in rows])
        silent = np.array([r["detik_periksa"] for r in rows if not r["putusan"]["dituduh"]])
        print(f"\n(6) waktu pemeriksaan: median {np.median(t):.2f} s, persentil 95 {np.percentile(t, 95):.2f} s "
              f"({len(t)} bukti); tanpa nama median {np.median(silent) if silent.size else float('nan'):.2f} s; "
              f"pelacakan median {np.median([r['detik_lacak'] for r in rows]):.1f} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "pilih", "ringkas", *PARTS])
    ap.add_argument("paths", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.bagian == "terbit":
        issue_all(args.paths[0])
    elif args.bagian == "pilih":
        print(json.dumps(choose(args.paths), indent=1))
    elif args.bagian == "ringkas":
        return summary(args.paths)
    else:
        _run(args.bagian, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
