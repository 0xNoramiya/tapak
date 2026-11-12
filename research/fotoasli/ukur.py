"""Real phone photos of a printed sample page (docs/keamanan.md batasan 10): measurements.

The photos themselves are not in the repository: they show a table and a room besides the
fictional sample page. Only numbers go to ``hasil/``. A folder of photos is read recursively;
a photo is named by its folder and the last six characters of its file name.

Per photo, ``foto`` records:

* registration against the master it shows: the plane fit (ECC) and the bend stage
  (``rectify.estimate_bend``), and whether the plane fit alone would have registered it;
* the same against another document (``--lain``): nothing may register;
* a trace against an issuance of the same master made for this study (``--data``, ``--keys``,
  ``--doc``; not the issuance the sheets were printed from, so nobody may be named): positions
  read, noise of the shift channel, best score and threshold. The trace is not logged (all of
  eps), one stage, as in ``make bench``;
* the fine field of the bent page (``hasil/medan.json``, points on a lattice of FIELD_MM): the
  shape of the real sheet as the camera saw it, for simulations on copies whose recipient is
  known.

``geser`` asks whether the sheets carry word-shift marks without knowing their copy: the shift
of every word group is predicted from the groups of the other rows nearby (a Gaussian kernel;
paper deformation is shared between neighbouring rows, word marks are not), the row nuisance
(offset and slope) is taken off, and what is left along the rows (dx: marks, if any) is compared
with what is left across them (dy: no word marks) and between photos. The kernel is the one
that leaves least in dy.

Process pools are capped at 3, BLAS and OpenCV at one thread per worker (shared machine).
Usage, from the repository root:

    PYTHONPATH=. python research/fotoasli/ukur.py foto FOLDER --induk samples/surat_telegram.pdf \\
        --lain samples/nota_dinas.pdf --data DATA --keys KEYS --doc HASH
    PYTHONPATH=. python research/fotoasli/ukur.py geser
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASIL = Path(__file__).resolve().parent / "hasil"
WORKERS = 3
MM = 72.0 / 25.4
FIELD_MM = 4.0  # lattice of the saved fields
KERNELS_MM = tuple(itertools.product((8, 12, 18, 25, 40), (4, 6, 9, 14)))  # along the row, across rows


def label(path: Path) -> str:
    return f"{path.parent.name}/{path.stem[-6:]}"


def _camera(path: Path) -> str:
    from PIL import Image

    exif = Image.open(path).getexif()
    return " ".join(str(exif.get(tag, "")).strip() for tag in (271, 272)).strip()


def _sizes(pdf: bytes) -> list[tuple[float, float]]:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return [(p.rect.width, p.rect.height) for p in doc]


def _registration(gray: np.ndarray, pdf: bytes) -> tuple[dict, object]:
    from tapak.decoder import rectify

    diag: dict = {}
    t0 = time.time()
    reg = rectify.register(gray, pdf, _sizes(pdf), diag=diag, rescue=False)
    bend = diag.get("bend") or {}
    plane = max((r["cc"] for r in diag["refined"]), default=None)
    row = {"registered": reg is not None, "plane_cc": plane, "plane_alone": plane is not None and plane >= 0.75,
           "bent_cc": bend.get("cc"), "fine_mm": bend.get("fine_mm"), "smooth_mm": bend.get("smooth_mm"),
           "seconds": round(time.time() - t0, 1)}
    if reg is not None:
        row.update(method=reg.method, page=reg.page, dpi=reg.dpi, correlation=reg.correlation,
                   effective_dpi=round(reg.effective_dpi, 1))
    return row, reg


def _groups(ctx, reg) -> list[list[float]]:
    """(row, group, centre x, centre y, dx, dy) in points of every word group measured."""
    from tapak.decoder import rectify
    from tapak.decoder.ch_shift import measure_image, template_boxes

    template = rectify.render_page_exact(ctx.master.pdf_bytes, reg.page, reg.dpi,
                                         boxes=template_boxes(ctx.master, reg.page, reg.dpi))
    disp = measure_image(reg.rectified, reg.valid, template, ctx.master, reg.page, reg.dpi)
    out = []
    for row in ctx.master.shift_layout.pages[reg.page].rows:
        for gi, g in enumerate(row.groups):
            wid = row.words[g.word_indices[0]].id
            if wid in disp:
                x0, y0, x1, y1 = g.bbox
                out.append([row.index, gi, round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2),
                            round(disp[wid][0], 4), round(disp[wid][1], 4)])
    return out


def _field(gray: np.ndarray, pdf: bytes, reg) -> dict:
    """The fine field of a bent page (``estimate_bend``) on a lattice of FIELD_MM, in points:
    the shape of a real sheet."""
    import cv2

    from tapak.decoder import rectify

    size = _sizes(pdf)[reg.page]
    fine = rectify.estimate_bend(rectify._prep(gray), rectify.master_ink(pdf, reg.page, reg.dpi),
                                 reg.h_page_to_img, reg.dpi, size)[0]
    cols, rows = int(np.ceil(size[0] / (FIELD_MM * MM))), int(np.ceil(size[1] / (FIELD_MM * MM)))
    lattice = cv2.resize(np.asarray(fine.field, dtype=np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    return {"page_size": [round(v, 2) for v in size], "field": np.round(lattice, 3).tolist()}


def _context(data: str, keys: str, doc: str):
    from tapak.decoder.trace import load_context
    from tapak.keys import load_code_secret
    from tapak.marker.issue import IssueManifest

    folder = Path(data) / "dokumen" / doc
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    return load_context((folder / "induk.pdf").read_bytes(), manifest, load_code_secret(Path(keys) / "code_secret.key"))


def _photo(job: tuple[str, str, str, str, str, str]) -> dict:
    import cv2

    cv2.setNumThreads(1)
    from tapak.decoder import rectify
    from tapak.decoder.trace import trace_files

    path, master, other, data, keys, doc = job
    p = Path(path)
    raw = p.read_bytes()
    gray = rectify.load_gray(raw)
    row: dict = {"photo": label(p), "camera": _camera(p), "pixels": [int(gray.shape[1]), int(gray.shape[0])]}
    ctx = _context(data, keys, doc)
    assert ctx.master.pdf_bytes == Path(master).read_bytes(), "the issuance is not of --induk"
    row["registrasi"], reg = _registration(gray, ctx.master.pdf_bytes)
    row["groups"] = _groups(ctx, reg) if reg is not None else []
    row["medan"] = _field(gray, ctx.master.pdf_bytes, reg) if reg is not None and reg.bend is not None else None
    if other:
        row["dokumen_lain"], _ = _registration(gray, Path(other).read_bytes())
    t0 = time.time()
    att, obs = trace_files([(p.name, raw)], ctx)
    shift = next((sb for sb in obs if sb.channel == "shift" or sb.meta.get("scheme")), None)
    best = max((c.score for c in att.candidates), default=None)
    row["lacak"] = {"verdict": att.verdict, "accused": len(att.accused), "n_observed": att.threshold.n_observed,
                    "threshold": att.threshold.threshold, "best_score": best,
                    "sigma_pt": None if shift is None else shift.meta.get("sigma_pt"),
                    "seconds": round(time.time() - t0, 1)}
    return row


def run_photos(args: argparse.Namespace) -> None:
    files = sorted(p for p in Path(args.folder).rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    jobs = [(str(p), args.induk, args.lain or "", args.data, args.keys, args.doc) for p in files]
    HASIL.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(WORKERS) as pool:
        for row in pool.map(_photo, jobs):
            rows.append(row)
            r, t = row["registrasi"], row["lacak"]
            print(row["photo"], r.get("method"), r["plane_cc"], r["bent_cc"], t["verdict"], t["n_observed"], flush=True)
    rows.sort(key=lambda r: r["photo"])
    fields = {row["photo"]: row.pop("medan") for row in rows}
    (HASIL / "medan.json").write_text(json.dumps({k: v for k, v in fields.items() if v}, separators=(",", ":")) + "\n",
                                      encoding="utf-8")
    with (HASIL / "foto.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=True, default=float) + "\n")


def _detrend(g: np.ndarray, v: np.ndarray) -> np.ndarray:
    """v minus its line along every row (offset and slope); rows of fewer than 3 groups: nan."""
    out = np.full(len(g), np.nan)
    ok = np.isfinite(v)
    for r in np.unique(g[:, 0]):
        i = np.nonzero((g[:, 0] == r) & ok)[0]
        if len(i) < 3:
            continue
        a = np.c_[np.ones(len(i)), g[i, 2] - g[i, 2].mean()]
        coef, *_ = np.linalg.lstsq(a, v[i], rcond=None)
        out[i] = v[i] - a @ coef
    return out


def _local(g: np.ndarray, v: np.ndarray, sx: float, sy: float) -> np.ndarray:
    """v minus its kernel prediction from the groups of the other rows."""
    out = np.full(len(g), np.nan)
    for i in range(len(g)):
        other = g[:, 0] != g[i, 0]
        w = np.exp(-0.5 * (((g[other, 2] - g[i, 2]) / sx) ** 2 + ((g[other, 3] - g[i, 3]) / sy) ** 2))
        if w.sum() >= 0.5:
            out[i] = v[i] - (w * v[other]).sum() / w.sum()
    return out


def _sd(v: np.ndarray) -> float:
    return float(1.4826 * np.nanmedian(np.abs(v - np.nanmedian(v))))


def run_shift(_: argparse.Namespace) -> None:
    rows = [json.loads(line) for line in (HASIL / "foto.jsonl").read_text(encoding="utf-8").splitlines()]
    g = {r["photo"]: np.array(r["groups"], dtype=np.float64) for r in rows if r["groups"]}
    names = sorted(g)

    def left(n: str, col: int, kernel: tuple[int, int]) -> np.ndarray:
        return _detrend(g[n], _local(g[n], g[n][:, col], kernel[0] * MM, kernel[1] * MM))

    kernel = min(KERNELS_MM, key=lambda k: float(np.mean([_sd(left(n, 5, k)) for n in names])))
    e = {n: (left(n, 4, kernel), left(n, 5, kernel)) for n in names}
    photos = {n: {"groups": len(g[n]),
                  "row_detrended_dx_pt": round(_sd(_detrend(g[n], g[n][:, 4])), 4),
                  "row_detrended_dy_pt": round(_sd(_detrend(g[n], g[n][:, 5])), 4),
                  "left_dx_pt": round(_sd(e[n][0]), 4), "left_dy_pt": round(_sd(e[n][1]), 4)} for n in names}

    def corr(a: str, b: str, k: int) -> float | None:
        da = {(int(r), int(c)): v for (r, c), v in zip(g[a][:, :2], e[a][k]) if np.isfinite(v)}
        db = {(int(r), int(c)): v for (r, c), v in zip(g[b][:, :2], e[b][k]) if np.isfinite(v)}
        common = sorted(set(da) & set(db))
        va, vb = np.array([da[q] for q in common]), np.array([db[q] for q in common])
        ok = (np.abs(va) < 4 * _sd(va)) & (np.abs(vb) < 4 * _sd(vb))
        return round(float(np.corrcoef(va[ok], vb[ok])[0, 1]), 3) if ok.sum() > 20 else None

    pairs = [{"a": a, "b": b, "dx": corr(a, b, 0), "dy": corr(a, b, 1)} for a, b in itertools.combinations(names, 2)]
    out = {"kernel_mm": {"along_row": kernel[0], "across_rows": kernel[1]}, "photos": photos, "pairs": pairs}
    (HASIL / "geser.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["kernel_mm"]))
    for n in names:
        print(n, photos[n])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("foto")
    f.add_argument("folder")
    f.add_argument("--induk", required=True)
    f.add_argument("--lain")
    f.add_argument("--data", required=True)
    f.add_argument("--keys", required=True)
    f.add_argument("--doc", required=True)
    f.set_defaults(run=run_photos)
    sub.add_parser("geser").set_defaults(run=run_shift)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
