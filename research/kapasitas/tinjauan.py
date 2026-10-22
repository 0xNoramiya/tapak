"""Review checks of geser-v2 (2026-10-22, after the held-out run; no part in any choice).

Two checks on the held-out issuances of ``ukur.py`` (read only, ``out/riset_kapasitas/uji``):

* ``lawan``: false accusations under adversarial or mismatched evidence. v1 and v2 issuances of
  one document share copy ids, so copy k carries the same codeword in both: tracing copy k of
  one scheme with the other scheme's manifest may name k, nobody else. Cases: old-scheme copy
  with the new-scheme manifest and the reverse (PDF and 4000 px print photo), composites of two
  and three v2 copies (horizontal bands and pixel averages, printed and photographed at 4000
  px; bands on a screen photo), a v1 + v2 composite, a copy of the other sample document, the
  unmarked master printed, and a v2 copy traced with its manifest edited to drop
  ``shift_scheme``. Output ``hasil/tinjauan_lawan.jsonl``.
* ``kalibrasi``: are the word-bit LLRs of the stored held-out print photos (laser, N = 100,
  copies 1 to 10, pages 1 and 2) as reliable as they claim? Errors against the leaked copy's
  codeword per |LLR| bin, with the errors the LLRs promise (sum of 1 / (1 + e^|LLR|)).
  Output ``hasil/tinjauan_kalibrasi.jsonl``.

    PYTHONPATH=. python research/kapasitas/tinjauan.py lawan [<part> <of>]
    PYTHONPATH=. python research/kapasitas/tinjauan.py kalibrasi
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import json  # noqa: E402
import sys  # noqa: E402

import numpy as np  # noqa: E402

import ukur  # noqa: E402

DOC = "nota_dinas"


def _ctx(doc: str, name: str):
    return ukur.context("uji", doc, 100, name)[0]


def _copy(doc: str, name: str, seq: int) -> bytes:
    return ukur.copy_pdf("uji", doc, 100, name, seq)


def _trace(obs, ctx, allowed: list[int]) -> dict:
    from tapak.decoder.trace import run_trace

    a = run_trace(obs, ctx)
    z = a.threshold.threshold
    accused = sorted(c.copy.seq for c in a.accused)
    others = [c.score for c in a.candidates if c.copy.seq not in allowed]
    return {"accused": accused, "false": [s for s in accused if s not in allowed],
            "allowed_named": [s for s in accused if s in allowed],
            "max_other_z": round(max(others) / z, 3) if others and np.isfinite(z) and z > 0 else None,
            "n_observed": int(a.threshold.n_observed)}


def _combine(imgs, mode: str):
    if mode == "average":
        return np.mean(np.stack([np.asarray(i, dtype=np.float32) for i in imgs]), axis=0).astype(imgs[0].dtype)
    h, k = imgs[0].shape[0], len(imgs)
    cuts = [int(round(h * i / k)) for i in range(k + 1)]
    return np.vstack([imgs[i][cuts[i]:cuts[i + 1]] for i in range(k)])


def _evidence(kind: str, pdfs: list[bytes], rng, page: int = 0, res: int = 4000, mode: str = "bands"):
    """(name, bytes): the PDF, a screen photo or a print photo; several copies are spliced in
    horizontal bands or averaged pixel by pixel."""
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, PrintParams, photo_jpeg, print_layers, print_page, printed_photo_jpeg

    if kind == "pdf":
        return "e.pdf", pdfs[0]
    if kind == "foto":
        img = _combine([render_pages(p, 200, [page])[0].astype(np.float32) for p in pdfs], mode)
        data, _ = photo_jpeg(np.clip(np.rint(img), 0, 255).astype(np.uint8), rng, PhotoParams(long_side=1600))
        return "e.jpg", data
    prm = PrintParams()
    photo = PhotoParams(sensor_long_side=max(2400, res), long_side=res)
    if len(pdfs) == 1:
        data, _ = printed_photo_jpeg(pdfs[0], page, rng, prm, photo)
        return "e.jpg", data
    layers = [print_layers(p, page, prm.device_dpi) for p in pdfs]
    sheet, _ = print_page(_combine([lay[0] for lay in layers], mode), _combine([lay[1] for lay in layers], mode),
                          rng, prm)
    data, _ = photo_jpeg(sheet, rng, photo)
    return "e.jpg", data


def cases() -> list[dict]:
    out = []
    for src, ctxn in (("v1", "v2cf"), ("v2cf", "v1")):
        for seq in (3, 7):
            for kind in ("pdf", "cetak"):
                out.append({"case": f"{src} salinan, catatan {ctxn}", "doc": DOC, "src": src, "ctx": ctxn,
                            "seqs": [seq], "kind": kind})
    for seqs in ([11, 12], [13, 14], [21, 22, 23], [24, 25, 26]):
        for mode in ("bands", "average"):
            out.append({"case": f"gabungan {len(seqs)} salinan v2 ({mode})", "doc": DOC, "src": "v2cf",
                        "ctx": "v2cf", "seqs": seqs, "kind": "cetak", "mode": mode})
    for seqs in ([31, 32], [33, 34, 35]):
        out.append({"case": f"gabungan {len(seqs)} salinan v2, foto layar", "doc": DOC, "src": "v2cf", "ctx": "v2cf",
                    "seqs": seqs, "kind": "foto", "mode": "bands"})
    out.append({"case": "gabungan v1 + v2, catatan v2", "doc": DOC, "src": "mix", "ctx": "v2cf", "seqs": [41, 42],
                "kind": "cetak", "mode": "bands"})
    for kind in ("pdf", "cetak", "foto"):
        out.append({"case": "salinan dokumen lain", "doc": "surat_telegram", "src": "v2cf", "ctx": "v2cf",
                    "ctx_doc": DOC, "seqs": [5], "kind": kind})
    for page in (0, 1):
        out.append({"case": "induk tanpa tanda", "doc": DOC, "src": "induk", "ctx": "v2cf", "seqs": [],
                    "kind": "cetak", "page": page})
    for kind in ("cetak", "pdf"):
        out.append({"case": "catatan v2 tanpa shift_scheme", "doc": DOC, "src": "v2cf", "ctx": "v2cf_as_v1",
                    "seqs": [9], "kind": kind})
    return out


def run_case(i: int, c: dict) -> dict:
    from tapak.decoder.trace import collect_file, load_context
    from tapak.marker.issue import IssueManifest

    rng = np.random.default_rng([90210, i])
    ctx_doc = c.get("ctx_doc", c["doc"])
    if c["ctx"] == "v2cf_as_v1":
        folder = ukur.issuance_dir("uji", ctx_doc, 100, "v2cf")
        d = json.loads((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        d.pop("shift_scheme", None)
        manifest = IssueManifest.from_json(json.dumps(d))
        ctx = load_context((ukur.ROOT / "samples" / f"{ctx_doc}.pdf").read_bytes(), manifest, ukur.SECRETS["uji"])
    else:
        ctx = _ctx(ctx_doc, c["ctx"])
    if c["src"] == "induk":
        pdfs = [(ukur.ROOT / "samples" / f"{c['doc']}.pdf").read_bytes()]
    elif c["src"] == "mix":
        pdfs = [_copy(c["doc"], "v1", c["seqs"][0]), _copy(c["doc"], "v2cf", c["seqs"][1])]
    else:
        pdfs = [_copy(c["doc"], c["src"], s) for s in c["seqs"]]
    name, data = _evidence(c["kind"], pdfs, rng, page=c.get("page", 0), mode=c.get("mode", "bands"))
    obs, _ = collect_file(name, data, ctx)
    return dict(c, **_trace(obs, ctx, c["seqs"] if ctx_doc == c["doc"] else []))


def lawan(part: int, of: int) -> None:
    import cv2

    cv2.setNumThreads(1)
    out = ukur.HASIL / "tinjauan_lawan.jsonl"
    for i, c in enumerate(cases()):
        if i % of == part:
            r = run_case(i, c)
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(r, flush=True)


def kalibrasi() -> None:
    edges = [0, 0.5, 1, 2, 4, 8, float("inf")]
    rows = []
    for variant in ("v1", "v2cf"):
        for res in (1600, 4000):
            bins = np.zeros((len(edges) - 1, 3))  # count, errors, promised errors
            for doc in ukur.DOCS:
                ctx, _, _ = ukur.context("uji", doc, 100, variant)
                kinds = ukur.subchannel_kinds(ctx)
                for seq in range(1, 11):
                    for page in (1, 2):
                        key = ukur.job_key({"phase": "uji", "kind": "cetak", "variant": variant, "doc": doc, "n": 100,
                                            "printer": "laser", "res": res, "seqs": [seq], "page": page})
                        if not ukur.obs_path(key).exists():
                            continue
                        x = ctx.codewords[seq - 1]
                        for sb in ukur.load_obs(key):
                            if sb.channel != "shift":
                                continue
                            for q, v in zip(sb.positions, sb.llr):
                                if kinds.get(int(q)) == "kata":
                                    k = int(np.searchsorted(edges, abs(v), side="right")) - 1
                                    bins[k] += (1, (v > 0) != (x[int(q)] == 1), 1.0 / (1.0 + np.exp(abs(v))))
            rows.append({"variant": variant, "printer": "laser", "res": res, "n": 100,
                         "bins": [{"llr_abs": [edges[k], edges[k + 1] if np.isfinite(edges[k + 1]) else None],
                                   "bits": int(b[0]), "errors": int(b[1]), "promised": round(float(b[2]), 1)}
                                  for k, b in enumerate(bins) if b[0]]})
            print(rows[-1], flush=True)
    (ukur.HASIL / "tinjauan_kalibrasi.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "lawan":
        lawan(int(sys.argv[2]) if len(sys.argv) > 2 else 0, int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    else:
        kalibrasi()
