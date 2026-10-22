"""Defense against agreement-targeted erasure: a per-copy mask on the background (research).

Protocol, fixed and committed before the held-out measurements (the decision rule is in
``ukur.py``):

Scheme ``samaran-latar-v1``. Every copy adds to every background cell a keyed mask drawn from
its own key, HMAC-SHA256(code secret, "TAPAK-samaran-latar-v1|" + doc hash + "|" + copy id),
so it is independent of every codeword. Cell c of position b shows

    base + A * pn_c * (s_b + e_c)

with e_c uniform on [-r, r]. The eight cells of a position are paired in their keyed order
and the second cell of a pair gets -e of the first, so the mask cancels in the decoder's
despread mean of the position (it does not cancel exactly once cells are partly masked by
ink, blurred or clipped). Unused cells get an unpaired e. The decoder is unchanged: it never
subtracts the mask and treats it as noise (a mask derived from the copy id must not be
removed per candidate copy, that would break the false-accusation bound). The paper white is
kept as the brightest level: base = 255 - A (1 + r).

Candidates (fixed now; no other is tried):

* K1 "di bawah ambang cetak": A = 1.0, r = 1.5, levels 250 to 255, so nothing prints on the
  assumed printer (as today's pattern); the signal is half of today's;
* K2 "amplitudo penuh": A = 2.0, r = 2.0, levels 243 to 255; today's signal.

A coalition that knows the scheme reads each copy's cell values (exact inverse of the image
upsampling) and flattens the cells whose posterior probability of agreement
(``tapak.collusion.agreement_posterior``, prior from the arcsine law) is at least 0.5; at
the other cells a random member (``acak``); shifts as in ``ukur.py`` (unchanged by the mask).

Parts:

* ``abstrak``: cell-level classification by the coalition for r in {0 (today), 1.5, 2, 3}
  and k = 2, 3, 4 copies, 20000 positions, seed 7301: the share of agreeing and of
  disagreeing positions' cells it flattens, and the residual despread signal of agreeing
  positions (mean over their eight cells of the kept level).
* ``visibilitas``: S-CIELAB texture at 35 cm (``scripts/cetak/visibility.py``) of a central
  120 mm region of page 1, on screen and on the simulated laser print, for today's pattern,
  K1 and K2 (cell bits uniform, seed 7302).
* ``bench``: the README benchmark issuance (benih riset 2026, 20 copies, nota dinas) issued
  again with each candidate that passes visibility, the same photo sets (``make photos`` and
  ``make photos-cetak`` seeds and parameters) traced as ``make bench`` does; correct counts
  compared with today's on every set (``bench hari_ini`` traces today's rebuilt sets the same
  way, for the score margin and the background bit errors).
* ``serang``: the uji issuances of ``ukur.py`` issued again with the candidate (same research
  seeds, so the same codewords), the same coalitions, semua/acak with the mask-aware
  coalition and jujur, channels pdf, layar and foto with the same channel seeds; escape
  rate compared with today's semua/acak on the same coalitions.

Usage (from the repository root):

    python research/sepakat/samaran.py abstrak --out research/sepakat/hasil/samaran_abstrak.jsonl
    python research/sepakat/samaran.py visibilitas --out research/sepakat/hasil/samaran_visibilitas.jsonl
    python research/sepakat/samaran.py bench K1 --out research/sepakat/hasil/samaran_bench.jsonl
    python research/sepakat/samaran.py serang K1 --out research/sepakat/hasil/samaran_serang.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

CANDIDATES = {"K1": (1.0, 1.5), "K2": (2.0, 2.0)}
SCHEME = "samaran-latar-v1"
OUT = ROOT / "out" / "sepakat" / "samaran"


def mask_settings(name: str):
    """BackgroundSettings of a candidate: amplitude A, base 255 - A (1 + r)."""
    from tapak.marker.background import BackgroundSettings

    a, r = CANDIDATES[name]
    return BackgroundSettings(base=255.0 - a * (1.0 + r), amplitude=a), r


def mask_key(secret: bytes, doc_hash: str, copy_id: str) -> bytes:
    """The per-copy mask key (independent of every codeword)."""
    return hmac.new(secret, f"TAPAK-samaran-latar-v1|{doc_hash}|{copy_id}".encode(), hashlib.sha256).digest()


def mask_values(grid, key: bytes, ratio: float) -> np.ndarray:
    """The mask e_c of every cell (ny, nx): uniform on [-ratio, ratio], paired to cancel within
    each position (pairs in the keyed cell order of ``PageGrid.cell_bit``)."""
    from tapak.tardos.code import uniform_stream

    n = grid.n_cells
    e = (2.0 * uniform_stream(key, f"bg-mask|{grid.page}".encode(), n) - 1.0) * ratio
    order = np.argsort(uniform_stream(grid.key, f"bg-cells|{grid.page}".encode(), n), kind="stable")
    k = grid.settings.cells_per_bit
    nb = grid.n_bits
    for j in range(1, k, 2):  # cells j * nb + b (j odd) mirror cells (j - 1) * nb + b
        e[order[j * nb:(j + 1) * nb]] = -e[order[(j - 1) * nb:j * nb]]
    return e.reshape(grid.ny, grid.nx)


def masked_levels(grid, slots, codeword: np.ndarray, key: bytes, ratio: float) -> np.ndarray:
    """Cell levels of a masked copy in amplitude units: pn (s + e), unused cells e."""
    from tapak.marker.background import cell_levels

    base = cell_levels(grid, slots, codeword)
    e = mask_values(grid, key, ratio)
    return np.where(grid.cell_bit >= 0, base + grid.pn * e, e)


# --- masked issuance (research only: workers = 1, hooks patched in this process) -----------

_CURRENT: dict[str, object] = {}


def issue_masked(doc: Path, recipients, out: Path, secret: bytes, copy_ids: list[str], n_max: int, name: str):
    """Issue copies with candidate ``name``: today's issuance with the masked background hook."""
    import tapak.marker.issue as issue_mod
    from tapak.marker.background import png_bytes, pattern_image
    from tapak.marker.plan import CHANNEL_BACKGROUND

    settings_bg, ratio = mask_settings(name)

    def hook_factory(plan, codeword, grids):
        slots = plan.channel(CHANNEL_BACKGROUND)
        by_page = {g.page: g for g in grids}
        key = mask_key(secret, _CURRENT["doc_hash"], _CURRENT["copy_id"])  # type: ignore[arg-type]

        def hook(doc_, page):
            import pymupdf

            grid = by_page.get(page.number)
            if grid is None:
                return
            img = pattern_image(grid, masked_levels(grid, slots, codeword, key, ratio))
            ox, oy = grid.offset_pt
            rect = pymupdf.Rect(ox, oy, ox + grid.nx * grid.cell_pt, oy + grid.ny * grid.cell_pt)
            page.insert_image(rect, stream=png_bytes(img), overlay=False)
            page.draw_rect(page.rect, color=None, fill=(grid.settings.base / 255.0,) * 3, overlay=False)

        return hook

    real_hook, real_render = issue_mod.background_hook, issue_mod._render_one

    def render_one(job):
        _CURRENT["copy_id"] = job[1]
        _CURRENT["doc_hash"] = issue_mod._W["master"].doc_hash  # type: ignore[union-attr]
        return real_render(job)

    issue_mod.background_hook, issue_mod._render_one = hook_factory, render_one
    try:
        return issue_mod.issue(doc, recipients, out, secret,
                               issue_mod.IssueSettings(n_max=n_max, workers=1, background=settings_bg,
                                                       canary_domain=None),
                               issuer="riset-samaran", copy_ids=copy_ids)
    finally:
        issue_mod.background_hook, issue_mod._render_one = real_hook, real_render


