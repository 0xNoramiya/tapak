"""Tables of the agreement-targeted erasure measurements (``ukur.py`` output).

    python research/sepakat/ringkas.py research/sepakat/hasil/serang_dev.jsonl research/sepakat/hasil/jujur_dev.jsonl
    python research/sepakat/ringkas.py ... --pilihan gabung --ambang 3.09

Per channel and configuration: evidence count, outcome of the single-stage and the staged
accusation (correct: at least one coalition member named and nobody else; insufficient:
nobody named; wrong: anyone outside the coalition named), members named, positions read, the
share of agreeing positions neutralized per channel (paired with the honest control) and the
erasure check's detection rate. Honest evidence: the erasure statistic's mean, standard
deviation, minimum and alarms per channel. Every wrong accusation is listed.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

STRENGTH_CHOICES = ("gabung", "mutlak", "energi")
TARGETED = ("semua/acak", "latar/acak", "geser/acak", "semua/salin")


def load(paths: list[str]) -> list[dict]:
    """All JSON lines of the given files."""
    rows = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def outcome(v: dict) -> str:
    """'benar', 'tidak cukup bukti' or 'salah' for one accusation record."""
    if v["salah"]:
        return "salah"
    return "benar" if v["anggota"] > 0 else "tidak cukup bukti"


def honest_key(r: dict) -> tuple:
    return (r["set"], r["benih"], r["k"], r["koalisi_ke"], r["kanal"])


def neutralized(rows: list[dict]) -> dict[tuple, dict[str, list[float]]]:
    """Per (channel, configuration): 1 - attacked / honest signed weight at agreeing positions."""
    honest = {honest_key(r): r for r in rows if r.get("bagian") == "serangan" and r["serangan"] == "jujur"}
    out: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("bagian") != "serangan" or r["serangan"] == "jujur":
            continue
        h = honest.get(honest_key(r))
        if h is None:
            continue
        for ch in ("shift", "background"):
            base = h["sama"][ch][1]
            if base > 0:
                out[(r["kanal"], r["serangan"])][ch].append(1.0 - r["sama"][ch][1] / base)
    return out


def _fmt(x: float | None, d: int = 2) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def attack_table(rows: list[dict], choice: str, thr: float) -> list[str]:
    """Markdown table of the attack grid."""
    neut = neutralized(rows)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("bagian") == "serangan":
            groups[(r["set"], r["kanal"], r["serangan"])].append(r)
    lines = ["| set | kanal | serangan | n | satu tahap b/t/s | bertahap b/t/s | anggota disebut (bertahap) | "
             "posisi terbaca | dinetralkan geser / latar | terdeteksi |", "|" + "---|" * 10]
    for key in sorted(groups):
        g = groups[key]
        one = [outcome(r["putusan"]["satu"]) for r in g]
        st = [outcome(r["putusan"]["bertahap"]) for r in g]
        named = [r["putusan"]["bertahap"]["anggota"] / r["k"] for r in g]
        read = np.mean([r["putusan"]["satu"]["terbaca"] for r in g])
        nz = neut.get((key[1], key[2]), {})
        det = [r["hapus"][choice] is not None and r["hapus"][choice] <= -thr for r in g]
        lines.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(g)} | {one.count('benar')}/{one.count('tidak cukup bukti')}/"
            f"{one.count('salah')} | {st.count('benar')}/{st.count('tidak cukup bukti')}/{st.count('salah')} | "
            f"{100 * np.mean(named):.0f} % | {read:.0f} | "
            f"{_fmt(np.mean(nz['shift']) if nz.get('shift') else None)} / "
            f"{_fmt(np.mean(nz['background']) if nz.get('background') else None)} | {sum(det)}/{len(g)} |")
    return lines


def by_k_table(rows: list[dict], choice: str, thr: float) -> list[str]:
    """Escape (staged: nobody named) and detection by coalition size, per set and channel, semua/acak."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("bagian") == "serangan" and r["serangan"] in ("semua/acak", "jujur"):
            groups[(r["set"], r["kanal"], r["serangan"], r["N"], r["k"])].append(r)
    lines = ["| set | kanal | serangan | N | k | n | lolos (bertahap) | terdeteksi |", "|" + "---|" * 8]
    for key in sorted(groups):
        g = groups[key]
        esc = sum(r["putusan"]["bertahap"]["anggota"] == 0 for r in g)
        det = sum(r["hapus"][choice] is not None and r["hapus"][choice] <= -thr for r in g)
        lines.append(f"| {' | '.join(str(v) for v in key)} | {len(g)} | {esc} | {det} |")
    return lines


