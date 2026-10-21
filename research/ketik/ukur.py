"""Measurements behind the word-choice (lexical) channel numbers in docs/cara-kerja.md.

Three parts. Every random choice (code secrets, copy ids, noise) comes from a seeded
``random.Random`` and the synthetic PDFs are saved without /ID (``fixed_id``), so each line is
reproduced exactly; the lines quoted in the docs are committed in ``research/ketik/hasil/``:

* ``kapasitas``: points, bits and body words of the sample PDFs and of long synthetic
  documents (the body paragraphs of both sample templates repeated R times, typeset by
  ``tapak.samplegen``), with the default lexicon, tier A, guard policy "lokal". Because the
  paragraphs repeat, every point of R >= 2 has a repeated context (``LexPoint.repeated``);
  the numbers below hold for a leak that keeps the sentence order;
* ``galat``: bits read and wrong after simulated retyping (``tapak.ketik``), K copies per
  document and noise level, each copy with a fresh code secret (new bias, positions and
  whitening), band positions as issued;
* ``atribusi``: lone-leaker attribution end to end on the text: the leaked copy's text is
  retyped at level "sedang", read by ``decode_lexical`` and decided by the real
  ``fuse`` + ``attribute`` (Chernoff threshold from the bias vector and the decoder
  weights only), with the budget of the first trace logged in the registry
  (``--pelacakan-ke 1``, 61 % of eps; 0 = a trace that is not logged, all of eps). Only
  lexical bits are used (no semantic bits), so this is conservative.

Usage (from the repository root):

    python research/ketik/ukur.py kapasitas > research/ketik/hasil/kapasitas.jsonl
    python research/ketik/ukur.py galat 500 > research/ketik/hasil/galat.jsonl
    python research/ketik/ukur.py atribusi 200 [--workers 4] > research/ketik/hasil/atribusi.jsonl

Results are printed as JSON lines.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def fixed_id(pdf: bytes) -> bytes:
    """The PDF saved again without its /ID.

    MuPDF writes a new random /ID (of varying length) on every render, which would give every
    run a different document hash, hence a different bias vector, positions and codewords.
    """
    import pymupdf

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    doc.xref_set_key(-1, "ID", "null")
    return doc.tobytes(garbage=3, deflate=True, no_new_id=True)


@lru_cache(maxsize=None)
def document(name: str):
    """(master, selection with every point approved) for a sample or a long synthetic document."""
    from tapak.marker.lexical import scan_candidates
    from tapak.marker.master import load_master
    from tapak.marker.semantic import STATUS_APPROVED

    if name.startswith("R"):
        from tapak.samplegen import load_template, render_template

        nota = load_template(ROOT / "samples" / "templates" / "nota_dinas.json")
        tele = load_template(ROOT / "samples" / "templates" / "surat_telegram.json")
        template = dict(nota)
        template["isi"] = (nota["isi"] + tele["isi"]) * int(name[1:])
        master = load_master(fixed_id(render_template(template)))
    else:
        master = load_master((ROOT / "samples" / f"{name}.pdf").read_bytes())
    sel = scan_candidates(master)
    for p in sel.points:
        sel.set_status(p.point_id, STATUS_APPROVED)
    return master, sel


def kapasitas(names: list[str]) -> None:
    """Points, bits and body words per document."""
    for name in names:
        master, sel = document(name)
        print(json.dumps({"bagian": "kapasitas", "dokumen": name, "halaman": len(master.layout.pages),
                          "kata_isi": sel.body_words, "titik": len(sel.points), "bit": sel.bits,
                          "titik_konteks_berulang": sum(p.repeated for p in sel.points),
                          "bit_per_100_kata": round(100 * sel.bits / max(sel.body_words, 1), 2),
                          "ditolak": sel.refused}), flush=True)


def _plan(master, sel, secret: bytes, n: int):
    from tapak.marker.lexical import lexical_slots
    from tapak.marker.plan import RETYPE_BAND, plan_key
    from tapak.tardos.code import derive_bias
    from tapak.tardos.params import TardosParams

    params = TardosParams(c=3, eps=1e-6, n_max=n)
    p = derive_bias(secret, master.doc_hash, params)
    slots = lexical_slots(sel, params.length, plan_key(secret, master.doc_hash), p, RETYPE_BAND)
    return params, p, slots


def galat_job(job: tuple[str, str, float, int, int]) -> dict[str, object]:
    """Bits read and wrong for ``copies`` copies of one document at one noise level."""
    from tapak.decoder.ch_lexical import LexReference, decode_lexical
    from tapak.ketik import apply_habit, retype
    from tapak.marker.lexical import choices_for_codeword, copy_text
    from tapak.tardos.code import derive_codeword

    name, level, habit, copies, seed = job
    master, sel = document(name)
    ref = LexReference(master, sel.carrying())
    rng = random.Random(f"galat|{name}|{level}|{habit}|{seed}")
    total = read = wrong = 0
    for k in range(copies):
        secret = rng.randbytes(32)
        params, p, slots = _plan(master, sel, secret, 20)
        x = derive_codeword(secret, master.doc_hash, f"salinan{k}", p)
        choice = choices_for_codeword(slots, x, sel.points)
        text = copy_text(master, sel.carrying(), apply_habit(choice, rng, habit) if habit else choice)
        leaked = text if level == "bersih" else retype(text, rng, level)
        sb = decode_lexical(leaked, ref, sel.points, slots)
        total += sum(len(s.positions) for s in slots)
        read += len(sb)
        wrong += int(np.sum((sb.llr > 0).astype(int) != x[sb.positions]))
    return {"bagian": "galat", "dokumen": name, "tingkat": level, "kebiasaan": habit, "salinan": copies,
            "bit_total": total, "bit_terbaca": read, "bit_salah": wrong,
            "terhapus": round(1 - read / total, 4), "salah_dari_terbaca": round(wrong / max(read, 1), 4)}


def atribusi_job(job: tuple[str, int, int, int, int]) -> dict[str, object]:
    """Lone-leaker trials on one document: named, false accusations, score over Z."""
    from tapak.decoder.accuse import CopyRef, attribute
    from tapak.decoder.ch_lexical import LexReference, decode_lexical
    from tapak.decoder.fuse import fuse, fuse_by_physical_channel
    from tapak.ketik import retype
    from tapak.marker.lexical import choices_for_codeword, copy_text
    from tapak.tardos.code import derive_codeword
    from tapak.tardos.spending import TraceSpending

    name, n, trials, seed, trace_no = job
    master, sel = document(name)
    ref = LexReference(master, sel.carrying())
    rng = random.Random(f"atribusi|{name}|{n}|{seed}")
    named = false = 0
    ratios, observed = [], []
    t0 = time.perf_counter()
    for _ in range(trials):
        secret = rng.randbytes(32)
        params, p, slots = _plan(master, sel, secret, n)
        ids = [rng.randbytes(8).hex() for _ in range(n)]
        x = np.vstack([derive_codeword(secret, master.doc_hash, cid, p) for cid in ids])
        leak = rng.randrange(n)
        text = retype(copy_text(master, sel.carrying(), choices_for_codeword(slots, x[leak], sel.points)), rng)
        sb = decode_lexical(text, ref, sel.points, slots)
        refs = [CopyRef(j + 1, ids[j], f"R{j + 1:03d}", f"Penerima {j + 1}") for j in range(n)]
        spending = TraceSpending.logged(params.eps, trace_no) if trace_no else None
        att = attribute(fuse([sb], params.length), fuse_by_physical_channel([sb], params.length), p, x, refs, params,
                        spending)
        accused = {c.copy.seq - 1 for c in att.accused}
        named += leak in accused
        false += len(accused - {leak})
        z = att.threshold.threshold
        top = next(c for c in att.candidates if c.copy.seq - 1 == leak)
        ratios.append(top.score / z if np.isfinite(z) else 0.0)
        observed.append(att.threshold.n_observed)
    return {"bagian": "atribusi", "dokumen": name, "N": n, "pelacakan_ke": trace_no, "percobaan": trials,
            "bit": sel.bits,
            "kata_isi": sel.body_words, "halaman": len(master.layout.pages),
            "median_bit_terbaca": float(np.median(observed)), "tersebut_benar": named, "tuduhan_salah": false,
            "median_skor_per_Z": round(float(np.median(ratios)), 3), "detik": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["kapasitas", "galat", "atribusi"])
    ap.add_argument("jumlah", type=int, nargs="?", default=200, help="salinan (galat) atau percobaan (atribusi)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pelacakan-ke", type=int, default=1, help="nomor pelacakan tercatat (0: tidak dicatat)")
    args = ap.parse_args()
    if args.bagian == "kapasitas":
        kapasitas(["nota_dinas", "surat_telegram", "R1", "R2", "R3", "R4", "R5", "R6"])
        return
    if args.bagian == "galat":
        jobs = [(doc, level, 0.0, args.jumlah, 1) for doc in ("nota_dinas", "surat_telegram", "R3")
                for level in ("bersih", "ringan", "sedang", "berat", "ocr")]
        jobs += [(doc, "sedang", 0.05, args.jumlah, 1) for doc in ("nota_dinas", "surat_telegram", "R3")]
        fn = galat_job
    else:
        jobs = [(doc, n, args.jumlah, 1, args.pelacakan_ke) for doc in ("nota_dinas", "R2", "R3", "R4", "R5")
                for n in (20, 100)]
        fn = atribusi_job
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(fn, jobs):
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
