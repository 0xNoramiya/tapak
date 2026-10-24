"""Wall-clock time of ``register`` for refusals and for ordinary evidence, with the code of one tree.

Refusals: every fifth case of research/registrasi/tinjau.py (crops of an unrelated fictional
document, blank bands, margins and footers; 11 cases), registered against the nota dinas of the
held-out issuance of research/registrasi. Ordinary evidence: every 150th stored held-out image
of research/registrasi (16 images). The master caches are warmed once before timing, as on a
running server. Run once per tree, one after the other on the same machine; threads as the tree
decides (``TAPAK_WORKERS`` unset):

    TAPAK_WT=<tree> TAPAK_REGISTRASI_KERJA=<work folder> python research/fotopotong/waktu.py <out.json>
"""
import json
import os
import sys
import time
from pathlib import Path

W = os.environ["TAPAK_WT"]
sys.path.insert(0, W)
sys.path.insert(0, W + "/research/registrasi")
import numpy as np  # noqa: E402
import pymupdf  # noqa: E402

from tinjau import cases  # noqa: E402
from tapak.decoder import rectify  # noqa: E402

K = Path(os.environ.get("TAPAK_REGISTRASI_KERJA") or Path(W) / "out" / "riset_registrasi")


def master(doc):
    pdf = next((K / "uji" / f"{doc}_v2" / "data" / "dokumen").glob("*/induk.pdf")).read_bytes()
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return pdf, [(p.rect.width, p.rect.height) for p in d]


class _Ctx:
    def __init__(self, pdf, n_pages):
        from types import SimpleNamespace
        self.master = SimpleNamespace(pdf_bytes=pdf, layout=SimpleNamespace(pages=list(range(n_pages))))


def main():
    out = {"tolak": [], "biasa": []}
    nd, td = master("nota_dinas"), master("surat_telegram")
    masters = {"nota_dinas": _Ctx(nd[0], len(nd[1])), "surat_telegram": _Ctx(td[0], len(td[1]))}
    picked = [c for i, c in enumerate(cases(masters)) if i % 5 == 0][:12]  # every fifth review case
    rectify.register(np.full((60, 60), 255, np.float32), nd[0], nd[1])  # warm the master caches once
    rectify.register(np.full((60, 60), 255, np.float32), td[0], td[1])
    for name, img in picked:
        t0 = time.perf_counter()
        reg = rectify.register(img.astype(np.float32), nd[0], nd[1])
        out["tolak"].append({"bukti": name, "detik": round(time.perf_counter() - t0, 2), "diterima": reg is not None})
        print("tolak", name, out["tolak"][-1], flush=True)
    files = sorted((K / "bukti" / "uji").glob("*.bin"))[::150][:16]
    for f in files:
        pdf, sizes = nd if "nota_dinas" in f.name else td
        img = rectify.load_gray(f.read_bytes())
        t0 = time.perf_counter()
        reg = rectify.register(img, pdf, sizes)
        out["biasa"].append({"bukti": f.name, "detik": round(time.perf_counter() - t0, 2),
                             "metode": None if reg is None else reg.method})
        print("biasa", f.name, out["biasa"][-1], flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