def honest_table(rows: list[dict], thr: float) -> list[str]:
    """Erasure statistic on honest evidence (calibration set, paired controls, benchmark)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("bagian") in ("jujur", "bench"):
            groups[(r.get("set", "bench"), r.get("kanal", r.get("jenis")), r["bagian"])].append(r)
        elif r.get("bagian") == "serangan" and r["serangan"] == "jujur":
            groups[(r["set"], r["kanal"], "kontrol")].append(r)
    lines = ["| set | kanal | sumber | n | " + " | ".join(f"{c}: rata2 / sd / min / alarm" for c in STRENGTH_CHOICES) + " |",
             "|" + "---|" * (4 + len(STRENGTH_CHOICES))]
    for key in sorted(groups):
        g = groups[key]
        cells = []
        for c in STRENGTH_CHOICES:
            z = np.array([r["hapus"][c] for r in g if r["hapus"][c] is not None])
            if z.size == 0:
                cells.append("-")
                continue
            cells.append(f"{z.mean():.2f} / {z.std(ddof=1) if z.size > 1 else 0:.2f} / {z.min():.2f} / {int(np.sum(z <= -thr))}")
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {len(g)} | " + " | ".join(cells) + " |")
    return lines


def calibration(rows: list[dict], which: str = "dev") -> dict[str, float]:
    """Sample standard deviation of Z per strength choice over all honest evidence of a set."""
    out = {}
    for c in STRENGTH_CHOICES:
        z = [r["hapus"][c] for r in rows if r["hapus"][c] is not None and r.get("set") == which
             and (r.get("bagian") == "jujur" or (r.get("bagian") == "serangan" and r["serangan"] == "jujur"))]
        out[c] = float(np.std(z, ddof=1)) if len(z) > 1 else float("nan")
        out[c + "_n"] = len(z)
    return out


def detection_rates(rows: list[dict], which: str, thr_by_choice: dict[str, float]) -> dict[str, float]:
    """Detection rate over the targeted attacks of a set, per strength choice."""
    out = {}
    for c in STRENGTH_CHOICES:
        g = [r for r in rows if r.get("bagian") == "serangan" and r["set"] == which and r["serangan"] in TARGETED]
        out[c] = float(np.mean([r["hapus"][c] is not None and r["hapus"][c] <= -thr_by_choice[c] for r in g])) if g else float("nan")
    return out


def docs_table(rows: list[dict], which: str, choice: str, thr: float) -> list[str]:
    """The table quoted in docs/cara-kerja.md: per channel, the honest control (named correctly,
    alarms) and per configuration escapes (staged: no member named) and detections."""
    configs = ("semua/acak", "latar/acak", "geser/acak", "semua/salin", "semua/rata")
    head = "| Kanal | Salinan pertama, jujur: benar; alarm | " + " | ".join(configs) + " |"
    lines = [head, "|" + "---|" * (2 + len(configs))]
    for channel in ("pdf", "layar", "foto", "cetak"):
        g = [r for r in rows if r.get("bagian") == "serangan" and r["set"] == which and r["kanal"] == channel]
        if not g:
            continue
        h = [r for r in g if r["serangan"] == "jujur"]
        cells = [f"{sum(outcome(r['putusan']['bertahap']) == 'benar' for r in h)} dari {len(h)}; "
                 f"{sum(r['hapus'][choice] is not None and r['hapus'][choice] <= -thr for r in h)}"]
        for cfg in configs:
            a = [r for r in g if r["serangan"] == cfg]
            if not a:
                cells.append("-")
                continue
            esc = sum(r["putusan"]["bertahap"]["anggota"] == 0 for r in a)
            det = sum(r["hapus"][choice] is not None and r["hapus"][choice] <= -thr for r in a)
            cells.append(f"lolos {esc}, terdeteksi {det} (dari {len(a)})")
        lines.append(f"| {channel} | " + " | ".join(cells) + " |")
    return lines


def wrong(rows: list[dict]) -> list[str]:
    """Every wrong accusation (anyone outside the coalition named at any stage)."""
    out = []
    for r in rows:
        for name in ("satu", "bertahap"):
            v = r.get("putusan", {}).get(name)
            if v and v["salah"]:
                out.append(f"{r.get('bagian')} {r.get('set')} {r.get('dok')} N={r.get('N')} {r.get('kanal')} "
                           f"{r.get('serangan', '')} {name}: {v['salah']}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--pilihan", default="gabung", choices=STRENGTH_CHOICES)
    ap.add_argument("--ambang", type=float, default=3.0902)
    args = ap.parse_args(argv)
    rows = load(args.files)
    cal = calibration(rows)
    print("Kalibrasi dev (sd Z):", {k: round(v, 3) if isinstance(v, float) else v for k, v in cal.items()})
    thr = {c: 3.0902 * max(1.0, math.ceil(cal[c] * 100) / 100) if not math.isnan(cal[c]) else 3.0902
           for c in STRENGTH_CHOICES}
    print("Ambang per pilihan:", {k: round(v, 3) for k, v in thr.items()})
    print("Deteksi dev per pilihan:", detection_rates(rows, "dev", thr))
    print()
    print("\n".join(attack_table(rows, args.pilihan, args.ambang)))
    print()
    print("\n".join(by_k_table(rows, args.pilihan, args.ambang)))
    print()
    print("\n".join(honest_table(rows, args.ambang)))
    print()
    for which in ("dev", "uji"):
        lines = docs_table(rows, which, args.pilihan, args.ambang)
        if len(lines) > 2:
            print(f"Tabel dokumen ({which}):")
            print("\n".join(lines))
            print()
    w = wrong(rows)
    print(f"Tuduhan salah: {len(w)}")
    for line in w:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
