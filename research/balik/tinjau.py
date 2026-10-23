"""Review check outside the protocol: fresh seeds 9871 and 9872, master against this branch, and
escapes from all three manipulation checks.

Run after the held-out run, with no rule, rate or threshold changed. Issuances (``tapak issue
--benih-riset``, N = 20, c = 3, eps = 1e-6, default background): W1 the fictional nota_dinas
under geser-v2 (9871), W2 the fictional surat_telegram under geser-v1 (9872). Neither seed is
used by any other protocol. Media are those of ``research/kontradiksi`` (its ``evidence``).

* ``jejak``: per issuance, copy 3, an honest pair (copies 5 and 11, ``acak``), the pair with
  its agreeing marks reversed (``balik``), a reversing trio (copies 2, 9, 17), the pair's
  erasure (``hapus``), the background flattened with the agreeing shift units randomized
  (``buang-acak``), a 0.45 partial reversal (``balik45``) and the unmarked master; copy 3, the
  honest pair and ``balik`` through ``pdf``, ``layar``, ``foto`` and ``cetak2``, the others
  through ``pdf`` and ``layar`` (attack seed [issuance, attack index], channel seed [9879,
  issuance, evidence index, medium index]). Every evidence is the first logged trace with the
  stage policy ``bertahap-v1``. ``--akar`` names the tree whose ``tapak`` traces it, so the
  same evidence can be traced with ``master`` (a ``git archive`` export) and with this branch;
  ``inti`` is a digest of the verdict, the threshold, every score, the channels, the stages, the
  contradiction check, the other notes and the erasure Z under "pola" (timestamps left out),
  which the branch must not change. ``--buta`` traces every evidence again with every codeword
  replaced, collection included, and records whether the code-blind checks changed.
* ``lolos``: a knowing coalition (or one copy, given twice, so every unit agrees) that tries to
  escape every warning: ``satu-buang-acak`` one copy, background flattened and every shift unit
  randomized; ``satu-acak`` one copy, every cell and unit randomized; ``buang-acak`` the pair
  (copies 6 and 14), background flattened and agreeing shift units randomized; ``balik50`` the
  pair reversing agreeing marks with probability 0.5; ``buang-hapus`` the pair, background
  flattened and agreeing shift units erased; each through ``pdf``, ``layar`` and ``foto``
  (attack seed [9878, issuance, attack index], channel seed [9877, issuance, attack index,
  medium index]). One copy is copy 7.

Usage (from the repository root, 1 BLAS thread; ``--kerja`` is the work folder of the
issuances, default ``out/balik/tinjau``):

    python research/balik/tinjau.py terbit
    python research/balik/tinjau.py jejak --akar EXPORT_MASTER --out research/balik/hasil/tinjau/jejak_master.jsonl
    python research/balik/tinjau.py jejak --buta --out research/balik/hasil/tinjau/jejak.jsonl
    python research/balik/tinjau.py banding research/balik/hasil/tinjau/jejak_master.jsonl research/balik/hasil/tinjau/jejak.jsonl
    python research/balik/tinjau.py lolos --out research/balik/hasil/tinjau/lolos.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OMP_THREAD_LIMIT"):
    os.environ.setdefault(_var, "1")

HERE = Path(__file__).resolve().parents[2]
ISSUANCES = {"W1": ("nota_dinas", 9871, "v2"), "W2": ("surat_telegram", 9872, "v1")}
EPS = 1e-6
WARNING_PREFIXES = ("bukti kemungkinan", "pola penghapusan", "bukti terbaca jelas")
LOLOS = ("satu-buang-acak", "satu-acak", "buang-acak", "balik50", "buang-hapus")


def issue(kerja: Path, root: Path) -> None:
    """Issue W1 and W2 into ``kerja`` (skips one already there)."""
    for name, (doc, seed, scheme) in ISSUANCES.items():
        folder = kerja / name
        if list(folder.glob("data/dokumen/*/salinan/manifest.json")):
            continue
        cmd = [sys.executable, "-m", "tapak.cli", "--data", str(folder / "data"), "--keys", str(folder / "keys"),
               "issue", str(root / "samples" / f"{doc}.pdf"), str(root / "samples" / "recipients.csv"),
               "--no-registry", "--canary-domain", "", "--workers", "3", "--geser", scheme, "--latar", "layar",
               "--benih-riset", str(seed)]
        subprocess.run(cmd, check=True, cwd=root, env={**os.environ, "PYTHONPATH": str(root)})


def media(root: Path):
    """``research/kontradiksi/ukur.py`` of the tree (its ``evidence``)."""
    spec = importlib.util.spec_from_file_location("kontradiksi_ukur", root / "research" / "kontradiksi" / "ukur.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def context(kerja: Path, root: Path, name: str):
    """(trace context, salinan folder) of an issuance."""
    from tapak.decoder.trace import load_context
    from tapak.keys import research_code_secret
    from tapak.marker.issue import IssueManifest

    doc, seed, _ = ISSUANCES[name]
    folder = next((kerja / name / "data").glob("dokumen/*/salinan"))
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    master = (root / "samples" / f"{doc}.pdf").read_bytes()
    return load_context(master, manifest, research_code_secret(seed)), folder


def copy_pdf(ctx, folder: Path, seq: int) -> bytes:
    return (folder / ctx.manifest.copies[seq - 1].file).read_bytes()


def forge(ctx, pdfs: list[bytes], how: str, seed: list[int], frac: float = 1.0) -> bytes:
    """A forged PDF of ``pdfs`` (first member first); ``satu-*`` gives the first copy twice."""
    import numpy as np

    from tapak.collusion import attack, forge_copy

    rng = np.random.default_rng(seed)
    if how.startswith("satu"):
        pdfs = [pdfs[0], pdfs[0]]
    if how == "jujur":
        return attack(ctx.master, pdfs, "acak", 0.0, rng=rng)[0]
    if how in ("buang-acak", "satu-buang-acak", "buang-hapus"):
        _, _, plan = attack(ctx.master, pdfs, "acak", frac, rng=rng, neutralize="hapus" if how == "buang-hapus" else "acak")
        for lv in plan.levels.values():
            lv[:] = 0.0
        return forge_copy(ctx.master, pdfs, plan)
    neutralize = {"balik": "balik", "hapus": "hapus", "satu-acak": "acak", "balik50": "balik"}[how]
    return attack(ctx.master, pdfs, "acak", 0.5 if how == "balik50" else frac, rng=rng, neutralize=neutralize)[0]


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k != "fixed_at"}
    if isinstance(o, list):
        return [_clean(x) for x in o]
    return o


def core(d: dict) -> str:
    """Digest of everything the branch must not change in a trace (module docstring)."""
    keep = {k: d.get(k) for k in ("verdict", "threshold", "candidates", "channels", "conflicts", "stages",
                                  "contradiction")}
    keep["notes"] = [n for n in d["notes"] if not n.startswith(WARNING_PREFIXES)]
    keep["erasure_pola"] = (d.get("erasure") or {}).get("z")
    return hashlib.sha256(json.dumps(_clean(keep), sort_keys=True, default=str).encode()).hexdigest()


def _trace(obs, ctx):
    from tapak.decoder.trace import run_trace
    from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

    return run_trace(obs, ctx, [], TraceSpending.logged(EPS, 1, DEFAULT_STAGE_POLICY))


def _summary(res, obs: list, members: list[int]) -> dict:
    """The recorded fields of one trace; ``members`` empty for the unmarked master."""
    d = res.to_dict()
    z = res.threshold.threshold
    scores = {c.copy.seq: c.score for c in res.candidates}
    row = {"dituduh": sorted(res.named_seqs), "salah": sorted(set(res.named_seqs) - set(members)), "Z": round(z, 2),
           "inti": core(d), "balik": d.get("reversal"), "hapus": d.get("erasure"),
           "kontradiksi": None if res.contradiction is None else bool(res.contradiction.flagged),
           "peringatan": sum(1 for n in res.notes if n.startswith(WARNING_PREFIXES)), "terbaca": {},
           "latar": [{k: sb.meta.get(k) for k in ("page", "pattern_found", "presence", "pilot_z")}
                     for sb in obs if sb.channel == "background"]}
    if members:
        row["skor_anggota_per_Z"] = [round(scores[s] / z, 3) for s in members]
        row["skor_lain_maks_per_Z"] = round(max(v for s, v in scores.items() if s not in members) / z, 3)
    for sb in obs:
        row["terbaca"][sb.channel] = row["terbaca"].get(sb.channel, 0) + len(sb)
    return row


def jejak(kerja: Path, root: Path, out: Path, blind: bool) -> None:
    import numpy as np

    kontra = media(root)
    rows = []
    for base, name in enumerate(("W1", "W2"), start=1):
        ctx, folder = context(kerja, root, name)
        pair, trio = [5, 11], [2, 9, 17]
        cases = [("salinan3", copy_pdf(ctx, folder, 3), [3]),
                 ("koalisi-jujur", forge(ctx, [copy_pdf(ctx, folder, s) for s in pair], "jujur", [base, 1]), pair),
                 ("balik", forge(ctx, [copy_pdf(ctx, folder, s) for s in pair], "balik", [base, 2]), pair),
                 ("balik-3", forge(ctx, [copy_pdf(ctx, folder, s) for s in trio], "balik", [base, 3]), trio),
                 ("hapus", forge(ctx, [copy_pdf(ctx, folder, s) for s in pair], "hapus", [base, 4]), pair),
                 ("buang-acak", forge(ctx, [copy_pdf(ctx, folder, s) for s in pair], "buang-acak", [base, 5]), pair),
                 ("balik45", forge(ctx, [copy_pdf(ctx, folder, s) for s in pair], "balik", [base, 6], 0.45), pair),
                 ("induk", ctx.master.pdf_bytes, [])]
        for label, pdf, members in cases:
            chans = ("pdf", "layar", "foto", "cetak2") if label in ("salinan3", "koalisi-jujur", "balik") \
                else ("pdf", "layar")
            for mi, medium in enumerate(chans):
                seed = [9879, base, len(rows), mi]
                obs = kontra.evidence(ctx, pdf, medium, np.random.default_rng(seed), mi)
                res = _trace(obs, ctx)
                row = {"terbitan": name, "bukti": label, "kanal": medium, "anggota": members,
                       **_summary(res, obs, members)}
                if blind:
                    fake = dataclasses.replace(ctx, codewords=np.random.default_rng(len(rows)).integers(
                        0, 2, ctx.codewords.shape).astype(ctx.codewords.dtype))
                    obs2 = kontra.evidence(fake, pdf, medium, np.random.default_rng(seed), mi)
                    d, d2 = res.to_dict(), _trace(obs2, fake).to_dict()
                    same_obs = len(obs) == len(obs2) and all(
                        a.channel == b.channel and np.array_equal(a.positions, b.positions) and np.array_equal(a.llr, b.llr)
                        for a, b in zip(obs, obs2))
                    row["buta"] = {"pengamatan": bool(same_obs), "balik": d.get("reversal") == d2.get("reversal"),
                                   "hapus": d.get("erasure") == d2.get("erasure"),
                                   "ambang": _clean(d["threshold"]) == _clean(d2["threshold"])}
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("terbitan", "bukti", "kanal", "dituduh")}),
                      "balik", (row["balik"] or {}).get("z_pilot"), (row["balik"] or {}).get("z_signs"),
                      (row["balik"] or {}).get("flagged"), "hapus", (row["hapus"] or {}).get("flagged"),
                      row.get("buta", ""), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def lolos(kerja: Path, root: Path, out: Path) -> None:
    import numpy as np

    from tapak.decoder.fuse import fuse_by_physical_channel
    from tapak.decoder.reversal import sign_statistic

    kontra = media(root)
    rows = []
    for base, name in enumerate(("W1", "W2"), start=1):
        ctx, folder = context(kerja, root, name)
        for ai, how in enumerate(LOLOS):
            members = [7] if how.startswith("satu") else [6, 14]
            pdf = forge(ctx, [copy_pdf(ctx, folder, s) for s in members], how, [9878, base, ai])
            for mi, medium in enumerate(("pdf", "layar", "foto")):
                obs = kontra.evidence(ctx, pdf, medium, np.random.default_rng([9877, base, ai, mi]), mi)
                res = _trace(obs, ctx)
                row = {"terbitan": name, "serangan": how, "kanal": medium, "anggota": members,
                       **_summary(res, obs, members)}
                row["z_tanda_per_kanal"] = {k: None if v[0] is None else round(v[0], 3) for k, v in
                                            ((k, sign_statistic(e, ctx.p)) for k, e in
                                             fuse_by_physical_channel(obs, ctx.params.length).items())}
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("terbitan", "serangan", "kanal", "dituduh", "skor_anggota_per_Z",
                                                      "peringatan", "terbaca")}),
                      "balik", row["balik"]["z_pilot"], row["balik"]["z_signs"], "hapus", row["hapus"]["z"],
                      row["hapus"]["z_all"], flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def banding(path_a: Path, path_b: Path) -> int:
    """Compare two ``jejak`` outputs (master first): the digests must be equal everywhere."""
    a = [json.loads(line) for line in path_a.read_text(encoding="utf-8").splitlines() if line]
    b = [json.loads(line) for line in path_b.read_text(encoding="utf-8").splitlines() if line]
    if len(a) != len(b):
        print(f"jumlah baris berbeda: {len(a)} dan {len(b)}")
        return 1
    diff = [(r["terbitan"], r["bukti"], r["kanal"]) for r, s in zip(a, b) if r["inti"] != s["inti"]]
    blind = [(s["terbitan"], s["bukti"], s["kanal"]) for s in b if "buta" in s and not all(s["buta"].values())]
    wrong = [(s["terbitan"], s["bukti"], s["kanal"], s["salah"]) for s in b if s["salah"] and s["anggota"]]
    print(f"inti berbeda: {len(diff)} dari {len(a)} {diff[:5]}")
    print(f"pemeriksaan berubah dengan kode lain: {len(blind)} {blind[:5]}")
    print(f"tuduhan salah: {len(wrong)}; induk disebut: {sum(1 for s in b if not s['anggota'] and s['dituduh'])}")
    for r, s in zip(a, b):
        rv, er = s["balik"] or {}, s["hapus"] or {}
        print(f"  {s['terbitan']} {s['bukti']:13s} {s['kanal']:6s} dituduh {s['dituduh']} | pilot {rv.get('z_pilot')} "
              f"tanda {rv.get('z_signs')} {'BALIK' if rv.get('flagged') else '-'} | hapus {er.get('z')} / "
              f"{er.get('z_all')} {'HAPUS' if er.get('flagged') else '-'} (master {(r['hapus'] or {}).get('flagged')})"
              f" | peringatan {s['peringatan']} (master {r['peringatan']})")
    return 1 if diff or blind or wrong else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bagian", choices=["terbit", "jejak", "lolos", "banding"])
    ap.add_argument("paths", nargs="*", type=Path, default=[])
    ap.add_argument("--kerja", type=Path, default=HERE / "out" / "balik" / "tinjau")
    ap.add_argument("--akar", type=Path, default=HERE, help="pohon kode yang melacak (bawaan: repositori ini)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--buta", action="store_true", help="lacak lagi dengan semua kata kode diganti")
    args = ap.parse_args(argv)
    if args.bagian == "banding":
        return banding(*args.paths)
    root = args.akar.resolve()
    sys.path.insert(0, str(root))
    import cv2

    cv2.setNumThreads(1)  # a shared machine
    if args.bagian == "terbit":
        issue(args.kerja.resolve(), root)
    elif args.bagian == "jejak":
        jejak(args.kerja.resolve(), root, args.out, args.buta)
    else:
        lolos(args.kerja.resolve(), root, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
