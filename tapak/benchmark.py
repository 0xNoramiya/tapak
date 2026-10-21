"""Regression benchmark over the synthetic photo set (``make bench``).

Traces every image listed in ``samples/photos/truth.json`` against the issued document it
was made from and counts, per kind and view angle: correct identifications, honest
"tidak cukup bukti" verdicts, and wrong accusations (which must stay at zero).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark; exit code 1 if any innocent recipient was accused."""
    ap = argparse.ArgumentParser(description="Uji regresi dekoder pada set foto sintetis")
    ap.add_argument("--photos", default="samples/photos")
    ap.add_argument("--data", default="out/photos/data")
    ap.add_argument("--keys", default="out/photos/keys")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    os.environ["TAPAK_DATA"] = args.data
    os.environ["TAPAK_KEY_DIR"] = args.keys

    from tapak.config import load_settings
    from tapak.decoder.accuse import VERDICT_IDENTIFIED, format_upper_bound
    from tapak.service import list_workspaces, trace_evidence

    settings = load_settings()
    truth = json.loads((Path(args.photos) / "truth.json").read_text(encoding="utf-8"))
    entries = truth["items"] if isinstance(truth, dict) else truth
    docs = list_workspaces(settings)
    if not docs:
        raise SystemExit("tidak ada dokumen terbitan; jalankan: make photos")
    doc = docs[0]
    by_copy = {c.copy_id: c.seq for c in doc.copies}
    rows = []
    t0 = time.perf_counter()
    for e in entries:
        data = (Path(args.photos) / e["file"]).read_bytes()
        expected = by_copy.get(e["copy_id"], e.get("seq"))
        out = trace_evidence(settings, doc.doc_hash, e["file"], data)
        a = out.attribution
        accused = [c.copy.seq for c in a.accused]
        if a.verdict != VERDICT_IDENTIFIED:
            outcome = "tidak cukup bukti"
        elif accused == [expected]:
            outcome = "benar"
        elif expected in accused:
            outcome = "benar + lain"
        else:
            outcome = "SALAH"
        best = a.accused[0] if a.accused else None
        rows.append({"file": e["file"], "kind": e["kind"], "angle": e.get("angle"), "expected": expected,
                     "accused": accused, "outcome": outcome,
                     "log10_fa": best.log10_false_accusation if best else None})
        print(f"{e['file']:<32} {outcome:<18} dituduh={accused} "
              + (f"peluang tuduhan salah<={format_upper_bound(best.log10_false_accusation)}" if best else ""),
              flush=True)
    summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = f"{r['kind']} {int(r['angle'] or 0):>2} derajat" if r['kind'] == 'photo' else r['kind']
        summary[key][r["outcome"]] += 1
    print(f"\nRingkasan ({len(rows)} gambar, {time.perf_counter() - t0:.0f} s):")
    for key in sorted(summary):
        print(f"  {key:<18} " + ", ".join(f"{k}: {v}" for k, v in sorted(summary[key].items())))
    wrong = sum(1 for r in rows if r["outcome"] in ("SALAH", "benar + lain"))
    correct = sum(1 for r in rows if r["outcome"] == "benar")
    print(f"Total: benar {correct}, tidak cukup bukti {len(rows) - correct - wrong}, tuduhan salah {wrong}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
