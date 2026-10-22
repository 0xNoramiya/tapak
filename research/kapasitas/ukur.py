"""Capacity of the shift channel on printed copies (docs/keamanan.md batasan 3): measurements.

The protocol below (``PROTOCOL``) was fixed before any run: candidate schemes, seeds, grids,
the rule that picks a candidate on the development seeds and the rule that decides the default
on the held-out seeds. Development seeds serve every design choice; the held-out seeds are run
once, at the end, for the old scheme and the chosen candidate on the same evidence (same copy
ids and codewords, same print and photo random numbers). Both sample documents are fictional.

Visibility was decided before capacity (see ``PROTOCOL["visibility"]`` and the docs):

* scheme a (vertical offsets of data groups on one baseline) is dropped. A vertical step
  between neighbouring words is a vernier task. A printer places a row on whole scan lines
  (600 dpi: 42.3 um), so any requested step either vanishes or prints as at least one scan
  line, 25 arcsec at 35 cm, while the vernier threshold for a word gap of 1.3 to 1.9 mm (13 to
  18 arcmin) is about 13 to 18 arcsec by the 1/60 Weber fraction for separated lines. Only a
  small development probe (``a010``) checks that a sub-threshold request (0.01 mm) is also
  unreadable on paper;
* scheme b (``geser-v2``: every group of a row carries a bit, decoded jointly) is admitted with
  a per-group shift of at most 0.025 mm: then no glyph moves more than in geser-v1, no word gap
  changes by more than geser-v1's 0.05 mm, and the left/right gap asymmetry stays within 0.10
  mm;
* scheme c (smaller groups, MIN_GROUP_WIDTH 10 pt) only regroups words; its cues are those of
  the scheme it is combined with.

Evidence kinds: ``cetak`` (phone photo of a page printed by the simulated laser or inkjet
printer, ``tapak.photos``), ``kolusi`` (a page cut together from three copies in the white
space between rows near 1/3 and 2/3 of the text, printed and photographed), ``pdf`` (the copy
itself), ``layar`` (screenshot) and ``foto`` (screen photo) of page 1, and ``induk_*`` (the
unmarked master through every kind, traced against every context: nobody may be accused).
Traces are not logged (all of eps), as in ``make bench``; one stage.

Issued copies, observations (LLR arrays) and caches go to ``out/riset_kapasitas/`` (large, not
committed); the summary rows quoted in the docs go to ``research/kapasitas/hasil/`` and the
crops to ``research/kapasitas/potongan/``. Process pools are capped at 3, BLAS and OpenCV at one
thread per worker (shared machine). Usage, from the repository root:

    PYTHONPATH=. python research/kapasitas/ukur.py dev          # development grid
    PYTHONPATH=. python research/kapasitas/ukur.py ringkas dev  # tables, candidate choice
    PYTHONPATH=. python research/kapasitas/ukur.py uji --kandidat v2   # held-out, once
    PYTHONPATH=. python research/kapasitas/ukur.py ringkas uji
    PYTHONPATH=. python research/kapasitas/ukur.py visibilitas  # geometric cues and crops
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the worktree's tapak, not an installed copy

WORK = ROOT / "out" / "riset_kapasitas"
HASIL = ROOT / "research" / "kapasitas" / "hasil"
POTONGAN = ROOT / "research" / "kapasitas" / "potongan"
WORKERS = 3
DOCS = ("nota_dinas", "surat_telegram")

PROTOCOL: dict = {
    "c": 3, "eps": 1e-6, "spending": "tidak dicatat (seluruh eps), satu tahap, seperti make bench",
    "secret": {"dev": "sha256('TAPAK-riset-kapasitas-dev-v1')", "uji": "sha256('TAPAK-riset-kapasitas-uji-v1')"},
    "copy_id_seed": {"dev": 51001, "uji": 52001},
    "evidence_seed": {"dev": 61001, "uji": 62001},
    "coalition_seed": 63001, "unmarked_seed": 64001,
    "photo": {"angle": "diundi seragam 0 sampai 30 derajat", "render_dpi": 200, "screen_long_side": 1600},
    "printers": {"laser": "PrintParams()", "inkjet": "INKJET"},
    "variants": {
        "v1": {"scheme": "geser-v1", "word_mm": 0.05, "row_mm": 0.05, "min_group_pt": 20.0},
        "v2": {"scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 20.0, "degree": 1,
               "field": None},
        "v2q": {"issued_as": "v2", "scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 20.0,
                "degree": 2, "field": None, "note": "sama dengan v2, didekode dengan gangguan kuadratik per baris"},
        "v1c": {"scheme": "geser-v1", "word_mm": 0.05, "row_mm": 0.05, "min_group_pt": 10.0},
        "v2c": {"scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 10.0, "degree": 1,
                "field": None},
        "v2cq": {"issued_as": "v2c", "scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 10.0,
                 "degree": 2, "field": None, "note": "sama dengan v2c, didekode dengan gangguan kuadratik per baris"},
        "v2f": {"issued_as": "v2", "scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 20.0,
                "degree": 1, "field": 3,
                "note": "sama dengan v2; medan geser halaman (polinomial derajat 3) dikurangkan sebelum dekode per baris"},
        "v2cf": {"issued_as": "v2c", "scheme": "geser-v2", "word_mm": 0.025, "row_mm": 0.05, "min_group_pt": 10.0,
                 "degree": 1, "field": 3, "note": "sama dengan v2c, dengan medan geser halaman seperti v2f"},
        "a010": {"issued_as": "v1", "probe_vshift_mm": 0.01, "rows": False,
                 "note": "uji coba skema a saja (bukan kandidat): kelompok data v1 juga bergeser vertikal 0,01 mm"},
    },
    "dev": {
        "n": [100], "copies": list(range(1, 9)),
        "cetak": [["nota_dinas", [1, 2]], ["surat_telegram", [1]]],
        "printers_resolutions": [["laser", 1600], ["laser", 4000], ["inkjet", 1600]],
        "variants": ["v1", "v2", "v1c", "v2c"], "decode_only": {"v2q": "v2", "v2cq": "v2c"},
        "probe": {"variant": "a010", "doc": "nota_dinas", "pages": [1], "printers_resolutions": [["laser", 1600],
                                                                                               ["laser", 4000]]},
        "layar_foto_pdf": {"variants": ["v1", "v2"], "copies": list(range(1, 9))},
        "veld": {"emit": {"v2": ["v2f"], "v2c": ["v2cf"]},
                 "amendment": ("2026-10-22, dari studi dekoder pada 40 foto dev (dekoder_dev.py): medan geser "
                               "halaman menaikkan skor salinan yang benar pada 1600 px; v2f dan v2cf ditambahkan "
                               "sebagai kandidat dekode saja, didekode ulang pada semua foto cetak dev v2 dan v2c "
                               "(bukti dibuat ulang dengan benih yang sama), hasil di dev_veld.jsonl.")},
        "choice_rule": ("di antara v2, v2q, v1c, v2c, v2cq, v2f dan v2cf dipilih kandidat dengan foto cetak satu halaman benar terbanyak "
                        "(laser dan inkjet, 1600 dan 4000 px, kedua dokumen) dan nol tuduhan salah; seri: benar dua "
                        "halaman terbanyak, lalu median skor/ambang salinan yang benar tertinggi. Kandidat itu dibawa "
                        "ke uji tertahan melawan v1, apa pun hasilnya."),
    },
    "uji": {
        "n": [20, 100],
        "cetak": [["nota_dinas", [1, 2]], ["surat_telegram", [1, 2]]],
        # [printer, resolution, code sizes, copies]
        "cetak_cells": [["laser", 1600, [20, 100], list(range(1, 11))], ["laser", 4000, [20, 100], list(range(1, 11))],
                        ["inkjet", 1600, [100], list(range(1, 6))], ["inkjet", 4000, [100], list(range(1, 6))]],
        "kolusi": {"n": 100, "coalitions": 6, "from_copies": list(range(1, 21)),
                   "printers_resolutions": [["laser", 1600], ["laser", 4000]],
                   "pages": {"nota_dinas": [1, 2], "surat_telegram": [1]}},
        "layar_foto_pdf": {"copies": list(range(1, 11))},
        "induk": {"layar": 2, "foto": 2, "cetak_pages": [1, 2],
                  "printers_resolutions": [["laser", 1600], ["laser", 4000], ["inkjet", 1600], ["inkjet", 4000]]},
        "latar_cetak": {"doc": "nota_dinas", "n": 100, "copies": list(range(1, 7)),
                        "laser": [[1600, [1, 2]], [4000, [1, 2]]], "inkjet": [[1600, [1]]],
                        "kolusi": {"coalitions": 6, "pages": [1], "resolution": 1600}},
        "amendment": ("2026-10-22, sebelum hasil kandidat dev mana pun terlihat (hanya baris v1 dev yang sudah ada): "
                      "grid uji dipangkas karena waktu hitung di mesin bersama (sekitar 3 jam, bukan 5): inkjet "
                      "hanya N = 100 dan salinan 1 sampai 5, 6 koalisi (bukan 8), profil latar cetak salinan 1 "
                      "sampai 6 dan 6 koalisi."),
    },
    "decision_rule": (
        "skema baru menjadi bawaan penerbitan baru hanya bila (1) lolos analisis keterlihatan, (2) tidak mundur "
        "pada PDF, tangkapan layar, dan foto layar (untuk setiap jenis: benar sama atau lebih banyak), (3) nol "
        "tuduhan salah di semua bukti tertahan (termasuk induk tanpa tanda, gabungan c = 3, dan profil latar "
        "cetak), dan (4) foto cetak satu halaman tertahan benar jelas lebih sering: selisih paling sedikit 10 "
        "poin persentase atas semua foto cetak satu halaman tertahan dan uji tanda McNemar eksak satu sisi pada "
        "pasangan foto yang sama p < 0,01. Bila tidak, skema baru tetap pilihan (bendera CLI dan pilihan web) "
        "atau dibuang."),
    "visibility": {
        "reading_distance_mm": 350, "arcsec_per_mm": 589.3,
        "vernier": ("ambang vernier garis bersebelahan beberapa detik busur (Westheimer 2010; Westheimer & McKee "
                    "1977); untuk elemen terpisah ambang naik sebanding jarak, sekitar 1/60 jarak (Westheimer & "
                    "McKee 1977) dan 2,8 sampai 3,8 % untuk dua titik (Groll & Hirsch 1987); panjang garis di atas "
                    "sekitar 5 menit busur tidak lagi menurunkan ambang"),
        "word_gap_mm": {"nota_dinas_p10": 1.29, "nota_dinas_median": 1.85},
        "printer_row_quantum_um": {"600 dpi": 42.3, "1200 dpi": 21.2},
        "scheme_a": "dibuang: tidak ada delta yang terbaca di kertas sekaligus di bawah ambang vernier dengan margin",
        "scheme_b_max_word_mm": 0.025, "scheme_c": "hanya mengelompokkan ulang kata",
    },
}
SECRETS = {"dev": hashlib.sha256(b"TAPAK-riset-kapasitas-dev-v1").digest(),
           "uji": hashlib.sha256(b"TAPAK-riset-kapasitas-uji-v1").digest()}
PRINTER_INDEX = {"laser": 0, "inkjet": 1}
KIND_INDEX = {"cetak": 1, "foto": 2, "layar": 3, "pdf": 4, "kolusi": 5}


# --- issuance -----------------------------------------------------------------------------


@contextlib.contextmanager
def group_width(pt: float):
    """Temporarily set the minimum shift-group width (scheme c) for layouts built inside."""
    import tapak.marker.layout as layout

    old = layout.MIN_GROUP_WIDTH
    layout.MIN_GROUP_WIDTH = pt
    try:
        yield
    finally:
        layout.MIN_GROUP_WIDTH = old


def variant(name: str) -> dict:
    return PROTOCOL["variants"][name]


def issued_name(name: str) -> str:
    return variant(name).get("issued_as", name)


def recipients(n: int):
    from tapak.marker.issue import Recipient

    return [Recipient(f"R{i:03d}", f"Penerima Fiktif {i:03d}", "Jabatan Uji", "Satuan Uji") for i in range(1, n + 1)]


def issuance_dir(phase: str, doc: str, n: int, name: str, latar: str = "layar") -> Path:
    return WORK / phase / f"{doc}_n{n}_{issued_name(name)}_{latar}"


def issue_variant(phase: str, doc: str, n: int, name: str, latar: str = "layar") -> Path:
    """Issue n copies of ``doc`` with the variant's scheme (copy ids seeded per phase, doc and n,
    so every variant of a phase has the same copy ids and codewords). Done once; reused."""
    import tapak.marker.issue as issue_mod
    from tapak.marker.background import background_profile
    from tapak.marker.issue import IssueSettings, issue
    from tapak.marker.pdf_shift import ShiftSettings

    folder = issuance_dir(phase, doc, n, name, latar)
    if (folder / "salinan" / "manifest.json").exists():
        return folder
    v = variant(issued_name(name))
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng([PROTOCOL["copy_id_seed"][phase], DOCS.index(doc), n])
    real = issue_mod.secrets.token_hex
    issue_mod.secrets.token_hex = lambda k=8: rng.bytes(k).hex()  # type: ignore[assignment]
    regroup = v["min_group_pt"] != 20.0
    try:
        settings = IssueSettings(
            c=PROTOCOL["c"], eps=PROTOCOL["eps"], n_max=n, workers=1 if regroup else WORKERS,
            shift=ShiftSettings(word_mm=v["word_mm"], row_mm=v["row_mm"], scheme=v["scheme"]),
            background=background_profile(latar), canary_domain=None)
        with group_width(v["min_group_pt"]):
            t0 = time.perf_counter()
            manifest = issue(ROOT / "samples" / f"{doc}.pdf", recipients(n), folder / "salinan", SECRETS[phase],
                             settings, issuer="riset-kapasitas")
        print(f"terbit {folder.name}: {time.perf_counter() - t0:.0f} s, {manifest.plan_summary.get('shift')}", flush=True)
    finally:
        issue_mod.secrets.token_hex = real
    return folder


# --- worker side --------------------------------------------------------------------------

_CTX: dict = {}


def _init() -> None:
    import cv2

    cv2.setNumThreads(1)


def context(phase: str, doc: str, n: int, name: str, latar: str = "layar"):
    """Trace context of an issuance (cached per process); scheme c layouts are rebuilt with
    their group width."""
    key = (phase, doc, n, issued_name(name), latar)
    if key not in _CTX:
        from tapak.decoder.trace import load_context
        from tapak.marker.issue import IssueManifest

        folder = issuance_dir(phase, doc, n, name, latar)
        manifest = IssueManifest.from_json((folder / "salinan" / "manifest.json").read_text(encoding="utf-8"))
        with group_width(variant(issued_name(name))["min_group_pt"]):
            ctx = load_context((ROOT / "samples" / f"{doc}.pdf").read_bytes(), manifest, SECRETS[phase])
        _CTX[key] = (ctx, manifest, folder)
    return _CTX[key]


def copy_pdf(phase: str, doc: str, n: int, name: str, seq: int, latar: str = "layar") -> bytes:
    if variant(name).get("probe_vshift_mm"):
        return probe_pdf(phase, doc, n, name, seq)
    _, manifest, folder = context(phase, doc, n, name, latar)
    return (folder / "salinan" / manifest.copies[seq - 1].file).read_bytes()


def probe_slots(ctx):
    """Scheme a probe: one keyed vertical bit per geser-v1 data group (own permutation and
    whitening stream "vshift"), never a codeword."""
    from tapak.marker.pdf_shift import data_groups, eligible_rows
    from tapak.marker.plan import assign_positions

    layout = ctx.master.shift_layout
    refs = [(p.index, (r.index, g), 1) for p in layout.pages for r in eligible_rows(layout, p.index, ctx.excluded)
            for g in data_groups(r)]
    return assign_positions("vshift", refs, ctx.params.length, ctx.key)


def probe_pdf(phase: str, doc: str, n: int, name: str, seq: int) -> bytes:
    """A copy of the scheme a probe: geser-v1 word shifts, no row shifts, data groups also moved
    vertically by +/- probe_vshift_mm. Text and background marks are left out (they play no part
    in what is measured here)."""
    import pymupdf

    from tapak.marker.pdf_shift import MM_TO_PT, carried_sign, shift_marks
    from tapak.marker.pdf_zerowidth import TextMarks
    from tapak.marker.render import _AdvanceCache, _draw_word, strip_text

    path = WORK / phase / "probe" / f"{doc}_n{n}_{name}_s{seq:03d}.pdf"
    if path.exists():
        return path.read_bytes()
    ctx, _, _ = context(phase, doc, n, name)
    x = ctx.codewords[seq - 1]
    group_dx, _ = shift_marks(ctx.plan, x, ctx.shift)
    dy_pt = variant(name)["probe_vshift_mm"] * MM_TO_PT
    group_dy = {(s.page, s.ref[0], s.ref[1]): carried_sign(x[s.positions[0]], s.whiten[0]) * dy_pt
                for s in probe_slots(ctx)}
    master = ctx.master
    cache = _AdvanceCache(master)
    marks = TextMarks({}, {})
    doc_pdf = pymupdf.open(stream=master.pdf_bytes, filetype="pdf")
    strip_text(doc_pdf)
    for page_layout, page in zip(master.layout.pages, doc_pdf):
        for row in page_layout.rows:
            for group in row.groups:
                for wi in group.word_indices:
                    _draw_word(page, master, cache, row.words[wi], group_dx.get(group.id, 0.0),
                               group_dy.get(group.id, 0.0), marks)
    doc_pdf.subset_fonts()
    data = doc_pdf.tobytes(garbage=3, deflate=True)
    doc_pdf.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def printer(name: str):
    from tapak.photos import INKJET, PrintParams

    return {"laser": PrintParams(), "inkjet": INKJET}[name]


def _cut_rows(ctx, page: int, dpi: int) -> list[int]:
    """Two cut lines (device pixels) in the white space between rows nearest 1/3 and 2/3 of
    the text block of ``page``."""
    rows = ctx.master.layout.pages[page].rows
    boxes = sorted((r.bbox[1], r.bbox[3]) for r in rows)
    top, bottom = boxes[0][0], boxes[-1][1]
    gaps = [0.5 * (boxes[i][1] + boxes[i + 1][0]) for i in range(len(boxes) - 1) if boxes[i][1] < boxes[i + 1][0]]
    return [int(round(min(gaps, key=lambda g: abs(g - (top + f * (bottom - top)))) * dpi / 72.0)) for f in (1 / 3, 2 / 3)]


def make_evidence(job: dict) -> tuple[str, bytes, dict]:
    """(file name, bytes, meta) of the evidence of a job; the random numbers depend only on the
    phase, kind, document, code size, printer, resolution, copies, page and repetition, never on
    the variant."""
    from tapak.marker.render import render_pages
    from tapak.photos import (PhotoParams, ScreenshotParams, photo_jpeg, print_layers, print_page,
                              printed_photo_jpeg, screenshot_jpeg)

    phase, kind, doc, n, name = job["phase"], job["kind"], job["doc"], job["n"], job["variant"]
    latar = job.get("latar", "layar")
    seqs, page, res, prn = job["seqs"], job.get("page", 1), job.get("res", 1600), job.get("printer", "laser")
    unmarked = kind.startswith("induk_")
    base = kind[len("induk_"):] if unmarked else kind
    seed = PROTOCOL["unmarked_seed"] if unmarked else PROTOCOL["evidence_seed"][phase]
    rng = np.random.default_rng([seed, KIND_INDEX[base], DOCS.index(doc), 0 if unmarked else n,
                                 PRINTER_INDEX[prn], res, *seqs, page, job.get("rep", 0)])
    master_pdf = (ROOT / "samples" / f"{doc}.pdf").read_bytes()
    pdf = master_pdf if unmarked else (copy_pdf(phase, doc, n, name, seqs[0], latar) if base != "kolusi" else None)
    meta: dict = {}
    photo = PhotoParams(sensor_long_side=max(2400, res), long_side=res)
    if base == "pdf":
        return f"{kind}.pdf", pdf, meta  # type: ignore[return-value]
    if base == "cetak":
        data, m = printed_photo_jpeg(pdf, page - 1, rng, printer(prn), photo)  # type: ignore[arg-type]
        meta = {"view_angle": round(m["view_angle_deg"], 1), "clip": round(m["params"]["highlight_clip_frac"], 3)}
        return f"{kind}.jpg", data, meta
    if base == "kolusi":
        ctx, _, _ = context(phase, doc, n, name, latar)
        prm = printer(prn)
        layers = [print_layers(copy_pdf(phase, doc, n, name, s, latar), page - 1, prm.device_dpi) for s in seqs]
        c1, c2 = _cut_rows(ctx, page - 1, prm.device_dpi)
        text = np.vstack([layers[0][0][:c1], layers[1][0][c1:c2], layers[2][0][c2:]])
        tint = np.vstack([layers[0][1][:c1], layers[1][1][c1:c2], layers[2][1][c2:]])
        del layers
        sheet, _ = print_page(text, tint, rng, prm)
        del text, tint
        data, m = photo_jpeg(sheet, rng, photo)
        meta = {"view_angle": round(m["view_angle_deg"], 1), "cuts_px": [c1, c2]}
        return f"{kind}.jpg", data, meta
    rdpi = PROTOCOL["photo"]["render_dpi"]
    img = render_pages(pdf, rdpi, [page - 1])[0]  # type: ignore[arg-type]
    if base == "layar":
        data, m = screenshot_jpeg(img, rng, ScreenshotParams(render_dpi=float(rdpi),
                                                             long_side=PROTOCOL["photo"]["screen_long_side"]))
        meta = {"effective_dpi": round(m["effective_dpi"], 1)}
        return f"{kind}.jpg", data, meta
    data, m = photo_jpeg(img, rng, PhotoParams(long_side=PROTOCOL["photo"]["screen_long_side"]))
    meta = {"view_angle": round(m["view_angle_deg"], 1), "clip": round(m["params"]["highlight_clip_frac"], 3)}
    return f"{kind}.jpg", data, meta


@contextlib.contextmanager
def capture_displacements(store: list):
    """Record the displacements every shift decode of a trace sees (for decode-only variants)."""
    import tapak.decoder.ch_shift as ch
    import tapak.decoder.image as im

    real = ch.decode_displacements

    def spy(master, plan, disp, settings, *args, **kwargs):
        store.append(disp)
        return real(master, plan, disp, settings, *args, **kwargs)

    ch.decode_displacements, im.decode_displacements = spy, spy
    try:
        yield
    finally:
        ch.decode_displacements, im.decode_displacements = real, real


def subchannel_kinds(ctx) -> dict[int, str]:
    """Code position -> sub-channel name for the shift slots of a plan ("kata" or "baris")."""
    from tapak.marker.plan import CHANNEL_SHIFT

    return {s.positions[0]: ("kata" if len(s.ref) == 2 else "baris") for s in ctx.plan.channel(CHANNEL_SHIFT)}


def channel_stats(obs, ctx, x: np.ndarray | None) -> dict[str, dict[str, int]]:
    """Positions read and bit errors (against the leaked copy, when one copy leaked) per
    sub-channel: kata, baris, latar, teks."""
    kinds = subchannel_kinds(ctx)
    out: dict[str, dict[str, int]] = {}
    for sb in obs:
        if not len(sb):
            continue
        for q, v in zip(sb.positions, sb.llr):
            name = kinds.get(int(q), "kata") if sb.channel == "shift" else (
                "latar" if sb.channel == "background" else "teks")
            d = out.setdefault(name, {"read": 0, "errors": 0})
            d["read"] += 1
            if x is not None:
                d["errors"] += int((v > 0) != (x[int(q)] == 1))
    return out


def verdict_row(obs, ctx, expected: list[int]) -> dict:
    """Accuse with the fixed rule (all of eps, one stage) and summarize against ``expected``."""
    from tapak.decoder.trace import run_trace

    a = run_trace(obs, ctx)
    accused = sorted(c.copy.seq for c in a.accused)
    z = a.threshold.threshold
    scores = {c.copy.seq: c.score for c in a.candidates}
    innocent = [s for k, s in scores.items() if k not in expected]
    if not accused:
        verdict = "tidak cukup bukti"
    elif set(accused) <= set(expected):
        verdict = "benar"
    else:
        verdict = "salah"
    return {"verdict": verdict, "accused": accused, "n_observed": int(a.threshold.n_observed),
            "z": round(float(z), 2),
            "score_z": [round(scores.get(s, 0.0) / z, 3) for s in expected] if np.isfinite(z) and z > 0 else None,
            "max_innocent_z": round(max(innocent) / z, 3) if innocent and np.isfinite(z) and z > 0 else None}


def obs_path(key: str) -> Path:
    safe = key.replace("|", "__").replace("/", "_")
    return WORK / "obs" / f"{safe}.npz"


def save_obs(key: str, obs, disps: list | None = None) -> None:
    """Observations (and the measured word displacements, for decoder studies) of one trace."""
    arrays = {}
    for k, sb in enumerate(obs):
        arrays[f"{k}_{sb.channel}_pos"] = sb.positions
        arrays[f"{k}_{sb.channel}_llr"] = sb.llr
    for k, disp in enumerate(disps or []):
        arrays[f"disp{k}_ids"] = np.array(list(disp.keys()), dtype=np.int32).reshape(-1, 3)
        arrays[f"disp{k}_xy"] = np.array(list(disp.values()), dtype=np.float64).reshape(-1, 2)
    path = obs_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def load_obs(key: str):
    from tapak.decoder.softbits import SoftBits

    data = np.load(obs_path(key))
    parts: dict[int, dict] = {}
    for name in data.files:
        if name.startswith("disp"):
            continue
        k, rest = name.split("_", 1)
        channel, what = rest.rsplit("_", 1)
        parts.setdefault(int(k), {"channel": channel})[what] = data[name]
    return [SoftBits(p["channel"], p["pos"], p["llr"]) for _, p in sorted(parts.items())]


def job_key(job: dict) -> str:
    return "|".join(str(job.get(k, "-")) for k in ("phase", "kind", "variant", "doc", "n", "latar", "printer", "res")) + \
        "|s" + "-".join(str(s) for s in job["seqs"]) + f"|p{job.get('page', 1)}|r{job.get('rep', 0)}"


def probe_stats(disp, ctx, x: np.ndarray, name: str, page: int) -> dict:
    """Scheme a probe: relative vertical offset of every data group (line through its two
    neighbours), its sign against the probe bit, and how often the printed step vanished."""
    from tapak.decoder.ch_shift import _group_displacement
    from tapak.marker.pdf_shift import MM_TO_PT, carried_sign, relative_offset

    layout = ctx.master.shift_layout
    dy_pt = variant(name)["probe_vshift_mm"] * MM_TO_PT
    vals = []
    for s in probe_slots(ctx):
        if s.page != page - 1:
            continue
        row, g = s.ref
        trip = []
        for k in (g - 1, g, g + 1):
            r = layout.pages[s.page].rows[row]
            ys = [disp[r.words[i].id][1] for i in r.groups[k].word_indices if r.words[i].id in disp]
            trip.append(None if not ys else (0.5 * (r.groups[k].bbox[0] + r.groups[k].bbox[2]), float(np.mean(ys))))
        if any(t is None for t in trip):
            continue
        (pl, dl), (pd, dd), (pr, dr) = trip
        vals.append((relative_offset(pl, dl, pd, dd, pr, dr), carried_sign(x[s.positions[0]], s.whiten[0])))
    if not vals:
        return {"read": 0}
    r = np.array([v[0] for v in vals]) / MM_TO_PT * 1000.0  # um
    sign = np.array([v[1] for v in vals])
    return {"read": int(r.size), "errors": int(np.sum(np.sign(r) != sign)),
            "median_abs_um": round(float(np.median(np.abs(r))), 1),
            "share_below_half_um": round(float(np.mean(np.abs(r) < 0.5 * dy_pt / MM_TO_PT * 1000.0)), 3),
            "requested_um": round(dy_pt / MM_TO_PT * 1000.0, 1)}


def run_job(job: dict) -> dict:
    """Make the evidence of one job, trace it under every requested context, return summaries."""
    from tapak.decoder.ch_shift import decode_displacements
    from tapak.decoder.trace import collect_file
    from tapak.marker.pdf_shift import ShiftSettings

    t0 = time.perf_counter()
    name, data, meta = make_evidence(job)
    rows = []
    contexts = job.get("contexts") or [[job["variant"], job["n"]]]
    for cvar, cn in contexts:
        ctx, _, _ = context(job["phase"], job["doc"], cn, cvar, job.get("latar", "layar"))
        sub = dict(job, variant=cvar, n=cn)
        sub.pop("contexts", None)
        key = job_key(sub)
        disps: list = []
        with capture_displacements(disps):
            obs, notes = collect_file(name, data, ctx)
        expected = [] if job["kind"].startswith("induk_") else list(job["seqs"])
        x = ctx.codewords[expected[0] - 1] if len(expected) == 1 else None
        if "emit" in job:  # a re-decode: only the listed decode-only variants
            decode_only = [(k, cvar) for k in job["emit"]]
        else:
            decode_only = [(k, v) for k, v in PROTOCOL[job["phase"]].get("decode_only", {}).items() if v == cvar]
            if job["phase"] == "uji":
                _check_production_decoder(cvar)
            rows.append(_summary(sub, key, obs, ctx, x, expected, meta, notes))
            save_obs(key, obs, disps)
        for dname, _ in decode_only:
            dv = variant(dname)
            settings = ShiftSettings(word_mm=dv["word_mm"], row_mm=dv["row_mm"], scheme=dv["scheme"])
            alt = [decode_displacements(ctx.master, ctx.plan, d, settings, ctx.excluded, joint_degree=dv["degree"],
                                        field_degree=dv.get("field")) for d in disps]
            obs2 = alt + [sb for sb in obs if sb.channel != "shift"]
            sub2 = dict(sub, variant=dname)
            rows.append(_summary(sub2, job_key(sub2), obs2, ctx, x, expected, meta, notes))
            save_obs(job_key(sub2), obs2)
        if variant(cvar).get("probe_vshift_mm") and disps and x is not None:
            rows[-1]["probe"] = probe_stats(disps[0], ctx, x, cvar, job.get("page", 1))
    for r in rows:
        r["seconds"] = round(time.perf_counter() - t0, 1)
    return {"rows": rows}


def _check_production_decoder(name: str) -> None:
    """The held-out run decodes with the production decoder: a variant with decoder settings must
    be the one production uses (otherwise the held-out numbers would describe another decoder)."""
    import tapak.decoder.ch_shift as ch
    from tapak.marker.pdf_shift import SCHEME_GROUP_WIDTH

    v = variant(name)
    if "degree" in v and (v["degree"], v.get("field")) != (ch.JOINT_DEGREE, ch.FIELD_DEGREE):
        raise RuntimeError(f"dekoder produksi bukan dekoder varian {name}")
    if "scheme" in v and SCHEME_GROUP_WIDTH[v["scheme"]] != v["min_group_pt"]:
        raise RuntimeError(f"lebar kelompok produksi bukan lebar varian {name}")


def _summary(job: dict, key: str, obs, ctx, x, expected: list[int], meta: dict, notes: list[str]) -> dict:
    reg = next((sb.meta for sb in obs if "correlation" in sb.meta), None)
    row = {k: v for k, v in job.items() if k not in ("contexts",)}
    row.update(key=key, registered=(reg is not None) if job["kind"] not in ("pdf", "induk_pdf") else True,
               eff_dpi=reg.get("effective_dpi") if reg else None, meta=meta,
               channels=channel_stats(obs, ctx, x))
    row.update(verdict_row(obs, ctx, expected) if expected else _unmarked(obs, ctx))
    found = [sb.meta["pattern_found"] for sb in obs if sb.channel == "background" and "pattern_found" in sb.meta]
    if found:
        row["pattern_found"] = bool(any(found))
    return row


def _unmarked(obs, ctx) -> dict:
    from tapak.decoder.trace import run_trace

    a = run_trace(obs, ctx)
    z = a.threshold.threshold
    top = max((c.score for c in a.candidates), default=0.0)
    return {"verdict": "salah" if a.accused else "tidak cukup bukti", "accused": sorted(c.copy.seq for c in a.accused),
            "n_observed": int(a.threshold.n_observed),
            "max_innocent_z": round(top / z, 3) if np.isfinite(z) and z > 0 else None}


# --- job lists ----------------------------------------------------------------------------


def coalitions(k: int, pool: list[int]) -> list[list[int]]:
    rng = np.random.default_rng(PROTOCOL["coalition_seed"])
    return [sorted(int(s) for s in rng.choice(np.array(pool), 3, replace=False)) for _ in range(k)]


def dev_jobs() -> list[dict]:
    g = PROTOCOL["dev"]
    jobs = []
    for name in g["variants"]:
        for n in g["n"]:
            for doc, pages in g["cetak"]:
                for prn, res in g["printers_resolutions"]:
                    for seq in g["copies"]:
                        for page in pages:
                            jobs.append({"phase": "dev", "kind": "cetak", "variant": name, "doc": doc, "n": n,
                                         "printer": prn, "res": res, "seqs": [seq], "page": page})
    pr = g["probe"]
    for prn, res in pr["printers_resolutions"]:
        for seq in g["copies"]:
            for page in pr["pages"]:
                jobs.append({"phase": "dev", "kind": "cetak", "variant": pr["variant"], "doc": pr["doc"], "n": 100,
                             "printer": prn, "res": res, "seqs": [seq], "page": page})
    for name in g["layar_foto_pdf"]["variants"]:
        for doc in DOCS:
            for seq in g["layar_foto_pdf"]["copies"]:
                for kind in ("pdf", "layar", "foto"):
                    jobs.append({"phase": "dev", "kind": kind, "variant": name, "doc": doc, "n": 100, "seqs": [seq]})
    return jobs


def uji_jobs(cand: str) -> list[dict]:
    g = PROTOCOL["uji"]
    names = ["v1", cand]
    jobs = []
    for name in names:
        for prn, res, ns, copies in g["cetak_cells"]:
            for n in ns:
                for doc, pages in g["cetak"]:
                    for seq in copies:
                        for page in pages:
                            jobs.append({"phase": "uji", "kind": "cetak", "variant": name, "doc": doc, "n": n,
                                         "printer": prn, "res": res, "seqs": [seq], "page": page})
        for n in g["n"]:
            for doc in DOCS:
                for seq in g["layar_foto_pdf"]["copies"]:
                    for kind in ("pdf", "layar", "foto"):
                        jobs.append({"phase": "uji", "kind": kind, "variant": name, "doc": doc, "n": n, "seqs": [seq]})
        k = g["kolusi"]
        for coal in coalitions(k["coalitions"], k["from_copies"]):
            for doc in DOCS:
                for prn, res in k["printers_resolutions"]:
                    for page in k["pages"][doc]:
                        jobs.append({"phase": "uji", "kind": "kolusi", "variant": name, "doc": doc, "n": k["n"],
                                     "printer": prn, "res": res, "seqs": coal, "page": page})
        lc = g["latar_cetak"]
        base = {"phase": "uji", "variant": name, "doc": lc["doc"], "n": lc["n"], "latar": "cetak"}
        for res, pages in lc["laser"]:
            for seq in lc["copies"]:
                for page in pages:
                    jobs.append(dict(base, kind="cetak", printer="laser", res=res, seqs=[seq], page=page))
        for res, pages in lc["inkjet"]:
            for seq in lc["copies"]:
                for page in pages:
                    jobs.append(dict(base, kind="cetak", printer="inkjet", res=res, seqs=[seq], page=page))
        for coal in coalitions(lc["kolusi"]["coalitions"], k["from_copies"]):
            for page in lc["kolusi"]["pages"]:
                jobs.append(dict(base, kind="kolusi", printer="laser", res=lc["kolusi"]["resolution"], seqs=coal,
                                 page=page))
    ind = g["induk"]
    contexts = [[name, n] for name in names for n in g["n"]]
    for doc in DOCS:
        base = {"phase": "uji", "variant": "v1", "doc": doc, "n": 20, "contexts": contexts}
        jobs.append(dict(base, kind="induk_pdf", seqs=[0]))
        jobs += [dict(base, kind="induk_layar", seqs=[0], rep=r) for r in range(ind["layar"])]
        jobs += [dict(base, kind="induk_foto", seqs=[0], rep=r) for r in range(ind["foto"])]
        for prn, res in ind["printers_resolutions"]:
            for page in ind["cetak_pages"]:
                jobs.append(dict(base, kind="induk_cetak", printer=prn, res=res, seqs=[0], page=page))
    return jobs


def ensure_issuances(jobs: list[dict]) -> None:
    need = set()
    for j in jobs:
        for cvar, cn in j.get("contexts") or [[j["variant"], j["n"]]]:
            need.add((j["phase"], j["doc"], cn, issued_name(cvar), j.get("latar", "layar")))
    for phase, doc, n, name, latar in sorted(need):
        issue_variant(phase, doc, n, name, latar)


def run_jobs(jobs: list[dict], out: Path) -> None:
    """Run the jobs not yet in ``out`` (JSON lines, appended as results come in)."""
    import multiprocessing as mp

    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["job"])
    todo = [j for j in jobs if job_key(j) not in done]
    print(f"{len(todo)} dari {len(jobs)} pekerjaan belum dijalankan", flush=True)
    ensure_issuances(todo)
    t0 = time.perf_counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        futs = {pool.submit(run_job, j): j for j in todo}
        for k, f in enumerate(as_completed(futs), 1):
            j = futs[f]
            try:
                res = f.result()
            except Exception:  # noqa: BLE001 - report and continue with the other jobs
                print(f"GAGAL {job_key(j)}\n{traceback.format_exc()}", flush=True)
                continue
            with out.open("a", encoding="utf-8") as fh:
                for r in res["rows"]:
                    fh.write(json.dumps(dict(r, job=job_key(j)), ensure_ascii=False) + "\n")
            r0 = res["rows"][0]
            print(f"[{k}/{len(todo)} {time.perf_counter() - t0:.0f} s] {job_key(j)} {r0['verdict']} "
                  f"{r0.get('channels')} {r0.get('seconds')} s", flush=True)


def write_protocol(phase: str, extra: dict | None = None) -> None:
    HASIL.mkdir(parents=True, exist_ok=True)
    path = HASIL / f"protokol_{phase}.json"
    path.write_text(json.dumps(dict(PROTOCOL, phase=phase, **(extra or {})), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dev")
    sub.add_parser("dev-veld")
    u = sub.add_parser("uji")
    u.add_argument("--kandidat", required=True, choices=["v2", "v2q", "v1c", "v2c", "v2cq", "v2f", "v2cf"])
    r = sub.add_parser("ringkas")
    r.add_argument("phase", choices=["dev", "uji"])
    sub.add_parser("visibilitas")
    args = ap.parse_args()
    if args.cmd == "dev":
        write_protocol("dev")
        run_jobs(dev_jobs(), HASIL / "dev.jsonl")
    elif args.cmd == "dev-veld":
        emit = PROTOCOL["dev"]["veld"]["emit"]
        jobs = [dict(j, emit=emit[j["variant"]]) for j in dev_jobs() if j["kind"] == "cetak" and j["variant"] in emit]
        run_jobs(jobs, HASIL / "dev_veld.jsonl")
    elif args.cmd == "uji":
        write_protocol("uji", {"kandidat": args.kandidat})
        run_jobs(uji_jobs(args.kandidat), HASIL / "uji.jsonl")
    elif args.cmd == "ringkas":
        from ringkas import summarize  # research/kapasitas/ringkas.py

        summarize(args.phase)
    else:
        from visibilitas import run  # research/kapasitas/visibilitas.py

        run()


if __name__ == "__main__":
    main()
