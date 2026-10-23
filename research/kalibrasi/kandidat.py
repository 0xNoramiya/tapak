"""Code-blind noise models for the background decoder, scored on development seeds only.

Every evidence of ``ukur.py`` keeps its registration and observations. For an image evidence
this script warps the same image with the same homography, measures the page once
(``ch_background.measure_background``) and decodes the background channel again with every
candidate noise model (``ch_background.background_soft_bits`` with a :data:`CellNoiseModel`),
puts that output in place of the stored background output and accuses exactly as ``ukur.py``
does (``ukur.analyse``). PDF evidence and evidence whose page was not found are the same for
every candidate (the PDF decoder takes no noise model).

Why these candidates. On development screenshots (K1, before this script) the standardized
residual of a cell, (u_c - g s_b) sqrt(n_c / v), had a variance of 2 to 3 within one cell of the
master's ink and 0.3 to 0.6 from two cells on, and after JPEG the pattern itself was attenuated
near text (mean u_c s_b / g 0.24 to 0.5 within half a cell at 40 and 56 dpi). One gain and one
noise variance per saturation stratum therefore overweights the cells next to text, and their
errors land in the top weight bin. Every candidate keeps the saturation strata and adds classes
of the distance from a cell to the master's ink (``ch_background.ink_distance_cells``), which
depend on the master alone:

* ``kejenuhan``: the decoder before this study (``ch_background.saturation_noise``);
* ``jarak_var``: gain per saturation stratum (pilot regression, as before); noise variance per
  saturation stratum and distance class, E[n u^2] - g^2 E[n] over the class's cells;
* ``jarak_gain``: gain and noise variance per saturation stratum and distance class, both by the
  pilot regression of ``stratum_gains`` on the combined class;
* ``jarak_pasangan``: gain per saturation stratum; noise variance per stratum and distance class
  from the cells of the same bit, whose pattern is the same: E[(u_c - u_c')^2] = v_c / n_c +
  v_c' / n_c' for two cells of one bit in one stratum, solved by least squares over all such
  pairs (no pilot, no codeword);
* ``jarak_gain_pasangan``: gain per stratum and class as ``jarak_gain``; variance from the pairs
  of cells of one bit, after taking off (g_c - g_c')^2;
* ``jarak_var_redam`` and ``jarak_gain_redam``: ``jarak_var`` and ``jarak_gain`` with every noise
  variance times REDAM (the LLRs times 1 / REDAM), a conservative variant in case the first ones
  stay overconfident.

A stratum and class with fewer than MIN_CLASS_CELLS cells takes the gain and variance of its
saturation stratum (the decoder before), so no cell is dropped that was used before. Distance
classes: CLASS_EDGES (cells).

The rule (``ATURAN``) is written here and committed before any candidate is scored on the full
development set; ``pilih`` applies it to ``hasil/dev_kandidat.jsonl.gz`` and writes
``hasil/pilihan.json``.

Usage (work folder as ``ukur.py``):

    python research/kalibrasi/kandidat.py periksa --split dev    # kejenuhan reproduces every stored output
    python research/kalibrasi/kandidat.py nilai --split dev
    python research/kalibrasi/kandidat.py pilih
    python research/kalibrasi/kandidat.py banding --split uji    # after the held-out run: the decoder before
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ukur  # noqa: E402

from tapak.decoder import ch_background as B  # noqa: E402

CLASS_EDGES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
MIN_CLASS_CELLS = 200
REDAM = 1.5
CANDIDATES = ("kejenuhan", "jarak_var", "jarak_gain", "jarak_pasangan", "jarak_gain_pasangan", "jarak_var_redam",
              "jarak_gain_redam")
# Medium classes of the calibration rule: the forwarded PDF, real-renderer screenshots per format
# and resolution band, and the simulated photo media.
BANDS = (("28-48", 28, 48), ("56-84", 56, 84), ("96-150", 96, 150))
ATURAN = {
    "1_tanpa_tuduhan_salah": "tidak ada tuduhan salah di pelacakan dev mana pun (salinan, koalisi jujur, induk tanpa tanda)",
    "2_tanpa_putusan_hilang": ("setiap salinan dev yang disebut dekoder sekarang tetap disebut, dan setiap koalisi dev "
                               "tidak kehilangan anggota yang disebut (tahap mana pun)"),
    "3_tanpa_peringatan_baru": ("tidak ada pelacakan jujur dev (salinan, koalisi jujur, induk tanpa tanda) tanpa "
                                "peringatan dengan dekoder sekarang yang mendapat peringatan (pola penghapusan, bacaan "
                                "jelas tanpa nama, atau pola tanda terbalik) dengan kandidat"),
    "4_kalibrasi": ("bobot pola latar salinan dev, per kelas medium (pdf; png, pesan, kecil x 28-48, 56-84, 96-150 dpi; "
                    "layar_sim; foto; ponsel; monitor; cetak) dan kelompok bobot W_EDGES: dengan n bit, k salah, dan "
                    "E = jumlah 1 / (1 + exp |L|), P(Poisson(E) >= k) >= 1e-4 (tidak terlalu yakin secara bermakna)"),
    "5_pilihan": ("di antara kandidat yang lolos 1 sampai 4, galat kalibrasi terkecil: rata-rata atas kelas medium dari "
                  "jumlah |k - E| atas kelompok bobot dibagi jumlah bit kelas itu; seri: lebih banyak putusan benar, "
                  "lalu median skor salinan / Z lebih besar; tidak ada yang lolos: dekoder tetap kejenuhan"),
    "level_poisson": 1e-4,
}


# --- candidate noise models (research implementations; the chosen one is ported to tapak) ----


def distance_class(distance: np.ndarray | None, n: int) -> np.ndarray:
    """Distance class (0 .. len(CLASS_EDGES) - 1) of every cell; class 0 for all when not measured."""
    if distance is None:
        return np.zeros(n, dtype=np.int64)
    return np.searchsorted(np.asarray(CLASS_EDGES), np.asarray(distance, dtype=np.float64), side="right") - 1


def _combined(stratum: np.ndarray, cls: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    k = len(CLASS_EDGES)
    comb = stratum * k + cls
    n_comb = len(B.SAT_EDGES) * k
    counts = np.bincount(comb, minlength=n_comb)
    return comb, n_comb, counts


def jarak_var(u, e, stratum, weight, distance, redam: float = 1.0):
    """Gain per saturation stratum, noise variance per stratum and distance class."""
    g_s, v_s = B.stratum_gains(u, e, stratum, len(B.SAT_EDGES), weight)
    g_c, v_c = g_s[stratum], v_s[stratum].copy()
    comb, n_comb, counts = _combined(stratum, distance_class(distance, u.size))
    power = np.bincount(comb, weights=weight * u * u, minlength=n_comb) / np.maximum(counts, 1)
    mean_w = np.bincount(comb, weights=weight, minlength=n_comb) / np.maximum(counts, 1)
    for k in np.flatnonzero(counts >= MIN_CLASS_CELLS):
        j = k // len(CLASS_EDGES)
        m = comb == k
        v_c[m] = max(power[k] - g_s[j] ** 2 * mean_w[k], max(0.01 * power[k], 1e-300))
    return g_c, v_c * redam


def jarak_gain(u, e, stratum, weight, distance, redam: float = 1.0):
    """Gain and noise variance per saturation stratum and distance class (pilot regression)."""
    g_s, v_s = B.stratum_gains(u, e, stratum, len(B.SAT_EDGES), weight)
    g_c, v_c = g_s[stratum].copy(), v_s[stratum].copy()
    comb, n_comb, counts = _combined(stratum, distance_class(distance, u.size))
    g_k, v_k = B.stratum_gains(u, e, comb, n_comb, weight)
    big = counts[comb] >= MIN_CLASS_CELLS
    g_c[big] = g_k[comb[big]]
    v_c[big] = v_k[comb[big]]
    return g_c, v_c * redam


def _pairs(bits: np.ndarray, group: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Every pair of cells of the same bit in the same group (saturation stratum)."""
    key = bits.astype(np.int64) * 64 + group.astype(np.int64)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    ends = np.r_[starts[1:], ks.size]
    first, second = [], []
    for a, b in zip(starts, ends):
        if b - a < 2:
            continue
        idx = order[a:b]
        i, j = np.triu_indices(b - a, 1)
        first.append(idx[i])
        second.append(idx[j])
    if not first:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(first), np.concatenate(second)


