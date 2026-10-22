"""Geometric cues and crops for the visibility gate (``python research/kapasitas/ukur.py visibilitas``).

From the glyph origins of the issued development copies (vector, exact) this measures, per
scheme, every cue a reader could use: how far a glyph moves from the master and between two
copies (per axis), how much a word gap changes, the left/right gap asymmetry around a word, and
the vertical step between neighbouring words on one baseline. It also writes the visual angles
at 35 cm and crops of master and copy at 100 % (600 dpi, a printer's resolution) and 4x, plus the
600 dpi raster of the printer simulator for the scheme a probe, where a requested 0.01 mm
vertical offset either vanishes or becomes a whole scan line. Output:
``hasil/visibilitas.jsonl`` and ``potongan/``.
"""

from __future__ import annotations

import json
import math

import numpy as np

import ukur

ARCSEC_PER_MM = 3600.0 * math.degrees(math.atan(1.0 / 350.0))  # at 35 cm


def _origins(pdf: bytes):
    from tapak.marker.layout import extract_layout

    return extract_layout(pdf)


def _cues(master_layout, copies: list) -> dict:
    """Largest cues over all copies (mm): per-glyph displacement per axis, between-copy
    displacement per axis, word gap change, gap asymmetry around a word, vertical step between
    neighbouring words of a row."""
    from tapak.decoder.ch_shift import PageFrame, match_words

    mm = 25.4 / 72.0
    per_copy = []
    out = {"glyph_dx": 0.0, "glyph_dy": 0.0, "gap_change": 0.0, "asymmetry": 0.0, "baseline_step": 0.0,
           "gaps_changed_share": 0.0}
    changed = total = 0
    for layout in copies:
        # Glyph origins against the master as drawn (no fitted page frame: a copy is never scaled).
        disp = match_words(master_layout, layout, {i: PageFrame(i) for i in range(len(master_layout.pages))})
        per_copy.append(disp)
        for row in master_layout.rows():
            words = [w for w in row.words if w.id in disp]
            for w in words:
                out["glyph_dx"] = max(out["glyph_dx"], abs(disp[w.id][0]) * mm)
                out["glyph_dy"] = max(out["glyph_dy"], abs(disp[w.id][1]) * mm)
            for a, b, c in zip(words, words[1:], words[2:]):
                left = (disp[b.id][0] - disp[a.id][0]) * mm
                right = (disp[c.id][0] - disp[b.id][0]) * mm
                out["asymmetry"] = max(out["asymmetry"], abs(left - right))
            for a, b in zip(words, words[1:]):
                g = abs(disp[b.id][0] - disp[a.id][0]) * mm
                out["gap_change"] = max(out["gap_change"], g)
                out["baseline_step"] = max(out["baseline_step"], abs(disp[b.id][1] - disp[a.id][1]) * mm)
                total += 1
                changed += g > 1e-4
    between = {"dx": 0.0, "dy": 0.0}
    for i in range(len(per_copy)):
        for j in range(i + 1, len(per_copy)):
            for wid, (dx, dy) in per_copy[i].items():
                if wid in per_copy[j]:
                    between["dx"] = max(between["dx"], abs(dx - per_copy[j][wid][0]) * mm)
                    between["dy"] = max(between["dy"], abs(dy - per_copy[j][wid][1]) * mm)
    out.update(between_dx=between["dx"], between_dy=between["dy"], gaps_changed_share=changed / max(total, 1))
    out = {k: round(v, 4) for k, v in out.items()}
    out.update({f"{k}_arcsec": round(out[k] * ARCSEC_PER_MM, 1) for k in ("gap_change", "asymmetry", "baseline_step",
                                                                         "between_dx", "between_dy")})
    return out


def _crop_png(path, img: np.ndarray) -> None:
    import cv2

    cv2.imwrite(str(path), img)


