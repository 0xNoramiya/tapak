"""Tables of the screenshot study (research/layar/ukur.py) for the docs.

Reads ``research/layar/hasil/{split}.jsonl`` (or the file given with ``--berkas``) and prints
markdown tables; ``--json`` writes the numbers to ``research/layar/hasil/ringkas_{split}.json``.
Every number is computed from the rows; nothing is decided here (the floor rule is
``PROTOCOL["floor_rule"]`` of ukur.py).

    python research/layar/ringkas.py --split dev
    python research/layar/ringkas.py --split uji --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ukur import HASIL, KINDS, PROTOCOL, RESOLUTIONS  # noqa: E402

SETS = ("semua", "geser", "latar")
WHOLE = ("utuh", "bingkai")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def traces(rows: list[dict]) -> list[tuple[dict, dict]]:
    """(row, trace) pairs; an unmarked master has one trace per scheme."""
    return [(r, t) for r in rows for t in r["traces"]]


def _ber(pairs: list[tuple[dict, dict]], kind: str) -> tuple[int, int, int, int]:
    """(read, wrong, wrong with abs LLR >= 4, images) of one bit kind over traces of marked copies."""
    read = wrong = conf = 0
    for _, t in pairs:
        b = t["bits"].get(kind) or {}
        read += b.get("read", 0)
        wrong += b.get("wrong", 0) or 0
        conf += b.get("wrong_llr4", 0) or 0
    return read, wrong, conf, len(pairs)


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f} %" if b else "-"


def _named(pairs: list[tuple[dict, dict]], which: str) -> int:
    return sum(t["accuse"][which]["verdict"] == "benar" for _, t in pairs)


def _false(pairs: list[tuple[dict, dict]]) -> int:
    return sum(t["accuse"][w]["verdict"] == "salah" for _, t in pairs for w in SETS)


def _median(vals: list[float]) -> str:
    vals = [v for v in vals if v is not None]
    return f"{np.median(vals):.2f}" if vals else "-"


def floors(pairs: list[tuple[dict, dict]], renderer: str, fmt: str, which: str) -> int | None:
    """Lowest grid resolution from which every whole-page image at it and above names the copy
    (None: not even at the highest resolution)."""
    floor = None
    for dpi in sorted(RESOLUTIONS, reverse=True):
        sel = [(r, t) for r, t in pairs if r["renderer"] == renderer and r["fmt"] == fmt and r["dpi"] == dpi]
        if not sel:
            continue
        if all(t["accuse"][which]["verdict"] == "benar" for _, t in sel):
            floor = dpi
        else:
            break
    return floor


def calibration(pairs: list[tuple[dict, dict]], kind: str) -> list[dict]:
    """Weight bins (w = tanh(abs(L) / 2)) with measured and calibrated error rates, merged into
    w = 0, (0, 0.5], (0.5, 0.8], (0.8, 0.9], (0.9, 0.95], (0.95, 0.99], (0.99, 1]."""
    n = np.zeros(21)
    wrong = np.zeros(21)
    wsum = np.zeros(21)
    for _, t in pairs:
        b = t["bits"].get(kind) or {}
        if "bins_n" in b:
            n += b["bins_n"]
            wrong += b["bins_wrong"]
            wsum += b["bins_wsum"]
    out = []
    groups = [(0, 0), (1, 10), (11, 16), (17, 18), (19, 19), (20, 20)]
    for lo, hi in groups:
        nn, ww, ws = n[lo:hi + 1].sum(), wrong[lo:hi + 1].sum(), wsum[lo:hi + 1].sum()
        w_lo = 0.0 if lo == 0 else (lo - 1) / 20
        w_hi = hi / 20
        out.append({"w": f"{w_lo:.2f}-{w_hi:.2f}" if lo else "0", "n": int(nn), "wrong": int(ww),
                    "rate": round(ww / nn, 4) if nn else None,
                    "calibrated": round((nn - ws) / (2 * nn), 4) if nn and lo else (0.5 if nn else None)})
    return out


def summarize(split: str, path: Path | None = None, write_json: bool = False) -> dict:
    rows = _load(path or HASIL / f"{split}.jsonl")
    pairs = traces(rows)
    marked = [(r, t) for r, t in pairs if r["seq"] is not None]
    out: dict = {"split": split, "images": len(rows), "traces": len(pairs),
                 "false_accusations": _false(pairs), "per_cell": {}, "floors": {}, "calibration": {}}
    print(f"# Set {split}: {len(rows)} gambar, {len(pairs)} pelacakan, tuduhan salah {out['false_accusations']}\n")

    main = [(r, t) for r, t in marked if r["grid"] in ("utama", "tanpa_aa") and r["framing"] in WHOLE]
    for scheme in ("v2", "v1"):
        sel_s = [(r, t) for r, t in main if r["scheme"] == scheme]
        if not sel_s:
            continue
        print(f"## Halaman utuh, {scheme}\n")
        print("| Penggambar | Format | dpi | Gambar | Baris: terbaca/gambar, galat, salah yakin | "
              "Kata: terbaca/gambar, galat, salah yakin | Latar: galat | Benar semua / geser / latar | "
              "Skor/ambang semua, geser (median) |")
        print("|---|---|---|---|---|---|---|---|---|")
        for renderer in ("mupdf", "poppler", "cairo", "poppler_tanpa_aa"):
            for fmt in ("png", "pesan", "kecil"):
                for dpi in RESOLUTIONS:
                    sel = [(r, t) for r, t in sel_s if r["renderer"] == renderer and r["fmt"] == fmt and r["dpi"] == dpi]
                    if not sel:
                        continue
                    k = len(sel)
                    rb, wb, cb, _ = _ber(sel, "baris")
                    rk, wk, ck, _ = _ber(sel, "kata")
                    rl, wl, _, _ = _ber(sel, "latar")
                    named = [_named(sel, w) for w in SETS]
                    cell = {"images": k, "baris": [rb, wb, cb], "kata": [rk, wk, ck], "latar": [rl, wl],
                            "named": dict(zip(SETS, named)), "false": _false(sel),
                            "score_semua": _median([t["accuse"]["semua"]["score_z"] for _, t in sel]),
                            "score_geser": _median([t["accuse"]["geser"]["score_z"] for _, t in sel]),
                            "registered": sum(t["registered"] for _, t in sel)}
                    out["per_cell"][f"{scheme}|{renderer}|{fmt}|{dpi}"] = cell
                    print(f"| {renderer} | {fmt} | {dpi} | {k} | {rb / k:.1f}, {_pct(wb, rb)}, {cb} | "
                          f"{rk / k:.1f}, {_pct(wk, rk)}, {ck} | {_pct(wl, rl)} | "
                          f"{named[0]} / {named[1]} / {named[2]} | {cell['score_semua']}, {cell['score_geser']} |")
        print()
        print(f"### Batas bawah resolusi, {scheme} (dpi terendah yang mulai dari sana setiap gambar halaman utuh "
              f"menyebut salinan)\n")
        print("| Penggambar | Format | semua kanal | geser saja | latar saja |")
        print("|---|---|---|---|---|")
        for renderer in ("mupdf", "poppler", "cairo", "poppler_tanpa_aa"):
            for fmt in ("png", "pesan", "kecil"):
                sel = [(r, t) for r, t in sel_s if r["renderer"] == renderer and r["fmt"] == fmt]
                if not sel:
                    continue
                f = {w: floors(sel, renderer, fmt, w) for w in SETS}
                out["floors"][f"{scheme}|{renderer}|{fmt}"] = f
                print(f"| {renderer} | {fmt} | " + " | ".join("-" if f[w] is None else str(f[w]) for w in SETS) + " |")
        print()

    crops = [(r, t) for r, t in marked if r["grid"] == "potong"]
    if crops:
        print("## Potongan jendela penampil (v2)\n")
        print("| Penggambar | Format | dpi | Gambar | Terdaftar | Kata terbaca/gambar, galat | Latar galat | "
              "Benar semua / geser / latar |")
        print("|---|---|---|---|---|---|---|---|")
        for renderer in ("mupdf", "poppler", "cairo"):
            for fmt in ("png", "pesan"):
                for dpi in PROTOCOL["grids"][split]["potong"]["resolutions"]:
                    sel = [(r, t) for r, t in crops if r["renderer"] == renderer and r["fmt"] == fmt and r["dpi"] == dpi]
                    if not sel:
                        continue
                    k = len(sel)
                    rk, wk, _, _ = _ber(sel, "kata")
                    rl, wl, _, _ = _ber(sel, "latar")
                    named = [_named(sel, w) for w in SETS]
                    out["per_cell"][f"potong|{renderer}|{fmt}|{dpi}"] = {
                        "images": k, "registered": sum(t["registered"] for _, t in sel), "kata": [rk, wk],
                        "latar": [rl, wl], "named": dict(zip(SETS, named)), "false": _false(sel)}
                    print(f"| {renderer} | {fmt} | {dpi} | {k} | {sum(t['registered'] for _, t in sel)} | "
                          f"{rk / k:.1f}, {_pct(wk, rk)} | {_pct(wl, rl)} | {named[0]} / {named[1]} / {named[2]} |")
        print()

    unmarked = [(r, t) for r, t in pairs if r["seq"] is None]
    if unmarked:
        top = max((t["accuse"][w]["max_innocent_z"] or 0.0) for _, t in unmarked for w in SETS)
        acc = _false(unmarked)
        out["unmarked"] = {"traces": len(unmarked), "accused": acc, "max_score_z": top}
        print(f"## Induk tanpa tanda\n\n{len(unmarked)} pelacakan, {acc} tuduhan, skor tertinggi {top:.2f} ambang\n")
    innocent = max((t["accuse"][w]["max_innocent_z"] or 0.0) for _, t in marked for w in SETS) if marked else 0.0
    out["max_innocent_z"] = innocent
    erasure = sum(bool(t["accuse"]["semua"]["erasure_flagged"]) for _, t in marked)
    out["erasure_flagged_honest"] = erasure
    print(f"Skor tak bersalah tertinggi: {innocent:.2f} ambang; peringatan penghapusan pada salinan jujur: "
          f"{erasure} dari {len(marked)}\n")

    print("## Kalibrasi bobot (semua gambar salinan, v2 dan v1)\n")
    for renderer in ("mupdf", "poppler", "cairo", "poppler_tanpa_aa", None):
        sel = [(r, t) for r, t in marked if renderer is None or r["renderer"] == renderer]
        for kind in KINDS:
            cal = calibration(sel, kind)
            out["calibration"][f"{renderer or 'semua'}|{kind}"] = cal
            cells = "; ".join(f"w {c['w']}: {c['n']}, salah {_pct(c['wrong'], c['n'])} "
                              f"(terkalibrasi {100 * c['calibrated']:.1f} %)" for c in cal if c["n"])
            print(f"* {renderer or 'semua'}, {kind}: {cells}")
    print()
    if write_json:
        (HASIL / f"ringkas_{split}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=("dev", "uji"), required=True)
    ap.add_argument("--berkas", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    summarize(args.split, args.berkas, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