_BITS: dict = {}  # the bit index of every cell, set by the caller before the pair models run


def _pair_variance(u, weight, comb, n_comb, counts, gains: np.ndarray | None, fallback: np.ndarray,
                   stratum: np.ndarray) -> np.ndarray:
    bits = _BITS["bits"]
    i, j = _pairs(bits, stratum)
    v_c = fallback.copy()
    if i.size == 0:
        return v_c
    y = (u[i] - u[j]) ** 2
    if gains is not None:
        y = y - (gains[i] - gains[j]) ** 2
    cols = np.unique(np.r_[comb[i], comb[j]])
    index = {c: n for n, c in enumerate(cols)}
    x = np.zeros((i.size, cols.size))
    rows = np.arange(i.size)
    np.add.at(x, (rows, np.array([index[c] for c in comb[i]])), 1.0 / weight[i])
    np.add.at(x, (rows, np.array([index[c] for c in comb[j]])), 1.0 / weight[j])
    a, *_ = np.linalg.lstsq(x, y, rcond=None)
    for n, c in enumerate(cols):
        if counts[c] >= MIN_CLASS_CELLS and a[n] > 0:
            v_c[comb == c] = a[n]
    return v_c


def jarak_pasangan(u, e, stratum, weight, distance, redam: float = 1.0):
    """Gain per saturation stratum; noise variance per stratum and class from pairs of cells of one bit."""
    g_s, v_s = B.stratum_gains(u, e, stratum, len(B.SAT_EDGES), weight)
    comb, n_comb, counts = _combined(stratum, distance_class(distance, u.size))
    v_c = _pair_variance(u, weight, comb, n_comb, counts, None, v_s[stratum], stratum)
    return g_s[stratum], v_c * redam


