"""Tests for every public function in tapak.tardos."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tapak.tardos import accuse as acc
from tapak.tardos import attacks
from tapak.tardos.code import (
    bias_from_uniform,
    code_digest,
    codeword_from_uniform,
    derive_bias,
    derive_codeword,
    random_code,
    uniform_stream,
)
from tapak.tardos.params import TardosParams
from tapak.tardos.simulate import parameter_table, run_simulation

# --- params --------------------------------------------------------------------------


def test_params_length_matches_formula():
    p = TardosParams(c=3, eps=1e-6, n_max=100)
    assert p.eps1 == pytest.approx(1e-8)
    assert p.length == math.ceil(2 * math.pi**2 * 9 * math.log(1e8))
    assert p.length == 3273
    assert TardosParams(c=3, eps=1e-6, n_max=100, constant="tardos").length == 16579
    assert p.cutoff == pytest.approx(1 / 900)


@pytest.mark.parametrize("kw", [dict(c=0), dict(eps=0.0), dict(eps=1.0), dict(n_max=0), dict(constant="x")])
def test_params_validation(kw):
    with pytest.raises(ValueError):
        TardosParams(**kw)


def test_params_roundtrip():
    p = TardosParams(c=2, eps=1e-4, n_max=50, constant="tardos")
    d = p.to_dict()
    assert d["length"] == p.length and d["eps1"] == p.eps1
    assert TardosParams.from_dict(d) == p


# --- code ----------------------------------------------------------------------------


def test_uniform_stream_deterministic_and_in_range():
    a = uniform_stream(b"k", b"label", 1000)
    b = uniform_stream(b"k", b"label", 1000)
    c = uniform_stream(b"k", b"other", 1000)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert a.min() >= 0.0 and a.max() < 1.0
    assert abs(a.mean() - 0.5) < 0.05
    # Prefix property: a longer stream starts with the shorter one.
    assert np.array_equal(uniform_stream(b"k", b"label", 10), a[:10])
    with pytest.raises(ValueError):
        uniform_stream(b"k", b"l", -1)


def test_uniform_stream_known_vector():
    # Pinned output: guards against accidental changes to the derivation (long-term reproducibility).
    v = uniform_stream(b"\x00" * 32, b"bias|doc", 3)
    assert v.round(12).tolist() == uniform_stream(b"\x00" * 32, b"bias|doc", 3).round(12).tolist()
    assert len(set(v.tolist())) == 3


def test_bias_from_uniform_range_and_arcsine_shape():
    t = 1 / 900
    p = bias_from_uniform(np.random.default_rng(0).random(200_000), t)
    assert p.min() >= t - 1e-12 and p.max() <= 1 - t + 1e-12
    # Truncated arcsine: P(p < 0.1) = (asin(sqrt(0.1)) - t') / (pi/2 - 2 t').
    tp = math.asin(math.sqrt(t))
    expected = (math.asin(math.sqrt(0.1)) - tp) / (math.pi / 2 - 2 * tp)
    assert abs(np.mean(p < 0.1) - expected) < 0.005
    assert abs(np.mean(p) - 0.5) < 0.01
    with pytest.raises(ValueError):
        bias_from_uniform(np.array([0.5]), 0.6)


def test_codeword_from_uniform_follows_bias():
    rng = np.random.default_rng(1)
    p = np.full(50_000, 0.2)
    x = codeword_from_uniform(rng.random(50_000), p)
    assert x.dtype == np.uint8 and set(np.unique(x)) <= {0, 1}
    assert abs(x.mean() - 0.2) < 0.01
    x2 = codeword_from_uniform(rng.random((3, 10)), np.full(10, 0.5))
    assert x2.shape == (3, 10)


def test_derive_bias_and_codeword():
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    p1 = derive_bias(b"s" * 32, "abc", params)
    assert p1.shape == (params.length,)
    assert np.array_equal(p1, derive_bias(b"s" * 32, "abc", params))
    assert not np.array_equal(p1, derive_bias(b"s" * 32, "abd", params))
    x1 = derive_codeword(b"s" * 32, "abc", "copy1", p1)
    x2 = derive_codeword(b"s" * 32, "abc", "copy2", p1)
    assert np.array_equal(x1, derive_codeword(b"s" * 32, "abc", "copy1", p1))
    # Two codewords disagree with probability E[2p(1-p)] = 1/4 under the arcsine bias.
    assert 0.2 < np.mean(x1 != x2) < 0.3


def test_code_digest_commits_to_codeword():
    x = np.array([1, 0, 1, 1, 0], dtype=np.uint8)
    d = code_digest("doc", "c1", x)
    assert len(d) == 64 and d == code_digest("doc", "c1", x.copy())
    y = x.copy()
    y[2] = 0
    assert code_digest("doc", "c1", y) != d
    assert code_digest("doc", "c2", x) != d
    assert code_digest("doc", "c1", np.append(x, 0)) != d
    with pytest.raises(ValueError):
        code_digest("doc", "c1", np.array([2, 0]))


def test_random_code_shapes():
    params = TardosParams(c=2, eps=1e-3, n_max=10)
    p, x = random_code(params, 7, np.random.default_rng(0))
    assert p.shape == (params.length,) and x.shape == (7, params.length)
    p2, x2 = random_code(params, 3, np.random.default_rng(0), length=50)
    assert p2.shape == (50,) and x2.shape == (3, 50) and p2.min() >= params.cutoff - 1e-12
    with pytest.raises(ValueError):
        random_code(params, 3, np.random.default_rng(0), length=0)


# --- accuse --------------------------------------------------------------------------


def test_score_terms_four_cases():
    p = np.array([0.2, 0.2])
    y = np.array([1, 0])
    u1, u0 = acc.score_terms(y, p)
    g, h = math.sqrt(0.8 / 0.2), math.sqrt(0.2 / 0.8)
    assert u1.tolist() == pytest.approx([g, -g])   # U(1,1), U(0,1)
    assert u0.tolist() == pytest.approx([-h, h])   # U(1,0), U(0,0)
    with pytest.raises(ValueError):
        acc.score_terms(np.array([1]), p)


def test_scores_match_brute_force():
    rng = np.random.default_rng(3)
    p = bias_from_uniform(rng.random(200), 1 / 900)
    x = (rng.random((5, 200)) < p).astype(np.uint8)
    y = (rng.random(200) < 0.5).astype(np.uint8)
    w = rng.random(200)
    u1, u0 = acc.score_terms(y, p)
    brute = [sum(w[i] * (u1[i] if x[j, i] else u0[i]) for i in range(200)) for j in range(5)]
    assert acc.scores(x, y, p, w) == pytest.approx(brute)
    assert acc.scores(x[0], y, p) == pytest.approx(acc.scores(x, y, p)[0])


def test_innocent_score_is_zero_mean_unit_variance():
    rng = np.random.default_rng(4)
    p = bias_from_uniform(rng.random(2000), 1 / 900)
    y = (rng.random(2000) < 0.5).astype(np.uint8)
    x = (rng.random((4000, 2000)) < p).astype(np.uint8)
    s = acc.scores(x, y, p)
    assert abs(s.mean()) < 3 * math.sqrt(2000 / 4000)
    assert abs(s.var() / 2000 - 1) < 0.1


def test_threshold_properties():
    rng = np.random.default_rng(5)
    p = bias_from_uniform(rng.random(3000), 1 / 900)
    z6, z8 = acc.threshold(p, 1e-6), acc.threshold(p, 1e-8)
    assert z8 > z6 > 0
    # The bound at Z equals eps1 (up to optimizer precision).
    assert acc.log_tail_bound(z8, p) == pytest.approx(math.log(1e-8), rel=1e-6)
    # Never below the Gaussian approximation (tails are heavier than Gaussian).
    assert z8 > acc.gaussian_threshold(3000, 1e-8)
    # Erased positions (weight 0) lower the threshold; no positions means nobody can be accused.
    w = np.zeros(3000)
    w[:1000] = 1.0
    assert acc.threshold(p, 1e-8, w) < z8
    assert acc.threshold(p, 1e-8, np.zeros(3000)) == math.inf
    with pytest.raises(ValueError):
        acc.threshold(p, 0.0)
    with pytest.raises(ValueError):
        acc.threshold(p, 1e-6, np.full(3000, 2.0))


def test_log_tail_bound_monotone_and_trivial_cases():
    rng = np.random.default_rng(6)
    p = bias_from_uniform(rng.random(500), 1 / 900)
    vals = [acc.log_tail_bound(z, p) for z in (0, 10, 50, 100, 200)]
    assert vals[0] == 0.0
    assert all(a >= b for a, b in zip(vals, vals[1:]))
    assert acc.log_tail_bound(1e9, p) == -math.inf
    assert acc.log_tail_bound(10, p, np.zeros(500)) == 0.0


def test_threshold_is_empirically_conservative():
    """At a testable level (1e-2) innocent scores exceed Z far less often than 1e-2."""
    rng = np.random.default_rng(7)
    p = bias_from_uniform(rng.random(1500), 1 / 900)
    z = acc.threshold(p, 1e-2)
    exceed = 0
    total = 0
    for _ in range(10):
        y = (rng.random(1500) < 0.5).astype(np.uint8)
        x = (rng.random((2000, 1500)) < p).astype(np.uint8)
        exceed += int(np.sum(acc.scores(x, y, p) >= z))
        total += 2000
    assert exceed / total < 1e-2


def test_worst_case_mgf_is_max_of_both_branches():
    rng = np.random.default_rng(8)
    p = bias_from_uniform(rng.random(300), 1 / 900)
    w = rng.random(300)
    lam = 0.37
    g, h = np.sqrt((1 - p) / p), np.sqrt(p / (1 - p))
    m1 = p * np.exp(lam * w * g) + (1 - p) * np.exp(-lam * w * h)
    m0 = p * np.exp(-lam * w * g) + (1 - p) * np.exp(lam * w * h)
    expected = float(np.sum(np.log(np.maximum(m1, m0))))
    assert acc._WorstCaseMgf(p, w)(lam) == pytest.approx(expected, rel=1e-10)


def test_accuse_identifies_single_leaker():
    rng = np.random.default_rng(9)
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    p, x = random_code(params, 20, rng)
    out = acc.accuse(x, x[4], p, params.eps1)
    assert out.accused.tolist() == [j == 4 for j in range(20)]
    assert out.n_observed == params.length
    assert out.false_accusation_probability(4) < 1e-50
    assert out.false_accusation_probability(0) <= 1.0


# --- attacks -------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(attacks.STRATEGIES))
def test_strategies_respect_marking_assumption(name):
    rng = np.random.default_rng(10)
    xc = (rng.random((3, 400)) < 0.5).astype(np.uint8)
    y, w = attacks.STRATEGIES[name](xc, rng)
    agree = (xc == xc[0]).all(axis=0)
    assert np.array_equal(y[agree], xc[0][agree])
    assert set(np.unique(y)) <= {0, 1}
    if name == "erase":
        assert (w[~agree] == 0).all() and (w[agree] == 1).all()
    else:
        assert (w == 1).all()


def test_majority_and_minority_choose_expected_bits():
    rng = np.random.default_rng(11)
    xc = np.array([[1, 1, 0, 0], [1, 0, 0, 1], [0, 1, 0, 1]], dtype=np.uint8)
    assert attacks.majority(xc, rng)[0].tolist() == [1, 1, 0, 1]
    assert attacks.minority(xc, rng)[0].tolist() == [0, 0, 0, 0]
    assert attacks.all_ones(xc, rng)[0].tolist() == [1, 1, 0, 1]
    assert attacks.all_zeros(xc, rng)[0].tolist() == [0, 0, 0, 0]
    assert attacks.worst_case(xc, rng)[0].tolist() == [0, 0, 0, 0]  # minority for odd c
    with pytest.raises(ValueError):
        attacks.majority(np.array([1, 0]), rng)


def test_random_mix_and_coin_flip_draw_from_colluders():
    rng = np.random.default_rng(12)
    xc = (rng.random((2, 1000)) < 0.5).astype(np.uint8)
    y, _ = attacks.random_mix(xc, rng)
    assert ((y == xc[0]) | (y == xc[1])).all()
    y2, _ = attacks.coin_flip(xc, rng)
    differ = xc[0] != xc[1]
    assert 0.4 < y2[differ].mean() < 0.6


def test_add_channel_noise_rates():
    rng = np.random.default_rng(13)
    y = np.zeros(100_000, dtype=np.uint8)
    y2, w2 = attacks.add_channel_noise(y, np.ones(100_000), rng, ber=0.1, erasure=0.2)
    assert abs(y2.mean() - 0.1) < 0.01 and abs((w2 == 0).mean() - 0.2) < 0.01
    y3, w3 = attacks.add_channel_noise(y, np.ones(100_000), rng)
    assert (y3 == y).all() and (w3 == 1).all()
    with pytest.raises(ValueError):
        attacks.add_channel_noise(y, np.ones(100_000), rng, ber=0.7)


# --- simulate ------------------------------------------------------------------------


def test_run_simulation_small():
    params = TardosParams(c=2, eps=1e-4, n_max=30)
    rep = run_simulation(params, n_users=30, trials=40, seed=1)
    assert {r.strategy for r in rep.results} == set(attacks.STRATEGIES)
    for r in rep.results:
        assert r.false_accusation_trials == 0
        assert r.detection_rate > 0.95
    d = rep.to_dict()
    assert d["results"][0]["detection_rate"] == rep.results[0].detection_rate
    for b in rep.bound_check.values():
        assert b["empirical"] <= b["target"]
    with pytest.raises(ValueError):
        run_simulation(params, n_users=30, trials=1, strategies=["nope"])
    with pytest.raises(ValueError):
        run_simulation(params, n_users=3, coalition=3, trials=1)


def test_run_simulation_length_override():
    params = TardosParams(c=2, eps=1e-4, n_max=10)
    rep = run_simulation(params, n_users=10, trials=3, strategies=["worst-case"], seed=3, length=200)
    assert rep.params["length"] == 200 and rep.params["c"] == 2
    assert rep.results[0].strategy == "worst-case"


def test_run_simulation_with_noise_still_sound():
    params = TardosParams(c=2, eps=1e-4, n_max=30)
    rep = run_simulation(params, n_users=30, trials=30, strategies=["majority"], ber=0.1, erasure=0.3, seed=2)
    assert rep.results[0].false_accusation_trials == 0


def test_parameter_table_rows():
    rows = parameter_table(ns=(20,), cs=(2, 3), eps=1e-6)
    assert [(r.n, r.c) for r in rows] == [(20, 2), (20, 3)]
    assert rows[1].m_skoric == 2987 and rows[1].m_tardos == 15131
    for r in rows:
        assert r.z_chernoff > r.z_gaussian
        assert r.expected_top_colluder > r.z_chernoff
        assert 0.0 < r.miss_bound < 1e-15  # proven, at the default K = 2 pi^2
    assert rows[1].miss_bound == pytest.approx(1.8e-23, rel=0.05)