def _crops(doc: str, name: str, seq: int, row_index: int, label: str, raster: bool = False) -> list[str]:
    """Master and copy crops of one row (600 dpi PDF render, or the printer simulator's 600 dpi
    raster with ``raster``) at 100 % and a 4x enlargement of its middle third."""
    import cv2

    from tapak.marker.render import render_pages
    from tapak.photos import print_layers

    ctx, _, _ = ukur.context("dev", doc, 100, name)
    copy = ukur.copy_pdf("dev", doc, 100, name, seq)
    master = (ukur.ROOT / "samples" / f"{doc}.pdf").read_bytes()
    row = ctx.master.layout.pages[0].rows[row_index]
    dpi = 600
    s = dpi / 72.0
    x0, y0, x1, y1 = row.bbox
    box = (int(x0 * s) - 20, int(y0 * s) - 25, int(x1 * s) + 20, int(y1 * s) + 25)
    files = []
    crops = {}
    for who, pdf in (("induk", master), ("salinan", copy)):
        if raster:
            cov, _ = print_layers(pdf, 0, dpi)
            img = (255 - 255 * (cov >= 0.5)).astype(np.uint8)
        else:
            img = render_pages(pdf, dpi, [0])[0]
        crop = img[box[1]:box[3], box[0]:box[2]]
        crops[who] = crop
        f = ukur.POTONGAN / f"{label}_{who}.png"
        _crop_png(f, crop)
        w = crop.shape[1]
        mid = crop[:, w // 3: 2 * w // 3]
        big = cv2.resize(mid, (mid.shape[1] * 4, mid.shape[0] * 4), interpolation=cv2.INTER_NEAREST)
        f4 = ukur.POTONGAN / f"{label}_{who}_perbesar4x.png"
        _crop_png(f4, big)
        files += [f.name, f4.name]
    # Where the copy differs from the master: white paper, black where only the master has ink,
    # gray where only the copy has ink (ink differences beyond 16 gray levels).
    a, b = crops["induk"].astype(int), crops["salinan"].astype(int)
    diff = np.full(a.shape, 255, np.uint8)
    diff[(b - a) > 16] = 0
    diff[(a - b) > 16] = 150
    f = ukur.POTONGAN / f"{label}_selisih.png"
    _crop_png(f, diff)
    files.append(f.name)
    return files


def run() -> None:
    ukur.POTONGAN.mkdir(parents=True, exist_ok=True)
    rows = []
    for doc in ukur.DOCS:
        master_layout = _origins((ukur.ROOT / "samples" / f"{doc}.pdf").read_bytes())
        for name in ("v1", "v2", "v1c", "v2c", "a010"):
            ukur.issue_variant("dev", doc, 100, name)
            copies = [_origins(ukur.copy_pdf("dev", doc, 100, name, s)) for s in range(1, 9)]
            rows.append({"doc": doc, "variant": name, "copies": 8, **_cues(master_layout, copies)})
            print(rows[-1], flush=True)
    angles = {f"{mm} mm": round(mm * ARCSEC_PER_MM, 1) for mm in (0.01, 0.0212, 0.025, 0.0423, 0.05, 0.10, 1.29, 1.85)}
    rows.append({"sudut_pandang_35cm_detik_busur": angles,
                 "ambang_vernier_1_60_detik_busur": {"celah 1,29 mm": round(1.29 * ARCSEC_PER_MM / 60.0, 1),
                                                     "celah 1,85 mm": round(1.85 * ARCSEC_PER_MM / 60.0, 1)},
                 "ambang_vernier_dua_titik_detik_busur": {
                     "celah 1,29 mm": [round(1.29 * ARCSEC_PER_MM * f, 1) for f in (0.0275, 0.0376)],
                     "celah 1,85 mm": [round(1.85 * ARCSEC_PER_MM * f, 1) for f in (0.0275, 0.0376)]}})
    files = []
    files += _crops("nota_dinas", "v2", 1, 20, "v2_kata")
    files += _crops("nota_dinas", "v1", 1, 20, "v1_kata")
    files += _crops("nota_dinas", "a010", 1, 20, "a010_vertikal_pdf")
    files += _crops("nota_dinas", "a010", 1, 20, "a010_vertikal_raster600", raster=True)
    rows.append({"potongan": files})
    (ukur.HASIL / "visibilitas.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                  encoding="utf-8")
