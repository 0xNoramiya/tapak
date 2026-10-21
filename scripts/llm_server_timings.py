"""Summarize llama-server per-request timings from its log (prototype helper).

Each finished request logs "prompt eval time = ... / N tokens (..., R tokens per second)",
"eval time = ... / N tokens (...)" and "total time". Requests that generated at most
JUDGE_MAX_TOKENS tokens are counted as judge calls, the others as paraphrase calls.

Usage: python scripts/llm_server_timings.py server.log [--after-task N]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics

_LINE = re.compile(r"task (\d+) \|\s+(prompt eval|eval|total) time =\s+([\d.]+) ms /\s+(\d+) tokens")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--after-task", type=int, default=-1)
    ap.add_argument("--judge-max-tokens", type=int, default=64)
    args = ap.parse_args()
    tasks: dict[int, dict[str, tuple[float, int]]] = {}
    with open(args.log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _LINE.search(line)
            if m and int(m.group(1)) > args.after_task:
                tasks.setdefault(int(m.group(1)), {})[m.group(2)] = (float(m.group(3)), int(m.group(4)))
    groups: dict[str, list[dict[str, float]]] = {"judge": [], "paraphrase": []}
    for t in tasks.values():
        if not {"prompt eval", "eval", "total"} <= set(t):
            continue
        kind = "judge" if t["eval"][1] <= args.judge_max_tokens else "paraphrase"
        groups[kind].append({
            "prompt_tokens": t["prompt eval"][1], "gen_tokens": t["eval"][1], "total_s": t["total"][0] / 1000,
            "prompt_tps": t["prompt eval"][1] / max(t["prompt eval"][0] / 1000, 1e-9),
            "gen_tps": t["eval"][1] / max(t["eval"][0] / 1000, 1e-9),
        })
    out = {}
    for kind, rows in groups.items():
        if not rows:
            continue
        out[kind] = {"n": len(rows)} | {
            k: {"median": round(statistics.median(r[k] for r in rows), 2),
                "min": round(min(r[k] for r in rows), 2), "max": round(max(r[k] for r in rows), 2)}
            for k in ("prompt_tokens", "gen_tokens", "total_s", "prompt_tps", "gen_tps")
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
