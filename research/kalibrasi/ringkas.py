"""Tables of the calibration study: before and after on the same evidence.

``--split dev``: the decoder before (``hasil/dev.jsonl``) against the development choice
(``hasil/dev_kandidat_putaranN.jsonl.gz``, model named in ``hasil/pilihan.json``). ``--split uji``: the
held-out run with the chosen decoder (``hasil/uji.jsonl``) against the decoder before on the
same registrations (``hasil/uji_banding.jsonl.gz``); PDF evidence is the same for both.

Per medium class (``kandidat.medium_class``): reliability tables per weight bin for the
background, shift rows, shift word groups and the fused read (positions, wrong, measured rate
with its exact 95 % Clopper-Pearson interval, the calibrated rate E / n and P(Poisson(E) >= k));
verdicts; score margins; the honest warnings of the three checks; the detection bound of the
read's weights against the measured stage-1 miss rate; false accusations.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kandidat  # noqa: E402
import ukur  # noqa: E402

CLASS_ORDER = ["pdf"] + [f"{f}|{b}" for f in ukur.SCREEN_FORMATS for b, _, _ in kandidat.BANDS] + \
    ["layar_sim", "foto", "ponsel", "monitor", "cetak"]
BIN_LABELS = [f"{lo:g}-{hi:g}" for lo, hi in zip(ukur.W_EDGES[:-1], ukur.W_EDGES[1:])]


def clopper_pearson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact two-sided interval for a binomial proportion."""
    from scipy.stats import beta

    if n <= 0:
        return 0.0, 1.0
    a = (1.0 - level) / 2.0
    lo = 0.0 if k == 0 else float(beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a, k + 1, n - k))
    return lo, hi


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def paired_rows(split: str) -> tuple[list[dict], list[dict], str]:
    """(before, after, model name) for a split, matched by evidence key."""
    if split == "dev":
        base = load_jsonl(ukur.HASIL / "dev.jsonl")
        choice = json.loads((ukur.HASIL / "pilihan.json").read_text(encoding="utf-8"))["dipilih"]
        rows, _ = kandidat.load_rounds()
        seen: set[str] = set()
        cand = []
        for r in rows:
            if r["kandidat"] == choice and r["key"] not in seen:
                seen.add(r["key"])
                cand.append(r)
        before = base
        after = [r for r in base if r["medium"] == "pdf"] + cand
        return before, after, choice
    after = load_jsonl(ukur.HASIL / "uji.jsonl")
    old = load_jsonl(ukur.HASIL / "uji_banding.jsonl.gz")
    before = [r for r in after if r["medium"] == "pdf"] + old
    fp = json.loads((ukur.HASIL / "pilihan.json").read_text(encoding="utf-8"))["dipilih"]
    return before, after, fp


def reliability_tables(rows: list[dict], kind: str) -> dict[str, list[dict]]:
    """Per medium class, per weight bin: n, wrong, rate, interval, calibrated rate, Poisson tail."""
    out = {}
    for c, bins in kandidat.calibration_table(rows, kind).items():
        cells = []
        for label, (n, k, e, ws) in zip(BIN_LABELS, bins):
            n, k = int(n), int(k)
            lo, hi = clopper_pearson(k, n)
            cells.append({"w": label, "n": n, "salah": k, "laju": k / n if n else None, "ci95": [lo, hi],
                          "terkalibrasi": e / n if n else None, "E": round(e, 3),
                          "p_terlalu_yakin": kandidat.poisson_tail(e, k) if n else None})
        out[c] = cells
    return out


def top_rates(rows: list[dict], kind: str = "latar", lo_bin: int = 4) -> dict[str, dict]:
    """Bins at and above ``lo_bin`` merged (w > 0.95 by default) per medium class."""
    out = {}
    for c, bins in kandidat.calibration_table(rows, kind).items():
        n = sum(b[0] for b in bins[lo_bin:])
        k = sum(b[1] for b in bins[lo_bin:])
        e = sum(b[2] for b in bins[lo_bin:])
        lo, hi = clopper_pearson(int(k), int(n))
        out[c] = {"n": int(n), "salah": int(k), "laju": k / n if n else None, "ci95": [lo, hi],
                  "terkalibrasi": e / n if n else None, "p_terlalu_yakin": kandidat.poisson_tail(e, int(k))}
    return out


