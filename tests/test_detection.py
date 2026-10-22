"""Tests for tapak.tardos.detection: the proven bound on the probability that a coalition escapes."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import minimize_scalar

from tapak.tardos import accuse as acc
from tapak.tardos import attacks
from tapak.tardos import detection as det
from tapak.tardos.code import bias_from_uniform, random_code
from tapak.tardos.detection import (
    LengthRequirement,
    MissBound,
    expected_coalition_score,
    min_length,
    miss_bound,
    proven_miss_probability,
    worst_case_strategy,
)
from tapak.tardos.params import TardosParams
from tapak.tardos.simulate import run_simulation
from tapak.tardos.spending import TraceSpending

C2 = TardosParams(c=2, eps=1e-6, n_max=20)
C3 = TardosParams(c=3, eps=1e-6, n_max=20)


def _colluder_sample(c: int, cutoff: float, n: int, rng: np.random.Generator):
    p = bias_from_uniform(rng.random(n), cutoff)
    z = rng.binomial(c, p)
    g, h = np.sqrt((1 - p) / p), np.sqrt(p / (1 - p))
    return p, z, z * g - (c - z) * h  # T(z, 1, p); T(z, 0, p) is its negative


# --- the bound -------------------------------------------------------------------------


def test_miss_bound_in_unit_interval_and_decreasing_in_length():
    lengths = [300, 464, 516, 592, 669, 900, C2.length]
    bounds = [miss_bound(C2, length=m) for m in lengths]
    assert all(isinstance(b, MissBound) and b.length == m for b, m in zip(bounds, lengths))
    vals = [b.bound for b in bounds]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert vals[0] == 1.0  # far too short: nothing proven
    assert all(a >= b for a, b in zip(vals, vals[1:]))
    assert vals[-1] < 1e-15  # default K = 2 pi^2
    assert all(b.log10_bound <= 0 and b.quadrature_error < 1e-8 for b in bounds)
    assert bounds[-1].log10_bound == pytest.approx(math.log10(vals[-1]), rel=1e-9)


def test_miss_bound_increases_with_coalition_size():
    logs = [miss_bound(C3, k).log10_bound for k in (1, 2, 3, 4)]
    assert all(a < b for a, b in zip(logs, logs[1:]))
    # Coalitions smaller than c are covered by taking the maximum, which sits at c' = c.
    assert proven_miss_probability(C3) == pytest.approx(miss_bound(C3, 3).bound, rel=1e-12)
    assert proven_miss_probability(C3) == max(miss_bound(C3, k).bound for k in (1, 2, 3))
    # A code for larger c at the same length is easier to escape (one more possible colluder).
    assert proven_miss_probability(C3, length=1000) > proven_miss_probability(C2, length=1000)


def test_miss_bound_threshold_overrides_and_validation():
    base = miss_bound(C3, length=1100)
    assert base.lam0 is not None and base.z is None and base.eps1 == C3.eps1
    # A smaller eps1 (the first logged trace spends 61 % of eps) raises Z, so the bound grows.
    logged = miss_bound(C3, length=1100, eps1=TraceSpending.logged(C3.eps, 1).eps1(C3.n_max))
    assert logged.bound > base.bound
    # Fixed thresholds: higher Z, larger bound; a typical Z gives a bound close to the real one.
    p = random_code(C3, 1, np.random.default_rng(0), length=1100)[0]
    z_typ = acc.threshold(p, C3.eps1)
    fixed = miss_bound(C3, length=1100, z=z_typ)
    assert fixed.lam0 is None and fixed.z == z_typ
    assert miss_bound(C3, length=1100, z=1.2 * z_typ).bound > fixed.bound
    assert 0.2 < fixed.bound / base.bound < 5
    for kw in (dict(coalition=0), dict(length=0), dict(eps1=0.0), dict(eps1=1.0), dict(z=-1.0), dict(z=math.inf)):
        with pytest.raises(ValueError):
            miss_bound(C3, **kw)


def test_tapak_threshold_never_exceeds_the_bounded_objective():
    """Step 2: Z(p) <= (1 + Z_SLACK) (Lambda_p(lam0) + L) / lam0 for every lam0, also with erasures."""
    rng = np.random.default_rng(1)
    log_inv = math.log(1 / C3.eps1)
    for k in range(20):
        p = bias_from_uniform(rng.random(C3.length), C3.cutoff)
        w = np.ones_like(p) if k % 2 == 0 else (rng.random(p.size) < 0.6).astype(float)
        z = acc.threshold(p, C3.eps1, w)
        keep = w > 0
        mgf = acc._WorstCaseMgf(p[keep], w[keep])

        def objective(u: float) -> float:
            return (mgf(math.exp(u)) + log_inv) / math.exp(u)

        # Tight minimum over TAPAK's whole lambda range: coarse grid, then a bounded refinement.
        us = np.linspace(math.log(det._LAM_RANGE[0]), math.log(det._LAM_RANGE[1]), 400)
        i = int(np.argmin([objective(u) for u in us]))
        res = minimize_scalar(objective, bounds=(us[max(i - 1, 0)], us[min(i + 1, us.size - 1)]),
                              method="bounded", options={"xatol": 1e-12})
        tight = min(float(res.fun), objective(us[i]))
        assert z <= (1 + det.Z_SLACK) * tight
        assert z >= tight * (1 - 1e-12)  # and it is the minimum, not a loose value


def test_per_position_factor_matches_monte_carlo():
    """G(alpha) is attained by the Chernoff choice and dominates any other per-z rule."""
    rng = np.random.default_rng(2)
    c, t = 3, C3.cutoff
    itg = det._Integrand(c, t, det._PANELS, det._ORDER)
    alpha, lam0 = 0.12, 0.09
    kappa = c * (1 + det.Z_SLACK)
    log_g, choice = itg.log_g(alpha, alpha * kappa * itg.log_mgf(lam0) / lam0)
    p, z, t1 = _colluder_sample(c, t, 400_000, rng)
    q = np.minimum(p, 1 - p)
    log_m = np.logaddexp(np.log(q) + lam0 * np.sqrt((1 - q) / q), np.log1p(-q) - lam0 * np.sqrt(q / (1 - q)))
    psi = kappa * log_m / lam0

    def factor(rule: np.ndarray) -> tuple[float, float]:
        y = rule[z]
        v = np.exp(-alpha * (np.where(y == 1, t1, -t1) - psi))
        return float(v.mean()), float(v.std() / math.sqrt(v.size))

    mean, se = factor(np.array(choice))
    assert abs(mean - math.exp(log_g)) < 5 * se
    for rule in ([0, 1, 0, 1], [0, 0, 0, 1], [0, 1, 1, 1]):  # minority, all-0, all-1
        assert factor(np.array(rule))[0] < math.exp(log_g) + 5 * se


def test_erasing_a_detectable_position_never_beats_the_maximum():
    """Step 5a: at 0 < z < c the maximized factor is at least 1, the factor of an erasure."""
    for c in (2, 3, 5):
        itg = det._Integrand(c, 1 / (300 * c), det._PANELS, det._ORDER)
        for alpha, lam0 in ((0.01, 0.2), (0.1, 0.09), (0.5, 0.05)):
            shift = alpha * c * (1 + det.Z_SLACK) * itg.log_mgf(lam0) / lam0
            a1 = np.log(np.sum(np.exp(itg.base - alpha * itg.t1 + shift), axis=1))
            a0 = np.log(np.sum(np.exp(itg.base + alpha * itg.t1 + shift), axis=1))
            log_pz = np.log(np.sum(np.exp(itg.base), axis=1))
            assert (np.maximum(a0, a1)[1:c] >= log_pz[1:c]).all()


def test_bound_dominates_monte_carlo_where_misses_are_frequent():
    """At a short code (bound about 0.79) most attacks miss often, yet none above the bound."""
    m = 480
    bound = proven_miss_probability(C2, length=m)
    assert 0.3 < bound < 1.0
    rep = run_simulation(C2, n_users=20, trials=200, seed=11, bound_levels=(), length=m)
    assert rep.params["length"] == m
    misses = {r.strategy: 1.0 - r.detection_rate for r in rep.results}
    assert set(misses) == set(attacks.STRATEGIES)
    assert all(rate <= bound for rate in misses.values()), (bound, misses)
    assert sum(rate >= 0.05 for rate in misses.values()) >= 5, misses  # the comparison is not vacuous
    assert all(r.false_accusation_trials == 0 for r in rep.results)


def _balancing_attack(c: int, cutoff: float):
    """Cross-position adversary that keeps the colluders' estimated scores level.

    The coalition does not see p, so it takes E[U(y, b, p) | z] (on the module's quadrature
    nodes) as the expected contribution of each choice, visits its detectable positions in a
    random order and leaks the bit that keeps the highest running estimate lowest. A miss needs
    every colluder below Z, so levelling the scores is what an evading coalition wants, and the
    rule depends on all positions, which none of the per-position rules in ``attacks`` does.
    """
    r, logw = det._nodes(cutoff, det._PANELS, det._ORDER)
    p = np.sin(r) ** 2
    g, h = np.sqrt((1 - p) / p), np.sqrt(p / (1 - p))
    eu = np.zeros((c + 1, 2, 2))  # [z, leaked bit, colluder bit]
    for z in range(c + 1):
        w = np.exp(logw + z * np.log(p) + (c - z) * np.log1p(-p))
        eg, eh = np.sum(w * g) / np.sum(w), np.sum(w * h) / np.sum(w)
        eu[z, 1, 1], eu[z, 1, 0], eu[z, 0, 0], eu[z, 0, 1] = eg, -eh, eh, -eg

    def attack(xc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        xc = np.asarray(xc, dtype=np.int64)
        ones = xc.sum(axis=0)
        y = (ones == c).astype(np.uint8)  # marking assumption; detectable positions below
        run = np.zeros(c)
        for i in rng.permutation(np.flatnonzero((ones > 0) & (ones < c))):
            up1, up0 = run + eu[ones[i], 1, xc[:, i]], run + eu[ones[i], 0, xc[:, i]]
            y[i] = int(up1.max() < up0.max() or (up1.max() == up0.max() and rng.random() < 0.5))
            run = up1 if y[i] else up0
        return y, np.ones(xc.shape[1])

    return attack


def test_bound_dominates_a_cross_position_balancing_attack():
    """The proof covers strategies that use other positions; this one misses more than any in attacks."""
    m = 464  # proven bound about 0.9 for c = 2, N = 20
    bound = proven_miss_probability(C2, length=m)
    attack = _balancing_attack(2, C2.cutoff)
    rng = np.random.default_rng(21)
    trials, misses = 300, 0
    for _ in range(trials):
        p, x = random_code(C2, 2, rng, length=m)
        y, w = attack(x, rng)
        ones = x.sum(axis=0)
        assert (y[ones == 0] == 0).all() and (y[ones == 2] == 1).all()
        misses += int(not np.any(acc.scores(x, y, p, w) >= acc.threshold(p, C2.eps1)))
    assert misses / trials <= bound, (bound, misses)
    assert misses / trials > 0.1, misses  # a strong attack, so the comparison is not vacuous


@pytest.mark.slow
def test_bound_dominates_monte_carlo_c3_several_lengths():
    for m in (973, 1070, 1212):
        bound = proven_miss_probability(C3, length=m)
        rep = run_simulation(C3, n_users=20, trials=600, seed=m, bound_levels=(), length=m)
        assert all(1.0 - r.detection_rate <= bound for r in rep.results)


# --- worst case per z ------------------------------------------------------------------


def test_expected_coalition_score_closed_form():
    rng = np.random.default_rng(3)
    c, t = 3, 1 / 900
    ez = expected_coalition_score(c, t)
    assert ez.shape == (c + 1, 2) and np.allclose(ez[:, 0], -ez[:, 1])
    _, z, t1 = _colluder_sample(c, t, 2_000_000, rng)
    for k in range(c + 1):
        sel = t1[z == k]
        assert abs(sel.mean() - ez[k, 1]) < 5 * sel.std() / math.sqrt(sel.size)
    # Forced positions carry the expected score; per position it sums to about 2/pi.
    pz = np.bincount(z, minlength=c + 1) / z.size
    assert pz[0] * ez[0, 0] + pz[c] * ez[c, 1] == pytest.approx(2 / (math.pi - 4 * math.asin(math.sqrt(t))), rel=0.01)
    with pytest.raises(ValueError):
        expected_coalition_score(0, t)
    with pytest.raises(ValueError):
        expected_coalition_score(3, 0.5)


@pytest.mark.parametrize("c", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("t", [1 / 1800, 1 / 900, 0.2])
def test_worst_case_strategy_is_minority_with_coin_on_ties(c, t):
    q = worst_case_strategy(c, t)
    assert q.shape == (c + 1,) and q[0] == 0.0 and q[c] == 1.0  # marking assumption
    for z in range(1, c):
        assert q[z] == (1.0 if 2 * z < c else 0.0 if 2 * z > c else 0.5)
    ez = expected_coalition_score(c, t)
    for z in range(1, c):
        chosen = ez[z, 1] if q[z] == 1 else ez[z, 0]
        assert chosen <= min(ez[z]) + 1e-15


def test_worst_case_attack_respects_marking_and_follows_the_table():
    rng = np.random.default_rng(4)
    for c in (2, 3, 4):
        xc = (rng.random((c, 3000)) < 0.5).astype(np.uint8)
        y, w = attacks.worst_case(xc, rng)
        ones = xc.sum(axis=0)
        assert (w == 1).all()
        assert (y[ones == 0] == 0).all() and (y[ones == c] == 1).all()
        assert (y[(2 * ones < c) & (ones > 0)] == 1).all() and (y[(2 * ones > c) & (ones < c)] == 0).all()
        tie = 2 * ones == c
        if tie.any():
            assert 0.4 < y[tie].mean() < 0.6
    # Same leaked word as minority for odd c, without drawing from the random stream.
    xc = (np.random.default_rng(5).random((3, 500)) < 0.5).astype(np.uint8)
    r1, r2 = np.random.default_rng(6), np.random.default_rng(6)
    assert np.array_equal(attacks.worst_case(xc, r1)[0], attacks.minority(xc, np.random.default_rng(0))[0])
    assert r1.random() == r2.random()


def test_chernoff_choice_is_reported_per_z():
    b = miss_bound(C3, 3)
    assert len(b.chernoff_choice) == 4 and b.chernoff_choice[0] == 0 and b.chernoff_choice[-1] == 1
    assert b.alpha > 0 and b.lam0 is not None and 0 < b.lam0 < 1


# --- shortest code ---------------------------------------------------------------------


def test_min_length_meets_delta_and_one_shorter_does_not():
    req = min_length(2, 1e-6, 20, 0.5)
    assert isinstance(req, LengthRequirement)
    assert req.bound <= 0.5 < req.bound_below
    assert proven_miss_probability(C2, length=req.length) <= 0.5 < proven_miss_probability(C2, length=req.length - 1)
    assert req.k_constant == pytest.approx(req.length / (4 * math.log(1 / C2.eps1)))
    assert req.length < C2.length  # the default K = 2 pi^2 is far longer than this target needs
    with pytest.raises(ValueError):
        min_length(2, 1e-6, 20, 1.0)


@pytest.mark.slow
def test_min_length_for_tight_targets():
    for c in (2, 3):
        req = min_length(c, 1e-6, 100, 1e-3)
        assert req.bound <= 1e-3 < req.bound_below
        assert req.k_constant < 2 * math.pi**2
