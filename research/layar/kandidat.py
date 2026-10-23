"""Decoder candidates for screenshots, compared on the development set only (research/layar).

Every development trace of ``ukur.py lacak --split dev`` kept its registration (homography,
analysis and effective resolution), its word displacements and its background observations
(``obs/dev/*.npz``). Here the shift channel is decoded again from those displacements by each
candidate, fused with the same background observations and accused with the fixed rule (all of
eps, one stage). Nothing else changes, so the differences come from the shift decoder alone.

Candidates:

* ``sekarang``: the decoder of this working tree (``decode_displacements``); must reproduce the
  observations of the run (checked).
* ``kuantum_baris``: rows of evidence whose rows sit on the image's pixel grid are decoded with a
  model of baseline rounding. MuPDF and Poppler's Splash draw every baseline on a whole device
  pixel (measured: ``kuantisasi.py`` in the exploration notes of the README), so in a capture
  that was not rescaled every row lands at the same offset from the pixel grid. The gate maps the
  measured positions of the control rows (unmarked, so code-blind) into the image with the
  registration homography and takes the mean resultant length of their positions modulo one
  pixel; with at least ``GRID_MIN_CONTROLS`` control rows and a value of at least
  ``GRID_MIN_CONCENTRATION`` the page is treated as rounded (measured before scoring: unscaled
  MuPDF and Poppler captures from 56 dpi up 0.9 to 0.98, photos, monitor photos and the
  screenshot simulator of tapak/photos.py at most 0.43). A data row's relative offset is then
  r = s * delta + e, with e = (the row's rounding) - (its neighbours' interpolated rounding) +
  matching noise, modelled as uniform over one pixel q of the evidence plus a Gaussian whose
  variance holds the neighbours' rounding (q^2 ((1 - t)^2 + t^2) / 12) and the matching noise read
  from the concentration; LLR = log f(r - delta) - log f(r + delta). A shift rounded away
  (r near 0) gets LLR near 0, a shift that moved the row a whole pixel (r near +/- q, which the
  current decoder drops as implausible beyond 3 delta) is read with confidence. Every other page
  and everything else (word groups, other evidence) is decoded as ``sekarang``.
* ``kisi_baris``: the same gate, but the rounding is modelled exactly instead of as independent
  uniform errors. Exploring one development copy at 56 to 120 dpi showed why the uniform model
  fails: with a line pitch that is not a whole number of pixels the neighbours' rounding drifts
  slowly and wraps, so a data row between a wrapped and an unwrapped neighbour sits half a pixel
  off whatever its mark, and the uniform model reads that half pixel as a confident sign. The
  renderer drew row j at pixel round(k y_j + phi); the control rows confine (k, phi) to a small
  region, and a data row's sign has the likelihood of the part of that region where its baseline
  plus or minus delta rounds to its measured pixel (``ch_shift.lattice_row_llrs``, the decoder of
  this working tree with the registration's ``PixelGrid``). On those exploration captures (MuPDF
  and Poppler, 48 to 120 dpi) it read 61 rows with abs LLR >= 2, none wrong, where the Gaussian
  rows had 11 of 66 wrong. Scored on the development set it failed condition (3): confidently
  wrong row bits fell from 204 to 112 (45 %), none of them on the pages it decoded; the rest were
  Cairo captures (quarter-pixel baselines), MuPDF below 56 dpi and downscaled captures.
* ``kisi_baris2``: ``kisi_baris`` with the grid step tested at one, a half and a quarter pixel,
  coarsest first (``ch_shift.GRID_PITCHES_PX``). Added after ``kisi_baris`` failed, with the rule
  unchanged: kuantisasi.py at 28 to 40 dpi showed that MuPDF puts the baselines of glyphs below
  about 8 pixels per em on half pixels (11 pt text below 56 dpi), and Cairo uses quarter pixels at
  every resolution. Downscaled captures (the rows on a grid of 2/3 pixel in ``kecil``) are left to
  the Gaussian model: a messenger's scale factor is arbitrary, and searching it would widen the
  gate.

Selection rule (``ATURAN``, fixed after exploring the current decoder's row offsets on part of the
development set and before any candidate was scored on the whole development set): a candidate
replaces the current decoder only if, on the development set, (1) nobody is falsely accused (all
three accusation sets, unmarked masters included), (2) no renderer and format loses a correct
verdict with all channels or with the shift channel alone, (3) confidently wrong row bits
(abs LLR >= 4) fall by at least half, and (4) among the rows the candidate decodes with its own
model, in every weight bin with at least 50 bits the measured error rate is at most 1.5 times
the calibrated rate (1 - w) / 2 plus 1 percentage point. Rows are only 19 to 21 of 250 shift
slots of a page, so no gain in verdicts is required. If several candidates pass, the one with the
fewest confidently wrong row bits is chosen; on a tie, the one with the most correct verdicts from
the shift channel alone (tie-break added with ``kisi_baris``, still before any scoring).

    python research/layar/kandidat.py nilai sekarang,kuantum_baris,kisi_baris
    python research/layar/kandidat.py nilai sekarang,kisi_baris --split uji --acuan kisi_baris

The second form is the paired before/after comparison of the held-out run: the held-out traces
were decoded once by the chosen decoder (``--acuan``, checked against the saved observations),
and the same displacements are decoded again by the decoder before this study (``sekarang``).
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ukur  # noqa: E402
from ukur import HASIL, KINDS, WORK, accusations, bit_stats, context, job_key  # noqa: E402

ATURAN = ("kandidat menggantikan dekoder sekarang hanya bila pada set dev: (1) tidak ada tuduhan salah (ketiga "
          "kumpulan kanal, termasuk induk tanpa tanda), (2) tidak ada penggambar dan format yang kehilangan putusan "
          "benar, dengan semua kanal maupun geser saja, (3) bit baris yang salah dengan yakin (abs LLR >= 4) turun "
          "paling sedikit separuh, dan (4) di antara baris yang didekode dengan model kandidat, di setiap kelompok "
          "bobot dengan paling sedikit 50 bit, laju salah terukur paling besar 1,5 kali laju terkalibrasi (1 - w)/2 "
          "ditambah 1 poin persentase. Bila beberapa kandidat lolos, dipilih yang bit baris salah yakinnya paling "
          "sedikit; bila sama, yang putusan benar dari kanal geser saja paling banyak")
CANDIDATES = ("sekarang", "kuantum_baris", "kisi_baris", "kisi_baris2")


def load_trace(row: dict, scheme: str) -> dict:
    """Saved observations, registration and displacements of one trace."""
    data = np.load(WORK / "obs" / row["split"] / f"{job_key(row)}__{scheme}.npz")
    out: dict = {"obs": {}}
    for name in data.files:
        if name.startswith("obs"):
            k, rest = name.split("_", 1)
            channel, what = rest.rsplit("_", 1)
            out["obs"].setdefault((int(k[3:]), channel), {})[what] = data[name]
    out["h"] = data["reg_h"] if "reg_h" in data.files else None
    out["reg"] = data["reg_meta"] if "reg_meta" in data.files else None
    disp = {}
    if "disp_ids" in data.files:
        for wid, xy in zip(data["disp_ids"], data["disp_xy"]):
            disp[tuple(int(v) for v in wid)] = (float(xy[0]), float(xy[1]))
    out["disp"] = disp
    return out


def decode(candidate: str, ctx, saved: dict):
    """Shift SoftBits of a candidate from the saved displacements."""
    from tapak.decoder.ch_shift import decode_displacements

    if candidate == "sekarang" or saved["reg"] is None:
        return decode_displacements(ctx.master, ctx.plan, saved["disp"], ctx.shift, ctx.excluded)
    if candidate == "kuantum_baris":
        return decode_quantized_rows(ctx, saved)
    if candidate in ("kisi_baris", "kisi_baris2"):
        from tapak.decoder import ch_shift
        from tapak.decoder.ch_shift import PixelGrid

        grid = PixelGrid(saved["h"], float(saved["reg"][1]), float(saved["reg"][2]))
        pitches = ch_shift.GRID_PITCHES_PX
        ch_shift.GRID_PITCHES_PX = (1.0,) if candidate == "kisi_baris" else (1.0, 0.5, 0.25)
        try:
            return decode_displacements(ctx.master, ctx.plan, saved["disp"], ctx.shift, ctx.excluded, grid=grid)
        finally:
            ch_shift.GRID_PITCHES_PX = pitches
    raise ValueError(candidate)


# --- candidate kuantum_baris (research version; the decoder copy lives in tapak/decoder once chosen) ---

GRID_MIN_CONTROLS = 8      # control rows a page needs before its pixel grid is tested
GRID_MIN_CONCENTRATION = 0.7


def axis_deviation(h: np.ndarray, width_px: float, height_px: float) -> float:
    """Largest distance (image pixels) between where H puts a page corner and where the best
    axis-aligned scale and offset puts it (explored as a gate; ECC leaves up to about one pixel
    at low resolution, so it does not separate screenshots from photos)."""
    corners = np.array([[0, 0], [width_px, 0], [width_px, height_px], [0, height_px]], dtype=np.float64)
    hom = np.c_[corners, np.ones(4)] @ np.asarray(h, dtype=np.float64).T
    img = hom[:, :2] / hom[:, 2:3]
    dev = 0.0
    for axis in (0, 1):
        a = np.c_[corners[:, axis], np.ones(4)]
        coef, *_ = np.linalg.lstsq(a, img[:, axis], rcond=None)
        dev = max(dev, float(np.abs(a @ coef - img[:, axis]).max()))
    return dev


def _log_uniform_gauss(e: np.ndarray, q: float, sigma: np.ndarray | float) -> np.ndarray:
    """log density at e of U(-q/2, q/2) + N(0, sigma^2) (q = 0: the Gaussian)."""
    from scipy.special import log_ndtr

    e = np.asarray(e, dtype=np.float64)
    sigma = np.broadcast_to(np.asarray(sigma, dtype=np.float64), e.shape)
    if q <= 1e-9:
        return -0.5 * (e / sigma) ** 2 - np.log(sigma * np.sqrt(2 * np.pi))
    # Phi(a) - Phi(b) with a > b, computed on the side where it does not cancel.
    a, b = (e + q / 2) / sigma, (e - q / 2) / sigma
    flip = (a + b) > 0
    hi = np.where(flip, -b, a)
    lo = np.where(flip, -a, b)
    lhi, llo = log_ndtr(hi), log_ndtr(lo)
    return lhi + np.log1p(-np.exp(np.minimum(llo - lhi, -1e-300))) - np.log(q)


def row_units(ctx, disp: dict) -> dict:
    """Per page: data rows (position, whitening, relative offset r, interpolation weight t) as in
    signed_measurements, and the control rows (x_ref, baseline + displacement) in points."""
    from tapak.decoder.ch_shift import _row_displacement, row_slope
    from tapak.marker.pdf_shift import eligible_rows, relative_offset
    from tapak.marker.plan import CHANNEL_SHIFT

    layout = ctx.master.shift_layout
    slot_of = {(s.page, s.ref[0]): s for s in ctx.plan.channel(CHANNEL_SHIFT) if len(s.ref) == 1}
    out: dict = {}
    for pg in layout.pages:
        rows = eligible_rows(layout, pg.index, ctx.excluded)
        slope = row_slope(layout, disp, pg.index)
        x_ref = 0.5 * pg.width
        meas = [_row_displacement(layout, disp, r.id, slope, x_ref) for r in rows]
        data_k = set(range(1, len(rows) - 1, 2))
        data = []
        for k in sorted(data_k):
            slot = slot_of.get((pg.index, rows[k].index))
            trip = meas[k - 1:k + 2]
            if slot is None or any(m is None for m in trip):
                continue
            (pl, dl), (pd, dd), (pr, dr) = trip
            t = (pd - pl) / (pr - pl) if pr != pl else 0.5
            data.append((slot.positions[0], slot.whiten[0], relative_offset(pl, dl, pd, dd, pr, dr), t))
        controls = [(x_ref, m[0] + m[1]) for k, m in enumerate(meas) if k not in data_k and m is not None]
        out[pg.index] = {"data": data, "controls": controls}
    return out


def grid_concentration(y_img: np.ndarray) -> float:
    """Mean resultant length of the image row positions modulo one pixel: near 1 when every row
    sits at the same offset from the pixel grid (a renderer rounding baselines), near 0 for
    positions with no relation to the grid."""
    y = np.asarray(y_img, dtype=np.float64)
    return float(np.abs(np.mean(np.exp(2j * np.pi * y)))) if y.size else 0.0


def decode_quantized_rows(ctx, saved: dict):
    from tapak.decoder.ch_shift import decode_displacements
    from tapak.decoder.softbits import SoftBits

    base = decode_displacements(ctx.master, ctx.plan, saved["disp"], ctx.shift, ctx.excluded)
    page = int(saved["reg"][0])
    dpi, eff = float(saved["reg"][1]), float(saved["reg"][2])
    units = row_units(ctx, saved["disp"]).get(page)
    if not units or len(units["controls"]) < GRID_MIN_CONTROLS:
        return base
    s = dpi / 72.0
    pts = np.array([[x * s, y * s] for x, y in units["controls"]], dtype=np.float64)
    hom = np.c_[pts, np.ones(len(pts))] @ np.asarray(saved["h"], dtype=np.float64).T
    y_img = hom[:, 1] / hom[:, 2]
    conc = grid_concentration(y_img)
    model = {"concentration": round(conc, 4), "controls": len(pts)}
    if conc < GRID_MIN_CONCENTRATION:
        return SoftBits(base.channel, base.positions, base.llr, dict(base.meta, row_model=model), base.strengths)
    delta = ctx.shift.row_pt
    q = 72.0 / eff
    sigma_m = max(float(np.sqrt(max(-np.log(conc), 0.0) / (2 * np.pi ** 2))) * q, 0.05 * delta)
    pos, llr = [], []
    for position, white, r, t in units["data"]:
        mix = (1 - t) ** 2 + t ** 2
        s_e = float(np.sqrt(sigma_m ** 2 * (1 + mix) + q ** 2 * mix / 12.0))
        if abs(r) > q + delta + 4 * s_e:
            continue
        v = float(_log_uniform_gauss(np.array([r - delta]), q, s_e)[0] - _log_uniform_gauss(np.array([r + delta]), q, s_e)[0])
        if v != 0.0:
            pos.append(position)
            llr.append(v * (1 - 2 * white))
    model.update(q_pt=round(q, 4), sigma_pt=round(sigma_m, 4), rows=len(pos))
    kinds = ukur.shift_kinds(ctx)
    keep = np.array([kinds.get(int(q_)) != "baris" for q_ in base.positions], dtype=bool)
    return SoftBits(base.channel, np.concatenate([base.positions[keep], np.array(pos, dtype=np.int64)]),
                    np.concatenate([base.llr[keep], np.array(llr)]), dict(base.meta, row_model=model), base.strengths)


# --- evaluation ----------------------------------------------------------------------------


def evaluate(args: tuple[dict, list[str]]) -> dict:
    """Every candidate on one development row (all its traces)."""
    from tapak.decoder.softbits import SoftBits

    row, candidates, reference = args
    out = {k: row.get(k) for k in ("split", "grid", "doc", "scheme", "renderer", "dpi", "fmt", "framing", "seq", "rep")}
    out["traces"] = []
    for t in row["traces"]:
        scheme = t["against"]
        ctx, _, _ = context(row["split"], row["doc"], scheme)
        saved = load_trace(row, scheme)
        background = [SoftBits(ch, v["pos"], v["llr"]) for (k, ch), v in sorted(saved["obs"].items())
                      if ch == "background"]
        shift_saved = [SoftBits(ch, v["pos"], v["llr"]) for (k, ch), v in sorted(saved["obs"].items())
                       if ch == "shift"]
        x = ctx.codewords[row["seq"] - 1] if row["seq"] is not None else None
        tr = {"against": scheme, "registered": t["registered"], "candidates": {}}
        for cand in candidates:
            if not t["registered"]:
                tr["candidates"][cand] = {"bits": t["bits"], "accuse": t["accuse"]}
                continue
            sb = decode(cand, ctx, saved)
            if cand == reference and shift_saved:
                ref = shift_saved[0]
                if not (np.array_equal(ref.positions, sb.positions) and np.allclose(ref.llr, sb.llr, atol=1e-9)):
                    raise RuntimeError(f"{job_key(row)}: dekode ulang tidak sama dengan pelacakan")
            obs = [sb] + background
            bits = bit_stats(obs, ctx, x)
            model = sb.meta.get("row_model")
            own = model and ("q_pt" in model or any("q_pt" in pg for pg in model.get("pages", [])))
            bits["baris_model"] = bits["baris"] if own else {"read": 0}
            tr["candidates"][cand] = {"bits": bits, "accuse": accusations(obs, ctx, row["seq"]), "row_model": model}
        out["traces"].append(tr)
    return out


def run_nilai(candidates: list[str], split: str = "dev", reference: str = "sekarang") -> None:
    import multiprocessing as mp

    rows = [json.loads(line) for line in (HASIL / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    out_rows = []
    with ProcessPoolExecutor(max_workers=ukur.WORKERS, mp_context=mp.get_context("spawn"), initializer=ukur._init) as pool:
        for i, r in enumerate(pool.map(evaluate, [(r, candidates, reference) for r in rows], chunksize=4)):
            out_rows.append(r)
            if i % 100 == 0:
                print(f"{i}/{len(rows)}", flush=True)
    import gzip

    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in out_rows)
    with gzip.GzipFile(HASIL / f"{split}_kandidat.jsonl.gz", "wb", mtime=0) as fh:  # several MB as plain text
        fh.write(text.encode("utf-8"))
    report(out_rows, candidates, split)


def report(rows: list[dict], candidates: list[str], split: str = "dev") -> dict:
    """Numbers for the selection rule, per candidate."""
    from ringkas import calibration

    res: dict = {}
    for cand in candidates:
        pairs = [(r, {"bits": t["candidates"][cand]["bits"], "accuse": t["candidates"][cand]["accuse"]})
                 for r in rows for t in r["traces"]]
        marked = [(r, t) for r, t in pairs if r["seq"] is not None]
        false = sum(t["accuse"][w]["verdict"] == "salah" for _, t in pairs for w in ("semua", "geser", "latar"))
        named: dict = {}
        for r, t in marked:
            key = f"{r['renderer']}|{r['fmt']}"
            cell = named.setdefault(key, {"semua": 0, "geser": 0, "n": 0})
            cell["n"] += 1
            cell["semua"] += t["accuse"]["semua"]["verdict"] == "benar"
            cell["geser"] += t["accuse"]["geser"]["verdict"] == "benar"
        conf = {k: sum((t["bits"].get(k) or {}).get("wrong_llr4", 0) or 0 for _, t in marked) for k in KINDS}
        wrong = {k: sum((t["bits"].get(k) or {}).get("wrong", 0) or 0 for _, t in marked) for k in KINDS}
        read = {k: sum((t["bits"].get(k) or {}).get("read", 0) for _, t in marked) for k in KINDS}
        res[cand] = {"false": false, "named": named, "confident_wrong": conf, "wrong": wrong, "read": read,
                     "calibration_rows": calibration(marked, "baris"),
                     "calibration_model_rows": calibration(marked, "baris_model"),
                     "calibration_words": calibration(marked, "kata")}
        print(json.dumps({cand: {k: v for k, v in res[cand].items() if k != "named"}}, ensure_ascii=False))
        print(json.dumps({cand: named}, ensure_ascii=False))
    res["rule"] = ATURAN
    (HASIL / f"{split}_kandidat_ringkas.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("nilai")
    n.add_argument("candidates", nargs="?", default=",".join(CANDIDATES))
    n.add_argument("--split", choices=("dev", "uji"), default="dev")
    n.add_argument("--acuan", default="sekarang", help="kandidat yang sama dengan dekoder pelacakan (diperiksa)")
    args = ap.parse_args(argv)
    run_nilai(args.candidates.split(","), args.split, args.acuan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
