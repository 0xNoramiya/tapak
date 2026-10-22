"""Phone ISP and monitor photos: measurements behind batasan 10 in docs/keamanan.md.

A simulation study. No real phone, monitor or ISP is involved: the evidence comes from
``tapak.photos`` with the opt-in phone ISP (``tapak.ponsel.IspParams``) and the simulated
monitor (``tapak.ponsel.ScreenParams``), whose parameter ranges and sources are listed in the
docstring of ``tapak/ponsel.py``.

The protocol and every seed are fixed here, before any run (``PROTOCOL``):

* Two fictional masters, ``samples/nota_dinas.pdf`` and ``samples/surat_telegram.pdf``,
  each issued to N = 20 recipients (c = 3, eps = 1e-6) with seeded copy ids, so every copy
  and every image is reproduced exactly. Evidence is page 1, rendered at 200 dpi.
* Two disjoint seed sets: ``pengembangan`` (development; every decoder change is chosen
  on it) and ``uji`` (held out; generated and traced once, at the end, with both decoders).
* Conditions per copy (one image each; the photo conditions share scene, pose and sensor
  noise, and so do the monitor conditions, so the differences are the ISP or display only):
  - ``foto_netral``: the plain photo of ``make photos`` (no ISP stage);
  - ``foto_ponsel``: the same photo through the full ISP profile "ponsel";
  - ``foto_nr``, ``foto_hdr``, ``foto_nada``, ``foto_tajam``, ``foto_jpeg``: one ISP step
    alone (noise reduction, burst HDR with highlight shoulder, local tone mapping,
    sharpening with halos, the camera's JPEG), the ablation;
  - ``layar_ideal``: the copy on a monitor without subpixel structure (gamma, backlight,
    angle, reflections only), plain camera tail;
  - ``layar_netral``: the same monitor with RGB subpixels (moire), plain camera tail;
  - ``layar_ponsel``: the same with the ISP profile "ponsel";
  - ``layar_silau``: as layar_ponsel plus glare (a reflected luminaire).
  View angle, monitor and camera distance follow a fixed design per copy (``design``):
  angles 0, 10, 20, 30 degrees; monitors fhd24 (92.6 ppi), qhd27 (108.8), uhd27 (163.2),
  laptop13 (227); distances 30, 45 and 60 cm.
* Unmarked masters: page 1 of each master itself (no marks) through ``foto_ponsel``,
  ``layar_netral`` and ``layar_ponsel``, 10 images per master and condition and split. Nobody
  may be accused.

Every image is traced as ``make bench`` does (not logged in a registry, all of eps). Verdicts:
``benar`` (exactly the leaked copy), ``tidak cukup bukti`` (nobody), ``salah`` (anyone else,
or anyone at all for an unmarked master). Per channel: positions read and bit errors
against the leaked copy's codeword (sign of the LLR).

Decoders: ``baru`` is the decoder of this working tree; ``lama`` is the decoder of commit
``PROTOCOL["base_commit"]`` (before any change for this study), exported with ``git archive``
into ``out/riset_ponsel/dekoder_lama`` and imported by the worker processes in its place.

Process pools are capped at 3 workers with BLAS and OpenCV at one thread each (shared machine).
Issued copies and evidence images go to ``out/riset_ponsel/`` (large, not committed); the JSON
lines quoted in the docs go to ``research/ponsel/hasil/``.

Usage (from the repository root):

    python research/ponsel/ukur.py terbit
    python research/ponsel/ukur.py buat --split pengembangan
    python research/ponsel/ukur.py lacak --split pengembangan --dekoder lama
    python research/ponsel/ukur.py lacak --split pengembangan --dekoder baru
    python research/ponsel/ukur.py buat --split uji               # once, at the end
    python research/ponsel/ukur.py lacak --split uji --dekoder lama
    python research/ponsel/ukur.py lacak --split uji --dekoder baru
    python research/ponsel/ukur.py ringkas
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "out" / "riset_ponsel"
RESULTS = ROOT / "research" / "ponsel" / "hasil"
WORKERS = 3
PROTOCOL = {
    "n": 20, "c": 3, "eps": 1e-6,
    "secret": "sha256('TAPAK-riset-ponsel-v1')",
    "documents": {"nota_dinas": "samples/nota_dinas.pdf", "surat_telegram": "samples/surat_telegram.pdf"},
    "copy_id_seed": {"nota_dinas": 20261101, "surat_telegram": 20261102},
    "render_dpi": 200, "page": 1,
    "splits": {"pengembangan": 7100, "uji": 7200},
    "photo_conditions": ["foto_netral", "foto_ponsel", "foto_nr", "foto_hdr", "foto_nada", "foto_tajam", "foto_jpeg"],
    "screen_conditions": ["layar_ideal", "layar_netral", "layar_ponsel", "layar_silau"],
    "master_conditions": ["foto_ponsel", "layar_netral", "layar_ponsel"],
    "master_images": 10,
    "angles": [0, 10, 20, 30],
    "monitors": ["fhd24", "qhd27", "uhd27", "laptop13"],
    "distances_cm": [30, 45, 60],
    "design": "copy s (1..20) or master image k: i = s - 1 or k; monitor = monitors[i % 4], "
              "distance = distances[(i // 4) % 3], angle = angles[(i + i // 4) % 4]",
    "generators": "photo: default_rng([split seed, document index, s, 11]), ISP default_rng([..., 12]); "
                  "monitor: [..., 21] and [..., 22]; master image k uses s = 1000 + k",
    "base_commit": "0de1e9752ca3fa5e8c9a436402409ab73db50003",
    "spending": "tidak dicatat (seluruh eps), seperti make bench",
}
SECRET = hashlib.sha256(b"TAPAK-riset-ponsel-v1").digest()
DOCS = list(PROTOCOL["documents"])


def design(i: int) -> dict:
    """Monitor, distance and view angle of copy index i (0-based) or master image i."""
    return {"monitor": PROTOCOL["monitors"][i % 4], "distance_cm": float(PROTOCOL["distances_cm"][(i // 4) % 3]),
            "angle": float(PROTOCOL["angles"][(i + i // 4) % 4])}


def jobs_for(split: str) -> list[dict]:
    """Every (document, copy or master image, condition) of a split, in a fixed order."""
    out = []
    for doc in DOCS:
        for s in range(1, PROTOCOL["n"] + 1):
            for cond in PROTOCOL["photo_conditions"] + PROTOCOL["screen_conditions"]:
                out.append({"split": split, "doc": doc, "seq": s, "cond": cond, **design(s - 1)})
        for k in range(PROTOCOL["master_images"]):
            for cond in PROTOCOL["master_conditions"]:
                out.append({"split": split, "doc": doc, "seq": None, "master_image": k, "cond": cond, **design(k)})
    return out


def _evidence_path(job: dict) -> Path:
    who = f"s{job['seq']:03d}" if job["seq"] is not None else f"induk{job['master_image']:02d}"
    return WORK / "bukti" / job["split"] / job["doc"] / f"{job['cond']}_{who}.jpg"


# --- issuance ------------------------------------------------------------------------------


def _issue(doc: str) -> dict:
    """Issue N copies of one master with seeded copy ids (secrets.token_hex patched here only)."""
    import tapak.marker.issue as issue_mod
    from tapak.marker.issue import IssueSettings, issue, read_recipients

    folder = WORK / doc
    if (folder / "salinan" / "manifest.json").exists():
        from tapak.marker.issue import IssueManifest

        manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        return {"doc": doc, "copies": len(manifest.copies), "plan_summary": manifest.plan_summary, "reused": True}
    folder.mkdir(parents=True, exist_ok=True)
    master = ROOT / PROTOCOL["documents"][doc]
    (folder / "induk.pdf").write_bytes(master.read_bytes())
    rng = np.random.default_rng(PROTOCOL["copy_id_seed"][doc])
    real = issue_mod.secrets.token_hex
    issue_mod.secrets.token_hex = lambda k=8: rng.bytes(k).hex()  # type: ignore[assignment]
    try:
        t0 = time.perf_counter()
        manifest = issue(folder / "induk.pdf", read_recipients(ROOT / "samples" / "recipients.csv")[:PROTOCOL["n"]],
                         folder / "salinan", SECRET,
                         IssueSettings(c=PROTOCOL["c"], eps=PROTOCOL["eps"], workers=WORKERS, n_max=PROTOCOL["n"]),
                         issuer="riset")
    finally:
        issue_mod.secrets.token_hex = real
    return {"doc": doc, "copies": len(manifest.copies), "issue_seconds": round(time.perf_counter() - t0, 1),
            "plan_summary": manifest.plan_summary, "copy_ids_sha256": hashlib.sha256(
                ",".join(c.copy_id for c in manifest.copies).encode()).hexdigest()}


def run_issue() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = [_issue(doc) for doc in DOCS]
    _write(RESULTS / "terbit.jsonl", rows)
    script = Path(__file__).read_bytes()
    proto = dict(PROTOCOL, script_sha256=hashlib.sha256(script).hexdigest())
    (RESULTS / "protokol.json").write_text(json.dumps(proto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))


# --- worker side ---------------------------------------------------------------------------

_CTX: dict[str, object] = {}


def _init(old_decoder: str | None) -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
        os.environ[var] = "1"
    if old_decoder:
        sys.path.insert(0, old_decoder)  # the old package shadows this tree's tapak
    import cv2

    cv2.setNumThreads(1)


def _context(doc: str):
    if doc not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

        folder = WORK / doc
        manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        _CTX[doc] = (load_context((folder / "induk.pdf").read_bytes(), manifest, SECRET), manifest, folder)
    return _CTX[doc]


def _make(job: dict) -> dict:
    """Render the page, simulate the evidence image, write it; return its simulation meta."""
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, photo_jpeg, screen_photo_jpeg
    from tapak.ponsel import ISP_PROFILES, ScreenParams

    path = _evidence_path(job)
    folder = WORK / job["doc"]
    dpi = PROTOCOL["render_dpi"]
    page_no = PROTOCOL["page"] - 1
    if job["seq"] is None:
        pdf = (folder / "induk.pdf").read_bytes()
        s = 1000 + job["master_image"]
    else:
        from tapak.marker.issue import IssueManifest

        manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        pdf = (folder / "salinan" / manifest.copies[job["seq"] - 1].file).read_bytes()
        s = job["seq"]
    page = render_pages(pdf, dpi, [page_no])[0]
    base = [PROTOCOL["splits"][job["split"]], DOCS.index(job["doc"]), s]
    cond = job["cond"]
    params = PhotoParams(angle_deg=job["angle"])
    ponsel = ISP_PROFILES["ponsel"]
    t0 = time.perf_counter()
    if cond.startswith("foto_"):
        step = cond.split("_", 1)[1]
        isp = None if step == "netral" else ponsel if step == "ponsel" else ponsel.only(step)  # type: ignore[union-attr]
        data, meta = photo_jpeg(page, np.random.default_rng(base + [11]), params, isp=isp,
                                isp_rng=np.random.default_rng(base + [12]))
    else:
        screen = ScreenParams(monitor=job["monitor"], distance_cm=job["distance_cm"],
                              subpixels=cond != "layar_ideal", glare=cond == "layar_silau")
        isp = ponsel if cond in ("layar_ponsel", "layar_silau") else None
        data, meta = screen_photo_jpeg(page, np.random.default_rng(base + [21]), params, screen, isp=isp,
                                       isp_rng=np.random.default_rng(base + [22]), render_dpi=float(dpi))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    p = meta["params"]
    sim = {"angle": job["angle"], "paper_clip_frac": round(p["paper_clip_frac"], 4),
           "image_size": meta["image_size"], "seconds": round(time.perf_counter() - t0, 1),
           "sha256": hashlib.sha256(data).hexdigest()}
    if "isp" in p:
        sim["isp"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p["isp"].items()}
    if "screen" in meta:
        sc = meta["screen"]
        sim.update(monitor=sc["monitor"], ppi=round(sc["ppi"], 1), distance_cm=sc["distance_cm"],
                   fill=round(sc["fill"], 3), page_dpi_on_screen=round(sc["page_dpi_on_screen"], 1),
                   grid_frequency=[round(f, 3) for f in sc["grid_frequency"]],
                   lens_sigma_px=round(p["lens_sigma_px"], 3), brightness_cd=round(p["brightness_cd"], 1),
                   glare_peak=round(p["glare_peak"], 3))
    return {**{k: job[k] for k in ("split", "doc", "seq", "cond")},
            **({"master_image": job["master_image"]} if job["seq"] is None else {}), "sim": sim}


def _channel_stats(obs, x: np.ndarray | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sb in obs:
        d = out.setdefault(sb.channel, {"read": 0, "errors": None if x is None else 0})
        d["read"] += int(len(sb))
        if x is not None and len(sb):
            d["errors"] += int(np.sum((sb.llr > 0) != (x[sb.positions] == 1)))
        meta = {k: sb.meta[k] for k in ("pattern_found", "signal_z", "pilot_z", "decoy_z", "clipped_share",
                                         "snr", "slots_read", "slots_implausible", "method", "dpi", "correlation",
                                         "effective_dpi", "registered", "moire_peaks", "moire_notched")
                if k in sb.meta}
        if "sigma_pt" in sb.meta:
            meta["sigma_pt"] = {k: round(float(v), 4) for k, v in sb.meta["sigma_pt"].items()}
        d["meta"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in meta.items()}
    return out


def _trace(job: dict) -> dict:
    """Trace one cached evidence image; verdict and channel statistics."""
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import run_trace

    ctx, _, _ = _context(job["doc"])
    data = _evidence_path(job).read_bytes()
    t0 = time.perf_counter()
    obs = collect_from_image(data, ctx)
    result = run_trace(obs, ctx)
    accused = [c.copy.seq for c in result.accused]
    expected = job["seq"]
    if expected is None:
        verdict = "salah" if accused else "tidak cukup bukti"
    elif not accused:
        verdict = "tidak cukup bukti"
    else:
        verdict = "benar" if accused == [expected] else "salah"
    x = ctx.codewords[expected - 1] if expected is not None else None
    best = result.accused[0].log10_false_accusation if result.accused else None
    return {**{k: job[k] for k in ("split", "doc", "seq", "cond")},
            **({"master_image": job["master_image"]} if expected is None else {}),
            "dekoder": job["dekoder"], "verdict": verdict, "accused": accused, "log10_fa_best": best,
            "positions_observed": int(result.threshold.n_observed), "channels": _channel_stats(obs, x),
            "evidence_sha256": hashlib.sha256(data).hexdigest(), "seconds": round(time.perf_counter() - t0, 1)}


def _pool(fn, jobs: list[dict], old_decoder: str | None = None) -> list[dict]:
    import multiprocessing as mp

    out = []
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init,
                             initargs=(old_decoder,)) as pool:
        for r in pool.map(fn, jobs, chunksize=1):
            brief = {k: r[k] for k in ("doc", "seq", "cond", "verdict", "accused") if k in r}
            print(json.dumps(brief, ensure_ascii=False), flush=True)
            out.append(r)
    return out


def run_make(split: str) -> None:
    jobs = jobs_for(split)
    rows = _pool(_make, jobs)
    _write(RESULTS / f"bukti_{split}.jsonl", rows)


def _old_decoder() -> str:
    """The base commit's tapak package, exported once (read-only use of git)."""
    target = WORK / "dekoder_lama"
    if not (target / "tapak" / "decoder" / "image.py").exists():
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", PROTOCOL["base_commit"], "tapak"],
                                 check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
    return str(target)


