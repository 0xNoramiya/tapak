"""Measure a real local llama.cpp model on TAPAK's semantic channel (prototype, not a test).

Runs TAPAK's own pipeline (``generate_variant_set``: automatic checks, then the provider's
judge) several times per candidate unit of a sample PDF and records, per run, every raw
candidate with the reason it was dropped or kept, and the latency of every model call.
It also scores the equivalence judge alone on a pre-registered set of equivalent and
meaning-changing pairs (``scripts/llm_judge_set.json``).

Usage (server already running on loopback):

    PYTHONPATH=. python scripts/llm_eval.py --url http://127.0.0.1:8799/completion \
        --runs 5 --out /path/to/result.json

The output holds document text (synthetic sample only) and stays out of the repository.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from tapak.llm.llamacpp import LlamaCppProvider
from tapak.marker.master import load_master
from tapak.marker.semantic import find_candidate_units, generate_variant_set

ROOT = Path(__file__).resolve().parents[1]


def paraphrase_prompt_v1(sentence: str, n: int) -> str:
    """The paraphrase prompt shipped at commit b3fd8fa (free rewording)."""
    return (
        "Anda adalah penyunting naskah dinas berbahasa Indonesia.\n"
        f"Tuliskan {n} parafrase dari kalimat di bawah ini dengan makna yang sama persis.\n"
        "Aturan:\n"
        "- pertahankan semua angka, nama, jabatan, satuan, waktu, dan kata berhuruf kapital apa adanya;\n"
        "- jangan menambah atau menghapus informasi, perintah, larangan, maupun kata ingkar;\n"
        "- gunakan bahasa dinas yang baku dengan panjang kalimat yang hampir sama;\n"
        "- tulis satu parafrase per baris dengan nomor 1., 2., dan seterusnya, tanpa penjelasan.\n"
        "\n"
        f"Kalimat: {sentence}\n"
        "\n"
        "Parafrase:\n"
    )


def judge_prompt_v1(original: str, candidate: str) -> str:
    """The judge prompt shipped at commit b3fd8fa ("bermakna sama persis")."""
    return (
        "Anda adalah pemeriksa kesetaraan makna naskah dinas berbahasa Indonesia.\n"
        "Apakah kalimat B bermakna sama persis dengan kalimat A, tanpa menambah, menghapus, "
        "atau mengubah informasi, angka, nama, waktu, perintah, larangan, maupun kata ingkar?\n"
        "Jawab dalam satu baris: YA atau TIDAK, lalu titik dua dan alasan singkat.\n"
        "\n"
        f"A: {original}\n"
        f"B: {candidate}\n"
        "\n"
        "Jawaban:"
    )


def paraphrase_prompt_v2(sentence: str, n: int) -> str:
    """Candidate prompt: ask for small synonym substitutions instead of free rewording.

    Motivated by the failures of the shipped prompt with Qwen2.5-3B (sentences restructured
    so they no longer fit the rows, "bersama ini" dropped, content added); evaluated on
    the held-out surat_telegram.pdf as well as on nota_dinas.pdf.
    """
    return (
        "Anda adalah penyunting naskah dinas berbahasa Indonesia.\n"
        f"Tuliskan {n} parafrase dari kalimat di bawah ini. Setiap parafrase hanya mengganti satu "
        "atau dua kata atau frasa dengan padanannya yang lazim dalam surat dinas, sehingga maknanya "
        "tetap sama persis.\n"
        "Aturan:\n"
        "- pertahankan susunan kalimat; jangan menghapus kata lain dan jangan menambah keterangan baru;\n"
        "- pertahankan semua angka, nama, jabatan, satuan, waktu, dan kata berhuruf kapital apa adanya;\n"
        "- jangan menambah atau menghapus informasi, perintah, larangan, maupun kata ingkar;\n"
        "- jangan memakai tanda baca yang tidak ada pada kalimat asli;\n"
        "- setiap parafrase harus berbeda dari kalimat asli dan dari parafrase lainnya;\n"
        "- tulis satu parafrase per baris dengan nomor 1., 2., dan seterusnya, tanpa penjelasan.\n"
        "\n"
        f"Kalimat: {sentence}\n"
    )


class TimedProvider(LlamaCppProvider):
    """LlamaCppProvider that records the latency and raw answer of every model call."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.calls: list[dict[str, object]] = []

    def complete(self, prompt: str, temperature: float | None = None, **kwargs: object) -> str:
        t0 = time.perf_counter()
        out = super().complete(prompt, temperature, **kwargs)  # type: ignore[arg-type]
        kind = "judge" if temperature == 0.0 else "paraphrase"
        self.calls.append({"kind": kind, "seconds": round(time.perf_counter() - t0, 3), "raw": out})
        return out


