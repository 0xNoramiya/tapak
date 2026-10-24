"""Tables of the registration study (research/registrasi/ukur.py) for the docs.

Reads ``research/registrasi/hasil/{split}.jsonl`` (or ``--berkas``) and prints the numbers; with
``--json`` they go to ``research/registrasi/hasil/ringkas_{split}.json``. Nothing is decided here.
"Before" is a trace with the rescue stage switched off (the pipeline before this study): a row
traced once (the rescue did not run) is the same before and after.

    python research/registrasi/ringkas.py --split dev
    python research/registrasi/ringkas.py --split uji --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ukur  # noqa: E402

STAGE_ORDER = ("tanpa_teks", "tanpa_kandidat", "awal_salah", "ecc_menyimpang", "ecc_di_bawah_ambang",
               "halaman_salah", "pose_salah")


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def before(row: dict) -> dict:
    """The trace without the rescue stage."""
    return row["sebelum"] if row.get("sebelum") is not None else row["sesudah"]


def pose_cls(t: dict) -> str:
    """'tidak_ditemukan' or the pose class of a registration (benar, kasar, salah)."""
    if not t["registered"]:
        return "tidak_ditemukan"
    return t["registration"].get("class") or ("benar" if t["registration"]["correct"] else "salah")


def group(row: dict) -> str:
    """Evidence type of a row: grid, with the source grid for cross-document rows."""
    if row["grid"] == "silang":
        return f"silang:{row['source_grid']}"
    if row["grid"] == "induk":
        return f"induk:{row['kind']}"
    return row["grid"]


def stage(row: dict, t: dict) -> str | None:
    """Which stage gave up on a marked copy of the right document (None: a correct or rough pose).

    tanpa_teks: no master word visible (nothing to register by content); tanpa_kandidat: no initial
    pose; awal_salah: initial poses, none of the true page within WRONG_POSE_PX; ecc_menyimpang: a
    good initial pose that ECC refined off; ecc_di_bawah_ambang: ECC on the true page within
    WRONG_POSE_PX but below the correlation threshold; halaman_salah and pose_salah: registered,
    but to another page or with the text off."""
    cls = pose_cls(t)
    if cls in ("benar", "kasar"):
        return None
    if t.get("n_text_points", 1) == 0:
        return "tanpa_teks"
    if cls == "salah":
        return "halaman_salah" if t["registration"]["page"] != row["page"] else "pose_salah"
    d = t["diag"]
    good_init = [c for c in d["candidates"] if c["page"] == row["page"] and c["err_p95"] is not None
                 and c["err_p95"] <= ukur.WRONG_POSE_PX]
    if not d["candidates"]:
        return "tanpa_kandidat"
    if not good_init:
        return "awal_salah"
    refined_true = [r for r in d["refined"] if r["page"] == row["page"]]
    if any(r["err_p95"] is not None and r["err_p95"] <= ukur.WRONG_POSE_PX for r in refined_true):
        return "ecc_di_bawah_ambang"
    return "ecc_menyimpang"


def height_bin(row: dict) -> str:
    if row.get("position") == "paragraf":
        return "paragraf"
    h = row.get("height")
    return "-" if h is None else f"{int(round(100 * h))}%"


def tally(rows: list[dict]) -> dict:
    """Found, pose classes and verdicts before and after, for one set of rows."""
    out: dict = {"n": len(rows)}
    for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"])):
        ts = [pick(r) for r in rows]
        cls = Counter(pose_cls(t) for t in ts)
        out[name] = {"ditemukan": sum(t["registered"] for t in ts), "benar": cls["benar"], "kasar": cls["kasar"],
                     "salah": cls["salah"], "disebut": sum(t["accuse"]["verdict"] == "benar" for t in ts),
                     "tuduhan_salah": sum(t["accuse"]["verdict"] == "salah" for t in ts)}
    return out


def summarize(split: str, path: Path | None = None, write_json: bool = False) -> dict:
    rows = load(path or ukur.HASIL / f"{split}.jsonl")
    marked = [r for r in rows if r["grid"] not in ("induk", "silang")]
    out: dict = {"split": split, "rows": len(rows), "traces": sum(1 + (r.get("sebelum") is not None) for r in rows)}

    # registration and verdicts per evidence type
    by_group = defaultdict(list)
    for r in rows:
        by_group[group(r)].append(r)
    out["per_jenis"] = {g: tally(rs) for g, rs in sorted(by_group.items())}

    # screenshot crops: position x height, chrome
    crop = [r for r in marked if r["grid"] in ("potong", "paragraf")]
    out["potong_posisi_tinggi"] = {}
    for r in crop:
        key = f"{r['position']} {height_bin(r)}"
        out["potong_posisi_tinggi"].setdefault(key, []).append(r)
    out["potong_posisi_tinggi"] = {k: tally(v) for k, v in sorted(out["potong_posisi_tinggi"].items())}
    out["potong_bingkai"] = {("bingkai" if c else "polos"): tally([r for r in crop if r["chrome"] == c])
                             for c in (False, True)}
    out["potong_dpi"] = {str(d): tally([r for r in crop if r["dpi"] == d]) for d in ukur.CROP_DPI}
    out["potong_format"] = {f: tally([r for r in crop if r["fmt"] == f]) for f in ("png", "pesan")}
    out["potong_halaman"] = {f"{d} hal {p}": tally([r for r in crop if r["doc"] == d and r["page"] == p])
                             for d in ukur.DOCS for p in ukur.PAGES}

    # whole pages at low resolution: per renderer and format, per dpi
    low = [r for r in marked if r["grid"] == "rendah"]
    out["rendah"] = {}
    for renderer in ukur.RENDERERS:
        for fmt in ("png", "pesan", "kecil"):
            sel = [r for r in low if r["renderer"] == renderer and r["fmt"] == fmt]
            if sel:
                out["rendah"][f"{renderer} {fmt}"] = {str(d): tally([r for r in sel if r["dpi"] == d])
                                                     for d in ukur.LOW_DPI}
    out["rendah_dpi"] = {str(d): tally([r for r in low if r["dpi"] == d]) for d in ukur.LOW_DPI}
    # floor as in research/layar: the lowest grid dpi from which every whole page at that and every
    # higher grid dpi names the leaked copy (research/layar: every image from 56 dpi up names it)
    out["rendah_batas"] = {}
    for renderer in ukur.RENDERERS:
        for fmt in ("png", "pesan", "kecil"):
            sel = [r for r in low if r["renderer"] == renderer and r["fmt"] == fmt]
            if not sel:
                continue
            cell = {}
            for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"])):
                floor = None
                for d in sorted(ukur.LOW_DPI, reverse=True):
                    if all(pick(r)["accuse"]["verdict"] == "benar" for r in sel if r["dpi"] == d):
                        floor = d
                    else:
                        break
                cell[name] = floor
            out["rendah_batas"][f"{renderer} {fmt}"] = cell

    # photos of part of a page
    photo = [r for r in marked if r["grid"] == "foto"]
    out["foto_posisi"] = {}
    for r in photo:
        out["foto_posisi"].setdefault(f"{r['position']} {height_bin(r)}", []).append(r)
    out["foto_posisi"] = {k: tally(v) for k, v in sorted(out["foto_posisi"].items())}
    out["foto_isp"] = {("isp" if i else "tanpa_isp"): tally([r for r in photo if r["isp"] == i]) for i in (False, True)}

    # which stage gave up (before), per evidence type, and what the rescue did with them
    stages: dict = {}
    for r in marked:
        s = stage(r, before(r))
        if s is None:
            continue
        g = stages.setdefault(r["grid"], {k: {"n": 0, "sesudah_benar": 0, "sesudah_kasar": 0, "sesudah_salah": 0,
                                               "sesudah_disebut": 0} for k in STAGE_ORDER})
        g[s]["n"] += 1
        a = r["sesudah"]
        c = pose_cls(a)
        if c in ("benar", "kasar", "salah"):
            g[s][f"sesudah_{c}"] += 1
        g[s]["sesudah_disebut"] += a["accuse"]["verdict"] == "benar"
    out["tahap_gagal"] = stages

    # oracle (only in rows traced with TAPAK_REG_ORAKEL): of the failures before, which single stage
    # could have found the page on its own with plain ECC
    orc: Counter = Counter()
    for r in marked:
        t = before(r)
        if stage(r, t) in (None, "tanpa_teks") or not t.get("oracle"):
            continue
        ok = sorted(k for k, v in t["oracle"].items() if v and v["ecc_p95"] is not None
                    and v["ecc_p95"] <= ukur.WRONG_POSE_PX and v["cc"] >= 0.75)
        orc["+".join(ok) or "tidak_ada"] += 1
    out["orakel"] = dict(orc)

    # score margin of named traces (all channels), before and after
    out["skor"] = {}
    for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"])):
        named = [pick(r)["accuse"] for r in marked if pick(r)["accuse"]["verdict"] == "benar"]
        z = [a["score_z"] for a in named if a["score_z"] is not None]
        inn = [pick(r)["accuse"]["max_innocent_z"] for r in rows if pick(r)["accuse"]["max_innocent_z"] is not None]
        fa = [a["log10_fa"] for a in named if a["log10_fa"] is not None]
        out["skor"][name] = {"disebut": len(named), "skor_min": round(min(z), 3) if z else None,
                             "skor_median": round(float(np.median(z)), 3) if z else None,
                             "tak_bersalah_maks": round(max(inn), 3) if inn else None,
                             "log10_fa_maks": max(fa) if fa else None}
    rescued = [r for r in marked if r["sesudah"]["accuse"]["verdict"] == "benar"
               and before(r)["accuse"]["verdict"] != "benar"]
    z = [r["sesudah"]["accuse"]["score_z"] for r in rescued]
    out["skor"]["baru_disebut"] = {"n": len(rescued), "skor_min": round(min(z), 3) if z else None,
                                   "skor_median": round(float(np.median(z)), 3) if z else None}
    lost = [r for r in marked if before(r)["accuse"]["verdict"] == "benar" and r["sesudah"]["accuse"]["verdict"] != "benar"]
    out["skor"]["hilang"] = len(lost)

    # warnings on honest evidence (marked copies of the right document and unmarked masters)
    honest = [r for r in rows if r["grid"] != "silang"]
    out["peringatan"] = {}
    for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"])):
        ts = [pick(r) for r in honest]
        reg = [t for t in ts if t["registered"]]
        wrong = [t for t in reg if pose_cls(t) == "salah"]
        out["peringatan"][name] = {
            "jejak": len(ts), "penghapusan": sum(bool(t["accuse"]["erasure_flagged"]) for t in ts),
            "bacaan_jelas_tanpa_nama": sum(bool(t["accuse"]["contradiction_flagged"]) for t in ts),
            "terdaftar": len(reg), "pose_salah": len(wrong),
            "penghapusan_pose_salah": sum(bool(t["accuse"]["erasure_flagged"]) for t in wrong),
            "bacaan_jelas_pose_salah": sum(bool(t["accuse"]["contradiction_flagged"]) for t in wrong)}
    cross = [r for r in rows if r["grid"] == "silang"]
    out["silang"] = {}
    for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"])):
        ts = [pick(r) for r in cross]
        out["silang"][name] = {"n": len(ts), "terdaftar": sum(t["registered"] for t in ts),
                               "penghapusan": sum(bool(t["accuse"]["erasure_flagged"]) for t in ts),
                               "bacaan_jelas_tanpa_nama": sum(bool(t["accuse"]["contradiction_flagged"]) for t in ts),
                               "tuduhan_salah": sum(t["accuse"]["verdict"] == "salah" for t in ts)}

    # false accusations over every trace
    out["tuduhan_salah"] = {name: sum(pick(r)["accuse"]["verdict"] == "salah" for r in rows)
                            for name, pick in (("sebelum", before), ("sesudah", lambda r: r["sesudah"]))}

    # rescue stage: how often it ran, its outcomes, and the wrong poses it accepted
    ran = [r for r in rows if r["sesudah"]["diag"].get("rescue")]
    out["penyelamat"] = {"berjalan": len(ran),
                         "hasil": dict(Counter(r["sesudah"]["diag"]["rescue"]["outcome"] for r in ran)),
                         "terdaftar_menurut_kelas": dict(Counter(pose_cls(r["sesudah"]) for r in ran
                                                                 if r["sesudah"]["registered"])),
                         "asal_pose": dict(Counter(r["sesudah"]["registration"]["method"] for r in ran
                                                   if r["sesudah"]["registered"]))}

    # time per trace
    def secs(pick):
        v = [pick(r)["seconds"] for r in rows]
        return {"median": round(float(np.median(v)), 1), "p95": round(float(np.percentile(v, 95)), 1),
                "maks": round(float(max(v)), 1)}
    out["detik"] = {"sebelum": secs(before), "sesudah": secs(lambda r: r["sesudah"]),
                    "sesudah_bila_penyelamat_berjalan": (
                        {"median": round(float(np.median([r["sesudah"]["seconds"] for r in ran])), 1),
                         "p95": round(float(np.percentile([r["sesudah"]["seconds"] for r in ran], 95)), 1)}
                        if ran else None)}

    _print(out)
    if write_json:
        (ukur.HASIL / f"ringkas_{split}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
    return out


def _fmt(t: dict) -> str:
    b, a = t["sebelum"], t["sesudah"]
    return (f"n={t['n']:4d}  ditemukan {b['ditemukan']:4d} -> {a['ditemukan']:4d}  benar {b['benar']:4d} -> "
            f"{a['benar']:4d}  kasar {b['kasar']:3d} -> {a['kasar']:3d}  salah {b['salah']:3d} -> {a['salah']:3d}  "
            f"disebut {b['disebut']:4d} -> {a['disebut']:4d}  tuduhan salah {b['tuduhan_salah']} -> {a['tuduhan_salah']}")


def _print(out: dict) -> None:
    print(f"# {out['split']}: {out['rows']} gambar, {out['traces']} pelacakan")
    for section in ("per_jenis", "potong_bingkai", "potong_format", "potong_dpi", "potong_halaman",
                    "potong_posisi_tinggi", "rendah_dpi", "foto_isp", "foto_posisi"):
        print(f"\n## {section}")
        for k, t in out[section].items():
            print(f"{k:28s} {_fmt(t)}")
    print("\n## rendah per penggambar dan format (disebut sebelum -> sesudah, per dpi)")
    for k, cells in out["rendah"].items():
        print(f"{k:24s} " + "  ".join(f"{d}:{c['sebelum']['disebut']}->{c['sesudah']['disebut']}/{c['n']}"
                                      for d, c in cells.items()))
    for section in ("rendah_batas", "tahap_gagal", "orakel", "skor", "peringatan", "silang", "tuduhan_salah", "penyelamat",
                    "detik"):
        print(f"\n## {section}")
        print(json.dumps(out[section], indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=("dev", "uji"), required=True)
    ap.add_argument("--berkas", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    summarize(args.split, Path(args.berkas) if args.berkas else None, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
