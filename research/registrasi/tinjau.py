"""Review (adversarial, after the held-out run): try to make registration accept a wrong pose or a
wrong page.

Evidence: crops of an unrelated fictional document set in the same font, margins and paper size,
blank bands and left margins of the real masters, footer-only strips, and non-document images
(noise, a gradient, a checkerboard). Each is registered against both sample masters of the
held-out issuances; anything registered is traced (all of eps, not logged) to check that nobody
is named. Writes ``hasil/tinjau.jsonl``. Usage, from the repository root, after ``ukur.py terbit
--split uji``:

    python research/registrasi/tinjau.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ukur  # noqa: E402

from tapak.decoder import rectify  # noqa: E402
from tapak.decoder.image import collect_from_gray  # noqa: E402
from tapak.decoder.trace import run_trace  # noqa: E402

FONT = next((ROOT / "tapak" / "assets").rglob("DejaVuSans.ttf"))
TEXT = ("Laporan kegiatan pelatihan gabungan triwulan ketiga disusun sebagai bahan evaluasi pimpinan. "
        "Seluruh peserta mengikuti rangkaian latihan sesuai jadwal yang telah ditetapkan, dan hasilnya "
        "dicatat oleh petugas administrasi pada setiap akhir sesi. ")
CROPS = {"atas40": (0.0, 0.4), "tengah40": (0.3, 0.7), "bawah25": (0.75, 1.0), "paragraf": (0.15, 0.3),
         "utuh": (0.0, 1.0)}


def unrelated_pdf() -> bytes:
    """Two A4 pages of a fictional report in DejaVu Sans with 72 pt margins, like the samples."""
    doc = pymupdf.open()
    for k in range(2):
        page = doc.new_page(width=595.5, height=843.0)
        page.insert_font(fontname="dv", fontfile=str(FONT))
        page.insert_text((72, 90), "LAPORAN KEGIATAN (FIKTIF)", fontname="dv", fontsize=13)
        y = 130
        for para in range(6):
            page.insert_textbox(pymupdf.Rect(72, y, 523, y + 100), TEXT * (2 + para % 2), fontname="dv",
                                fontsize=11, align=3)
            y += 112
        page.insert_text((72, 800), f"Halaman {k + 1} dari 2", fontname="dv", fontsize=9)
    return doc.tobytes()


def render(pdf: bytes, page: int, dpi: float) -> np.ndarray:
    """Page ``page`` of ``pdf`` drawn by MuPDF at ``dpi``, uint8 gray."""
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        pix = d[page].get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def chrome(img: np.ndarray) -> np.ndarray:
    """A dark viewer frame with a toolbar around ``img``."""
    h, w = img.shape
    c = np.full((h + 60, w + 60), 60, np.uint8)
    c[:40] = 40
    c[50:50 + h, 30:30 + w] = img
    return c


def jpeg(img: np.ndarray, quality: int = 65) -> np.ndarray:
    """``img`` after one JPEG round trip."""
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def cases(masters: dict) -> list[tuple[str, np.ndarray]]:
    """(name, gray image) of every evidence of the review."""
    rng = np.random.default_rng(4242)
    out = []
    other = unrelated_pdf()
    for dpi in (48, 120):
        for pg in (0, 1):
            full = render(other, pg, dpi)
            h = full.shape[0]
            for name, (a, b) in CROPS.items():
                crop = full[int(a * h):int(b * h)]
                out.append((f"lain_p{pg + 1}_{name}_{dpi}", crop))
                out.append((f"lain_p{pg + 1}_{name}_{dpi}_bingkai_jpeg", jpeg(chrome(crop))))
    for doc, ctx in masters.items():
        for pg in range(len(ctx.master.layout.pages)):
            full = render(ctx.master.pdf_bytes, pg, 84)
            h, w = full.shape
            out.append((f"{doc}_p{pg + 1}_kosong_bawah_84", full[int(0.86 * h):int(0.93 * h)]))  # blank band above the footer
            out.append((f"{doc}_p{pg + 1}_kaki_84", full[int(0.93 * h):]))  # the footer alone
            out.append((f"{doc}_p{pg + 1}_tepi_kiri_84", full[:, :int(0.1 * w)]))  # the left margin
    out.append(("derau", rng.integers(0, 256, (900, 640)).astype(np.uint8)))
    out.append(("gradasi", np.tile(np.linspace(40, 230, 640), (900, 1)).astype(np.uint8)))
    out.append(("kotak_kotak", (np.indices((900, 640)).sum(0) // 40 % 2 * 200 + 30).astype(np.uint8)))
    return out


def main() -> int:
    masters = {doc: ukur.context("uji", doc)[0] for doc in ("nota_dinas", "surat_telegram")}
    rows = []
    for name, img in cases(masters):
        for doc, ctx in masters.items():
            sizes = [(p.width, p.height) for p in ctx.master.layout.pages]
            diag: dict = {}
            t0 = time.time()
            reg = rectify.register(img, ctx.master.pdf_bytes, sizes, diag=diag)
            row = {"bukti": name, "induk": doc, "reg": None if reg is None else reg.method,
                   "page": None if reg is None else reg.page, "rescue": (diag.get("rescue") or {}).get("outcome"),
                   "detik": round(time.time() - t0, 1)}
            if reg is not None:
                row["dituduh"] = sorted(run_trace(collect_from_gray(img, ctx), ctx).named_seqs)
            rows.append(row)
            print(json.dumps(row), flush=True)
    (ukur.HASIL / "tinjau.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