def verdicts(rows: list[dict]) -> dict:
    """Per part and medium class: evidence, named correctly (any member), not named, false accusations."""
    out: dict = defaultdict(lambda: {"bukti": 0, "benar": 0, "tidak_disebut": 0, "tuduhan_salah": 0, "peringatan": 0,
                                     "hapus": 0, "kontradiksi": 0, "balik": 0, "skor": [], "skor_lain": []})
    for r in rows:
        key = f"{r['part']}|{kandidat.medium_class(r)}"
        d = out[key]
        d["bukti"] += 1
        if r["part"] != "induk":
            d["benar"] += 1 if r["anggota"] else 0
            d["tidak_disebut"] += 0 if r["anggota"] else 1
            if r["skor_anggota"] is not None:
                d["skor"].append(r["skor_anggota"])
        d["tuduhan_salah"] += 1 if r["salah"] else 0
        if r["skor_lain"] is not None:
            d["skor_lain"].append(r["skor_lain"])
        d["hapus"] += int(r["hapus"]["ditandai"])
        d["kontradiksi"] += int(bool((r["kontradiksi"] or {}).get("ditandai")))
        d["balik"] += int(r["balik"]["ditandai"])
        d["peringatan"] += int(kandidat._warned(r))
    final = {}
    for key, d in out.items():
        s, so = d.pop("skor"), d.pop("skor_lain")
        d["skor_median"] = round(float(np.median(s)), 3) if s else None
        d["skor_min"] = round(float(np.min(s)), 3) if s else None
        d["skor_lain_maks"] = round(float(np.max(so)), 3) if so else None
        final[key] = d
    return final


def paired_changes(before: list[dict], after: list[dict]) -> dict:
    """Verdicts gained and lost, new and cleared warnings, on the same evidence."""
    b = {r["key"]: r for r in before}
    gained, lost, warn_new, warn_gone, ratio = [], [], [], [], defaultdict(list)
    for r in after:
        o = b.get(r["key"])
        if o is None:
            continue
        if r["part"] != "induk":
            if len(r["anggota"]) > len(o["anggota"]):
                gained.append(r["key"])
            elif len(r["anggota"]) < len(o["anggota"]):
                lost.append(r["key"])
            if r["skor_anggota"] and o["skor_anggota"]:
                ratio[kandidat.medium_class(r)].append(r["skor_anggota"] / o["skor_anggota"])
        if kandidat._warned(r) and not kandidat._warned(o):
            warn_new.append(r["key"])
        if kandidat._warned(o) and not kandidat._warned(r):
            warn_gone.append(r["key"])
    return {"putusan_bertambah": gained, "putusan_hilang": lost, "peringatan_baru": warn_new,
            "peringatan_hilang": warn_gone,
            "rasio_skor_median": {c: round(float(np.median(v)), 4) for c, v in ratio.items()}}


def bound_vs_miss(rows: list[dict]) -> dict:
    """Per part, medium class and coalition size: evidence, stage-1 misses (no member named at
    stage 1), the mean proven bound for the read's weights (tempering 1 and 0.3) and the
    one-sided 95 % upper limit of the measured miss rate."""
    from scipy.stats import beta

    acc: dict = defaultdict(lambda: {"bukti": 0, "lolos": 0, "batas": [], "batas_03": []})
    for r in rows:
        if r["part"] == "induk" or "log10_batas_deteksi" not in r:
            continue
        k = 1 if r["part"] == "salinan" else len(r["members"])
        d = acc[f"{r['part']}|{kandidat.medium_class(r)}|c{k}"]
        d["bukti"] += 1
        members = set(r["members"] or [r["seq"]])
        d["lolos"] += 0 if members & set(r["dituduh_tahap1"]) else 1
        d["batas"].append(10.0 ** r["log10_batas_deteksi"]["1.0"])
        d["batas_03"].append(10.0 ** r["log10_batas_deteksi"]["0.3"])
    out = {}
    for key, d in sorted(acc.items()):
        n, m = d["bukti"], d["lolos"]
        upper = 1.0 if m == n else float(beta.ppf(0.95, m + 1, n - m))
        out[key] = {"bukti": n, "lolos": m, "laju_lolos": m / n, "batas_atas_95": upper,
                    "batas_rata2": float(np.mean(d["batas"])), "batas_rata2_tau03": float(np.mean(d["batas_03"])),
                    "batas_maks": float(np.max(d["batas"]))}
    return out