def reason_category(reason: str) -> str:
    """Coarse category of a drop reason from ``generate_variant_set``."""
    for key, cat in (
        ("token terlindungi", "protected_tokens"), ("pemeriksaan keamanan", "safety_check"),
        ("tanda baca", "punctuation"), ("tanda akhir", "punctuation"), ("tidak muat", "layout_fit"),
        ("sama dengan kalimat asli", "same_as_original"), ("terlalu mirip", "near_duplicate"),
        ("kandidat kosong", "empty"), ("tidak setara menurut pemeriksa", "judge_rejected"),
    ):
        if key in reason:
            return cat
    return "other"


def judge_prompt_v2(original: str, candidate: str) -> str:
    """Candidate judge prompt: synonyms and word order are allowed, changes of content are not.

    Declared after the shipped judge refused 5 of the first 6 equivalent pairs of the
    pre-registered set ("ada perbedaan kata"), before its negatives were seen.
    """
    return (
        "Anda adalah pemeriksa naskah dinas berbahasa Indonesia.\n"
        "Kalimat B adalah usulan parafrase dari kalimat A. Parafrase boleh memakai sinonim atau "
        "susunan kata yang berbeda.\n"
        "Jawab YA bila B menyampaikan informasi dan maksud yang sama dengan A.\n"
        "Jawab TIDAK bila B menambah, menghapus, atau mengubah informasi, pelaku, sasaran, angka, nama, "
        "waktu, perintah, larangan, atau kata ingkar.\n"
        "Jawab dalam satu baris: YA atau TIDAK, lalu titik dua dan alasan singkat.\n"
        "\n"
        f"A: {original}\n"
        f"B: {candidate}\n"
        "\n"
        "Jawaban:"
    )


def eval_pipeline(provider: TimedProvider, pdf: Path, runs: int, n_candidates: int,
                  save: Callable[[dict[str, object]], None]) -> dict[str, object]:
    master = load_master(pdf.read_bytes())
    units = find_candidate_units(master)
    out_runs: list[dict[str, object]] = []
    pipe: dict[str, object] = {"units": [u.text for u in units], "runs": out_runs}
    for unit in units:
        for r in range(runs):
            provider.calls.clear()
            t0 = time.perf_counter()
            try:
                vs = generate_variant_set(master, unit, provider, n_candidates=n_candidates)
            except RuntimeError as exc:  # timeout or server error: record it and go on
                out_runs.append({"unit_id": unit.unit_id, "run": r, "error": str(exc),
                                 "seconds": round(time.perf_counter() - t0, 3), "calls": list(provider.calls)})
                print(f"{unit.unit_id} run {r}: ERROR {exc}", flush=True)
                save(pipe)
                continue
            wall = time.perf_counter() - t0
            out_runs.append({
                "unit_id": unit.unit_id, "run": r, "original": unit.text, "seconds": round(wall, 3),
                "kept": vs.variants[1:], "judge_reasons_kept": [w for _, w in vs.equivalence[1:]],
                "dropped": [{"text": t, "reason": why, "category": reason_category(why)} for t, why in vs.dropped],
                "calls": list(provider.calls),
            })
            print(f"{unit.unit_id} run {r}: {len(vs.variants) - 1} kept, {len(vs.dropped)} dropped, {wall:.1f} s",
                  flush=True)
            save(pipe)
    return pipe


