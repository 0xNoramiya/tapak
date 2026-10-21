"""Tardos accusation: symmetric score, rigorous threshold, false-accusation bound.

Score (symmetric version, Skoric et al.): for leaked bit y_i, recipient bit x_ji, bias p_i

    U(1, 1, p) =  sqrt((1-p)/p)     U(1, 0, p) = -sqrt(p/(1-p))
    U(0, 0, p) =  sqrt(p/(1-p))     U(0, 1, p) = -sqrt((1-p)/p)

    S_j = sum_i w_i * U(y_i, x_ji, p_i)

``w_i`` is a reliability weight in [0, 1] supplied by the decoder (1 for a certain bit,
0 for an erased position). Plain Tardos is the special case w = 1 everywhere.

Why the threshold is rigorous. An innocent recipient's codeword is independent of the
leaked word y (the coalition never saw it) and of the weights (the decoder computes them
without looking at any codeword). Given p, the innocent score is then a sum of independent
two-point variables. The Chernoff bound

    P(S >= z) <= exp( min_{lam > 0} [ Lambda(lam) - lam * z ] )
    Lambda(lam) = sum_i log max_{y_i in {0,1}} E[exp(lam * w_i * U(y_i, X_i, p_i))]

holds for every possible y because it takes the worst case over y_i at each position. The
threshold Z is the smallest z with bound <= eps1. It depends only on (p, w, eps1), so it is
fixed before any recipient's score is computed. No Gaussian approximation is involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
_LAMBDA_LO = 1e-7
_LAMBDA_HI = 60.0


def score_terms(y: np.ndarray, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (u1, u0): the score contribution for x_ji = 1 and x_ji = 0 at each position."""
    y = np.asarray(y)
    p = np.asarray(p, dtype=np.float64)
    if y.shape != p.shape:
        raise ValueError("y and p must have the same shape")
    g = np.sqrt((1.0 - p) / p)
    h = np.sqrt(p / (1.0 - p))
    s = np.where(y > 0, 1.0, -1.0)
    return s * g, -s * h


