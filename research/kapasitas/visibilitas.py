"""Geometric cues and crops for the visibility gate (``python research/kapasitas/ukur.py visibilitas``).

From the glyph origins of the issued development copies (vector, exact) this measures, per
scheme, every cue a reader could use: how far a glyph moves from the master and between two
copies (per axis), how much a word gap changes, the left/right gap asymmetry around a word, and
the vertical step between neighbouring words on one baseline. Added in review (2026-10-22, after
the held-out run, so it did not take part in any choice): the cross-row alignment cues, i.e.
how far the left edges (first word) and right edges (last word) of two consecutive rows that
share a margin in the master move apart, and the same for interior words that share an x with
a word of the next row (tab stops, such as the colon column of a letter head). geser-v1 never
moves the first or last group of a row, so its margins stay exact; geser-v2 moves them. It also
writes the visual angles
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
           "gaps_changed_share": 0.0, "left_edge_step": 0.0, "right_edge_step": 0.0, "tab_step": 0.0}
    changed = total = 0
    edge_moved = edge_total = 0
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
        # Cross-row alignment: rows that share a left margin, a right edge or a tab stop in the master.
        for page in master_layout.pages:
            rows = [r for r in page.rows if r.words]
            for a, b in zip(rows, rows[1:]):
                pairs = [("left_edge_step", a.words[0], b.words[0], abs(a.words[0].x0 - b.words[0].x0)),
                         ("right_edge_step", a.words[-1], b.words[-1], abs(a.words[-1].x1 - b.words[-1].x1))]
                pairs += [("tab_step", u, v, abs(u.x0 - v.x0)) for u in a.words[1:-1] for v in b.words[1:-1]]
                for key, u, v, gap in pairs:
                    if gap < 0.3 and u.id in disp and v.id in disp:
                        step = abs(disp[u.id][0] - disp[v.id][0]) * mm
                        out[key] = max(out[key], step)
                        if key != "tab_step":
                            edge_total += 1
                            edge_moved += step > 1e-4
    between = {"dx": 0.0, "dy": 0.0}
    for i in range(len(per_copy)):
        for j in range(i + 1, len(per_copy)):
            for wid, (dx, dy) in per_copy[i].items():
                if wid in per_copy[j]:
                    between["dx"] = max(between["dx"], abs(dx - per_copy[j][wid][0]) * mm)
                    between["dy"] = max(between["dy"], abs(dy - per_copy[j][wid][1]) * mm)
    out.update(between_dx=between["dx"], between_dy=between["dy"], gaps_changed_share=changed / max(total, 1),
               edges_moved_share=edge_moved / max(edge_total, 1))
    out = {k: round(v, 4) for k, v in out.items()}
    out.update({f"{k}_arcsec": round(out[k] * ARCSEC_PER_MM, 1) for k in ("gap_change", "asymmetry", "baseline_step",
                                                                         "between_dx", "between_dy", "left_edge_step",
                                                                         "right_edge_step", "tab_step")})
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


def _margin_crops(doc: str, name: str, seq: int, rows: range, label: str) -> list[str]:
    """Master and copy crops of the left text edge of ``rows`` (page 1, 600 dpi PDF render) at
    100 % and 4x (upper rows), plus the difference image: where geser-v2 moves the first group of a row."""
    import cv2

    from tapak.marker.render import render_pages

    ctx, _, _ = ukur.context("dev", doc, 100, name)
    copy = ukur.copy_pdf("dev", doc, 100, name, seq)
    master = (ukur.ROOT / "samples" / f"{doc}.pdf").read_bytes()
    page_rows = [ctx.master.layout.pages[0].rows[i] for i in rows]
    s = 600 / 72.0
    x0 = min(r.bbox[0] for r in page_rows)
    y0, y1 = min(r.bbox[1] for r in page_rows), max(r.bbox[3] for r in page_rows)
    box = (int(x0 * s) - 30, int(y0 * s) - 20, int(x0 * s) + 420, int(y1 * s) + 20)
    crops, files = {}, []
    for who, pdf in (("induk", master), ("salinan", copy)):
        crop = render_pages(pdf, 600, [0])[0][box[1]:box[3], box[0]:box[2]]
        crops[who] = crop
        f = ukur.POTONGAN / f"{label}_{who}.png"
        _crop_png(f, crop)
        top = crop[: crop.shape[0] * 2 // 5]  # 4x of the upper rows only (paragraph 1 and its label)
        f4 = ukur.POTONGAN / f"{label}_{who}_perbesar4x.png"
        _crop_png(f4, cv2.resize(top, (top.shape[1] * 4, top.shape[0] * 4), interpolation=cv2.INTER_NEAREST))
        files += [f.name, f4.name]
    a, b = crops["induk"].astype(int), crops["salinan"].astype(int)
    diff = np.full(a.shape, 255, np.uint8)
    diff[(b - a) > 16] = 0
    diff[(a - b) > 16] = 150
    f = ukur.POTONGAN / f"{label}_selisih.png"
    _crop_png(f, diff)
    return files + [f.name]


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
                     "celah 1,85 mm": [round(1.85 * ARCSEC_PER_MM * f, 1) for f in (0.0275, 0.0376)]},
                 # Left/right text edge: the letters of two consecutive rows are a pitch (15.87 pt,
                 # 5.6 mm) minus a letter height apart: cap height 2.96 mm, x-height 2.2 mm (DejaVu
                 # Sans 11.5 pt), so 2.6 to 3.4 mm.
                 "ambang_vernier_1_60_tepi_baris_detik_busur": {
                     "celah 2,6 mm": round(2.6 * ARCSEC_PER_MM / 60.0, 1),
                     "celah 3,4 mm": round(3.4 * ARCSEC_PER_MM / 60.0, 1)}})
    files = []
    files += _crops("nota_dinas", "v2c", 1, 20, "v2_kata")
    files += _crops("nota_dinas", "v1", 1, 20, "v1_kata")
    files += _crops("nota_dinas", "a010", 1, 20, "a010_vertikal_pdf")
    files += _crops("nota_dinas", "a010", 1, 20, "a010_vertikal_raster600", raster=True)
    files += _margin_crops("nota_dinas", "v2c", 1, range(14, 26), "v2_tepi_kiri")
    files += _margin_crops("nota_dinas", "v1", 1, range(14, 26), "v1_tepi_kiri")
    rows.append({"potongan": files})
    (ukur.HASIL / "visibilitas.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                  encoding="utf-8")
