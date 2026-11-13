"""Numbers and pictures behind the landing page (``/``) of the web UI.

Every number on the landing page comes from a result file in this repository; this script
reads them and writes ``tapak/web/landing.json``, which the page draws its charts from:

* ``pemisahan``: the accusation scores of fig_hasil.py (N=100, c=3, eps=1e-6, 1000 trials,
  seed 2026, every collusion strategy) binned over the threshold, innocents and members apart;
* ``media``: verdicts per kind of evidence, from the README benchmark
  (docs/results/bench_photos.json) and the held-out runs of research/registrasi and
  research/fotopotong;
* ``sungguhan``: the real phone photos of real prints of known copies (research/fotoasli),
  as taken and as a messaging app forwards them;
* ``batas``: the false-accusation bound of the README benchmark per set (median and worst);
* ``uji``: honest held-out traces of the studies and how many named someone else.

The pictures (``tapak/web/static/img/landing-*.webp``) are the synthetic phone photo of copy 13
of ``fig_alur.py`` (run it first), page 1 of the berita acara of tracing it again, and the
channel close-ups of ``fig_kanal.py`` (docs/img/kanal-*.png). Usage::

    .venv/bin/python docs/figures/fig_landing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "tapak" / "web" / "landing.json"
IMG = ROOT / "tapak" / "web" / "static" / "img"
ALUR = ROOT / "out" / "figures-work" / "alur" / "demo"
EDGES = np.round(np.arange(-0.5, 3.01, 0.1), 2) + 0.0  # score / threshold (+ 0.0: no -0.0)

# README benchmark sets in reading order: (medium key in bench_photos.json, label)
BENCH = [  # (medium, label, short label for the log chart)
    ("layar", "Foto layar dan tangkapan layar", "Foto layar"),
    ("foto ponsel", "Foto dengan pemrosesan kamera ponsel", "Foto ISP ponsel"),
    ("foto layar (monitor)", "Foto layar monitor", "Foto monitor"),
    ("cetak, 2 halaman", "Cetakan difoto, dua halaman", "Cetak, 2 halaman"),
    ("cetak, 1 halaman", "Cetakan difoto, satu halaman", "Cetak, 1 halaman"),
]
# research/registrasi held-out kinds: (key in ringkas_uji.json, label)
REGISTRASI = [
    ("rendah", "Halaman utuh 24 sampai 48 dpi"),
    ("potong", "Potongan tangkapan layar"),
    ("foto", "Foto ponsel sebagian halaman"),
    ("paragraf", "Satu paragraf saja"),
]


def pemisahan() -> dict:
    from fig_hasil import simulate_scores

    innocent, member, _ = simulate_scores()
    clip = lambda v: np.clip(v, EDGES[0], EDGES[-1] - 1e-9)  # noqa: E731
    return {
        "tepi": EDGES.tolist(),
        "tak_bersalah": np.histogram(clip(innocent), EDGES)[0].tolist(),
        "anggota": np.histogram(clip(member), EDGES)[0].tolist(),
        "n_tak_bersalah": int(innocent.size), "n_anggota": int(member.size),
        "maks_tak_bersalah": round(float(innocent.max()), 3), "min_anggota": round(float(member.min()), 3),
        "sumber": "docs/figures/fig_hasil.py (docs/results/simulate_n100_c3.json)",
    }


def media_and_bounds() -> tuple[list, list]:
    rows = json.loads((ROOT / "docs" / "results" / "bench_photos.json").read_text())["rows"]
    media, bounds = [], []
    for key, label, short in BENCH:
        sel = [r for r in rows if r["medium"] == key]
        fa = [r["log10_fa"] for r in sel if r["log10_fa"] is not None]
        media.append({"label": label, "benar": sum(r["outcome"] == "benar" for r in sel), "n": len(sel),
                      "salah": sum(bool(set(r["accused"]) - {r["expected"]}) for r in sel),
                      "sumber": "docs/results/bench_photos.json"})
        bounds.append({"label": short, "median": round(float(np.median(fa)), 1), "terburuk": round(max(fa), 1)})
    reg = json.loads((ROOT / "research" / "registrasi" / "hasil" / "ringkas_uji.json").read_text())["per_jenis"]
    for key, label in REGISTRASI:
        after = reg[key]["sesudah"]
        media.append({"label": label, "benar": after["disebut"], "n": reg[key]["n"], "salah": after["tuduhan_salah"],
                      "sumber": "research/registrasi/hasil/ringkas_uji.json"})
    crops = [r for r in _jsonl("research/fotopotong/hasil/uji.jsonl") if not r["silang"] and r["scale"] < 1.0]
    media.append({"label": "Foto ponsel dipotong lalu diperkecil", "n": len(crops),
                  "benar": sum(1 for r in crops if (r.get("lacak_sesudah") or {}).get("verdict") == "benar"),
                  "salah": sum(1 for r in crops if (r.get("lacak_sesudah") or {}).get("verdict") == "salah"),
                  "sumber": "research/fotopotong/hasil/uji.jsonl"})
    return media, bounds


def real_prints() -> list:
    """Real phone photos of real prints of known copies: rows as in ``media``."""
    rows = _jsonl("research/fotoasli/hasil/salinan.jsonl")
    return [{"label": label, "n": len(rows), "benar": sum(r[kind]["verdict"] == "benar" for r in rows),
             "salah": sum(r[kind]["verdict"] == "salah" for r in rows), "sumber": "research/fotoasli/hasil/salinan.jsonl"}
            for kind, label in (("asli", "Foto ponsel dari cetakan sungguhan"),
                                ("pesan", "Foto yang sama setelah aplikasi pesan"))]


def _jsonl(rel: str) -> list[dict]:
    return [json.loads(x) for x in (ROOT / rel).read_text(encoding="utf-8").splitlines() if x.strip()]


def honest_traces() -> dict:
    """Held-out traces of the studies (each run once after its rules were fixed) and how many
    named someone who did not leak."""
    kal = _jsonl("research/kalibrasi/hasil/uji.jsonl")
    geser = _jsonl("research/geser/hasil/uji.jsonl")
    crops = [r["lacak_sesudah"] for r in _jsonl("research/fotopotong/hasil/uji.jsonl") if r.get("lacak_sesudah")]
    reg = json.loads((ROOT / "research" / "registrasi" / "hasil" / "ringkas_uji.json").read_text())
    reg_wrong = sum(v["sesudah"]["tuduhan_salah"] for v in reg["per_jenis"].values())
    return {"n": len(kal) + reg["traces"] + len(geser) + len(crops),
            "tuduhan_salah": sum(bool(r["salah"]) for r in kal + geser) + reg_wrong
            + sum(1 for v in crops if v["verdict"] == "salah"),
            "sumber": ["research/kalibrasi/hasil/uji.jsonl", "research/registrasi/hasil/ringkas_uji.json",
                       "research/geser/hasil/uji.jsonl", "research/fotopotong/hasil/uji.jsonl"]}


def example_and_pictures() -> dict | None:
    """Trace fig_alur.py's synthetic photo of copy 13 again (in a throwaway copy of its demo
    folder, so its registry is untouched), write the berita acara, and keep the photo and page 1
    of that berita acara as landing pictures. None when fig_alur.py has not been run."""
    import os
    import shutil
    import tempfile
    import time

    import cv2
    import pymupdf

    if not (ALUR / "foto_bocor.jpg").exists():
        print(f"lewati contoh dan gambar: jalankan fig_alur.py dulu ({ALUR})")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "demo"
        shutil.copytree(ALUR, work)
        os.environ.update(TAPAK_DATA=str(work / "data"), TAPAK_KEY_DIR=str(work / "keys"))
        os.environ.pop("TAPAK_ANCHOR_LOG", None)
        from tapak.config import load_settings
        from tapak.service import list_workspaces, trace_evidence, write_report

        settings = load_settings()
        doc = list_workspaces(settings)[0]
        photo = (work / "foto_bocor.jpg").read_bytes()
        t0 = time.perf_counter()
        outcome = trace_evidence(settings, doc.doc_hash, "foto_bocor.jpg", photo)
        seconds = time.perf_counter() - t0
        a = outcome.attribution
        top = a.accused[0]
        report = write_report(outcome, case_number="DEMO-TAPAK-001", examiner_name="Mayor Chk Pemeriksa Fiktif",
                              examiner_rank="Mayor / NRP 99990003")
        with pymupdf.open(stream=report, filetype="pdf") as d:
            pix = d[0].get_pixmap(dpi=110, alpha=False)
            page = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        cv2.imwrite(str(IMG / "landing-ba.webp"), cv2.cvtColor(page, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_WEBP_QUALITY, 85])
        img = cv2.imdecode(np.frombuffer(photo, np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        s = 900 / max(h, w)
        cv2.imwrite(str(IMG / "landing-bukti.webp"),
                    cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_WEBP_QUALITY, 82])
        return {"salinan": top.copy.seq, "penerima": top.copy.nama, "jabatan": top.copy.jabatan, "satuan": top.copy.satuan, "skor": round(float(top.score), 1),
                "ambang": round(float(a.threshold.threshold), 1), "log10_tuduhan_salah": round(top.log10_false_accusation, 1),
                "n_salinan": len(doc.copies), "detik": round(seconds, 1),
                "sumber": "out/figures-work/alur/demo/foto_bocor.jpg (fig_alur.py), dilacak ulang di salinan folder"}


def channel_pictures() -> None:
    """The README channel close-ups as WebP (alpha kept) for the landing page."""
    import cv2

    for theme in ("light", "dark"):
        img = cv2.imread(str(ROOT / "docs" / "img" / f"kanal-{theme}.png"), cv2.IMREAD_UNCHANGED)
        cv2.imwrite(str(IMG / f"landing-kanal-{theme}.webp"), img, [cv2.IMWRITE_WEBP_QUALITY, 90])


def main() -> int:
    media, bounds = media_and_bounds()
    data = {"pemisahan": pemisahan(), "media": media, "sungguhan": real_prints(), "batas": bounds,
            "uji": honest_traces(), "contoh": example_and_pictures()}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    channel_pictures()
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