def false_accusations(rows: list[dict]) -> dict:
    wrong = [r["key"] for r in rows if r["salah"]]
    masters = [r for r in rows if r["part"] == "induk"]
    innocent = [r["skor_lain"] for r in rows if r["skor_lain"] is not None]
    return {"pelacakan": len(rows), "tuduhan_salah": wrong, "induk": len(masters),
            "induk_dituduh": sum(1 for r in masters if r["dituduh"]),
            "skor_tak_bersalah_maks": round(max(innocent), 4) if innocent else None}


def summarize(split: str, write_json: bool) -> dict:
    before, after, model = paired_rows(split)
    out = {"split": split, "model": model, "bukti": {"sebelum": len(before), "sesudah": len(after)}}
    for name, rows in (("sebelum", before), ("sesudah", after)):
        out[name] = {"kalibrasi": {kind: reliability_tables(rows, kind) for kind in ukur.KINDS},
                     "atas_095": {kind: top_rates(rows, kind) for kind in ukur.KINDS},
                     "putusan": verdicts(rows), "batas_vs_lolos": bound_vs_miss(rows),
                     "tuduhan_salah": false_accusations(rows)}
    out["berpasangan"] = paired_changes(before, after)
    print(f"# {split}: model {model}, {len(after)} bukti\n")
    print("## Pola latar, bobot di atas 0,95: salah / n (laju, CI 95 %; terkalibrasi)\n")
    for c in CLASS_ORDER:
        cells = []
        for name in ("sebelum", "sesudah"):
            t = out[name]["atas_095"]["latar"].get(c)
            if t and t["n"]:
                cells.append(f"{name} {t['salah']}/{t['n']} ({100 * t['laju']:.3f} %, {100 * t['ci95'][0]:.3f} sampai "
                             f"{100 * t['ci95'][1]:.3f}; {100 * t['terkalibrasi']:.3f} %, p {t['p_terlalu_yakin']:.2g})")
        if cells:
            print(f"* {c}: " + "; ".join(cells))
    print("\n## Gagal uji terlalu yakin (p < 1e-4), per jenis\n")
    for name in ("sebelum", "sesudah"):
        for kind in ukur.KINDS:
            bad = [(c, cell["w"], cell["salah"], cell["n"], round(cell["E"], 1))
                   for c, cells in out[name]["kalibrasi"][kind].items() for cell in cells
                   if cell["n"] and cell["p_terlalu_yakin"] is not None and cell["p_terlalu_yakin"] < 1e-4]
            print(f"* {name}, {kind}: {len(bad)} sel {bad[:12]}")
    print("\n## Putusan (benar / bukti; peringatan; skor median dan minimum)\n")
    for key in sorted(out["sesudah"]["putusan"]):
        a, b = out["sesudah"]["putusan"][key], out["sebelum"]["putusan"].get(key, {})
        print(f"* {key}: sebelum {b.get('benar')}/{b.get('bukti')} peringatan {b.get('peringatan')} skor "
              f"{b.get('skor_median')} min {b.get('skor_min')}; sesudah {a['benar']}/{a['bukti']} peringatan "
              f"{a['peringatan']} skor {a['skor_median']} min {a['skor_min']}; salah {b.get('tuduhan_salah')} -> "
              f"{a['tuduhan_salah']}")
    p = out["berpasangan"]
    print(f"\n## Berpasangan: putusan bertambah {len(p['putusan_bertambah'])}, hilang {len(p['putusan_hilang'])}; "
          f"peringatan baru {len(p['peringatan_baru'])}, hilang {len(p['peringatan_hilang'])}")
    print(f"rasio skor median: {p['rasio_skor_median']}")
    print("\n## Batas deteksi terhadap laju lolos tahap 1\n")
    for key, d in out["sesudah"]["batas_vs_lolos"].items():
        o = out["sebelum"]["batas_vs_lolos"].get(key, {})
        print(f"* {key}: lolos {d['lolos']}/{d['bukti']} (atas 95 % {d['batas_atas_95']:.3g}); batas rata-rata "
              f"sebelum {o.get('batas_rata2', float('nan')):.3g}, sesudah {d['batas_rata2']:.3g} (tau 0,3: "
              f"{d['batas_rata2_tau03']:.3g})")
    for name in ("sebelum", "sesudah"):
        f = out[name]["tuduhan_salah"]
        print(f"\n{name}: {f['pelacakan']} pelacakan, tuduhan salah {len(f['tuduhan_salah'])}, induk {f['induk']} "
              f"(dituduh {f['induk_dituduh']}), skor tak bersalah maks {f['skor_tak_bersalah_maks']}")
    if write_json:
        path = ukur.HASIL / f"ringkas_{split}.json"
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=("dev", "uji"), required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    summarize(args.split, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
