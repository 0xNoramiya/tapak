"""Tables of research/kapasitas (``python research/kapasitas/ukur.py ringkas dev|uji``).

Reads the summary rows of one phase, adds the traces made of two pieces of evidence (pages 1
and 2 of the same printed copy, or of the same printed coalition page set) by fusing the saved
observations, and writes ``hasil/ringkas_<phase>.json`` plus the two-page rows
``hasil/<phase>_dua_halaman.jsonl``. The candidate choice (dev) and the default decision (uji)
follow the rules fixed in ``PROTOCOL``.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np

import ukur

SUB = ("kata", "baris", "latar")


def _rows(phase: str) -> list[dict]:
    """Summary rows of a phase, with the dev re-decode (``dev_veld.jsonl``) for dev."""
    rows = []
    for name in (f"{phase}.jsonl", f"{phase}_veld.jsonl"):
        path = ukur.HASIL / name
        if path.exists():
            rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def _count(rows: list[dict]) -> dict[str, int]:
    out = {"benar": 0, "tidak cukup bukti": 0, "salah": 0}
    for r in rows:
        out[r["verdict"]] += 1
    return out


def _pages_table(rows: list[dict]) -> dict:
    """Per page: median positions read and pooled bit error per sub-channel."""
    out = {}
    for page in sorted({r.get("page", 1) for r in rows}):
        sel = [r for r in rows if r.get("page", 1) == page]
        d = {"photos": len(sel), "registered": sum(1 for r in sel if r["registered"])}
        for s in SUB:
            reads = [r["channels"].get(s, {}).get("read", 0) for r in sel]
            errs = sum(r["channels"].get(s, {}).get("errors", 0) for r in sel)
            if sum(reads):
                d[s] = {"read_median": float(np.median(reads)), "ber": round(errs / sum(reads), 4)}
        d["positions_median"] = float(np.median([r["n_observed"] for r in sel]))
        out[f"hal{page}"] = d
    return out


def _score(rows: list[dict]) -> float | None:
    vals = [r["score_z"][0] for r in rows if r.get("score_z")]
    return round(float(np.median(vals)), 3) if vals else None


def _two_page(phase: str, rows: list[dict], out_rows: list[dict]) -> dict:
    """Fuse pages 1 and 2 of the same copy (or coalition), same variant, code, printer and
    resolution, and accuse once."""
    by: dict[tuple, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        by[(r["variant"], r["doc"], r["n"], r.get("latar", "-"), r.get("printer"), r.get("res"),
            tuple(r["seqs"]))][r.get("page", 1)] = r
    results: dict[tuple, list[dict]] = defaultdict(list)
    for key, pages in sorted(by.items(), key=lambda kv: str(kv[0])):
        if 1 not in pages or 2 not in pages:
            continue
        name, doc, n, latar, prn, res, seqs = key
        ctx, _, _ = ukur.context(phase, doc, n, name, "layar" if latar == "-" else latar)
        obs = ukur.load_obs(pages[1]["key"]) + ukur.load_obs(pages[2]["key"])
        row = ukur.verdict_row(obs, ctx, list(seqs))
        row.update(variant=name, doc=doc, n=n, latar=latar, printer=prn, res=res, seqs=list(seqs),
                   kind=pages[1]["kind"], pages=[1, 2])
        out_rows.append(row)
        results[(name, doc, n, latar, prn, res)].append(row)
    return results


def _mcnemar(pairs: list[tuple[bool, bool]]) -> dict:
    """Exact one-sided sign test on paired outcomes (old correct, new correct)."""
    b = sum(1 for o, n in pairs if not o and n)  # new right, old wrong
    c = sum(1 for o, n in pairs if o and not n)
    k = b + c
    p = sum(math.comb(k, i) for i in range(b, k + 1)) / 2 ** k if k else 1.0
    return {"pairs": len(pairs), "baru_saja_benar": b, "lama_saja_benar": c, "p_satu_sisi": p}


def _members(rows: list[dict]) -> dict:
    """c = 3 composites: pages with at least one colluder named, all three, members named,
    and innocents accused."""
    d = {"pages": len(rows), "min1": 0, "all3": 0, "members": 0, "innocent_pages": 0}
    for r in rows:
        named = set(r["accused"]) & set(r["seqs"])
        d["min1"] += bool(named)
        d["all3"] += len(named) == 3
        d["members"] += len(named)
        d["innocent_pages"] += bool(set(r["accused"]) - set(r["seqs"]))
    return d


def _per_printer(cetak: list[dict], two_rows: list[dict]) -> dict:
    """Default background, all documents and code sizes together, per variant, printer and
    resolution: one-page and two-page verdicts, positions read (median per page kind) and
    pooled bit error per sub-channel."""
    out = {}
    keys = sorted({(r["variant"], r["printer"], r["res"]) for r in cetak if r.get("latar", "-") == "-"}, key=str)
    for name, prn, res in keys:
        sel = [r for r in cetak if (r["variant"], r["printer"], r["res"]) == (name, prn, res) and r.get("latar", "-") == "-"]
        two = [r for r in two_rows if (r["variant"], r.get("printer"), r.get("res")) == (name, prn, res)
               and r.get("latar", "-") == "-" and r["kind"] == "cetak"]
        d = {"satu_halaman": _count(sel), "dua_halaman": _count(two), "skor_z_median": _score(sel)}
        for s in SUB:
            reads = sum(r["channels"].get(s, {}).get("read", 0) for r in sel)
            errs = sum(r["channels"].get(s, {}).get("errors", 0) for r in sel)
            if reads:
                d[f"ber_{s}"] = round(errs / reads, 4)
        for doc in sorted({r["doc"] for r in sel}):
            for page in (1, 2):
                vals = [r["n_observed"] for r in sel if r["doc"] == doc and r.get("page") == page]
                if vals:
                    d[f"posisi_{doc}_hal{page}"] = float(np.median(vals))
        out[f"{name}/{prn}/{res}"] = d
    return out


def _decision(out: dict, cetak: list[dict]) -> dict:
    """The default decision rule of PROTOCOL, criteria (2) to (4); (1) is the visibility gate."""
    names = [n for n in out["total_cetak"] if n != "v1"]
    if not names:
        return {}
    cand = names[0]
    kinds = out["layar_pdf_total"]
    no_regress = {k: kinds[k].get(cand, {}).get("benar", 0) >= kinds[k].get("v1", {}).get("benar", 0) for k in kinds}
    one_old = out["total_cetak"]["v1"]["satu_halaman"]
    one_new = out["total_cetak"][cand]["satu_halaman"]
    n_old, n_new = sum(one_old.values()), sum(one_new.values())
    diff_pp = 100.0 * (one_new["benar"] / max(n_new, 1) - one_old["benar"] / max(n_old, 1))
    test = out["banding_v1"].get(cand, {})
    induk_wrong = sum(v["dituduh"] for v in out["induk"].values())
    return {"kandidat": cand, "tidak_mundur_per_jenis": no_regress, "tuduhan_salah": out["salah_total"] + induk_wrong,
            "satu_halaman_lama": f"{one_old['benar']}/{n_old}", "satu_halaman_baru": f"{one_new['benar']}/{n_new}",
            "selisih_poin_persen": round(diff_pp, 1), "mcnemar_p": test.get("p_satu_sisi"),
            "lolos_2": all(no_regress.values()), "lolos_3": out["salah_total"] + induk_wrong == 0,
            "lolos_4": diff_pp >= 10.0 and (test.get("p_satu_sisi") or 1.0) < 0.01}


def summarize(phase: str) -> dict:
    rows = _rows(phase)
    out: dict = {"phase": phase, "rows": len(rows)}
    two_rows: list[dict] = []
    cetak = [r for r in rows if r["kind"] == "cetak"]
    two = _two_page(phase, cetak, two_rows)
    cells: dict = {}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in cetak:
        groups[(r["variant"], r["doc"], r["n"], r.get("latar", "-"), r["printer"], r["res"])].append(r)
    for key, sel in sorted(groups.items(), key=lambda kv: str(kv[0])):
        name = "/".join(str(k) for k in key)
        cells[name] = {"pages": _pages_table(sel), "satu_halaman": _count(sel), "skor_z_median": _score(sel),
                       "max_tak_bersalah_z": max((r["max_innocent_z"] or 0) for r in sel),
                       "dua_halaman": _count(two.get(key, [])), "dua_halaman_skor_z": _score(two.get(key, []))}
        if "probe" in sel[0]:
            pr = [r["probe"] for r in sel if r.get("probe", {}).get("read")]
            reads = sum(p["read"] for p in pr)
            cells[name]["probe"] = {"read": reads, "ber": round(sum(p["errors"] for p in pr) / max(reads, 1), 3),
                                    "share_below_half": round(float(np.mean([p["share_below_half_um"] for p in pr])), 3),
                                    "median_abs_um": float(np.median([p["median_abs_um"] for p in pr]))}
    out["cetak"] = cells
    # Totals per variant (default background only), for the choice and decision rules.
    totals: dict = {}
    for name in sorted({r["variant"] for r in cetak}):
        sel = [r for r in cetak if r["variant"] == name and r.get("latar", "-") == "-"]
        sel2 = [r for r in two_rows if r["variant"] == name and r.get("latar", "-") == "-" and r["kind"] == "cetak"]
        totals[name] = {"satu_halaman": _count(sel), "dua_halaman": _count(sel2), "skor_z_median": _score(sel),
                        "posisi_median_hal1": float(np.median([r["n_observed"] for r in sel if r.get("page") == 1]))
                        if sel else None}
    out["total_cetak"] = totals
    # Paired comparison of every variant with v1 on the same evidence.
    base = {(r["doc"], r["n"], r["printer"], r["res"], tuple(r["seqs"]), r.get("page")): r["verdict"] == "benar"
            for r in cetak if r["variant"] == "v1" and r.get("latar", "-") == "-"}
    out["banding_v1"] = {}
    for name in totals:
        if name == "v1":
            continue
        pairs = [(base[k], r["verdict"] == "benar") for r in cetak
                 if r["variant"] == name and r.get("latar", "-") == "-"
                 and (k := (r["doc"], r["n"], r["printer"], r["res"], tuple(r["seqs"]), r.get("page"))) in base]
        out["banding_v1"][name] = _mcnemar(pairs)
    # Composites.
    kol = [r for r in rows if r["kind"] == "kolusi"]
    kol_two: list[dict] = []
    two_k = _two_page(phase, kol, kol_two)
    two_rows += kol_two
    kcells = {}
    kg: dict[tuple, list[dict]] = defaultdict(list)
    for r in kol:
        kg[(r["variant"], r["doc"], r["n"], r.get("latar", "-"), r["printer"], r["res"])].append(r)
    for key, sel in sorted(kg.items(), key=lambda kv: str(kv[0])):
        kcells["/".join(str(k) for k in key)] = {"satu_halaman": _members(sel), "dua_halaman": _members(two_k.get(key, [])),
                                                 "max_tak_bersalah_z": max((r["max_innocent_z"] or 0) for r in sel)}
    out["kolusi"] = kcells
    # PDF, screenshots, screen photos.
    other = defaultdict(list)
    for r in rows:
        if r["kind"] in ("pdf", "layar", "foto"):
            other[(r["variant"], r["doc"], r["n"], r["kind"])].append(r)
    out["layar_pdf"] = {"/".join(str(k) for k in key): dict(_count(sel), max_tak_bersalah_z=max(
        (r["max_innocent_z"] or 0) for r in sel), pola_latar=sum(1 for r in sel if r.get("pattern_found")))
        for key, sel in sorted(other.items(), key=lambda kv: str(kv[0]))}
    per_kind: dict = defaultdict(dict)
    for r in rows:
        if r["kind"] in ("pdf", "layar", "foto"):
            per_kind[r["kind"]].setdefault(r["variant"], {"benar": 0, "tidak cukup bukti": 0, "salah": 0})
            per_kind[r["kind"]][r["variant"]][r["verdict"]] += 1
    out["layar_pdf_total"] = per_kind
    # Unmarked master.
    ind = defaultdict(list)
    for r in rows:
        if r["kind"].startswith("induk_"):
            ind[(r["variant"], r["n"], r["kind"])].append(r)
    out["induk"] = {"/".join(str(k) for k in key): {"traces": len(sel), "dituduh": sum(1 for r in sel if r["accused"]),
                                                    "max_skor_z": max((r["max_innocent_z"] or 0) for r in sel)}
                    for key, sel in sorted(ind.items(), key=lambda kv: str(kv[0]))}
    out["salah_total"] = sum(1 for r in rows + two_rows if r["verdict"] == "salah" or (
        r.get("kind") == "kolusi" and set(r["accused"]) - set(r["seqs"])))
    out["per_printer"] = _per_printer(cetak, two_rows)
    if phase == "uji":
        out["keputusan"] = _decision(out, cetak)
    (ukur.HASIL / f"{phase}_dua_halaman.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in two_rows), encoding="utf-8")
    (ukur.HASIL / f"ringkas_{phase}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")
    _print(out)
    return out


def _print(out: dict) -> None:
    print(f"== {out['phase']}: {out['rows']} baris, tuduhan salah {out['salah_total']}")
    for name, c in out["cetak"].items():
        pages = "; ".join(f"{p}: " + ", ".join(f"{s} {v[s]['read_median']:.0f} ({100 * v[s]['ber']:.1f} %)"
                                                for s in SUB if s in v) for p, v in c["pages"].items())
        print(f"{name:<40} 1 hal {c['satu_halaman']} skor {c['skor_z_median']}  2 hal {c['dua_halaman']}  | {pages}"
              + (f" | probe {c['probe']}" if "probe" in c else ""))
    print("total cetak:", json.dumps(out["total_cetak"], ensure_ascii=False))
    print("banding v1:", json.dumps(out["banding_v1"], ensure_ascii=False))
    for name, c in out["kolusi"].items():
        print(f"kolusi {name}: {c}")
    print("layar/pdf:", json.dumps(out["layar_pdf_total"], ensure_ascii=False))
    for name, c in out["induk"].items():
        print(f"induk {name}: {c}")
    for name, c in out["per_printer"].items():
        print(f"per printer {name}: {c}")
    if "keputusan" in out:
        print("keputusan:", json.dumps(out["keputusan"], ensure_ascii=False))