# --- part abstrak ----------------------------------------------------------------------------


def abstract_rows() -> list[dict]:
    """Cell-level classification by a mask-aware coalition (see the module docstring)."""
    from tapak.collusion import agreement_posterior

    rng = np.random.default_rng(7301)
    rows = []
    n_pos, cells = 20000, 8
    t = 1.0 / 900.0
    for ratio in (0.0, 1.5, 2.0, 3.0):
        for k in (2, 3, 4):
            p = np.sin(rng.uniform(np.arcsin(np.sqrt(t)), np.pi / 2 - np.arcsin(np.sqrt(t)), n_pos)) ** 2
            x = (rng.random((k, n_pos)) < p).astype(np.float64)
            s = (2 * x - 1)[:, :, None] * np.ones((1, 1, cells))
            pn = np.where(rng.random((n_pos, cells)) < 0.5, -1.0, 1.0)
            if ratio > 0:
                e = rng.uniform(-ratio, ratio, (k, n_pos, cells // 2))
                e = np.concatenate([e, -e], axis=2)
                v = pn * (s + e) + rng.normal(0, 0.07, (k, n_pos, cells))  # reading error as measured
                post = agreement_posterior(v, ratio, quant=0.3)
            else:
                v = pn * s
                post = np.all(v == v[:1], axis=0).astype(float)
            agree = np.all(x == x[:1], axis=0)
            flat = post >= 0.5
            kept_signal = np.where(flat, 0.0, v[0] * pn).mean(axis=1)  # despread residual of copy 1's level
            rows.append({"bagian": "abstrak", "rasio": ratio, "k": k, "posisi": n_pos,
                         "sel_sama_diratakan": round(float(flat[agree].mean()), 4),
                         "sel_beda_diratakan": round(float(flat[~agree].mean()), 4),
                         "sisa_sinyal_sama": round(float(np.mean(kept_signal[agree] * (2 * x[0, agree] - 1))), 4),
                         "sisa_sinyal_beda": round(float(np.mean(kept_signal[~agree] * (2 * x[0, ~agree] - 1))), 4)})
    return rows


# --- part visibilitas ------------------------------------------------------------------------


def visibility_rows() -> list[dict]:
    """S-CIELAB texture of today's pattern and both candidates, on screen and on laser paper."""
    import cv2

    from scripts.cetak import visibility as vis
    from tapak.marker.background import SCREEN_BACKGROUND, PageGrid, pattern_image
    from tapak.photos import PrintParams, print_page

    rng = np.random.default_rng(7302)
    out = []
    for name in ("hari_ini", "K1", "K2"):
        if name == "hari_ini":
            settings, ratio = SCREEN_BACKGROUND, 0.0
        else:
            settings, ratio = mask_settings(name)
        grid = PageGrid(0, 595.28, 841.89, settings, b"samaran-visibilitas")
        signs = np.where(rng.random(grid.n_bits) < 0.5, -1.0, 1.0)
        cb = grid.cell_bit
        level = np.where(cb >= 0, signs[np.clip(cb, 0, None)], 0.0) * grid.pn
        if ratio > 0:
            e = mask_values(grid, b"samaran-visibilitas-salinan", ratio)
            level = np.where(cb >= 0, level + grid.pn * e, e)
        img = pattern_image(grid, level)
        row = {"bagian": "visibilitas", "kandidat": name, "rasio": ratio, "amplitudo": settings.amplitude,
               "dasar": settings.base, "tingkat_min": int(img.min()), "tingkat_maks": int(img.max())}
        for medium, dpi in (("layar", 300), ("laser", PrintParams().device_dpi)):
            s = dpi / 72.0
            gw, gh = int(round(grid.nx * grid.cell_pt * s)), int(round(grid.ny * grid.cell_pt * s))
            full = cv2.resize(img.astype(np.float32), (gw, gh), interpolation=cv2.INTER_LINEAR)
            n = int(round(vis.REGION_MM / 25.4 * dpi))
            y0, x0 = (gh - n) // 2, (gw - n) // 2
            pat = np.rint(full[y0:y0 + n, x0:x0 + n]).astype(np.uint8)
            m = int(10 / 25.4 * dpi)
            if medium == "layar":
                lp = vis.lstar(vis.scielab_lum(vis.srgb_to_y(pat.astype(np.float64)), dpi, 350.0))
                row["layar"] = vis.stats(lp - float(lp[m:-m, m:-m].mean()), m)
                row["layar_rona_dL"] = round(float(vis.lstar(vis.srgb_to_y(np.array(settings.base))) - 100.0), 2)
            else:
                params = PrintParams()
                zero = np.zeros(pat.shape, dtype=np.float32)
                sheet = print_page(zero, pat, np.random.default_rng(11), params)[0]
                paper = print_page(zero, np.full_like(pat, 255), np.random.default_rng(11), params)[0]
                odpi = params.out_dpi
                mo = int(10 / 25.4 * odpi)
                ys = [(v / 255.0 * (1 - vis.R0) + vis.R0).astype(np.float64) for v in (sheet, paper)]
                lp, lw = (vis.lstar(vis.scielab_lum(y, odpi, 350.0)) for y in ys)
                row["laser"] = vis.stats(lp - float(lp[mo:-mo, mo:-mo].mean()), mo)
                row["laser_rona_dL"] = round(float((lp - lw)[mo:-mo, mo:-mo].mean()), 2)
        row["lolos"] = all(row[mm]["mean"] <= 0.75 and row[mm]["p95"] <= 2.0 for mm in ("layar", "laser"))
        out.append(row)
        print(json.dumps(row), flush=True)
    return out


# --- part bench ------------------------------------------------------------------------------


def bench_rows(name: str) -> list[dict]:
    """The README photo benchmark on a masked issuance (same seeds as make photos / photos-cetak)."""
    from tapak.decoder.trace import collect_file, load_context, run_trace
    from tapak.keys import research_code_secret, research_copy_ids
    from tapak.marker.issue import read_recipients
    from tapak.photos import PrintParams, make_photo_set

    secret = research_code_secret(2026)
    if name == "hari_ini":  # today's scheme: the benchmark rebuilt by make photos (ukur.BENCH)
        folder = ROOT / "out" / "sepakat" / "bench"
        issued = next((folder / "data" / "dokumen").glob("*/salinan"))
    else:
        folder = OUT / f"bench_{name}"
        issued = folder / "salinan"
        recipients = read_recipients(ROOT / "samples" / "recipients.csv")
        if not (issued / "manifest.json").exists():
            issue_masked(ROOT / "samples" / "nota_dinas.pdf", recipients, issued, secret,
                         research_copy_ids(2026, len(recipients)), len(recipients), name)
    sets = {"layar": folder / "photos", "cetak": folder / "photos-cetak"}
    if not (sets["layar"] / "truth.json").exists():
        make_photo_set(issued, sets["layar"], seqs=[13, 7, 1, 20], per_copy=2, seed=2026)
    if not (sets["cetak"] / "truth.json").exists():
        make_photo_set(issued, sets["cetak"], seqs=[13, 7, 1, 20], angles=(10, 30), per_copy=1, seed=2026,
                       all_pages=True, screenshots=False, print_params=PrintParams())
    from tapak.marker.issue import IssueManifest

    manifest = IssueManifest.from_json((issued / "manifest.json").read_text(encoding="utf-8"))
    ctx = load_context((ROOT / "samples" / "nota_dinas.pdf").read_bytes(), manifest, secret)
    rows = []
    items = []
    for medium, f in sets.items():
        truth = json.loads((f / "truth.json").read_text(encoding="utf-8"))["items"]
        if medium == "layar":
            items += [("layar", [it["file"]], it["seq"], f) for it in truth]
        else:
            items += [("cetak, 1 halaman", [it["file"]], it["seq"], f) for it in truth]
            pairs: dict[tuple, dict] = {}
            for it in truth:
                index = it["file"].rsplit("_", 1)[-1].split(".")[0]
                pairs.setdefault((it["seq"], it["angle"], index), {})[it["page"]] = it["file"]
            items += [("cetak, 2 halaman", [d[p] for p in sorted(d)], key[0], f) for key, d in pairs.items()]
    for medium, files, seq, f in items:
        obs = []
        for fn in files:
            o, _ = collect_file(fn, (f / fn).read_bytes(), ctx)
            obs += o
        res = run_trace(obs, ctx)
        accused = sorted(c.copy.seq for c in res.accused)
        outcome = "benar" if accused == [seq] else ("tidak cukup bukti" if not accused else "salah")
        bg = [sb for sb in obs if sb.channel == "background"]
        rows.append({"bagian": "bench", "kandidat": name, "medium": medium, "berkas": files, "salinan": seq,
                     "hasil": outcome, "dituduh": accused,
                     "skor_per_ambang": round(max(c.score for c in res.candidates if c.copy.seq == seq)
                                              / res.threshold.threshold, 3),
                     "latar_terbaca": sum(len(b) for b in bg),
                     "latar_salah": int(sum(np.sum((b.llr > 0) != (ctx.codewords[seq - 1][b.positions] == 1))
                                            for b in bg)),
                     "hapus_z": res.erasure.z if res.erasure else None})
        print(json.dumps(rows[-1]), flush=True)
    return rows


# --- part serang -----------------------------------------------------------------------------


def attack_rows(name: str, which: str = "uji", only: list[int] | None = None) -> list[dict]:
    """semua/acak with the mask-aware coalition on masked copies of the ukur.py issuances
    (``only``: the issuance indices to run, all by default; one process per index in parallel)."""
    import ukur

    from tapak.collusion import attack
    from tapak.decoder.trace import load_context
    from tapak.keys import research_code_secret, research_copy_ids
    from tapak.marker.issue import IssueManifest, read_recipients

    settings_bg, ratio = mask_settings(name)
    rows = []
    for iss, (doc, n, seed) in enumerate(ukur.ISSUANCES[which]):
        if only is not None and iss not in only:
            continue
        folder = OUT / f"{name}_{doc}_{n}_{seed}" / "salinan"
        secret = research_code_secret(seed)
        if not (folder / "manifest.json").exists():
            csv = ukur._recipients_csv(OUT / f"{name}_{doc}_{n}_{seed}", n)
            issue_masked(ROOT / "samples" / f"{doc}.pdf", read_recipients(csv), folder, secret,
                         research_copy_ids(seed, n), n, name)
        manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
        ctx = load_context((ROOT / "samples" / f"{doc}.pdf").read_bytes(), manifest, secret)
        for k in ukur.KS:
            for ci, members in enumerate(ukur.coalitions(which, iss, n, k)):
                pdfs = [(folder / manifest.copies[s - 1].file).read_bytes() for s in members]
                x = ctx.codewords[[s - 1 for s in members]].astype(np.int64)
                agree = np.all(x == x[:1], axis=0)
                rng = np.random.default_rng([ukur.SEEDS[which]["serangan"], iss, k, ci, 0])
                forged, view, plan = attack(ctx.master, pdfs, "acak", 1.0, ("latar", "geser"), rng,
                                            mask=(settings_bg.base, settings_bg.amplitude, ratio))
                for label, data in (("jujur", pdfs[0]), ("semua/acak", forged)):
                    for channel in ("pdf", "layar", "foto"):
                        t0 = time.perf_counter()
                        crng = np.random.default_rng([ukur.SEEDS[which]["kanal"], iss, k, ci,
                                                      ukur.CHANNELS.index(channel)])
                        obs, _ = ukur.evidence(ctx, data, channel, crng, ci)
                        row = {"bagian": "samaran", "kandidat": name, "set": which, "dok": doc, "N": n,
                               "benih": seed, "k": k, "koalisi_ke": ci, "koalisi": members, "serangan": label,
                               "kanal": channel, "rencana": plan.counts if label != "jujur" else {}}
                        row.update(ukur.record(obs, ctx, members, x[0], agree))
                        row["detik"] = round(time.perf_counter() - t0, 1)
                        rows.append(row)
                        print(json.dumps({k2: row[k2] for k2 in ("dok", "N", "k", "serangan", "kanal")}
                                         | {"dituduh": row["putusan"]["bertahap"]["dituduh"]}), flush=True)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["abstrak", "visibilitas", "bench", "serang"])
    ap.add_argument("kandidat", nargs="?", default="K1", choices=sorted(CANDIDATES) + ["hari_ini"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--penerbitan", type=int, nargs="*", default=None, help="indeks penerbitan uji (serang)")
    args = ap.parse_args(argv)
    if args.bagian == "abstrak":
        rows = abstract_rows()
    elif args.bagian == "visibilitas":
        rows = visibility_rows()
    elif args.bagian == "bench":
        rows = bench_rows(args.kandidat)
    else:
        rows = attack_rows(args.kandidat, only=args.penerbitan)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
