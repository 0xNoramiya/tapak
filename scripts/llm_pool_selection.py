"""Build a varian.json from real-model variants collected by scripts/llm_eval.py (prototype).

Every listed variant must appear as a kept candidate (it passed TAPAK's automatic checks and
the model judge inside ``generate_variant_set``) in one of the given harness result files.
New variants are written as pending ("menunggu"): the human decision is then recorded with
``tapak semantic approve``, exactly as for a fresh ``tapak semantic suggest``.

Usage: python scripts/llm_pool_selection.py DOC.pdf OUT.json --from a.json b.json \
           --pick u0="variant text" --pick u1="variant text" ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tapak.marker.issue import SemanticSelection
from tapak.marker.master import load_master
from tapak.marker.semantic import STATUS_APPROVED, STATUS_PENDING, VariantSet, find_candidate_units


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("out")
    ap.add_argument("--from", dest="sources", nargs="+", required=True)
    ap.add_argument("--pick", action="append", default=[], help='unit_id="variant text"')
    args = ap.parse_args()
    kept: dict[tuple[str, str], tuple[str, str]] = {}  # (unit, text) -> (judge reason, source)
    for src in args.sources:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        for run in data["pipeline"]["runs"]:
            for text, why in zip(run.get("kept", []), run.get("judge_reasons_kept", [])):
                kept.setdefault((run["unit_id"], text), (why, f"{Path(src).name}:{run['unit_id']}:run{run['run']}"))
    master = load_master(Path(args.doc).read_bytes())
    units = find_candidate_units(master)
    sets = {u.unit_id: VariantSet(u.unit_id, [u.text], [(True, "kalimat asli")], [STATUS_APPROVED],
                                  provider="llamacpp", unit_key=u.fingerprint) for u in units}
    for pick in args.pick:
        uid, text = pick.split("=", 1)
        if (uid, text) not in kept:
            raise SystemExit(f"not a kept real-model candidate of {uid}: {text!r}")
        why, source = kept[(uid, text)]
        vs = sets[uid]
        vs.variants.append(text)
        vs.equivalence.append((True, why))
        vs.status.append(STATUS_PENDING)
        print(f"{uid}: v{len(vs.variants) - 1} from {source}: {text}")
    sel = SemanticSelection(units, [sets[u.unit_id] for u in units])
    Path(args.out).write_text(json.dumps(sel.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