def scores(
    codewords: np.ndarray,
    y: np.ndarray,
    p: np.ndarray,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Accusation score S_j for every row of ``codewords`` (shape n x m, or m for one user)."""
    x = np.asarray(codewords)
    w = np.ones(len(p)) if weights is None else np.asarray(weights, dtype=np.float64)
    u1, u0 = score_terms(y, p)
    return x @ (w * (u1 - u0)) + float(np.sum(w * u0))


class _WorstCaseMgf:
    """Lambda(lam) = sum_i log of the worst-case innocent moment generating function.

    The worst case over y_i has a closed form. With q = min(p, 1 - p), the innocent score
    at a position is +sqrt((1-q)/q) with probability q and -sqrt(q/(1-q)) otherwise, i.e.
    the leaked bit equals the rarer symbol. Proof sketch: for p < 1/2 the two candidate
    MGFs differ by 2k(sinh(lam*w*g)/g - sinh(lam*w*h)/h) with k = sqrt(p(1-p)), g > h,
    and sinh(x)/x is increasing, so y_i = 1 dominates for every lam > 0 (symmetric for
    p > 1/2).
    """

    def __init__(self, p: np.ndarray, w: np.ndarray) -> None:
        q = np.minimum(p, 1.0 - p)
        self.log_q = np.log(q)
        self.log_1mq = np.log1p(-q)
        self.w_big = w * np.sqrt((1.0 - q) / q)
        self.w_small = w * np.sqrt(q / (1.0 - q))
        self.max_score = float(np.sum(self.w_big))

    def __call__(self, lam: float) -> float:
        return float(
            np.sum(np.logaddexp(self.log_q + lam * self.w_big, self.log_1mq - lam * self.w_small))
        )


def _golden_min(f, lo: float, hi: float, iters: int = 70) -> tuple[float, float]:
    """Minimize a unimodal function on [lo, hi]; returns (argmin, min)."""
    a, b = lo, hi
    c = b - _GOLDEN * (b - a)
    d = a + _GOLDEN * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _GOLDEN * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + _GOLDEN * (b - a)
            fd = f(d)
    return (c, fc) if fc < fd else (d, fd)


def _active(p: np.ndarray, weights: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(p, dtype=np.float64)
    w = np.ones_like(p) if weights is None else np.asarray(weights, dtype=np.float64)
    if w.shape != p.shape:
        raise ValueError("weights and p must have the same shape")
    if (w < 0).any() or (w > 1).any():
        raise ValueError("weights must be in [0, 1]")
    keep = w > 0
    return p[keep], w[keep]


def log_tail_bound(z: float, p: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Natural log of the Chernoff upper bound on P(innocent score >= z). Always <= 0."""
    pa, wa = _active(p, weights)
    if pa.size == 0 or z <= 0:
        return 0.0
    mgf = _WorstCaseMgf(pa, wa)
    if z > mgf.max_score:
        return -math.inf

    # Lambda(lam) - lam*z is convex in lam; search on log(lam) where it is unimodal too.
    def obj(t: float) -> float:
        lam = math.exp(t)
        return mgf(lam) - lam * z

    _, best = _golden_min(obj, math.log(_LAMBDA_LO), math.log(_LAMBDA_HI))
    return min(0.0, best)


def threshold(p: np.ndarray, eps1: float, weights: np.ndarray | None = None) -> float:
    """Smallest score Z such that P(innocent score >= Z) <= eps1 by the Chernoff bound.

    Z = min_{lam > 0} (Lambda(lam) + ln(1/eps1)) / lam. Returns +inf when no position is
    observed (nobody can be accused without evidence).
    """
    if not 0.0 < eps1 < 1.0:
        raise ValueError("eps1 must be in (0, 1)")
    pa, wa = _active(p, weights)
    if pa.size == 0:
        return math.inf
    log_inv = math.log(1.0 / eps1)
    mgf = _WorstCaseMgf(pa, wa)

    def obj(t: float) -> float:
        lam = math.exp(t)
        return (mgf(lam) + log_inv) / lam

    _, z = _golden_min(obj, math.log(_LAMBDA_LO), math.log(_LAMBDA_HI))
    # A threshold above the largest achievable score means "cannot accuse anyone".
    return z if z <= mgf.max_score else math.inf


def gaussian_threshold(n_observed: float, eps1: float) -> float:
    """Gaussian approximation sqrt(n) * Phi^-1(1 - eps1); shown for comparison only."""
    from scipy.stats import norm

    return float(norm.isf(eps1) * math.sqrt(n_observed))


@dataclass
class AccusationOutcome:
    """Result of running the accusation against a list of codewords.

    Attributes:
        scores: S_j per recipient.
        threshold: Z, fixed from (p, weights, eps1) before scores were computed.
        log_bounds: natural log of the per-recipient bound P(innocent >= S_j).
        accused: boolean mask S_j >= Z.
        eps1: per-recipient false-accusation target used for Z.
        n_observed: number of positions with non-zero weight.
    """

    scores: np.ndarray
    threshold: float
    log_bounds: np.ndarray
    accused: np.ndarray
    eps1: float
    n_observed: int
    effective_positions: float = field(default=0.0)

    def false_accusation_probability(self, j: int) -> float:
        """Bound on P(some innocent among the others reaches S_j): (n-1) * bound_j, capped at 1."""
        n_others = max(len(self.scores) - 1, 1)
        return float(min(1.0, n_others * math.exp(self.log_bounds[j])))


def accuse(
    codewords: np.ndarray,
    y: np.ndarray,
    p: np.ndarray,
    eps1: float,
    weights: np.ndarray | None = None,
) -> AccusationOutcome:
    """Fix the threshold first, then score every recipient and compare."""
    w = np.ones(len(p)) if weights is None else np.asarray(weights, dtype=np.float64)
    z = threshold(p, eps1, w)
    s = scores(codewords, y, p, w)
    bounds = np.array([log_tail_bound(float(v), p, w) for v in s])
    return AccusationOutcome(
        scores=s,
        threshold=z,
        log_bounds=bounds,
        accused=s >= z,
        eps1=eps1,
        n_observed=int(np.count_nonzero(w > 0)),
        effective_positions=float(np.sum(w**2)),
    )