def run_trace_split(split: str, decoder: str, conds: list[str] | None, again: bool) -> None:
    out = RESULTS / f"{split}_{decoder}.jsonl"
    if split == "uji" and out.exists() and not again:
        raise SystemExit(f"{out} sudah ada: set uji hanya dilacak sekali per dekoder (pakai --ulang untuk menimpa)")
    jobs = [dict(j, dekoder=decoder) for j in jobs_for(split) if not conds or j["cond"] in conds]
    missing = [j for j in jobs if not _evidence_path(j).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} gambar bukti belum dibuat; jalankan: ukur.py buat --split {split}")
    rows = _pool(_trace, jobs, _old_decoder() if decoder == "lama" else None)
    if conds and out.exists():  # a partial run replaces only its own conditions
        keep = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        rows = [r for r in keep if r["cond"] not in conds] + rows
    _write(out, rows)


# --- summary -------------------------------------------------------------------------------


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _counts(rows: list[dict]) -> str:
    c = {v: sum(r["verdict"] == v for r in rows) for v in ("benar", "tidak cukup bukti", "salah")}
    return f"{c['benar']} / {c['tidak cukup bukti']} / {c['salah']}"


def _channel_cell(rows: list[dict], channel: str) -> str:
    read = [r["channels"].get(channel, {}).get("read", 0) for r in rows]
    errs = [r["channels"].get(channel, {}).get("errors") or 0 for r in rows]
    total = sum(read)
    ber = f"{100 * sum(errs) / total:.1f} %" if total else "-"
    found = ""
    if channel == "background":
        n_found = sum(bool(r["channels"].get(channel, {}).get("meta", {}).get("pattern_found")) for r in rows)
        found = f", pola {n_found}/{len(rows)}"
    return f"{np.mean(read):.0f}; {ber}{found}"


