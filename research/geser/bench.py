"""The README benchmark photo sets with the image word model before and after this study.

An extra check on evidence no choice was made on: the four photo sets of ``make bench``
(research seed 2026; ``make photos``, ``photos-cetak``, ``photos-ponsel``, ``photos-layar``),
traced exactly as ``tapak.benchmark`` traces them (``service.trace_evidence``: no registry, all
of eps, one stage), once with the word model before this study (``gauss``) and once with the chosen
one (``ch_shift.IMAGE_WORD_MODEL``).
Recorded per trace and model: the outcome, the false-accusation bound, the three manipulation
checks (and whether the merged warning was written), and for single images the reliability
counts of the word groups, the background and the fused read against the copy's codeword (bins as
``ukur.W_EDGES``), as ``research/deteksi/llr_foto.py`` does for the screen photos.

Usage, after ``make photos photos-cetak photos-ponsel photos-layar`` (or with the folders of
``make bench-check``):

    python research/geser/bench.py --data out/photos/data --keys out/photos/keys \
        --sets samples/photos,samples/photos-cetak,samples/photos-ponsel,samples/photos-layar \
        --json research/geser/hasil/bench.json
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "kalibrasi"  # research/kalibrasi/ukur.py: kind_counts
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--sets", required=True, help="folder set foto, dipisah koma")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    os.environ["TAPAK_DATA"] = args.data
    os.environ["TAPAK_KEY_DIR"] = args.keys

    import ukur
    from tapak.benchmark import KIND_PRINT, _entries, medium, print_pairs
    from tapak.config import load_settings
    from tapak.decoder import ch_shift
    from tapak.decoder.fuse import fuse
    from tapak.decoder.manipulation import is_manipulation_note
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import load_context
    from tapak.service import ensure_keys, list_workspaces, load_workspace, trace_evidence

    settings = load_settings()
    keys = ensure_keys(settings, create_signing_key=False, create_secret=False)
    doc = list_workspaces(settings)[0]
    manifest, master, folder = load_workspace(settings, doc.doc_hash)
    ctx = load_context(master, manifest, keys.code_secret, folder=folder)
    by_copy = {c.copy_id: c.seq for c in doc.copies}
    jobs = []
    for f in args.sets.split(","):
        path = Path(f)
        entries = _entries(path)
        for e in entries:
            jobs.append(([(path, e)], {"kind": e["kind"], "angle": e.get("angle"), "pages": 1}))
        for p1, p2 in print_pairs(entries):
            jobs.append(([(path, p1), (path, p2)], {"kind": KIND_PRINT, "angle": p1.get("angle"), "pages": 2}))
    rows = []
    for name in dict.fromkeys(("gauss", ch_shift.IMAGE_WORD_MODEL)):
        default = ch_shift.IMAGE_WORD_MODEL
        ch_shift.IMAGE_WORD_MODEL = name
        try:
            for items, info in jobs:
                files = [(e["file"], (fold / e["file"]).read_bytes()) for fold, e in items]
                e = items[0][1]
                expected = by_copy[e["copy_id"]]
                out = trace_evidence(settings, doc.doc_hash, files[0][0], files[0][1], more=files[1:])
                a = out.attribution
                accused = [c.copy.seq for c in a.accused]
                row = {"model": name, "file": " + ".join(n for n, _ in files), **info, "expected": expected,
                       "accused": accused, "log10_fa": a.accused[0].log10_false_accusation if a.accused else None,
                       "hapus": bool(a.erasure.flagged), "hapus_z": a.erasure.z, "hapus_z_semua": a.erasure.z_all,
                       "kontradiksi": bool(a.contradiction and a.contradiction.flagged),
                       "balik": bool(a.reversal.flagged), "balik_z_pilot": a.reversal.z_pilot,
                       "balik_z_tanda": a.reversal.z_signs,
                       "peringatan": sum(1 for n in a.notes if is_manipulation_note(n))}
                row["medium"] = medium(row)
                if len(files) == 1:
                    obs = collect_from_image(files[0][1], ctx)
                    x = ctx.codewords[expected - 1].astype(np.uint8)
                    row["kalibrasi"] = ukur.kind_counts(obs, ctx, x)
                rows.append(row)
                print(f"{name} {row['file']}: {accused} peringatan {row['peringatan']}", flush=True)
        finally:
            ch_shift.IMAGE_WORD_MODEL = default
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