def jarak_gain_pasangan(u, e, stratum, weight, distance, redam: float = 1.0):
    """Gain per stratum and class (pilot); variance from pairs of cells of one bit, gains taken off."""
    g_c, v_fallback = jarak_gain(u, e, stratum, weight, distance)
    comb, n_comb, counts = _combined(stratum, distance_class(distance, u.size))
    v_c = _pair_variance(u, weight, comb, n_comb, counts, g_c, v_fallback, stratum)
    return g_c, v_c * redam


MODELS = {
    "kejenuhan": B.saturation_noise,
    "jarak_var": jarak_var,
    "jarak_gain": jarak_gain,
    "jarak_pasangan": jarak_pasangan,
    "jarak_gain_pasangan": jarak_gain_pasangan,
    "jarak_var_redam": lambda *a: jarak_var(*a, redam=REDAM),
    "jarak_gain_redam": lambda *a: jarak_gain(*a, redam=REDAM),
}


def with_bits(model, grid, measure):
    """The pair models need each used cell's bit index: wrap a model so it sees them."""
    ok = (measure.frac >= B.MIN_VALID_FRACTION) & (grid.cell_bit >= 0)
    bits = grid.cell_bit[ok]

    def wrapped(u, e, stratum, weight, distance):
        _BITS["bits"] = bits
        return model(u, e, stratum, weight, distance)

    return wrapped


# --- re-decoding ---------------------------------------------------------------------------


def load_obs(job: dict) -> dict:
    with ukur.obs_path(job).open("rb") as fh:
        return pickle.load(fh)


def measure_of(job: dict, stored: dict):
    """(measure, grid, reg meta) of an image evidence from its stored registration."""
    from tapak.decoder.rectify import load_gray, render_page, warp_to_page
    from tapak.marker.background import page_grids

    ctx, _ = ukur.context(job["iss"])
    _, data, _ = ukur.evidence(job)
    reg = stored["reg"]
    sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
    page, dpi = reg["page"], reg["dpi"]
    w_pt, h_pt = sizes[page]
    size = (int(round(w_pt * dpi / 72.0)), int(round(h_pt * dpi / 72.0)))
    rect, valid = warp_to_page(load_gray(data), np.asarray(reg["h_page_to_img"]), size)
    master_render = render_page(ctx.master.pdf_bytes, page, dpi)
    grid = page_grids(sizes, ctx.key, ctx.background)[page]
    measure = B.measure_background(rect, valid, master_render, dpi, grid, image=True)
    reg_meta = {"page": page, "dpi": dpi, "correlation": round(reg["correlation"], 4), "method": reg["method"],
                "effective_dpi": round(reg["effective_dpi"], 1)}
    return measure, grid, reg_meta


