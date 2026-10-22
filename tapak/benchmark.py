"""Regression benchmark over the synthetic photo sets (``make bench``).

Traces every image listed in ``samples/photos/truth.json`` (phone photos of a page as it
looks on screen, and screenshots; ``make photos``) and, when they exist,
``samples/photos-cetak/truth.json`` (phone photos of printed pages, ``make photos-cetak``),
``samples/photos-ponsel/truth.json`` (the photos of ``make photos`` processed by the
simulated phone ISP, ``make photos-ponsel``) and ``samples/photos-layar/truth.json`` (phone
photos of the copy on a simulated monitor, with the ISP, ``make photos-layar``) against the
issued document they were made from. Printed photos are traced one page at a time and as
two-page pairs (pages 1 and 2 of the same copy, angle and repetition, fused in one trace).
Results are counted per medium: "layar" (screen photos and screenshots), "cetak, 1 halaman",
"cetak, 2 halaman", "foto ponsel" and "foto layar (monitor)". No medium is ever counted
together with another: the background pattern survives only on screens, and the phone and
monitor sets are simulation studies of their own. For each medium the benchmark counts
correct identifications, honest "tidak cukup bukti" verdicts and wrong accusations (which
must stay at zero).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

KIND_PRINT = "cetak"  # same values as tapak.photos.KIND_PRINT, KIND_PHONE and KIND_SCREEN_PHOTO
KIND_PHONE = "ponsel"  # (kept import-free here)
KIND_SCREEN_PHOTO = "fotolayar"
MEDIUM_SCREEN = "layar"
MEDIUM_PRINT_1 = "cetak, 1 halaman"
MEDIUM_PRINT_2 = "cetak, 2 halaman"
MEDIUM_PHONE = "foto ponsel"
MEDIUM_SCREEN_PHOTO = "foto layar (monitor)"
MEDIA = (MEDIUM_SCREEN, MEDIUM_PRINT_1, MEDIUM_PRINT_2, MEDIUM_PHONE, MEDIUM_SCREEN_PHOTO)
_REMAKE = {KIND_PRINT: "make photos-cetak", KIND_PHONE: "make photos-ponsel", KIND_SCREEN_PHOTO: "make photos-layar"}


def medium(row: dict) -> str:
    """The medium a benchmark row belongs to: screen, print with one or two pages, the phone
    ISP set or the monitor set."""
    if row["kind"] == KIND_PHONE:
        return MEDIUM_PHONE
    if row["kind"] == KIND_SCREEN_PHOTO:
        return MEDIUM_SCREEN_PHOTO
    if row["kind"] != KIND_PRINT:
        return MEDIUM_SCREEN
    return MEDIUM_PRINT_2 if row.get("pages", 1) == 2 else MEDIUM_PRINT_1


def group_label(row: dict) -> str:
    """Row label of the per-group summary (kind and view angle; prints by page count)."""
    angle = int(row.get("angle") or 0)
    if row["kind"] == "photo":
        return f"foto {angle:>2} derajat"
    if row["kind"] == KIND_PRINT:
        return "cetak 2 halaman" if row.get("pages", 1) == 2 else f"cetak {angle:>2} derajat"
    if row["kind"] == KIND_PHONE:
        return f"ponsel {angle:>2} derajat"
    if row["kind"] == KIND_SCREEN_PHOTO:
        return f"monitor {angle:>2} derajat"
    return "tangkapan layar"


def summarize(rows: list[dict]) -> dict[str, Counter]:
    """Outcome counts per medium, in the order of ``MEDIA`` (media without rows are left out)."""
    out: dict[str, Counter] = {}
    for m in MEDIA:
        sel = [r["outcome"] for r in rows if medium(r) == m]
        if sel:
            out[m] = Counter(sel)
    return out


def print_pairs(entries: list[dict]) -> list[tuple[dict, dict]]:
    """Pages 1 and 2 of the same printed copy, angle and repetition, as (page 1, page 2)."""
    by_key: dict[tuple, dict[int, dict]] = defaultdict(dict)
    for e in entries:
        if e.get("kind") != KIND_PRINT:
            continue
        index = e["file"].rsplit("_", 1)[-1].split(".")[0]
        by_key[(e["copy_id"], e.get("angle"), index)][int(e["page"])] = e
    return [(pages[1], pages[2]) for pages in by_key.values() if 1 in pages and 2 in pages]


def _entries(folder: Path) -> list[dict]:
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    return truth["items"] if isinstance(truth, dict) else truth


def check_issuance(folder: Path, entries: list[dict], by_copy: dict[str, int]) -> None:
    """Refuse (SystemExit) a photo set made from another issuance than the one traced against:
    its copy ids are not copies of this document, so every trace would count as an honest
    "tidak cukup bukti" without anyone noticing."""
    stale = [e["file"] for e in entries if e.get("copy_id") not in by_copy]
    if stale:
        remake = next((_REMAKE[e["kind"]] for e in entries if e.get("kind") in _REMAKE), "make photos")
        raise SystemExit(f"set foto {folder} dibuat dari penerbitan lain ({len(stale)} dari {len(entries)} foto "
                         f"bukan salinan dokumen terbitan yang diuji, misalnya {stale[0]}); jalankan ulang: {remake}")


def _outcome(accused: list[int], expected: int, identified: bool) -> str:
    if not identified:
        return "tidak cukup bukti"
    if accused == [expected]:
        return "benar"
    return "benar + lain" if expected in accused else "SALAH"


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark; exit code 1 if any innocent recipient was accused."""
    ap = argparse.ArgumentParser(description="Uji regresi dekoder pada set foto sintetis")
    ap.add_argument("--photos", default="samples/photos", help="foto layar dan tangkapan layar (make photos)")
    ap.add_argument("--cetak", default="samples/photos-cetak",
                    help="foto kertas cetak (make photos-cetak); dilewati bila tidak ada")
    ap.add_argument("--ponsel", default="samples/photos-ponsel",
                    help="foto dengan ISP ponsel simulasi (make photos-ponsel); dilewati bila tidak ada")
    ap.add_argument("--layar", default="samples/photos-layar",
                    help="foto monitor simulasi (make photos-layar); dilewati bila tidak ada")
    ap.add_argument("--data", default="out/photos/data")
    ap.add_argument("--keys", default="out/photos/keys")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    os.environ["TAPAK_DATA"] = args.data
    os.environ["TAPAK_KEY_DIR"] = args.keys

    from tapak.config import load_settings
    from tapak.decoder.accuse import VERDICT_IDENTIFIED, format_upper_bound
    from tapak.service import list_workspaces, trace_evidence

    settings = load_settings()
    folders = [Path(f) for f in (args.photos, args.cetak, args.ponsel, args.layar) if (Path(f) / "truth.json").exists()]
    if not folders:
        raise SystemExit("tidak ada set foto; jalankan: make photos (dan make photos-cetak)")
    for folder, what, target in ((args.cetak, "Foto kertas cetak", "make photos-cetak"),
                                 (args.ponsel, "Foto ISP ponsel", "make photos-ponsel"),
                                 (args.layar, "Foto monitor", "make photos-layar")):
        if not (Path(folder) / "truth.json").exists():
            print(f"{what} dilewati ({folder} belum ada; jalankan: {target})")
    docs = list_workspaces(settings)
    if not docs:
        raise SystemExit("tidak ada dokumen terbitan; jalankan: make photos")
    doc = docs[0]
    by_copy = {c.copy_id: c.seq for c in doc.copies}
    jobs: list[tuple[list[tuple[Path, dict]], dict]] = []
    for folder in folders:
        entries = _entries(folder)
        check_issuance(folder, entries, by_copy)
        for e in entries:
            jobs.append(([(folder, e)], {"kind": e["kind"], "angle": e.get("angle"), "pages": 1}))
        for p1, p2 in print_pairs(entries):
            jobs.append(([(folder, p1), (folder, p2)], {"kind": KIND_PRINT, "angle": p1.get("angle"), "pages": 2}))
    rows = []
    t0 = time.perf_counter()
    for items, info in jobs:
        files = [(e["file"], (folder / e["file"]).read_bytes()) for folder, e in items]
        e = items[0][1]
        expected = by_copy[e["copy_id"]]
        out = trace_evidence(settings, doc.doc_hash, files[0][0], files[0][1], more=files[1:])
        a = out.attribution
        accused = [c.copy.seq for c in a.accused]
        outcome = _outcome(accused, expected, a.verdict == VERDICT_IDENTIFIED)
        best = a.accused[0] if a.accused else None
        row = {"file": " + ".join(n for n, _ in files), **info, "expected": expected, "accused": accused,
               "outcome": outcome, "log10_fa": best.log10_false_accusation if best else None}
        row["medium"] = medium(row)
        rows.append(row)
        print(f"{row['file']:<32} {outcome:<18} dituduh={accused} "
              + (f"peluang tuduhan salah<={format_upper_bound(best.log10_false_accusation)}" if best else ""),
              flush=True)
    groups: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        groups[f"{r['medium']}: {group_label(r)}"][r["outcome"]] += 1
    print(f"\nRingkasan ({len(rows)} pelacakan, {time.perf_counter() - t0:.0f} s):")
    for key in groups:
        print(f"  {key:<36} " + ", ".join(f"{k}: {v}" for k, v in sorted(groups[key].items())))
    wrong = 0
    for m, counts in summarize(rows).items():
        bad = counts["SALAH"] + counts["benar + lain"]
        wrong += bad
        print(f"Total {m}: benar {counts['benar']}, tidak cukup bukti {counts['tidak cukup bukti']}, "
              f"tuduhan salah {bad}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