def summarize(splits: list[str]) -> None:
    """Print the tables quoted in the docs (markdown) from research/ponsel/hasil."""
    sims = {}
    for split in splits:
        for r in _load(RESULTS / f"bukti_{split}.jsonl"):
            sims[(r["split"], r["doc"], r["seq"], r.get("master_image"), r["cond"])] = r["sim"]
    for split in splits:
        tables = {d: _load(RESULTS / f"{split}_{d}.jsonl") for d in ("lama", "baru")}
        tables = {d: rows for d, rows in tables.items() if rows}
        if not tables:
            continue
        print(f"\n### {split}\n")
        heads = " | ".join(f"{d}: benar / tcb / salah | {d}: geser (posisi; galat) | {d}: latar (posisi; galat)"
                           for d in tables)
        print(f"| kondisi | {heads} |")
        print("|---|" + "---|" * (3 * len(tables)))
        conds = PROTOCOL["photo_conditions"] + PROTOCOL["screen_conditions"]
        for cond in conds:
            cells = []
            for rows in tables.values():
                sel = [r for r in rows if r["cond"] == cond and r["seq"] is not None]
                cells += [_counts(sel), _channel_cell(sel, "shift"), _channel_cell(sel, "background")]
            print(f"| {cond} | " + " | ".join(cells) + " |")
        for cond in PROTOCOL["master_conditions"]:
            cells = []
            for rows in tables.values():
                sel = [r for r in rows if r["cond"] == cond and r["seq"] is None]
                cells += [_counts(sel), _channel_cell(sel, "shift"), _channel_cell(sel, "background")]
            print(f"| induk tanpa tanda, {cond} | " + " | ".join(cells) + " |")
        # Monitor conditions by monitor and distance.
        for d, rows in tables.items():
            print(f"\n{split}, dekoder {d}: foto layar per monitor dan jarak (benar dari jumlah)\n")
            for cond in PROTOCOL["screen_conditions"]:
                parts = []
                for mon in PROTOCOL["monitors"]:
                    sel = [r for r in rows if r["cond"] == cond and r["seq"] is not None
                           and design(r["seq"] - 1)["monitor"] == mon]
                    parts.append(f"{mon} {sum(r['verdict'] == 'benar' for r in sel)}/{len(sel)}")
                for dist in PROTOCOL["distances_cm"]:
                    sel = [r for r in rows if r["cond"] == cond and r["seq"] is not None
                           and design(r["seq"] - 1)["distance_cm"] == dist]
                    parts.append(f"{dist} cm {sum(r['verdict'] == 'benar' for r in sel)}/{len(sel)}")
                print(f"- {cond}: " + ", ".join(parts))
        wrong = sum(r["verdict"] == "salah" for rows in tables.values() for r in rows)
        print(f"\nTuduhan salah di {split}: {wrong}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("terbit")
    b = sub.add_parser("buat")
    b.add_argument("--split", choices=list(PROTOCOL["splits"]), required=True)
    t = sub.add_parser("lacak")
    t.add_argument("--split", choices=list(PROTOCOL["splits"]), required=True)
    t.add_argument("--dekoder", choices=["lama", "baru"], required=True)
    t.add_argument("--kondisi", default="", help="hanya kondisi ini (dipisah koma), untuk pengembangan")
    t.add_argument("--ulang", action="store_true", help="timpa hasil set uji yang sudah ada")
    r = sub.add_parser("ringkas")
    r.add_argument("--split", default="pengembangan,uji")
    args = ap.parse_args(argv)
    if args.cmd == "terbit":
        run_issue()
    elif args.cmd == "buat":
        run_make(args.split)
    elif args.cmd == "lacak":
        run_trace_split(args.split, args.dekoder, [c for c in args.kondisi.split(",") if c], args.ulang)
    else:
        summarize(args.split.split(","))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
