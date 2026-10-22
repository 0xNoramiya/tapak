"""Staged accusation ("pelacakan bertahap"): the budget split, the side-informed weights, the
false-accusation guarantee of the later stages, and how the stages reach the registry, the
decoder, the CLI and the berita acara."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tapak.decoder.accuse import (
    STAGE_BASIS_TEXT,
    STAGE_THRESHOLD_RULE,
    THRESHOLD_RULE,
    Attribution,
    StageAttribution,
    attribute,
)
from tapak.decoder.fuse import FusedEstimate
from tapak.registry.chain import (
    KIND_TRACE,
    STAGE_TRACE_FIELDS,
    TRACE_FIELDS,
    Registry,
    trace_payload_problems,
)
from tapak.registry.verify import verify_registry
from tapak.tardos.accuse import scores, threshold
from tapak.tardos.attacks import STRATEGIES
from tapak.tardos.code import random_code
from tapak.tardos.params import TardosParams
from tapak.tardos.simulate import (
    StagedSimulationReport,
    StagedStrategyResult,
    run_simulation,
    run_staged_simulation,
)
from tapak.tardos.spending import (
    DEFAULT_STAGE_POLICY,
    STAGE_POLICIES,
    StagePolicy,
    TraceSpending,
    eps_for_trace,
    split_stage_eps,
    stage_policy,
)
from tapak.tardos.staged import (
    REFERENCE_REMAINING,
    WEIGHT_SCALE,
    Stage,
    side_information_weights,
    stage_weights,
    staged_accuse,
    unexplained_positions,
)

DOC = "d" * 64
EVIDENCE = ["a1" * 32]


# --- the budget split ---------------------------------------------------------------------------


def test_stage_policy_splits_the_trace_share_exactly():
    policy = stage_policy(DEFAULT_STAGE_POLICY)
    assert policy is STAGE_POLICIES["bertahap-v1"] and isinstance(policy, StagePolicy)
    f = policy.fractions()
    assert f[0] == 0.9 and len(f) == policy.max_stages == 4
    assert f[1:] == pytest.approx([0.1 * 36 / 49, 0.1 * 9 / 49, 0.1 * 4 / 49], rel=1e-12)
    assert math.fsum(f) == pytest.approx(1.0, abs=1e-15)
    for k in (1, 2, 3, 10, 100):
        share = eps_for_trace(1e-6, k)
        stages = split_stage_eps(share, DEFAULT_STAGE_POLICY)
        assert math.fsum(stages) == pytest.approx(share, rel=1e-12)
        sp = TraceSpending.logged(1e-6, k, DEFAULT_STAGE_POLICY)
        assert sp.stage_eps == stages and sp.stage_eps1(2, 20) == pytest.approx(stages[1] / 20)
    assert split_stage_eps(3e-7, None) == (3e-7,)
    single = TraceSpending.logged(1e-6, 2)
    assert single.policy is None and single.stage_eps == (single.eps_share,)
    assert single.stage_eps1(1, 20) == single.eps1(20)
    assert TraceSpending.unlogged(1e-6, DEFAULT_STAGE_POLICY).stage_eps[0] == pytest.approx(0.9e-6)
    assert StagePolicy("satu", 1.0, 1).fractions() == (1.0,)
    for bad in (lambda: stage_policy("tidak-ada"), lambda: TraceSpending.logged(1e-6, 1, "tidak-ada"),
                lambda: StagePolicy("x", 0.0, 3), lambda: StagePolicy("x", 0.9, 1), lambda: StagePolicy("x", 1.0, 3),
                lambda: StagePolicy("x", 0.9, True), lambda: single.stage_eps1(2, 20), lambda: single.stage_eps1(1, 0),
                lambda: split_stage_eps(0.0, None)):
        with pytest.raises(ValueError):
            bad()


# --- the weights ---------------------------------------------------------------------------------


def test_side_information_weights_follow_the_closed_forms():
    q = np.array([0.5, 0.3, 0.104, 0.02, 0.001, 0.5, 0.3, 0.02])
    y = np.array([1, 1, 1, 1, 1, 0, 0, 0])  # p = q: y = 1 is the rarer symbol, y = 0 the common one
    accused = (1 - y)[None, :]  # the named copy holds the other bit everywhere: every position unexplained
    w = side_information_weights(y, q, accused)
    rare = np.sqrt(q * (1 - q)) * np.log(1 / q)
    common = np.sqrt(q * (1 - q)) * np.log((1 + 2 * q) * (1 - q) / (1 - 2 * q * q))
    assert w == pytest.approx(np.where(y == 1, rare, common) / WEIGHT_SCALE, rel=1e-12)
    assert REFERENCE_REMAINING == 2 and 0.999 < w[2] <= 1.0 and (w >= 0).all() and (w <= 1).all()
    assert w[0] == pytest.approx(w[5])  # both formulas agree at q = 1/2
    # Explained positions (some named copy holds y) and erased positions get no weight.
    explained = np.vstack([1 - y, y])
    assert (side_information_weights(y, q, explained) == 0).all()
    base = np.linspace(0, 1, len(q))
    assert side_information_weights(y, q, accused, base) == pytest.approx(base * w)
    assert unexplained_positions(y, np.zeros((0, len(y)))).all()
    assert unexplained_positions(y, 1 - y).all() and not unexplained_positions(y, explained).any()
    with pytest.raises(ValueError):
        side_information_weights(y, q[:3], accused)
    with pytest.raises(ValueError):
        unexplained_positions(y, np.zeros((1, 3)))
    with pytest.raises(ValueError):
        stage_weights(2, y, q, explained, np.array([], dtype=int))
    assert (stage_weights(1, y, q, explained, np.array([0]), base) == base).all()


def test_weights_and_thresholds_never_depend_on_the_scored_copy():
    """Property: replacing an unnamed copy's codeword never changes any stage's weights,
    threshold or named set, as long as that copy is not named in either run."""
    params = TardosParams(c=3, eps=1e-3, n_max=40)
    stage_e1 = [e / 40 for e in split_stage_eps(1e-3, DEFAULT_STAGE_POLICY)]
    checked = later = 0
    for seed in range(24):
        rng = np.random.default_rng(seed)
        p, x = random_code(params, 40, rng, length=900)
        members = rng.choice(40, size=5, replace=False)
        y, w = STRATEGIES[["minority", "majority", "random-mix", "worst-case"][seed % 4]](x[members], rng)
        base = staged_accuse(x, y, p, stage_e1, w)
        later += any(st.stage >= 2 and st.n_observed for st in base)
        named = set().union(*(set(st.accused.tolist()) for st in base))
        for j in [k for k in range(40) if k not in named][:6]:
            x2 = x.copy()
            x2[j] = (rng.random(len(p)) < p).astype(np.uint8)
            other = staged_accuse(x2, y, p, stage_e1, w)
            if j in set().union(*(set(st.accused.tolist()) for st in other)):
                continue
            assert len(other) == len(base)
            for a, b in zip(base, other):
                assert (a.weights == b.weights).all() and a.threshold == b.threshold
                assert (a.accused == b.accused).all() and (a.basis == b.basis).all()
            checked += 1
    assert checked >= 100 and later >= 8


def test_stage_threshold_is_the_weighted_chernoff_threshold_of_p_and_w():
    params = TardosParams(c=3, eps=1e-6, n_max=30)
    stage_e1 = [e / 30 for e in split_stage_eps(1e-6, DEFAULT_STAGE_POLICY)]
    rng = np.random.default_rng(5)
    p, x = random_code(params, 30, rng)
    members = rng.choice(30, size=4, replace=False)
    y, w = STRATEGIES["minority"](x[members], rng)
    stages = staged_accuse(x, y, p, stage_e1, w)
    assert stages[0].stage == 1 and stages[0].basis.size == 0 and (stages[0].weights == w).all()
    assert all(isinstance(st, Stage) for st in stages)
    for st in stages:
        assert st.threshold == threshold(p, stage_e1[st.stage - 1], st.weights)
        if st.stage >= 2:
            assert (st.weights == side_information_weights(y, p, x[st.basis], w)).all()
            assert not np.isin(st.scored, st.basis).any()
        expected = scores(x[st.scored].astype(float), y, p, st.weights) if st.n_observed else 0 * st.scores
        assert st.scores == pytest.approx(expected)
        assert set(st.accused.tolist()) == set(st.scored[st.scores >= st.threshold].tolist())
    with pytest.raises(ValueError):
        staged_accuse(x, y, p, [])
    with pytest.raises(ValueError):
        staged_accuse(x[:, :10], y, p, stage_e1)


def test_innocent_stage_two_rate_stays_under_a_measurable_bound():
    """At eps1 = 1e-2 per stage the rate of innocent stage-2 scores at or above Z_2 is measurable;
    the proof says it is at most 1e-2 per innocent copy."""
    params = TardosParams(c=3, eps=1e-2, n_max=60)
    rng = np.random.default_rng(11)
    exceed = evaluations = 0
    for _ in range(120):
        p, x = random_code(params, 60, rng, length=500)
        members = rng.choice(60, size=4, replace=False)
        y, w = STRATEGIES[["minority", "majority", "coin"][_ % 3]](x[members], rng)
        for st in staged_accuse(x, y, p, [1e-2, 1e-2], w):
            if st.stage == 2 and st.n_observed:
                innocent = ~np.isin(st.scored, members)
                evaluations += int(innocent.sum())
                exceed += int(np.count_nonzero(st.scores[innocent] >= st.threshold))
    assert evaluations > 2000
    assert exceed / evaluations <= 1e-2


# --- simulation ----------------------------------------------------------------------------------


def test_staged_simulation_shares_draws_with_the_single_stage_simulation():
    params = TardosParams(c=3, eps=1e-3, n_max=20)
    rep = run_staged_simulation(params, 20, 5, trials=6, seed=4, strategies=["minority", "erase"], bound_levels=(1e-2,))
    ref = run_simulation(params, 20, 5, trials=6, seed=4, strategies=["minority", "erase"])
    assert isinstance(rep, StagedSimulationReport) and isinstance(rep.results[0], StagedStrategyResult)
    for a, b in zip(rep.results, ref.results):
        assert (a.single_detected_trials, a.single_all_caught_trials, a.single_false_accusation_trials) == (
            b.detected_trials, b.all_caught_trials, b.false_accusation_trials)
        assert a.single_mean_threshold == pytest.approx(b.mean_threshold)
        assert a.staged_members_caught == sum(a.stage_members) and a.stage_runs[0] == 6
        assert 0 <= a.single_member_fraction <= 1 and 0 <= a.staged_member_fraction <= 1
        assert a.staged_false_accusation_trials == 0 and sum(a.stage_innocents) == 0
    assert math.fsum(rep.stage_eps1) == pytest.approx(rep.single_eps1)
    json.dumps(rep.to_dict(), allow_nan=False)
    with pytest.raises(ValueError):
        run_staged_simulation(params, 20, 25, trials=1)
    with pytest.raises(ValueError):
        run_staged_simulation(params, 20, 3, trials=1, strategies=["onbekend"])


# --- decoder, CLI and berita acara ----------------------------------------------------------------


def _hidden_colluder(ctx, a: int = 4, b: int = 11):
    """A fused estimate in which copy a explains almost everything and copy b only the rest.

    The read covers the positions where a and b differ; the leaked bit is b's on a third of
    them (where b holds the rarer symbol) and a's elsewhere. Stage 1 names a only; at the
    positions a cannot explain, b holds the leaked bit every time.
    """
    xa, xb, p = ctx.codewords[a].astype(int), ctx.codewords[b].astype(int), ctx.p
    differ = xa != xb
    rare_b = np.where(xb == 1, p, 1 - p) < 0.5
    take_b = differ & rare_b & (np.arange(len(p)) % 3 == 0)
    y = np.where(take_b, xb, xa).astype(np.uint8)
    weights = differ.astype(float)
    llr = np.where(y == 1, 5.0, -5.0) * weights
    fused = FusedEstimate(m=len(p), llr=llr, y=y, weights=weights, observations=differ.astype(np.int64))
    return fused, a, b


def _staged_attribution(ctx, trace_no=1):
    fused, a, b = _hidden_colluder(ctx)
    spending = TraceSpending.logged(ctx.params.eps, trace_no, DEFAULT_STAGE_POLICY)
    return attribute(fused, {}, ctx.p, ctx.codewords, ctx.refs, ctx.params, spending), fused, a, b, spending


def test_attribute_names_a_hidden_colluder_at_stage_two(ctx):
    att, fused, a, b, spending = _staged_attribution(ctx)
    seq_a, seq_b = ctx.refs[a].seq, ctx.refs[b].seq
    assert [c.copy.seq for c in att.accused] == [seq_a]
    t1 = att.threshold
    assert t1.stage == 1 and t1.rule == THRESHOLD_RULE and t1.stage_policy == DEFAULT_STAGE_POLICY
    assert t1.stage_eps == pytest.approx(spending.stage_eps[0]) and t1.eps_share == spending.eps_share
    assert t1.eps1 == pytest.approx(spending.stage_eps[0] / ctx.params.n_max)
    assert t1.threshold == threshold(ctx.p, t1.eps1, fused.weights)
    st = att.stages[0]
    assert isinstance(st, StageAttribution) and st.stage == 2 and st.basis == [seq_a]
    assert [c.copy.seq for c in st.accused] == [seq_b] and seq_a not in {c.copy.seq for c in st.candidates}
    t2 = st.threshold
    assert t2.stage == 2 and t2.rule == STAGE_THRESHOLD_RULE and t2.stage_eps == pytest.approx(spending.stage_eps[1])
    w2 = side_information_weights(fused.y, ctx.p, ctx.codewords[[a]], fused.weights)
    assert t2.threshold == threshold(ctx.p, t2.eps1, w2) and t2.n_observed == int(np.count_nonzero(w2))
    hit = st.accused[0]
    # The bound of a stage-2 name is divided by the stage's own share of eps.
    assert hit.log10_false_accusation == pytest.approx(
        math.log10(len(ctx.refs) - 1) + hit.log10_bound - math.log10(t2.stage_share))
    assert t2.stage_share == pytest.approx(spending.stage_eps[1] / ctx.params.eps)
    assert att.named == [(1, att.accused[0]), (2, hit)] and att.named_seqs == {seq_a, seq_b}
    assert st.basis_text() == f"tahap 2: {STAGE_BASIS_TEXT} #{seq_a}"
    # Stage 3 ran with both named copies and found nobody else; nothing runs after it.
    assert [s.stage for s in att.stages] == [2, 3] and att.stages[1].basis == sorted([seq_a, seq_b])
    assert not att.stages[1].accused
    # Same result as the code-level procedure.
    ref = staged_accuse(ctx.codewords, fused.y, ctx.p, [e / ctx.params.n_max for e in spending.stage_eps],
                        fused.weights)
    assert [sorted(ctx.refs[j].seq for j in s.accused) for s in ref] == [[seq_a], [seq_b], []]
    assert [s.threshold for s in ref] == [t1.threshold, t2.threshold, att.stages[1].threshold.threshold]
    text = "\n".join(att.summary_lines())
    assert "Tahap 2 (pelacakan bertahap)" in text and f"tahap 2: {STAGE_BASIS_TEXT} #{seq_a}" in text
    assert "Tidak ada salinan lain yang mencapai ambang tahap 3" in text
    assert "tahap 1 memakai" in t1.budget_text()


def test_single_stage_traces_decode_exactly_as_before(ctx):
    fused, a, b = _hidden_colluder(ctx)
    for spending in (None, TraceSpending.logged(ctx.params.eps, 1)):  # no policy: logged before staging
        att = attribute(fused, {}, ctx.p, ctx.codewords, ctx.refs, ctx.params, spending)
        share = 1.0 if spending is None else spending.share
        t = att.threshold
        assert att.stages == [] and t.stage == 1 and t.stage_eps is None and t.stage_policy is None
        assert t.stage_share == t.share == pytest.approx(share)
        assert t.threshold == threshold(ctx.p, ctx.params.eps * share / ctx.params.n_max, fused.weights)
        assert "tahap" not in t.budget_text() and att.named_seqs == {c.copy.seq for c in att.accused}


def test_berita_acara_shows_stages_with_their_basis(ctx, issued):
    from tapak.decoder.report import build_report_info, check_consistent, render_html, rerun_command

    att, fused, a, b, _ = _staged_attribution(ctx, trace_no=2)
    seq_a, seq_b = ctx.refs[a].seq, ctx.refs[b].seq
    info = build_report_info(ctx, "bocor.png", b"x", [], case_number="UJI-1", examiner_name="Pemeriksa Uji",
                             examiner_rank="Penata")
    html = " ".join(render_html(att, info).split())
    assert f"Tahap 2: mencari anggota koalisi lain berdasarkan salinan yang sudah dituduh (#{seq_a})" in html
    assert f"tahap 2: {STAGE_BASIS_TEXT} #{seq_a}" in html and ctx.refs[b].nama in html
    assert "Skor tahap 2" in html and "Pelacakan bertahap." in html and "Tahap 3" in html
    assert "Tidak ada salinan lain yang skornya mencapai ambang tahap 3" in html
    assert "--pelacakan-ke 2 --bertahap bertahap-v1" in html
    assert rerun_command(info, None, 2, DEFAULT_STAGE_POLICY).endswith("--pelacakan-ke 2 --bertahap bertahap-v1")
    # Nobody else is named: identities of other copies stay out of the report.
    others = [r for r in ctx.refs if r.seq not in (seq_a, seq_b)]
    assert not any(f">{r.nama}<" in html or r.recipient_id in html for r in others)
    # A stage that does not rest on the copies named before it, or that names a copy below its
    # own threshold, is refused.
    check_consistent(att)
    att.stages[0].basis = [seq_b]
    with pytest.raises(ValueError, match="tahap 2"):
        check_consistent(att)
    att, *_ = _staged_attribution(ctx)
    att.stages[0].candidates[-1].accused = True
    with pytest.raises(ValueError, match="tahap 2"):
        check_consistent(att)
    att, *_ = _staged_attribution(ctx)
    lone = Attribution(att.verdict, att.threshold, [c for c in att.candidates], att.channels, att.conflicts,
                       stages=[att.stages[1]])
    with pytest.raises(ValueError):
        check_consistent(lone)


def test_cli_json_keeps_stage_names_with_their_basis(ctx, tmp_path):
    from tapak.cli import _write_json

    att, fused, a, b, _ = _staged_attribution(ctx)
    path = tmp_path / "hasil.json"
    _write_json(path, att)
    data = json.loads(path.read_text(encoding="utf-8"))
    stage2 = data["stages"][0]
    assert stage2["stage"] == 2 and stage2["basis"] == [ctx.refs[a].seq]
    named = [c for c in stage2["candidates"] if c["accused"]]
    assert [c["copy"]["seq"] for c in named] == [ctx.refs[b].seq]
    assert all(c["copy"]["seq"] is None for c in stage2["candidates"] if not c["accused"])
    assert data["threshold"]["stage"] == 1 and data["threshold"]["stage_policy"] == DEFAULT_STAGE_POLICY


# --- registry ------------------------------------------------------------------------------------


def _registry(path):
    reg = Registry.open(path)
    reg.record_document(doc_hash=DOC, doc_name="sha256:" + "0" * 64, params={"c": 3, "eps": 1e-6, "n_max": 5},
                        channels=["zw"], shift_mm={}, excluded_rows=[], plan_summary={}, threshold_rule="Chernoff",
                        threshold_full=100.0, issuer="uji", issued_at="2026-10-01T00:00:00+00:00")
    return reg


def test_trace_entries_with_and_without_the_stage_policy_verify(tmp_path):
    from tapak.registry.signing import Signer

    signer = Signer(bytes([7]) * 32)
    with _registry(tmp_path / "r.db") as reg:
        old =reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6)
        new = reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, stage_policy=DEFAULT_STAGE_POLICY)
    assert set(old.payload) == TRACE_FIELDS and set(new.payload) == TRACE_FIELDS | STAGE_TRACE_FIELDS
    assert new.kind == KIND_TRACE and new.payload["stage_policy"] == DEFAULT_STAGE_POLICY
    assert new.payload["stage_eps"] == pytest.approx(list(split_stage_eps(eps_for_trace(1e-6, 2), DEFAULT_STAGE_POLICY)))
    assert math.fsum(new.payload["stage_eps"]) == pytest.approx(new.payload["eps_share"], rel=1e-12)
    rep = verify_registry(tmp_path / "r.db", signer.public_key_hex, require_signed=False)
    assert rep.ok, rep.problems
    good = dict(new.payload)
    assert trace_payload_problems(good) == []
    for change in ({"stage_policy": "tidak-ada"}, {"stage_eps": good["stage_eps"][:3]},
                   {"stage_eps": [good["eps_share"]] + [0.0] * 3}, {"stage_eps": "semua"},
                   {"stage_eps": [float("nan")] * 4}):
        assert trace_payload_problems({**good, **change}), change
    lone = {k: v for k, v in good.items() if k != "stage_eps"}
    assert any("bersama" in t for t in trace_payload_problems(lone))
    with _registry(tmp_path / "s.db") as reg:
        stamp = reg.head().created_at
        with pytest.raises(ValueError, match="stage_eps"):
            reg.append(KIND_TRACE, {**good, "trace_no": 1, "eps_share": eps_for_trace(1e-6, 1), "created_at": stamp},
                       created_at=stamp)


def test_service_records_the_stage_policy_before_decoding(tmp_path, monkeypatch):
    from tapak.decoder import trace as trace_module
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.service import TRACE_STAGE_POLICY, ensure_keys, issue_document, trace_evidence, write_report
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    from tapak.config import load_settings

    s = load_settings()
    keys = ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:3], IssueSettings(workers=1), "uji", keys)
    evidence = extract_pdf_text((out.folder / "salinan" / out.manifest.copies[1].file).read_bytes()).encode()
    doc = out.manifest.doc_hash
    original = trace_module.trace_files
    seen = []

    def spy(items, ctx, spending=None):
        with Registry.open(s.registry_path) as reg:  # policy and stage eps are in the registry before decoding
            seen.append(reg.traces(doc)[-1])
        return original(items, ctx, spending)

    monkeypatch.setattr(trace_module, "trace_files", spy)
    outcome = trace_evidence(s, doc, "bocor.txt", evidence, keys)
    assert TRACE_STAGE_POLICY == DEFAULT_STAGE_POLICY
    entry = seen[0]
    assert entry["stage_policy"] == DEFAULT_STAGE_POLICY and math.fsum(entry["stage_eps"]) == pytest.approx(
        entry["eps_share"])
    a = outcome.attribution
    assert a.threshold.stage_policy == DEFAULT_STAGE_POLICY and a.threshold.stage_eps == entry["stage_eps"][0]
    assert [c.copy.seq for c in a.accused] == [2]
    # A single leaker explains every read position: stage 2 has nothing to weigh and names nobody.
    assert [st.stage for st in a.stages] == [2] and not a.stages[0].accused
    assert verify_registry(s.registry_path, s.public_key_path.read_text().strip()).ok
    import pymupdf

    with pymupdf.open(stream=write_report(outcome), filetype="pdf") as pdf:
        compact = "".join("".join(page.get_text() for page in pdf).split())
    assert "Tahap2:mencarianggotakoalisilainberdasarkansalinanyangsudahdituduh(#2)" in compact
    assert "--bertahapbertahap-v1" in compact


def test_loose_mode_repeats_a_staged_trace(tmp_path, issued, secret, capsys):
    from tapak import cli
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tests_support import SAMPLE

    out, manifest = issued
    mpath = tmp_path / "manifest.json"
    mpath.write_text(manifest.to_json(), encoding="utf-8")
    key = tmp_path / "rahasia.key"
    key.write_text(secret.hex(), encoding="ascii")
    evidence = tmp_path / "bocor.txt"
    evidence.write_text(extract_pdf_text((out / manifest.copies[2].file).read_bytes()), encoding="utf-8")
    base = ["--data", str(tmp_path / "data"), "trace", str(evidence), "--master", str(SAMPLE),
            "--manifest", str(mpath), "--secret", str(key), "--pelacakan-ke", "1"]
    assert cli.main(base + ["--bertahap", "--json", str(tmp_path / "b.json")]) == 0
    printed = capsys.readouterr().out
    staged = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert staged["threshold"]["stage_policy"] == DEFAULT_STAGE_POLICY and staged["stages"][0]["stage"] == 2
    assert "Tahap 2 (pelacakan bertahap)" in printed
    assert cli.main(base + ["--json", str(tmp_path / "s.json")]) == 0
    single = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert single["stages"] == [] and single["threshold"]["threshold"] < staged["threshold"]["threshold"]
    code = cli.main(["--data", str(tmp_path / "data"), "trace", str(evidence), "--doc", "a" * 16, "--bertahap"])
    assert code == 2 and "hanya untuk mode lepas" in capsys.readouterr().err


def test_cli_simulate_staged(capsys):
    from tapak import cli

    code = cli.main(["simulate", "--n", "20", "--c", "2", "--eps", "1e-3", "--trials", "3", "--coalition", "3",
                     "--strategies", "minority,majority", "--bertahap"])
    printed = capsys.readouterr().out
    assert code == 0 and "pelacakan bertahap (bertahap-v1)" in printed and "minoritas" in printed
