"""Real photos of real prints of known copies, made worse (docs/keamanan.md batasan 3 and 10).

The 18 photos of ``salinan.py`` are sharp, taken straight on and show the whole page. A leaked
photo is often smaller, cropped, tilted, blurred or overexposed. The print and the camera
here are real; what is done to each photo afterwards is simulated, one thing at a time:

* forwarded smaller than a messaging app sends it (long side 1280 down to 640 px);
* cropped to the upper half, the lower half or the middle of the frame, then forwarded;
* seen from 30 degrees off the vertical (a homography of the photo), then forwarded;
* blurred after forwarding, as an out-of-focus or shaken shot;
* overexposed until the paper clips.

Every image is traced against the issuance its copy came from (the right answer is known),
all channels, not logged (all of eps), one stage. The protocol below was fixed before the run
and nothing is chosen from its results. The issuances, their secret and the photos are not in
the repository; ``hasil/tekan.jsonl`` holds the rows. One process. Usage, from the repository
root:

    PYTHONPATH=. python research/fotoasli/tekan.py jalan FOLDER --isu A=DIR_A:7,B=DIR_B:13,C=DIR_C:4 --kunci KEYFILE
    PYTHONPATH=. python research/fotoasli/tekan.py ringkas
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASIL = HERE / "hasil"
PROTOCOL: dict = {
    "photos": "the 18 photos of salinan.py: sets A (geser-v2, default background), B (geser-v2, print background), "
              "C (geser-v1, default background), pages 1 and 2, three photos each",
    "forwarded": {"long_side": 1600, "quality": 75, "times": 2},  # salinan.FORWARD, the base of most conditions
    "conditions": {
        "sisi_1280": {"kind": "forward", "long_side": 1280},
        "sisi_1024": {"kind": "forward", "long_side": 1024},
        "sisi_800": {"kind": "forward", "long_side": 800},
        "sisi_640": {"kind": "forward", "long_side": 640},
        # crops of the frame (x0, y0, x1, y1 as shares of the photo), cut at full resolution, then forwarded
        "potong_atas": {"kind": "crop", "box": [0.0, 0.0, 1.0, 0.5]},
        "potong_bawah": {"kind": "crop", "box": [0.0, 0.5, 1.0, 1.0]},
        "potong_tengah": {"kind": "crop", "box": [0.25, 0.25, 0.75, 0.75]},
        # the photo seen from this angle off the vertical, the far edge at the top, then forwarded
        "miring_30": {"kind": "tilt", "degrees": 30.0, "distance": 1.5},
        # Gaussian blur (sigma in px at the forwarded size), then JPEG once more
        "buram_1.5": {"kind": "blur", "sigma": 1.5},
        # exposure raised so that the paper (95th percentile) would reach this multiple of white, clipped, then forwarded
        "terang_1.10": {"kind": "bright", "paper": 1.10},
    },
    "c": 3, "eps": 1e-6, "spending": "not logged (all of eps), one stage, as in make bench",
}


def _salinan():
    """The known-copies study next to this file, loaded by path (other studies have modules of
    the same name)."""
    spec = importlib.util.spec_from_file_location("fotoasli_salinan", HERE / "salinan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forward(gray: np.ndarray, long_side: int, quality: int = 75, times: int = 2) -> np.ndarray:
    """The image as a messaging app forwards it: long side at most ``long_side``, JPEG ``times`` times."""
    import cv2

    s = min(1.0, long_side / max(gray.shape))
    small = np.clip(gray, 0, 255).astype(np.uint8)
    if s < 1.0:
        small = cv2.resize(small, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    for _ in range(times):
        small = cv2.imdecode(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])[1], cv2.IMREAD_GRAYSCALE)
    return small.astype(np.float32)


def tilted(gray: np.ndarray, degrees: float, distance: float) -> np.ndarray:
    """The photo as a camera ``distance`` image heights away sees it after the sheet is tipped
    back by ``degrees`` about the horizontal line through its middle (the top edge moves away)."""
    import cv2

    h, w = gray.shape
    a = math.radians(degrees)
    f = distance * h  # focal length in pixels: the untilted photo fills the frame

    def project(x: float, y: float) -> tuple[float, float]:
        yc, z = (y - h / 2.0) * math.cos(a), distance * h - (y - h / 2.0) * math.sin(a)
        return (x - w / 2.0) * f / z, yc * f / z

    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst = np.array([project(x, y) for x, y in src], dtype=np.float32)
    dst -= dst.min(axis=0)
    size = (int(math.ceil(dst[:, 0].max())), int(math.ceil(dst[:, 1].max())))
    table = float(np.percentile(gray, 2))  # what lies around the sheet
    return cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, dst), size, flags=cv2.INTER_AREA,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=table)


def degraded(gray: np.ndarray, spec: dict) -> np.ndarray:
    """One photo under one condition of the protocol."""
    import cv2

    base = PROTOCOL["forwarded"]
    kind = spec["kind"]
    if kind == "forward":
        return forward(gray, spec["long_side"], base["quality"], base["times"])
    if kind == "crop":
        h, w = gray.shape
        x0, y0, x1, y1 = spec["box"]
        return forward(gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], base["long_side"], base["quality"], base["times"])
    if kind == "tilt":
        return forward(tilted(gray, spec["degrees"], spec["distance"]), base["long_side"], base["quality"], base["times"])
    if kind == "blur":
        small = forward(gray, base["long_side"], base["quality"], base["times"])
        return forward(cv2.GaussianBlur(small, (0, 0), spec["sigma"]), base["long_side"], base["quality"], 1)
    if kind == "bright":
        gain = spec["paper"] * 255.0 / max(float(np.percentile(gray, 95)), 1.0)
        return forward(np.clip(gray * gain, 0, 255), base["long_side"], base["quality"], base["times"])
    raise ValueError(f"kondisi tidak dikenal: {kind!r}")


def run(args: argparse.Namespace) -> None:
    from tapak.decoder import rectify
    from tapak.decoder.trace import load_context
    from tapak.keys import load_code_secret
    from tapak.marker.issue import IssueManifest

    salinan = _salinan()
    secret = load_code_secret(Path(args.kunci))
    sets: dict[str, tuple] = {}
    for item in args.isu.split(","):
        label, rest = item.split("=")
        folder, seq = rest.rsplit(":", 1)
        manifest = IssueManifest.from_json((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
        sets[label] = (load_context((Path(folder) / "induk.pdf").read_bytes(), manifest, secret), int(seq))
    HASIL.mkdir(parents=True, exist_ok=True)
    (HASIL / "protokol_tekan.json").write_text(json.dumps(PROTOCOL, indent=1) + "\n", encoding="utf-8")
    path = HASIL / "tekan.jsonl"
    done = set()
    if path.exists():
        done = {(r["set"], r["photo"], r["condition"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    with path.open("a", encoding="utf-8") as out:
        for label in sorted(sets):
            ctx, seq = sets[label]
            for photo in sorted(p for p in (Path(args.folder) / label).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")):
                todo = [c for c in PROTOCOL["conditions"] if (label, photo.name, c) not in done]
                if not todo:
                    continue
                gray = rectify.load_gray(photo.read_bytes())
                for name in todo:
                    t0 = time.time()
                    image = degraded(gray, PROTOCOL["conditions"][name])
                    row = {"set": label, "photo": photo.name, "copy": seq, "condition": name,
                           "pixels": [int(image.shape[1]), int(image.shape[0])], **salinan.trace(image, ctx, seq)}
                    row["seconds"] = round(time.time() - t0, 1)
                    out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")
                    out.flush()
                    print(f"{label} {photo.name} {name}: {row['verdict']} {row['score_z']} (lain {row['max_other_z']}) "
                          f"hal {row['page']} {row['method']} {row['bits']}", flush=True)


def summarize() -> None:
    rows = [json.loads(line) for line in (HASIL / "tekan.jsonl").read_text(encoding="utf-8").splitlines()]
    out: dict = {"photos": len({(r["set"], r["photo"]) for r in rows}), "traces": len(rows),
                 "wrong": sum(r["verdict"] == "salah" for r in rows),
                 "max_other_z": max((r["max_other_z"] or 0.0) for r in rows), "conditions": {}}
    for name in PROTOCOL["conditions"]:
        cell = {}
        for label in sorted({r["set"] for r in rows}):
            sel = [r for r in rows if r["condition"] == name and r["set"] == label]
            if not sel:
                continue
            scores = sorted(r["score_z"] for r in sel if r["score_z"] is not None)
            latar = [sum(r["bits"]["latar"][i] for r in sel) for i in (0, 1)]
            cell[label] = {"n": len(sel), "found": sum(r["registered"] for r in sel),
                           "benar": sum(r["verdict"] == "benar" for r in sel), "salah": sum(r["verdict"] == "salah" for r in sel),
                           "score_z": [scores[0], scores[-1]] if scores else None,
                           "background_wrong": round(latar[1] / latar[0], 3) if latar[0] else None}
        out["conditions"][name] = cell
    (HASIL / "ringkas_tekan.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, cell in out["conditions"].items():
        parts = [f"{label} {c['benar']}/{c['n']} (ditemukan {c['found']}, skor {c['score_z']}, latar salah {c['background_wrong']})"
                 for label, c in cell.items()]
        print(f"{name:14s} " + "; ".join(parts))
    print(f"{out['traces']} pelacakan dari {out['photos']} foto; salah {out['wrong']}; skor orang lain paling tinggi {out['max_other_z']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cmd", choices=("jalan", "ringkas"))
    parser.add_argument("folder", nargs="?")
    parser.add_argument("--isu")
    parser.add_argument("--kunci")
    args = parser.parse_args()
    if args.cmd == "ringkas":
        summarize()
    elif args.folder and args.isu and args.kunci:
        run(args)
    else:
        parser.error("jalan needs FOLDER, --isu and --kunci")


if __name__ == "__main__":
    main()
