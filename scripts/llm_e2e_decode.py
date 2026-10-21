"""Check that semantic variants issued from a real model decode from retyped text (prototype).

For every copy of an issued document: extract the text layer, strip invisible marks and
look-alike letters (what retyping leaves), optionally add typos, decode the semantic
channel and compare the decoded bits with the copy's codeword. The codeword is used here
only to score the decoder; the decoder itself never sees it.

Usage (same TAPAK_DATA and TAPAK_KEY_DIR as the issuance):

    PYTHONPATH=. python scripts/llm_e2e_decode.py <doc-hash> [--typo-trials 20] [--write-txt DIR]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

from tapak.config import load_settings
from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.decoder.trace import collect_from_text, load_context, run_trace
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.service import ensure_keys, load_workspace


def typos(text: str, rate: float, rng: random.Random) -> str:
    """Random single-character inserts, deletes and substitutions (same model as the tests)."""
    chars = list(text)
    for _ in range(int(rate * len(chars))):
        i = rng.randrange(len(chars))
        op = rng.choice("ids")
        if op == "i":
            chars.insert(i, rng.choice("abcdefghijklmnopqrstuvwxyz"))
        elif op == "d":
            del chars[i]
        else:
            chars[i] = rng.choice("abcdefghijklmnopqrstuvwxyz")
    return "".join(chars)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--typo-rate", type=float, default=0.05)
    ap.add_argument("--typo-trials", type=int, default=20)
    ap.add_argument("--write-txt", default=None, help="write the clean retyped text of each copy here")
    args = ap.parse_args()
    s = load_settings()
    keys = ensure_keys(s, create_signing_key=False, create_secret=False)
    manifest, master, folder = load_workspace(s, args.doc)
    ctx = load_context(master, manifest, keys.code_secret, folder=folder)
    if ctx.semantic is None:
        raise SystemExit("no semantic selection: " + "; ".join(ctx.warnings))
    rng = random.Random(2026)
    out = {"copies": len(manifest.copies), "semantic_bits": int(manifest.plan_summary["semantic"]["bits"]),
           "variant_ids": {}, "clean_exact": 0, "typo_exact": 0, "typo_trials": 0, "typo_bit_errors": 0,
           "typo_bits_read": 0, "accused_from_semantic_only": 0}
    for k, copy in enumerate(manifest.copies):
        text = normalize_text(extract_pdf_text((folder / "salinan" / copy.file).read_bytes()))
        if args.write_txt:
            Path(args.write_txt).mkdir(parents=True, exist_ok=True)
            (Path(args.write_txt) / (Path(copy.file).stem + ".txt")).write_text(text, encoding="utf-8")
        x = ctx.codewords[k]
        out["variant_ids"][str(k + 1)] = list(copy.semantic_variant_ids)
        sem = next(o for o in collect_from_text(text, ctx) if o.channel == "semantic")
        exact = len(sem) == out["semantic_bits"] and np.array_equal((sem.llr > 0).astype(int), x[sem.positions])
        out["clean_exact"] += int(exact)
        out["accused_from_semantic_only"] += len(run_trace([sem], ctx).accused)
        for _ in range(args.typo_trials):
            sem = next(o for o in collect_from_text(typos(text, args.typo_rate, rng), ctx) if o.channel == "semantic")
            read = (sem.llr > 0).astype(int)
            out["typo_trials"] += 1
            out["typo_bits_read"] += len(sem)
            out["typo_bit_errors"] += int(np.sum(read != x[sem.positions]))
            out["typo_exact"] += int(len(sem) == out["semantic_bits"]
                                     and np.array_equal(read, x[sem.positions]))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
