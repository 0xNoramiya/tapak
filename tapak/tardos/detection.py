"""Proven, non-asymptotic upper bound on the probability that a coalition escapes detection.

The false-accusation side of TAPAK is rigorous (``accuse.py``). This module does the same for
detection: it computes, for the actual parameters (code length m, coalition size c', bias
cutoff t, the truncated arcsine bias density of ``code.py`` and the threshold Z that
``accuse.threshold`` fixes for a full hard-decision read), a number B such that

    P(no colluder reaches Z) <= B

for every collusion strategy that obeys the marking assumption. The probability is over the
draw of the code (bias vector and codewords) and the coalition's own randomness, for any
fixed coalition of c' recipients. Nothing here is asymptotic or Gaussian; the only numerics
are a one-dimensional quadrature (checked by refinement, see below) and an optimizer whose
inaccuracy can only make B larger.

Derivation
----------
Notation as in ``accuse.py``: g(p) = sqrt((1-p)/p), h(p) = sqrt(p/(1-p)), and the symmetric
score U(1,1,p) = g, U(1,0,p) = -h, U(0,0,p) = h, U(0,1,p) = -g. Let the coalition C have c'
members, let z_i be the number of ones among their bits at position i and y the forged word.
The coalition's total score is

    sum_{j in C} S_j = sum_i T_i,   T_i = T(z_i, y_i, p_i) = z_i U(y_i,1,p_i) + (c'-z_i) U(y_i,0,p_i),

so T_i depends on position i only through (z_i, y_i, p_i). Note T(z,0,p) = -T(z,1,p).

1. Factorization. The strategy is y = f(X_C, R) with R independent of the code: it may use
   every position, be randomized and position dependent, but it does not see p (the code
   secret). Given X_C, the p_i are independent and p_i depends on X_C only through z_i,
   because the joint density is prod_i f(p_i) p_i^{z_i} (1-p_i)^{c'-z_i}. For alpha > 0 and
   any function psi,

       E[exp(-alpha sum_i (T_i - psi(p_i))) | X_C, R] = prod_i E[exp(-alpha (T(z_i,y_i,p_i) - psi(p_i))) | z_i]
                                                      <= prod_i H(z_i),

   with H(z) = max over the y allowed for z of E[exp(-alpha (T(z,y,p) - psi(p))) | z]. The
   marking assumption allows only y = 0 for z = 0 and only y = 1 for z = c'. The columns of
   X_C are independent, so taking the expectation over X_C gives G(alpha)^m with
   G(alpha) = sum_z P(z) H(z). A randomized choice of y only averages the two candidates, so
   the max over the deterministic choices covers it.

2. The threshold is random. TAPAK's Z(p) = min over lam in [1e-7, 60] of (Lambda_p(lam) + L) / lam,
   with L = ln(1/eps1) and Lambda_p(lam) = sum_i log M(lam, p_i), M the worst-case innocent
   moment generating function of ``accuse._WorstCaseMgf``. For any fixed lam0 in that range,
   Z(p) <= (1 + delta) (sum_i phi(p_i) + L / lam0) with phi(p) = log M(lam0, p) / lam0, where
   delta = 1e-9 covers the golden-section search and rounding (``Z_SLACK``). If Z(p) is
   reported as infinite (above the largest possible score), no colluder can reach the
   finite search value either, and the inclusion below still holds.

3. Markov. If no colluder reaches Z, every S_j < Z, so sum_i T_i < c' Z(p). With
   psi = c' (1 + delta) phi and K0 = c' (1 + delta) L / lam0 the miss event implies
   sum_i (T_i - psi(p_i)) < K0, hence

       P(miss) <= exp(alpha K0) G(alpha)^m   for every alpha > 0 and lam0 in [1e-7, 60].

   ``miss_bound`` minimizes over (alpha, lam0). Any (alpha, lam0) gives a valid bound, so an
   imperfect optimizer only loosens it. With a fixed threshold z (``z=`` argument) the same
   argument holds with psi = 0 and K0 = c' z.

4. Numerics. E[ . | z] P(z) is an integral over the bias. With p = sin^2(r) the code draws r
   uniformly on [t', pi/2 - t'], sin^2(t') = t, so G is a sum over z of maxima of integrals
   of smooth functions of r. They are computed with composite Gauss-Legendre quadrature in
   log space, panels graded towards both ends where g or h is large. At the optimum the
   quadrature is repeated on a grid with twice as many panels, and m times the difference in
   log G, plus ``FLOAT_SLACK`` = 1e-14 per position, is added to the log bound
   (``MissBound.quadrature_error``; about 1e-10 at TAPAK's parameters). The refinement
   difference alone can be exactly 0 while the computed log G is still a few ulp below the
   exact value; against a 40-digit mpmath reference in p (not r) the error of log G was at
   most 5e-16 at the optimum for c' = 1 to 5, default and short codes, so the per-position
   slack covers floating-point rounding and the 2^-53 grid of the uniforms that draw r.

5. Erasures. A position with weight 0 drops out of the scores and of Z(p, w)
   (``accuse._active``), so step 2 holds with the sum over observed positions only.
   (a) Erasures by the coalition where their bits differ (0 < z < c', the ``erase`` attack)
   are already covered: an erased position contributes the factor 1, and H(z) >= 1 there.
   Indeed log M >= 0 (Jensen, the innocent score has mean 0), so psi >= 0, and the y with
   E[T | z] <= 0 (one exists since T(z,0,p) = -T(z,1,p)) has
   E[exp(-alpha (T - psi)) | z] >= exp(alpha E[psi - T | z]) >= 1.
   (b) Erasures chosen independently of the code (a missing page, an unreadable region):
   given the erasure pattern the read is a full read of the m' observed positions, so the
   bound with ``length=m'`` applies.

Worst-case strategy per z. With the arcsine density f(p) = 1 / (N0 sqrt(p(1-p))) on
[t, 1-t], N0 = pi - 4 asin(sqrt(t)), the expected score has a closed form:

    P(z) E[T(z,1,p) | z] = C(c',z) / N0 * [ (1-t)^z t^(c'-z) - t^z (1-t)^(c'-z) ],

because f(p) P(z|p) T(z,1,p) is C(c',z)/N0 times the derivative of p^z (1-p)^(c'-z). For
0 < z < c' this is positive exactly when z > c'/2, for every t in (0, 1/2). The y that
minimizes E[T | z] is therefore the minority bit (a tie at z = c'/2, where both choices give
0). ``worst_case_strategy`` returns that table and ``attacks.worst_case`` plays it. Its
expected score per detectable position is only O(t) below zero; what the Chernoff bound is
sensitive to is the lower tail, and ``MissBound.chernoff_choice`` reports the y attaining the
maximum in G at the optimum (the majority bit at TAPAK's parameters). Both rules are in
``attacks.STRATEGIES`` and the bound covers every rule. Neither is the most evasive
strategy: a miss needs every colluder below Z, and a coalition that uses its other positions
to keep the members' estimated scores level misses up to about 4 times as often on short
codes (``research/deteksi/penyeimbang.py``), still below the bound, which covers it too.

Coalitions smaller than c. ``proven_miss_probability`` returns the maximum of the bound over
c' = 1, ..., c, so it covers every coalition of at most c recipients.

Scope. The bound is for hard-decision reads (weights 0 or 1) with the threshold TAPAK
computes for that read. Soft weights (the decoder's tanh(|LLR|/2)), bit errors, and erasures
that target positions where the colluders' bits agree are not covered; those cases are still
only measured by simulation. It also assumes that the coalition learns nothing about p
beyond its own bits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from tapak.tardos.params import TardosParams

# Relative slack between TAPAK's numerically minimized threshold and the Chernoff objective
# at a fixed lam0 (step 2 of the derivation).
Z_SLACK = 1e-9
# Per-position allowance in log G for floating-point rounding and the 2^-53 grid of the
# uniforms that draw the bias (step 4 of the derivation), added with the quadrature check.
FLOAT_SLACK = 1e-14
# TAPAK's threshold search range for lambda (``accuse._LAMBDA_LO`` / ``_LAMBDA_HI``).
_LAM_RANGE = (1e-7, 60.0)
_ALPHA_RANGE = (1e-7, 20.0)
_PANELS = 24
_ORDER = 24


def _check_coalition(coalition: int) -> int:
    if isinstance(coalition, bool) or int(coalition) != coalition or coalition < 1:
        raise ValueError("ukuran koalisi minimal 1")
    return int(coalition)


def _check_cutoff(cutoff: float) -> float:
    if not 0.0 < cutoff < 0.5:
        raise ValueError("batas bias harus di antara 0 dan 0,5")
    return float(cutoff)


def worst_case_strategy(coalition: int, cutoff: float) -> np.ndarray:
    """Per-z leak rule that minimizes the coalition's expected total score E[T | z].

    Returns an array ``q`` of length ``coalition + 1``: ``q[z]`` is the probability of leaking
    1 at a position where ``z`` colluders hold a 1. Forced by the marking assumption:
    ``q[0] = 0`` and ``q[c'] = 1``. Elsewhere 1 when E[T(z,1)|z] < E[T(z,0)|z], 0 when the
    reverse holds, and 0.5 on an exact tie (both choices have the same expected score). From
    the closed form in the module docstring this is the minority bit for every cutoff in
    (0, 1/2); the cutoff is still taken so the rule is computed, not assumed.
    """
    return np.array(_worst_case_table(_check_coalition(coalition), _check_cutoff(cutoff)))


@lru_cache(maxsize=64)
def _worst_case_table(c: int, t: float) -> tuple[float, ...]:
    ez = expected_coalition_score(c, t)
    q = [0.0] * (c + 1)
    q[c] = 1.0
    for z in range(1, c):
        diff = ez[z, 1] - ez[z, 0]
        scale = max(abs(ez[z, 1]), abs(ez[z, 0]), 1e-300)
        q[z] = 0.5 if abs(diff) <= 1e-12 * scale else (1.0 if diff < 0 else 0.0)
    return tuple(q)


def expected_coalition_score(coalition: int, cutoff: float) -> np.ndarray:
    """E[T(z, y, p) | z] for z = 0..c' and y = 0, 1 under the truncated arcsine bias density.

    Shape ``(c' + 1, 2)``; column y. Entries that the marking assumption forbids (y = 1 at
    z = 0 and y = 0 at z = c') are still the formula's value, for completeness. Exact closed
    form (module docstring); P(z) uses the regularized incomplete beta function.
    """
    from scipy.special import betainc, betaln, gammaln

    c = _check_coalition(coalition)
    t = _check_cutoff(cutoff)
    n0 = math.pi - 4.0 * math.asin(math.sqrt(t))
    out = np.empty((c + 1, 2))
    for z in range(c + 1):
        log_comb = gammaln(c + 1) - gammaln(z + 1) - gammaln(c - z + 1)
        # P(z) = C(c,z)/N0 * int_t^{1-t} p^(z-1/2) (1-p)^(c-z-1/2) dp
        a, b = z + 0.5, c - z + 0.5
        mass = betainc(a, b, 1.0 - t) - betainc(a, b, t)
        log_pz = log_comb - math.log(n0) + betaln(a, b) + math.log(mass)
        num = (1.0 - t) ** z * t ** (c - z) - t**z * (1.0 - t) ** (c - z)
        e1 = math.exp(log_comb - math.log(n0) - log_pz) * num
        out[z, 1], out[z, 0] = e1, -e1
    return out


def _logsumexp(a: np.ndarray, axis: int = -1) -> np.ndarray:
    mx = np.max(a, axis=axis, keepdims=True)
    return np.squeeze(mx, axis=axis) + np.log(np.sum(np.exp(a - mx), axis=axis))


@lru_cache(maxsize=64)
def _nodes(cutoff: float, panels: int, order: int) -> tuple[np.ndarray, np.ndarray]:
    """Nodes r and log weights for E over r uniform on [t', pi/2 - t'] (p = sin^2 r).

    Panels are graded towards both ends: half of the breakpoints are geometric in the
    distance to the end, half uniform, so panels near the ends are about t' wide.
    """
    tp = math.asin(math.sqrt(cutoff))
    half = math.pi / 4 - tp
    k = panels // 2
    geo = np.geomspace(min(tp, half) / 4, half, k)
    uni = np.linspace(0.0, half, k + 1)[1:]
    brk_half = np.concatenate([[0.0], 0.5 * (geo + uni)])
    left = tp + brk_half
    right = (math.pi / 2 - tp) - brk_half[::-1]
    brk = np.concatenate([left, right[1:]])
    x, w = np.polynomial.legendre.leggauss(order)
    lo, hi = brk[:-1, None], brk[1:, None]
    r = (lo + hi) / 2 + (hi - lo) / 2 * x[None, :]
    lw = np.log((hi - lo) / 2 * w[None, :] / (math.pi / 2 - 2 * tp))
    return r.ravel(), lw.ravel()


class _Integrand:
    """Per-node quantities for one coalition size, cutoff and quadrature resolution."""

    def __init__(self, coalition: int, cutoff: float, panels: int = _PANELS, order: int = _ORDER) -> None:
        from scipy.special import gammaln

        c = coalition
        r, logw = _nodes(cutoff, panels, order)
        s, co = np.sin(r), np.cos(r)
        g, h = co / s, s / co
        log_p, log_1mp = 2.0 * np.log(s), 2.0 * np.log(co)
        zs = np.arange(c + 1)
        log_comb = gammaln(c + 1) - gammaln(zs + 1) - gammaln(c - zs + 1)
        self.c = c
        self.n = r.size
        # log of (quadrature weight * P(z | p)) per (z, node)
        self.base = logw[None, :] + log_comb[:, None] + zs[:, None] * log_p[None, :] + (c - zs)[:, None] * log_1mp[None, :]
        self.t1 = zs[:, None] * g[None, :] - (c - zs)[:, None] * h[None, :]  # T(z, 1, p); T(z, 0, p) = -t1
        q_is_p = s <= co
        self.g_q = np.where(q_is_p, g, h)
        self.h_q = np.where(q_is_p, h, g)
        self.log_q = np.where(q_is_p, log_p, log_1mp)
        self.log_1mq = np.where(q_is_p, log_1mp, log_p)
        self.logw = logw

    def log_mgf(self, lam: float) -> np.ndarray:
        """log M(lam, p) at every node (worst-case innocent MGF, as in ``accuse``)."""
        return np.logaddexp(self.log_q + lam * self.g_q, self.log_1mq - lam * self.h_q)

    def log_g(self, alpha: float, shift: np.ndarray | float) -> tuple[float, np.ndarray]:
        """log G(alpha) with exponent -alpha T + shift(p); also the maximizing y per z."""
        a1 = _logsumexp(self.base - alpha * self.t1 + shift, axis=1)
        a0 = _logsumexp(self.base + alpha * self.t1 + shift, axis=1)
        best = np.maximum(a0, a1)
        best[0], best[self.c] = a0[0], a1[self.c]
        choice = (a1 > a0).astype(int)
        choice[0], choice[self.c] = 0, 1
        return float(_logsumexp(best, axis=0)), choice


@lru_cache(maxsize=128)
def _integrand(coalition: int, cutoff: float, panels: int, order: int) -> _Integrand:
    return _Integrand(coalition, cutoff, panels, order)


@dataclass(frozen=True)
class MissBound:
    """Proven bound on P(no colluder reaches the threshold) for one coalition size.

    Attributes:
        coalition: number of colluders c'.
        length: code length m.
        eps1: per-recipient false-accusation target that sets the threshold.
        z: fixed threshold used instead of TAPAK's Z(p), or None for TAPAK's own threshold.
        log_bound: natural log of the bound (may exceed 0; see :attr:`bound`).
        alpha: Chernoff parameter at the optimum.
        lam0: lambda at which Z(p) is bounded (None with a fixed ``z``).
        chernoff_choice: per z = 0..c', the leaked bit attaining the maximum in G at the
            optimum (the strategy the bound is computed against).
        quadrature_error: m * (|log G(finer grid) - log G(base grid)| + FLOAT_SLACK),
            already added to ``log_bound``.
    """

    coalition: int
    length: int
    eps1: float
    z: float | None
    log_bound: float
    alpha: float
    lam0: float | None
    chernoff_choice: tuple[int, ...]
    quadrature_error: float

    @property
    def bound(self) -> float:
        """The bound as a probability, capped at 1."""
        return 1.0 if self.log_bound >= 0 else math.exp(self.log_bound)

    @property
    def log10_bound(self) -> float:
        """log10 of the capped bound (exact even when the bound underflows a float)."""
        return min(0.0, self.log_bound) / math.log(10.0)


def _min_scalar(f, lo: float, hi: float, xatol: float) -> tuple[float, float]:
    from scipy.optimize import minimize_scalar

    res = minimize_scalar(f, bounds=(lo, hi), method="bounded", options={"xatol": xatol})
    return float(res.x), float(res.fun)


def _expected_threshold_lambda(itg: _Integrand, m: int, log_inv: float) -> float:
    """lam minimizing (m E[log M(lam, p)] + L) / lam: TAPAK's lambda for a typical bias vector."""
    w = np.exp(itg.logw)

    def obj(u: float) -> float:
        lam = math.exp(u)
        return (m * float(np.sum(w * itg.log_mgf(lam))) + log_inv) / lam

    u, _ = _min_scalar(obj, math.log(_LAM_RANGE[0]), math.log(_LAM_RANGE[1]), 1e-6)
    return math.exp(u)


def _optimize(itg: _Integrand, m: int, c: int, log_inv: float, z: float | None) -> tuple[float, float, float | None]:
    """Return (log bound, alpha, lam0) minimized over alpha (and lam0 unless z is fixed)."""
    kappa = c * (1.0 + Z_SLACK)
    a_lo, a_hi = math.log(_ALPHA_RANGE[0]), math.log(_ALPHA_RANGE[1])

    def inner(lam0: float | None) -> tuple[float, float]:
        if lam0 is None:
            k0, phi = c * float(z), 0.0  # type: ignore[arg-type]
        else:
            k0, phi = kappa * log_inv / lam0, kappa * itg.log_mgf(lam0) / lam0

        def f(u: float) -> float:
            alpha = math.exp(u)
            return alpha * k0 + m * itg.log_g(alpha, alpha * phi)[0]

        u, val = _min_scalar(f, a_lo, a_hi, 1e-7)
        return val, math.exp(u)

    if z is not None:
        val, alpha = inner(None)
        return val, alpha, None
    lam_star = _expected_threshold_lambda(itg, m, log_inv)
    lo = max(math.log(_LAM_RANGE[0]), math.log(lam_star) - 1.0)
    hi = min(math.log(_LAM_RANGE[1]), math.log(lam_star) + 1.0)
    # The bound is valid for every lam0 and only second-order sensitive to it near the optimum.
    u, _ = _min_scalar(lambda v: inner(math.exp(v))[0], lo, hi, 1e-3)
    candidates = [math.exp(u), lam_star]
    best = min((inner(lam) + (lam,) for lam in candidates), key=lambda x: x[0])
    return best[0], best[1], best[2]


def miss_bound(
    params: TardosParams,
    coalition: int | None = None,
    length: int | None = None,
    z: float | None = None,
    eps1: float | None = None,
) -> MissBound:
    """Proven upper bound on P(no member of a c'-coalition reaches the threshold).

    Args:
        params: code parameters (cutoff t and, unless overridden, m and eps1).
        coalition: number of colluders c' (default ``params.c``). May exceed ``params.c``.
        length: code length m (default ``params.length``).
        z: a fixed threshold instead of TAPAK's Z(p) for a full read (default: TAPAK's).
        eps1: per-recipient target that sets Z(p) (default ``params.eps1``, the full-eps
            threshold recorded at issuance; pass ``TraceSpending.eps1(n_max)`` for a logged
            trace).

    The bound holds for every strategy obeying the marking assumption, on a full
    hard-decision read (see the module docstring for the derivation and scope).
    """
    c = _check_coalition(params.c if coalition is None else coalition)
    m = params.length if length is None else int(length)
    if m < 1:
        raise ValueError("panjang kode minimal 1")
    e1 = params.eps1 if eps1 is None else float(eps1)
    if not 0.0 < e1 < 1.0:
        raise ValueError("eps1 harus di antara 0 dan 1")
    if z is not None and not (math.isfinite(z) and z > 0):
        raise ValueError("ambang z harus positif dan berhingga")
    log_inv = math.log(1.0 / e1)
    t = params.cutoff
    itg = _integrand(c, t, _PANELS, _ORDER)
    val, alpha, lam0 = _optimize(itg, m, c, log_inv, z)

    # Quadrature check at the optimum: repeat on a grid with twice as many panels.
    fine = _integrand(c, t, 2 * _PANELS, _ORDER)
    if lam0 is None:
        shift_c, shift_f = 0.0, 0.0
    else:
        kappa = c * (1.0 + Z_SLACK)
        shift_c = alpha * kappa * itg.log_mgf(lam0) / lam0
        shift_f = alpha * kappa * fine.log_mgf(lam0) / lam0
    lg_c, choice = itg.log_g(alpha, shift_c)
    lg_f, _ = fine.log_g(alpha, shift_f)
    q_err = m * (abs(lg_f - lg_c) + FLOAT_SLACK)
    return MissBound(
        coalition=c,
        length=m,
        eps1=e1,
        z=None if z is None else float(z),
        log_bound=val + q_err,
        alpha=alpha,
        lam0=lam0,
        chernoff_choice=tuple(int(v) for v in choice),
        quadrature_error=q_err,
    )


def proven_miss_probability(
    params: TardosParams,
    length: int | None = None,
    z: float | None = None,
    eps1: float | None = None,
) -> float:
    """Proven bound on P(no colluder caught) for every coalition of 1 to ``params.c`` members.

    The maximum of :func:`miss_bound` over c' = 1, ..., c, capped at 1. Same arguments as
    :func:`miss_bound`.
    """
    return max(miss_bound(params, k, length, z, eps1).bound for k in range(1, params.c + 1))


@dataclass(frozen=True)
class LengthRequirement:
    """Shortest code whose proven miss bound meets a target.

    Attributes:
        c, eps, n_max: code parameters (coalitions of up to c members are covered).
        delta: target for the proven miss probability.
        length: smallest m with bound(m) <= delta found by bisection (bound(m - 1) > delta).
        k_constant: the K giving that m: length / (c^2 ln(1/eps1)).
        bound: proven miss bound at ``length``.
        bound_below: proven miss bound at ``length - 1``.
    """

    c: int
    eps: float
    n_max: int
    delta: float
    length: int
    k_constant: float
    bound: float
    bound_below: float


def min_length(c: int, eps: float, n_max: int, delta: float, eps1: float | None = None) -> LengthRequirement:
    """Smallest code length m whose proven miss bound (coalitions of at most c) is <= delta.

    The exact bound decreases with m (each Chernoff term does once it is below 1). The search
    doubles m until the bound meets ``delta`` and then bisects, so the returned m always has
    bound(m) <= delta and bound(m - 1) > delta as computed, even if optimizer noise made the
    computed bound locally non-monotone. Thresholds use ``eps1`` (default eps / n_max).
    """
    if not 0.0 < delta < 1.0:
        raise ValueError("target delta harus di antara 0 dan 1")
    params = TardosParams(c=c, eps=eps, n_max=n_max)
    e1 = params.eps1 if eps1 is None else eps1

    def meets(m: int) -> bool:
        # Largest coalition first: it has the largest bound, so failures exit after one term.
        return all(miss_bound(params, k, m, None, e1).bound <= delta for k in range(c, 0, -1))

    lo, hi = 0, params.length
    while not meets(hi):
        lo, hi = hi, 2 * hi
        if hi > 10**8:
            raise ValueError("target delta tidak tercapai sampai m = 10^8")
    # Invariant: the bound at lo exceeds delta (lo = 0 means "no code"), the bound at hi meets it.
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if meets(mid):
            hi = mid
        else:
            lo = mid
    return LengthRequirement(
        c=c,
        eps=eps,
        n_max=n_max,
        delta=delta,
        length=hi,
        k_constant=hi / (c * c * math.log(1.0 / e1)),
        bound=proven_miss_probability(params, length=hi, eps1=e1),
        bound_below=1.0 if lo == 0 else proven_miss_probability(params, length=lo, eps1=e1),
    )
