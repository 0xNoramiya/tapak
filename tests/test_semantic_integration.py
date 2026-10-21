"""Semantic channel through the real issuer and trace (M2 acceptance, integration level)."""

from __future__ import annotations

import random

import numpy as np
import pytest

from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.decoder.trace import collect_from_text, load_context, run_trace
from tapak.llm.provider import get_provider
from tapak.marker.issue import IssueSettings, SemanticSelection, issue
from tapak.marker.master import load_master
from tapak.marker.pdf_zerowidth import normalize_text
from tapak.marker.semantic import STATUS_APPROVED, IssuanceBlocked, find_candidate_units, generate_variant_set
from tests_support import SAMPLE


def _typos(text: str, rate: float, rng: random.Random) -> str:
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


@pytest.fixture(scope="module")
def semantic_issue(tmp_path_factory, recipients, secret):
    master = load_master(SAMPLE.read_bytes())
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, get_provider("mock")) for u in units]
    sel = SemanticSelection(units, sets)
    out = tmp_path_factory.mktemp("sem")
    with pytest.raises(IssuanceBlocked):
        issue(SAMPLE, recipients, out / "blocked", secret, IssueSettings(), semantic=sel)
    for vs in sets:
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED)
    manifest = issue(SAMPLE, recipients, out / "ok", secret, IssueSettings(), semantic=sel)
    return out / "ok", manifest, sel


def test_semantic_rows_excluded_and_recorded(semantic_issue):
    _, manifest, sel = semantic_issue
    assert manifest.semantic_digest == sel.digest
    assert {tuple(r) for r in manifest.excluded_rows} == sel.carrying_rows()
    assert all(len(c.semantic_variant_ids) == len(sel.units) for c in manifest.copies)
    assert manifest.plan_summary["semantic"]["bits"] >= 2


def test_retyped_text_with_typos_decodes_20_of_20(semantic_issue, secret):
    folder, manifest, sel = semantic_issue
    ctx = load_context(SAMPLE.read_bytes(), manifest, secret, semantic=sel)
    rng = random.Random(2026)
    recovered = 0
    for seq in range(1, 21):
        text = normalize_text(extract_pdf_text((folder / manifest.copies[seq - 1].file).read_bytes()))
        obs = collect_from_text(_typos(text, 0.05, rng), ctx)
        sem = next(o for o in obs if o.channel == "semantic")
        x = ctx.codewords[seq - 1]
        recovered += int(len(sem) > 0 and np.array_equal((sem.llr > 0).astype(int), x[sem.positions]))
        # A handful of semantic bits never suffices to name anyone at eps = 1e-6.
        assert run_trace([sem], ctx).accused == []
    assert recovered == 20


def test_semantic_context_warns_without_variants(semantic_issue, secret):
    _, manifest, _ = semantic_issue
    ctx = load_context(SAMPLE.read_bytes(), manifest, secret)
    assert ctx.semantic is None and any("varian semantik" in w for w in ctx.warnings)