def redecoded(job: dict, stored: dict, names: tuple[str, ...]) -> dict[str, list]:
    """Observations of an evidence with the background decoded again by every model in ``names``."""
    ctx, _ = ukur.context(job["iss"])
    obs = stored["obs"]
    index = [i for i, sb in enumerate(obs) if sb.channel == "background"]
    if stored["reg"] is None or not index:
        return {name: obs for name in names}
    measure, grid, reg_meta = measure_of(job, stored)
    out = {}
    for name in names:
        sb = B.background_soft_bits(measure, grid, ctx.plan.channel("background"), ctx.p,
                                    with_bits(MODELS[name], grid, measure))
        sb.meta.update(reg_meta)
        new = list(obs)
        new[index[0]] = sb
        out[name] = new
    return out


def same_soft_bits(a, b) -> bool:
    """Exact equality of two background outputs (positions, LLRs, meta, strengths)."""
    if not (np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)):
        return False
    if json.dumps(a.meta, sort_keys=True, default=str) != json.dumps(b.meta, sort_keys=True, default=str):
        return False
    if (a.strengths is None) != (b.strengths is None):
        return False
    return a.strengths is None or (np.array_equal(a.strengths.positions, b.strengths.positions)
                                   and np.array_equal(a.strengths.values, b.strengths.values))


def _row_of(job: dict) -> dict:
    return {k: job.get(k) for k in ("split", "iss", "part", "medium", "renderer", "dpi", "framing", "seq", "page",
                                    "rep", "members", "index")}


def periksa_job(job: dict) -> dict:
    """kejenuhan must reproduce the stored background output exactly (decoder before this study)."""
    if not ukur.obs_path(job).exists():
        return {"key": ukur.job_key(job), "checked": False}
    stored = load_obs(job)
    if stored["reg"] is None:
        return {"key": ukur.job_key(job), "checked": False}
    obs = redecoded(job, stored, ("kejenuhan",))["kejenuhan"]
    a = next(sb for sb in stored["obs"] if sb.channel == "background")
    b = next(sb for sb in obs if sb.channel == "background")
    return {"key": ukur.job_key(job), "checked": True, "same": same_soft_bits(a, b)}


def nilai_job(item: tuple) -> list[dict]:
    """Every candidate on one development evidence."""
    job, names = item
    ctx, _ = ukur.context(job["iss"])
    stored = load_obs(job)
    members = job["members"] if job["part"] == "koalisi" else [job["seq"]] if job["part"] == "salinan" else []
    x = ctx.codewords[job["seq"] - 1].astype(np.uint8) if job["part"] == "salinan" else None
    t0 = time.perf_counter()
    variants = redecoded(job, stored, names)
    rows = []
    for name in names:
        row = {"key": ukur.job_key(job), "kandidat": name, **_row_of(job)}
        row.update(ukur.analyse(variants[name], ctx, members, x))
        rows.append(row)
    rows[0]["detik"] = round(time.perf_counter() - t0, 1)
    return rows


def _pool(fn, items: list, out: Path | None, key) -> list:
    import multiprocessing as mp

    done = set()
    if out is not None and out.exists():
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            done = {key(json.loads(line)) for line in fh if line.strip()}
    todo = [it for it in items if key(it) not in done]
    print(f"{len(done)} selesai, {len(todo)} tersisa", flush=True)
    results = []
    t0 = time.time()
    fh = gzip.open(out, "at", encoding="utf-8") if out is not None else None
    try:
        with ProcessPoolExecutor(max_workers=ukur.WORKERS, mp_context=mp.get_context("spawn"),
                                 initializer=ukur._init) as pool:
            for i, r in enumerate(pool.map(fn, todo, chunksize=1)):
                rows = r if isinstance(r, list) else [r]
                if fh is not None:
                    for row in rows:
                        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()
                results.extend(rows)
                if (i + 1) % 25 == 0 or i + 1 == len(todo):
                    print(f"[{i + 1}/{len(todo)} {time.time() - t0:.0f}s]", flush=True)
    finally:
        if fh is not None:
            fh.close()
    return results


def image_jobs(split: str) -> list[dict]:
    return [j for j in ukur.jobs_for(split) if j["medium"] != "pdf"]


