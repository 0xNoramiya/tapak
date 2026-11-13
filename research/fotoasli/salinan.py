"""Real phone photos of real prints of known copies (docs/keamanan.md batasan 3 and 10).

Three copies of the sample Surat Telegram, each from its own issuance (20 fictional recipients,
the same code secret): A the default issuance (geser-v2, screen background profile), B geser-v2
with the print background profile, C geser-v1 with the screen profile. The team printed both
pages of each on a real printer and photographed every sheet flat with a phone. Which copy each
file is was known to the study only, so every trace has a right answer.

Per photo, and again for the photo as a messaging app forwards it (long side 1600 px, JPEG
quality 75, twice):

* the trace against its own issuance: verdict, score against the threshold, wrong bits per
  sub-channel (word groups, rows, background);
* the same trace with the shift channel alone and with the background channel alone;
* the trace against another of the three issuances (the original photo only). Its copies have
  other copy ids and so other codewords under the same bias vector: nobody may be named.

Traces are not logged (all of eps), one stage, as in ``make bench``. The issuances and their
secret are not in the repository, the photos neither; ``hasil/salinan.jsonl`` holds the rows.
One process (a 12 megapixel photo takes more than a gigabyte). Usage, from the repository root:

    PYTHONPATH=. python research/fotoasli/salinan.py FOLDER --isu A=DIR_A:7,B=DIR_B:13,C=DIR_C:4 --kunci KEYFILE
    PYTHONPATH=. python research/fotoasli/salinan.py --ringkas

FOLDER holds one subfolder per set (A, B, C); DIR_x is the ``dokumen/<id>`` folder of the
issuance (``induk.pdf`` and ``manifest.json``), the number the copy that was printed.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASIL = Path(__file__).resolve().parent / "hasil" / "salinan.jsonl"
FORWARD = {"long_side": 1600, "quality": 75, "times": 2}


def forwarded(gray: np.ndarray) -> np.ndarray:
    """The photo as a messaging app forwards it."""
    import cv2

    s = FORWARD["long_side"] / max(gray.shape)
    small = cv2.resize(np.clip(gray, 0, 255).astype(np.uint8), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    for _ in range(FORWARD["times"]):
        small = cv2.imdecode(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, FORWARD["quality"]])[1],
                             cv2.IMREAD_GRAYSCALE)
    return small.astype(np.float32)


def _verdict(obs, ctx, seq: int | None) -> dict:
    from tapak.decoder.trace import run_trace

    a = run_trace(obs, ctx)
    accused = sorted(c.copy.seq for c in a.accused)
    z = a.threshold.threshold
    ok = bool(np.isfinite(z) and z > 0)
    scores = {c.copy.seq: c.score for c in a.candidates}
    others = [s for k, s in scores.items() if k != seq]
    verdict = "tidak cukup bukti" if not accused else ("benar" if accused == [seq] else "salah")
    return {"verdict": verdict, "accused": accused, "n_observed": int(a.threshold.n_observed),
            "score_z": round(scores.get(seq, 0.0) / z, 3) if ok and seq else None,
            "max_other_z": round(max(others) / z, 3) if ok and others else None}


def _bits(obs, ctx, x: np.ndarray) -> dict:
    from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

    kinds = {s.positions[0]: ("kata" if len(s.ref) == 2 else "baris") for s in ctx.plan.channel(CHANNEL_SHIFT)}
    out = {k: [0, 0] for k in ("kata", "baris", "latar")}
    for sb in obs:
        if sb.channel in (CHANNEL_SHIFT, CHANNEL_BACKGROUND):
            for q, v in zip(sb.positions, sb.llr):
                c = out["latar" if sb.channel == CHANNEL_BACKGROUND else kinds[int(q)]]
                c[0] += 1
                c[1] += int((v > 0) != (x[int(q)] == 1))
    return out


def trace(gray: np.ndarray, ctx, seq: int) -> dict:
    """One image against the issuance it came from: all channels, then each alone."""
    from tapak.decoder.image import collect_from_gray
    from tapak.marker.plan import CHANNEL_BACKGROUND, CHANNEL_SHIFT

    t0 = time.time()
    obs = collect_from_gray(gray, ctx, read_text=False)
    reg = next((sb.meta for sb in obs if "method" in sb.meta), {})
    return {**_verdict(obs, ctx, seq), "bits": _bits(obs, ctx, ctx.codewords[seq - 1]),
            "geser_saja": _verdict([sb for sb in obs if sb.channel == CHANNEL_SHIFT], ctx, seq),
            "latar_saja": _verdict([sb for sb in obs if sb.channel == CHANNEL_BACKGROUND], ctx, seq),
            "registered": bool(reg), "method": reg.get("method"), "correlation": reg.get("correlation"),
            "page": None if not reg else reg["page"] + 1, "effective_dpi": reg.get("effective_dpi"),
            "seconds": round(time.time() - t0, 1)}


def run(args: argparse.Namespace) -> None:
    from tapak.decoder import rectify
    from tapak.decoder.image import collect_from_gray
    from tapak.decoder.trace import load_context
    from tapak.keys import load_code_secret
    from tapak.marker.issue import IssueManifest

    secret = load_code_secret(Path(args.kunci))
    sets: dict[str, tuple] = {}
    for item in args.isu.split(","):
        label, rest = item.split("=")
        folder, seq = rest.rsplit(":", 1)
        manifest = IssueManifest.from_json((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
        ctx = load_context((Path(folder) / "induk.pdf").read_bytes(), manifest, secret)
        sets[label] = (ctx, int(seq), {"scheme": manifest.shift_settings.scheme,
                                       "background": [manifest.background_settings.base, manifest.background_settings.amplitude]})
    labels = sorted(sets)
    done = set()
    if HASIL.exists():
        done = {(r["set"], r["photo"]) for r in map(json.loads, HASIL.read_text(encoding="utf-8").splitlines())}
    HASIL.parent.mkdir(parents=True, exist_ok=True)
    with HASIL.open("a", encoding="utf-8") as out:
        for label in labels:
            ctx, seq, issued = sets[label]
            other = labels[(labels.index(label) + 1) % len(labels)]
            for photo in sorted(p for p in (Path(args.folder) / label).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")):
                if (label, photo.name) in done:
                    continue
                gray = rectify.load_gray(photo.read_bytes())
                row = {"set": label, "photo": photo.name, "copy": seq, "issued": issued, "pixels": [int(gray.shape[1]), int(gray.shape[0])],
                       "asli": trace(gray, ctx, seq), "pesan": trace(forwarded(gray), ctx, seq)}
                cross = collect_from_gray(gray, sets[other][0], read_text=False)
                row["silang"] = {"against": other, **_verdict(cross, sets[other][0], None)}
                out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")
                out.flush()
                a, m = row["asli"], row["pesan"]
                print(f"{label} {photo.name} hal {a['page']}: {a['verdict']} {a['score_z']} | geser saja {a['geser_saja']['verdict']} "
                      f"{a['geser_saja']['score_z']} | latar saja {a['latar_saja']['verdict']} {a['latar_saja']['score_z']} | pesan "
                      f"{m['verdict']} {m['score_z']} | silang {row['silang']['verdict']} {row['silang']['max_other_z']}", flush=True)


def summarize() -> None:
    rows = [json.loads(line) for line in HASIL.read_text(encoding="utf-8").splitlines()]
    for label in sorted({r["set"] for r in rows}):
        for page in (1, 2):
            cell = [r for r in rows if r["set"] == label and r["asli"]["page"] == page]
            if not cell:
                continue

            def share(kind: str, key: str) -> str:
                n = sum(r[kind]["bits"][key][0] for r in cell)
                e = sum(r[kind]["bits"][key][1] for r in cell)
                return f"{e}/{n}" if n else "-"

            def named(kind: str, sub: str | None = None) -> str:
                got = [(r[kind] if sub is None else r[kind][sub]) for r in cell]
                scores = [g["score_z"] for g in got if g["score_z"] is not None]
                span = f" ({min(scores):.2f}..{max(scores):.2f})" if scores else ""
                return f"{sum(g['verdict'] == 'benar' for g in got)}/{len(cell)}{span}"

            print(f"{label} hal {page} {cell[0]['issued']}: semua {named('asli')}, geser saja {named('asli', 'geser_saja')}, "
                  f"latar saja {named('asli', 'latar_saja')}, pesan {named('pesan')}; bit salah kata {share('asli', 'kata')} "
                  f"baris {share('asli', 'baris')} latar {share('asli', 'latar')}; pesan: kata {share('pesan', 'kata')} "
                  f"latar {share('pesan', 'latar')}")
    wrong = [r for r in rows for k in ("asli", "pesan") if r[k]["verdict"] == "salah"]
    crossed = [r for r in rows if r["silang"]["accused"]]
    print(f"{len(rows)} foto; salah {len(wrong)}; silang menuduh {len(crossed)} "
          f"(skor tertinggi {max(r['silang']['max_other_z'] or 0 for r in rows)} kali ambang)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", nargs="?")
    parser.add_argument("--isu")
    parser.add_argument("--kunci")
    parser.add_argument("--ringkas", action="store_true")
    args = parser.parse_args()
    if args.ringkas:
        summarize()
    elif args.folder and args.isu and args.kunci:
        run(args)
    else:
        parser.error("FOLDER, --isu and --kunci, or --ringkas")


if __name__ == "__main__":
    main()
