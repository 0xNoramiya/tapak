"""Tables of the word-group study: the held-out run before and after on the same registrations.

``hasil/uji.jsonl`` holds every held-out evidence traced with the chosen word model and, under
``sebelum``, the same registration decoded with the decoder before this study (``gauss``); PDF
evidence is the same for both. The tables are research/kalibrasi's (``ringkas.py``): reliability
per medium class and weight bin for the word groups (``kata``), the shift rows, the background and
the fused read; verdicts; paired changes; the detection bound against the measured stage-1 miss
rate; false accusations.

    python research/geser/ringkas.py --json      # hasil/ringkas_uji.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HASIL = ROOT / "research" / "geser" / "hasil"
KAL = ROOT / "research" / "kalibrasi"
sys.path.insert(0, str(KAL))


def _kal_ringkas():
    spec = importlib.util.spec_from_file_location("kal_ringkas", KAL / "ringkas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def paired() -> tuple[list[dict], list[dict], str]:
    """(before, after, model) of the held-out run, matched by evidence key."""
    after = [json.loads(x) for x in (HASIL / "uji.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    before = []
    for r in after:
        b = dict(r)
        if r.get("sebelum"):
            b.update(r["sebelum"])
        b.pop("sebelum", None)
        before.append(b)
    model = json.loads((HASIL / "pilihan.json").read_text(encoding="utf-8"))["dipilih"]
    return before, after, model


def summarize(write_json: bool) -> dict:
    R = _kal_ringkas()
    before, after, model = paired()
    kinds = ("kata", "gabungan", "baris", "latar")
    out: dict = {"model": model, "bukti": len(after)}
    for name, rows in (("sebelum", before), ("sesudah", after)):
        out[name] = {"kalibrasi": {k: R.reliability_tables(rows, k) for k in kinds},
                     "atas_095": {k: R.top_rates(rows, k) for k in kinds},
                     "atas_099": {k: R.top_rates(rows, k, lo_bin=5) for k in kinds},
                     "putusan": R.verdicts(rows), "batas_vs_lolos": R.bound_vs_miss(rows),
                     "tuduhan_salah": R.false_accusations(rows)}
        bad = {}
        for k in kinds:
            bad[k] = [(c, cell["w"], cell["salah"], cell["n"], round(cell["E"], 1))
                      for c, cells in out[name]["kalibrasi"][k].items() for cell in cells
                      if cell["n"] and cell["p_terlalu_yakin"] is not None and cell["p_terlalu_yakin"] < 1e-4]
        out[name]["sel_terlalu_yakin"] = bad
    out["berpasangan"] = R.paired_changes(before, after)
    print(f"# uji: model {model}, {len(after)} bukti\n")
    for name in ("sebelum", "sesudah"):
        for k in kinds:
            cells = out[name]["sel_terlalu_yakin"][k]
            print(f"* {name}, {k}: {len(cells)} sel terlalu yakin {cells[:14]}")
    print("\n## Kelompok kata, bobot di atas 0,99: salah / n (terkalibrasi E / n)\n")
    for c in R.CLASS_ORDER:
        cells = []
        for name in ("sebelum", "sesudah"):
            t = out[name]["atas_099"]["kata"].get(c)
            if t and t["n"]:
                cells.append(f"{name} {t['salah']}/{t['n']} ({100 * t['laju']:.2f} %; {100 * t['terkalibrasi']:.2f} %)")
        if cells:
            print(f"* {c}: " + "; ".join(cells))
    print("\n## Putusan\n")
    for key in sorted(out["sesudah"]["putusan"]):
        a, b = out["sesudah"]["putusan"][key], out["sebelum"]["putusan"].get(key, {})
        print(f"* {key}: {b.get('benar')}/{b.get('bukti')} -> {a['benar']}/{a['bukti']}; peringatan "
              f"{b.get('peringatan')} -> {a['peringatan']}; skor median {b.get('skor_median')} -> {a['skor_median']}")
    p = out["berpasangan"]
    print(f"\nberpasangan: bertambah {len(p['putusan_bertambah'])}, hilang {len(p['putusan_hilang'])}, peringatan baru "
          f"{len(p['peringatan_baru'])}, hilang {len(p['peringatan_hilang'])}; rasio skor {p['rasio_skor_median']}")
    for name in ("sebelum", "sesudah"):
        f = out[name]["tuduhan_salah"]
        print(f"{name}: {f['pelacakan']} pelacakan, tuduhan salah {len(f['tuduhan_salah'])}, induk {f['induk']} "
              f"(dituduh {f['induk_dituduh']}), skor tak bersalah maks {f['skor_tak_bersalah_maks']}")
    print("\n## Batas deteksi terhadap laju lolos tahap 1\n")
    for key, d in out["sesudah"]["batas_vs_lolos"].items():
        o = out["sebelum"]["batas_vs_lolos"].get(key, {})
        print(f"* {key}: lolos {d['lolos']}/{d['bukti']}; batas rata-rata {o.get('batas_rata2', float('nan')):.3g} -> "
              f"{d['batas_rata2']:.3g}")
    if write_json:
        (HASIL / "ringkas_uji.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float) + "\n",
                                                encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    summarize(ap.parse_args(argv).json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