def run_periksa(split: str) -> None:
    rows = _pool(periksa_job, image_jobs(split), None, lambda it: None)
    checked = [r for r in rows if r["checked"]]
    bad = [r["key"] for r in checked if not r["same"]]
    print(f"{len(checked)} keluaran latar diperiksa, {len(bad)} berbeda", flush=True)
    for k in bad[:20]:
        print("  berbeda:", k)
    if bad:
        raise SystemExit(1)


def run_nilai(split: str) -> None:
    if split != "dev":
        raise SystemExit("kandidat hanya dinilai pada set dev")
    out = ukur.HASIL / "dev_kandidat.jsonl.gz"
    items = [(j, CANDIDATES) for j in image_jobs(split)]
    _pool(nilai_job, items, out, lambda it: it["key"] if isinstance(it, dict) else ukur.job_key(it[0]))


# --- the rule --------------------------------------------------------------------------------


def medium_class(row: dict) -> str | None:
    """The calibration class of an evidence (``ATURAN`` 4), None when it has none."""
    m = row["medium"]
    if m in ukur.SCREEN_FORMATS:
        for band, lo, hi in BANDS:
            if lo <= row["dpi"] <= hi:
                return f"{m}|{band}"
    return m


def poisson_tail(e: float, k: int) -> float:
    """P(Poisson(e) >= k)."""
    from scipy.stats import poisson

    return 1.0 if k <= 0 else float(poisson.sf(k - 1, e))


def calibration_table(rows: list[dict], kind: str = "latar") -> dict[str, list[list[float]]]:
    """Per medium class: summed [n, k, E, sum w] per weight bin over single-copy evidence."""
    out: dict[str, np.ndarray] = {}
    for r in rows:
        if r["part"] != "salinan" or "kalibrasi" not in r:
            continue
        c = medium_class(r)
        acc = out.setdefault(c, np.zeros((len(ukur.W_EDGES) - 1, 4)))
        acc += np.asarray(r["kalibrasi"][kind], dtype=np.float64)
    return {c: v.tolist() for c, v in out.items()}


def calibration_verdict(table: dict) -> tuple[bool, float, list]:
    """(passes rule 4, mean calibration error over classes, failing cells)."""
    fails, errors = [], []
    for c, bins in sorted(table.items()):
        n_total = sum(b[0] for b in bins)
        if n_total <= 0:
            continue
        errors.append(sum(abs(b[1] - b[2]) for b in bins) / n_total)
        for i, (n, k, e, _) in enumerate(bins):
            p = poisson_tail(e, int(k))
            if p < ATURAN["level_poisson"]:
                fails.append({"kelas": c, "bin": i, "n": int(n), "salah": int(k), "E": round(e, 2), "p": p})
    return not fails, float(np.mean(errors)) if errors else 0.0, fails


def _honest(r: dict) -> bool:
    return r["part"] in ("salinan", "koalisi", "induk")


def _warned(r: dict) -> bool:
    return bool(r["hapus"]["ditandai"] or (r["kontradiksi"] or {}).get("ditandai") or r["balik"]["ditandai"])


def choose(dev_rows: list[dict], cand_rows: list[dict]) -> dict:
    """Apply ATURAN to the development rows: the base rows (``dev.jsonl``, the decoder before, for
    PDF evidence and every candidate alike) and the re-decoded image rows."""
    pdf_rows = [r for r in dev_rows if r["medium"] == "pdf"]
    by_cand: dict[str, list[dict]] = {name: list(pdf_rows) for name in CANDIDATES}
    for r in cand_rows:
        by_cand[r["kandidat"]].append(r)
    base = {r["key"]: r for r in by_cand["kejenuhan"]}
    report = {}
    for name in CANDIDATES:
        rows = by_cand[name]
        if len(rows) != len(base):
            raise SystemExit(f"{name}: {len(rows)} baris, {len(base)} diharapkan")
        wrong = [r["key"] for r in rows if r["salah"]]
        lost, new_warn = [], []
        for r in rows:
            b = base[r["key"]]
            if r["part"] in ("salinan", "koalisi") and len(r["anggota"]) < len(b["anggota"]):
                lost.append(r["key"])
            if _honest(r) and _warned(r) and not _warned(b):
                new_warn.append(r["key"])
        ok4, err, fails = calibration_verdict(calibration_table(rows))
        right = sum(1 for r in rows if r["part"] == "salinan" and r["anggota"])
        margins = [r["skor_anggota"] for r in rows if r["part"] == "salinan" and r["skor_anggota"] is not None]
        report[name] = {"tuduhan_salah": wrong, "putusan_hilang": lost, "peringatan_baru": new_warn,
                        "kalibrasi_lolos": ok4, "galat_kalibrasi": round(err, 6), "sel_gagal": fails[:40],
                        "sel_gagal_jumlah": len(fails), "benar": right,
                        "median_skor": round(float(np.median(margins)), 4) if margins else None,
                        "lolos": not wrong and not lost and not new_warn and ok4}
    passing = [n for n in CANDIDATES if report[n]["lolos"] and n != "kejenuhan"]
    chosen = "kejenuhan"
    if passing:
        chosen = min(passing, key=lambda n: (report[n]["galat_kalibrasi"], -report[n]["benar"],
                                             -(report[n]["median_skor"] or 0.0)))
    return {"aturan": ATURAN, "kandidat": report, "dipilih": chosen}