def eval_judge(provider: TimedProvider, judge_set: Path) -> dict[str, object]:
    data = json.loads(judge_set.read_text(encoding="utf-8"))
    rows = []
    for label, pairs in (("positive", data["positives"]), ("negative", data["negatives"])):
        for uid, cand in pairs:
            provider.calls.clear()
            try:
                ok, why = provider.judge_equivalent(data["units"][uid], cand)
            except RuntimeError as exc:
                ok, why = False, f"ERROR {exc}"
            secs = sum(float(c["seconds"]) for c in provider.calls)  # type: ignore[arg-type]
            rows.append({"label": label, "unit_id": uid, "candidate": cand, "accepted": ok, "reason": why,
                         "seconds": round(secs, 3), "raw": [c["raw"] for c in provider.calls]})
            print(f"judge {label}: {'YA' if ok else 'TIDAK'} ({secs:.1f} s) {why[:60]}", flush=True)
    pos = [r for r in rows if r["label"] == "positive"]
    neg = [r for r in rows if r["label"] == "negative"]
    return {"rows": rows, "true_accept": sum(r["accepted"] for r in pos), "n_pos": len(pos),
            "false_accept": sum(r["accepted"] for r in neg), "n_neg": len(neg),
            "errors": sum(r["reason"].startswith("ERROR") for r in rows)}


def summarize(pipe: dict[str, object]) -> dict[str, object]:
    runs: list[dict] = pipe["runs"]  # type: ignore[assignment]
    cats: Counter[str] = Counter()
    raw_total = kept_total = 0
    lat: dict[str, list[float]] = {"paraphrase": [], "judge": []}
    ok_runs = [r for r in runs if "error" not in r]
    for run in runs:
        for c in run["calls"]:
            lat[c["kind"]].append(c["seconds"])
    for run in ok_runs:
        kept_total += len(run["kept"])
        raw_total += len(run["kept"]) + len(run["dropped"])
        cats.update(d["category"] for d in run["dropped"])

    def stats(xs: list[float]) -> dict[str, float]:
        if not xs:
            return {}
        s = sorted(xs)
        return {"n": len(s), "min": s[0], "median": s[len(s) // 2], "max": s[-1], "mean": round(sum(s) / len(s), 3)}

    per_unit = {}
    for uid in sorted({r["unit_id"] for r in ok_runs}):
        kept = [len(r["kept"]) for r in ok_runs if r["unit_id"] == uid]
        per_unit[uid] = {"runs": len(kept), "kept_per_run": kept, "runs_with_kept": sum(k > 0 for k in kept)}
    return {"runs": len(runs), "errors": len(runs) - len(ok_runs), "raw_candidates": raw_total,
            "kept": kept_total, "per_unit": per_unit, "dropped_by_category": dict(cats),
            "latency_paraphrase": stats(lat["paraphrase"]), "latency_judge": stats(lat["judge"]),
            "set_seconds": stats([r["seconds"] for r in ok_runs])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--pdf", default=str(ROOT / "samples" / "nota_dinas.pdf"))
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--n-candidates", type=int, default=6)
    ap.add_argument("--judge-set", default=str(ROOT / "scripts" / "llm_judge_set.json"))
    ap.add_argument("--skip-judge", action="store_true")
    ap.add_argument("--skip-pipeline", action="store_true")
    ap.add_argument("--timeout", type=float, default=300.0)
    # v1: prompts shipped at b3fd8fa ("shipped" in the limits report); v2: the current provider prompts
    ap.add_argument("--prompt", choices=["v1", "v2"], default="v2")
    ap.add_argument("--judge", choices=["v1", "v2"], default="v2")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    import tapak.llm.llamacpp as mod

    # paraphrase() and judge_equivalent() look these names up at call time
    mod.build_paraphrase_prompt = paraphrase_prompt_v1 if args.prompt == "v1" else paraphrase_prompt_v2
    mod.build_judge_prompt = judge_prompt_v1 if args.judge == "v1" else judge_prompt_v2
    provider = TimedProvider(server_url=args.url, timeout=args.timeout)
    result: dict[str, object] = {"url": args.url, "pdf": Path(args.pdf).name, "prompt": args.prompt, "judge": args.judge}
    if not args.skip_pipeline:
        def save(partial: dict[str, object]) -> None:
            result["pipeline"] = partial
            Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")

        pipe = eval_pipeline(provider, Path(args.pdf), args.runs, args.n_candidates, save)
        result["pipeline"] = pipe
        result["summary"] = summarize(pipe)
        print(json.dumps(result["summary"], indent=2))
    if not args.skip_judge:
        judge = eval_judge(provider, Path(args.judge_set))
        result["judge"] = judge
        print(f"judge: {judge['true_accept']}/{judge['n_pos']} equivalent accepted, "
              f"{judge['false_accept']}/{judge['n_neg']} meaning-changing accepted")
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