def run_pilih() -> None:
    dev_rows = ukur._load(ukur.HASIL / "dev.jsonl")
    with gzip.open(ukur.HASIL / "dev_kandidat.jsonl.gz", "rt", encoding="utf-8") as fh:
        cand_rows = [json.loads(line) for line in fh if line.strip()]
    res = choose(dev_rows, cand_rows)
    (ukur.HASIL / "pilihan.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, r in res["kandidat"].items():
        print(f"{name}: lolos {r['lolos']}, tuduhan salah {len(r['tuduhan_salah'])}, putusan hilang "
              f"{len(r['putusan_hilang'])}, peringatan baru {len(r['peringatan_baru'])}, kalibrasi "
              f"{r['kalibrasi_lolos']} ({r['sel_gagal_jumlah']} sel gagal), galat {r['galat_kalibrasi']}, benar "
              f"{r['benar']}, median skor {r['median_skor']}")
    print("dipilih:", res["dipilih"])


# --- held out: the decoder before on the same evidence -------------------------------------------


def banding_job(job: dict) -> dict:
    """Held-out evidence: the shipped model must reproduce the stored output; then the decoder
    before (kejenuhan) on the same registration, accused the same way."""
    ctx, _ = ukur.context(job["iss"])
    stored = load_obs(job)
    members = job["members"] if job["part"] == "koalisi" else [job["seq"]] if job["part"] == "salinan" else []
    x = ctx.codewords[job["seq"] - 1].astype(np.uint8) if job["part"] == "salinan" else None
    shipped = B.NOISE_MODEL
    variants = redecoded(job, stored, ("kejenuhan", shipped)) if shipped in MODELS else None
    if variants is None:
        raise SystemExit(f"model {shipped} tidak dikenal di kandidat.py")
    same = True
    if stored["reg"] is not None:
        a = next(sb for sb in stored["obs"] if sb.channel == "background")
        b = next(sb for sb in variants[shipped] if sb.channel == "background")
        same = same_soft_bits(a, b)
    row = {"key": ukur.job_key(job), "kandidat": "kejenuhan", "sama_dengan_tersimpan": same, **_row_of(job)}
    row.update(ukur.analyse(variants["kejenuhan"], ctx, members, x))
    return row


def run_banding(split: str) -> None:
    if split != "uji":
        raise SystemExit("banding untuk set uji")
    out = ukur.HASIL / "uji_banding.jsonl.gz"
    rows = _pool(banding_job, image_jobs(split), out, lambda it: it["key"] if "key" in it else ukur.job_key(it))
    bad = [r["key"] for r in rows if not r["sama_dengan_tersimpan"]]
    print(f"{len(rows)} bukti dibandingkan; {len(bad)} keluaran latar tidak terulang", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("periksa", "nilai", "banding"):
        p = sub.add_parser(name)
        p.add_argument("--split", choices=("dev", "uji"), required=True)
    sub.add_parser("pilih")
    args = ap.parse_args(argv)
    if args.cmd == "periksa":
        run_periksa(args.split)
    elif args.cmd == "nilai":
        run_nilai(args.split)
    elif args.cmd == "banding":
        run_banding(args.split)
    else:
        run_pilih()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
