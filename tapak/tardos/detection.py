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
from collections.abc import Callable, Mapping, Sequence
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
# Support points per block in the vectorized channel factor (memory, not accuracy).
_CHUNK = 128
# A channel bound is optimized on at most this many groups of support points, then evaluated
# exactly on every support point at the chosen (alpha, lam0).
_GROUPS = 32


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

    def log_mgf_weighted(self, lam: float, w: np.ndarray) -> np.ndarray:
        """log M(lam w_k, p) per weight (rows) and node (columns): the weighted read's MGF."""
        lw = lam * np.asarray(w, dtype=np.float64)[:, None]
        return np.logaddexp(self.log_q[None, :] + lw * self.g_q[None, :], self.log_1mq[None, :] - lw * self.h_q[None, :])

    def log_g_channel(self, alpha: float, lam0: float | None, kappa: float, w: np.ndarray, e: np.ndarray) -> np.ndarray:
        """log G(alpha; w_k, e_k) per support point: weight w_k > 0 and flip rate e_k.

        The exponent is -alpha w (1 - 2 f) T(z, y, p) + alpha psi(p, w) with
        psi = kappa log M(lam0 w, p) / lam0 (0 with a fixed threshold, ``lam0=None``); the flip
        f ~ Bernoulli(e) is averaged inside the maximum over the leaked bit y.
        """
        w = np.asarray(w, dtype=np.float64)
        e = np.asarray(e, dtype=np.float64)
        out = np.empty(w.size)
        with np.errstate(divide="ignore"):
            log_e = np.log(e)
        log_1me = np.log1p(-e)
        for s in range(0, w.size, _CHUNK):
            sl = slice(s, s + _CHUNK)
            core = np.broadcast_to(self.base, (w[sl].size,) + self.base.shape)
            if lam0 is not None:
                core = core + (alpha * kappa / lam0) * self.log_mgf_weighted(lam0, w[sl])[:, None, :]
            at = (alpha * w[sl])[:, None, None] * self.t1[None, :, :]
            le, l1 = log_e[sl][:, None, None], log_1me[sl][:, None, None]
            a1 = _logsumexp(core + np.logaddexp(l1 - at, le + at), axis=2)  # leak 1: T = t1
            a0 = _logsumexp(core + np.logaddexp(l1 + at, le - at), axis=2)  # leak 0: T = -t1
            best = np.maximum(a0, a1)
            best[:, 0], best[:, self.c] = a0[:, 0], a1[:, self.c]  # marking assumption
            out[sl] = _logsumexp(best, axis=1)
        return out


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


def _minimize_chernoff(
    objective: Callable[[float | None], Callable[[float], float]], lam_star: float | None
) -> tuple[float, float, float | None]:
    """Minimize a Chernoff log bound over alpha, and over lam0 near ``lam_star``.

    ``objective(lam0)`` returns the function alpha -> log bound for that lam0 (lam0 None: a
    fixed threshold, no lam0 to choose; pass ``lam_star=None`` then). Returns (log bound,
    alpha, lam0). Every (alpha, lam0) gives a valid bound, so optimizer error only loosens it.
    """
    a_lo, a_hi = math.log(_ALPHA_RANGE[0]), math.log(_ALPHA_RANGE[1])

    def inner(lam0: float | None) -> tuple[float, float]:
        f = objective(lam0)
        u, val = _min_scalar(lambda u: f(math.exp(u)), a_lo, a_hi, 1e-7)
        return val, math.exp(u)

    if lam_star is None:
        val, alpha = inner(None)
        return val, alpha, None
    lo = max(math.log(_LAM_RANGE[0]), math.log(lam_star) - 1.0)
    hi = min(math.log(_LAM_RANGE[1]), math.log(lam_star) + 1.0)
    # The bound is valid for every lam0 and only second-order sensitive to it near the optimum.
    u, _ = _min_scalar(lambda v: inner(math.exp(v))[0], lo, hi, 1e-3)
    candidates = [math.exp(u), lam_star]
    best = min((inner(lam) + (lam,) for lam in candidates), key=lambda x: x[0])
    return best[0], best[1], best[2]


def _optimize(itg: _Integrand, m: int, c: int, log_inv: float, z: float | None) -> tuple[float, float, float | None]:
    """Return (log bound, alpha, lam0) minimized over alpha (and lam0 unless z is fixed)."""
    kappa = c * (1.0 + Z_SLACK)

    def objective(lam0: float | None) -> Callable[[float], float]:
        if lam0 is None:
            k0, phi = c * float(z), 0.0  # type: ignore[arg-type]
        else:
            k0, phi = kappa * log_inv / lam0, kappa * itg.log_mgf(lam0) / lam0
        return lambda alpha: alpha * k0 + m * itg.log_g(alpha, alpha * phi)[0]

    lam_star = None if z is not None else _expected_threshold_lambda(itg, m, log_inv)
    return _minimize_chernoff(objective, lam_star)


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
            threshold recorded at issuance; pass ``TraceSpending.stage_eps1(1, n_max)`` for a
            logged or staged trace: the bound covers stage 1 only).

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


def _bisect_length(meets: Callable[[int], bool], start: int) -> tuple[int, int]:
    """(lo, hi) with meets(hi) true and meets(lo) false (lo = 0: no code), hi - lo = 1.

    Doubles from ``start`` until ``meets`` holds, then bisects, so the result is consistent as
    computed even if optimizer noise made the computed bound locally non-monotone.
    """
    lo, hi = 0, start
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
    return lo, hi


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

    lo, hi = _bisect_length(meets, params.length)
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


# --- noisy and soft-weighted reads ---------------------------------------------------------


def calibrated_error_rates(weights: np.ndarray | Sequence[float] | float) -> np.ndarray:
    """Flip rate (1 - w) / 2 that a calibrated LLR implies for the decoder weight w = tanh(|L| / 2).

    For an exact LLR L, P(decided bit wrong | L) = 1 / (1 + e^|L|), and 1 - 2 / (1 + e^|L|) is
    tanh(|L| / 2). Whether the decoder's LLRs are calibrated is a measurement, not a given
    (``research/deteksi/llr_foto.py``).
    """
    w = np.asarray(weights, dtype=np.float64)
    if (w < 0).any() or (w > 1).any():
        raise ValueError("bobot harus di antara 0 dan 1")
    return (1.0 - w) / 2.0


def _check_rates(e: np.ndarray) -> np.ndarray:
    if not np.all((e >= 0.0) & (e <= 0.5)):
        raise ValueError("laju bit salah harus di antara 0 dan 0,5")
    return e


@dataclass(frozen=True)
class ChannelLaw:
    """Law of the read at one position, the same for every position and independent across them.

    With probability ``probabilities[k]`` the decoder gives the position the weight
    ``weights[k]`` (0: erased), and its decided bit is wrong with probability
    ``error_rates[k]`` given that weight. Conditions (C1) and (C2) of the module docstring
    apply: the weights and the flips come from channel noise that does not depend on the code,
    on the coalition's choices or on the leaked bit.
    """

    weights: tuple[float, ...]
    error_rates: tuple[float, ...]
    probabilities: tuple[float, ...]

    def __post_init__(self) -> None:
        w = np.asarray(self.weights, dtype=np.float64).reshape(-1)
        e = np.asarray(self.error_rates, dtype=np.float64).reshape(-1)
        q = np.asarray(self.probabilities, dtype=np.float64).reshape(-1)
        if w.size == 0 or e.shape != w.shape or q.shape != w.shape:
            raise ValueError("bobot, laju bit salah, dan peluang harus sama panjang dan tidak kosong")
        if (w < 0).any() or (w > 1).any():
            raise ValueError("bobot harus di antara 0 dan 1")
        _check_rates(e)
        if (q < 0).any() or abs(float(q.sum()) - 1.0) > 1e-9:
            raise ValueError("peluang harus tidak negatif dan berjumlah 1")
        object.__setattr__(self, "weights", tuple(float(v) for v in w))
        object.__setattr__(self, "error_rates", tuple(float(v) for v in e))
        object.__setattr__(self, "probabilities", tuple(float(v) for v in q / q.sum()))

    @classmethod
    def binary_symmetric(cls, error_rate: float) -> "ChannelLaw":
        """Hard decisions (weight 1 everywhere) through a binary symmetric channel."""
        return cls((1.0,), (float(error_rate),), (1.0,))

    @classmethod
    def calibrated(cls, weights: Sequence[float], probabilities: Sequence[float]) -> "ChannelLaw":
        """Soft weights whose flip rate is the calibrated (1 - w) / 2 (``calibrated_error_rates``)."""
        return cls(tuple(weights), tuple(calibrated_error_rates(np.asarray(weights, dtype=np.float64))),
                   tuple(probabilities))

    @classmethod
    def from_dict(cls, d: Mapping[str, Sequence[float]]) -> "ChannelLaw":
        """Inverse of :meth:`to_dict` (the ``law`` object of ``research/deteksi/hasil/llr_foto.json``)."""
        return cls(tuple(d["weights"]), tuple(d["error_rates"]), tuple(d["probabilities"]))

    def to_dict(self) -> dict[str, list[float]]:
        """Serializable form."""
        return {"weights": list(self.weights), "error_rates": list(self.error_rates),
                "probabilities": list(self.probabilities)}

    def with_error_rate(self, error_rate: float) -> "ChannelLaw":
        """The same weights with one flip rate at every weight (flips independent of the weight)."""
        return ChannelLaw(self.weights, (float(error_rate),) * len(self.weights), self.probabilities)

    @property
    def effective_fraction(self) -> float:
        """(E[w (1 - 2e)])^2 / E[w^2]: roughly what one position is worth next to a hard, error-free one.

        A heuristic for comparing laws (squared mean over second moment of the coalition's
        per-position signal); the bound does not use it.
        """
        w, e, q = (np.asarray(v) for v in (self.weights, self.error_rates, self.probabilities))
        second = float(np.sum(q * w * w))
        return 0.0 if second == 0 else float(np.sum(q * w * (1 - 2 * e))) ** 2 / second


@dataclass(frozen=True)
class ChannelMissBound:
    """Proven bound on P(no colluder reaches the threshold) for a noisy or soft-weighted read.

    Attributes:
        coalition: number of colluders c'.
        length: code length m (positions of the read, observed or not).
        observed: positions with weight > 0 (for a :class:`ChannelLaw`: the expected number).
        eps1: per-recipient target that sets Z(p, w).
        z: fixed threshold used instead of Z(p, w), or None.
        log_bound: natural log of the bound (may exceed 0; see :attr:`bound`).
        alpha: Chernoff parameter at the optimum (nan when nothing is observed).
        lam0: lambda at which Z(p, w) is bounded (None with a fixed ``z`` or nothing observed).
        quadrature_error: refinement difference plus ``FLOAT_SLACK`` per position, already
            added to ``log_bound``.
        conditional: True for :func:`read_miss_bound` (given the read's weights), False for
            :func:`channel_miss_bound` (averaged over the law of the weights).
    """

    coalition: int
    length: int
    observed: float
    eps1: float
    z: float | None
    log_bound: float
    alpha: float
    lam0: float | None
    quadrature_error: float
    conditional: bool

    @property
    def bound(self) -> float:
        """The bound as a probability, capped at 1."""
        return 1.0 if self.log_bound >= 0 else math.exp(self.log_bound)

    @property
    def log10_bound(self) -> float:
        """log10 of the capped bound (exact even when the bound underflows a float)."""
        return min(0.0, self.log_bound) / math.log(10.0)


@dataclass(frozen=True)
class _Support:
    """Support points (w > 0) of a read with their mass, and how their factors combine.

    Conditional reads: ``mass`` counts positions and the log bound adds sum mass * log G.
    Laws: ``mass`` is a probability, ``zero`` the probability of weight 0, and the log bound
    adds m * log(zero + sum mass * G).
    """

    w: np.ndarray
    e: np.ndarray
    mass: np.ndarray
    zero: float
    m: int
    conditional: bool

    def combine(self, log_g: np.ndarray) -> float:
        if self.conditional:
            return float(np.sum(self.mass * log_g))
        terms = np.log(self.mass) + log_g
        if self.zero > 0:
            terms = np.append(terms, math.log(self.zero))
        return self.m * float(_logsumexp(terms, axis=0))

    def position_mass(self) -> np.ndarray:
        """Expected number of positions per support point."""
        return self.mass if self.conditional else self.m * self.mass

    def grouped(self, groups: int = _GROUPS) -> "_Support":
        """At most ``groups`` support points (mass-weighted means), for the optimizer only."""
        if self.w.size <= groups:
            return self
        order = np.lexsort((self.e, self.w))
        w, e, mass = [], [], []
        for idx in np.array_split(order, groups):
            mk = self.mass[idx]
            w.append(float(np.sum(mk * self.w[idx]) / mk.sum()))
            e.append(float(np.sum(mk * self.e[idx]) / mk.sum()))
            mass.append(float(mk.sum()))
        return _Support(np.array(w), np.array(e), np.array(mass), self.zero, self.m, self.conditional)


def _channel_bound(params: TardosParams, sup: _Support, coalition: int | None, eps1: float | None,
                   z: float | None) -> ChannelMissBound:
    c = _check_coalition(params.c if coalition is None else coalition)
    e1 = params.eps1 if eps1 is None else float(eps1)
    if not 0.0 < e1 < 1.0:
        raise ValueError("eps1 harus di antara 0 dan 1")
    if z is not None and not (math.isfinite(z) and z > 0):
        raise ValueError("ambang z harus positif dan berhingga")
    zf = None if z is None else float(z)
    observed = float(np.sum(sup.position_mass()))
    if sup.w.size == 0:  # nothing observed: Z is infinite and nobody can be caught
        return ChannelMissBound(c, sup.m, 0.0, e1, zf, 0.0, math.nan, None, 0.0, sup.conditional)
    log_inv = math.log(1.0 / e1)
    kappa = c * (1.0 + Z_SLACK)
    itg = _integrand(c, params.cutoff, _PANELS, _ORDER)

    def k0(lam0: float | None) -> float:
        return c * zf if lam0 is None else kappa * log_inv / lam0  # type: ignore[operator]

    red = sup.grouped()

    def objective(lam0: float | None) -> Callable[[float], float]:
        return lambda alpha: alpha * k0(lam0) + red.combine(itg.log_g_channel(alpha, lam0, kappa, red.w, red.e))

    lam_star = None
    if zf is None:  # TAPAK's lambda for a typical bias vector with these weights
        mass, wq = red.position_mass(), np.exp(itg.logw)

        def threshold_objective(u: float) -> float:
            lam = math.exp(u)
            return (float(np.sum(mass[:, None] * wq[None, :] * itg.log_mgf_weighted(lam, red.w))) + log_inv) / lam

        u, _ = _min_scalar(threshold_objective, math.log(_LAM_RANGE[0]), math.log(_LAM_RANGE[1]), 1e-6)
        lam_star = math.exp(u)
    _, alpha, lam0 = _minimize_chernoff(objective, lam_star)
    # Exact value at the chosen (alpha, lam0) on every support point, then the quadrature check.
    fine = _integrand(c, params.cutoff, 2 * _PANELS, _ORDER)
    lg_c = itg.log_g_channel(alpha, lam0, kappa, sup.w, sup.e)
    lg_f = fine.log_g_channel(alpha, lam0, kappa, sup.w, sup.e)
    total = sup.combine(lg_c)
    if sup.conditional:
        q_err = float(np.sum(sup.mass * np.abs(lg_f - lg_c))) + observed * FLOAT_SLACK
    else:
        q_err = abs(sup.combine(lg_f) - total) + sup.m * FLOAT_SLACK
    return ChannelMissBound(
        coalition=c, length=sup.m, observed=observed, eps1=e1, z=zf, log_bound=alpha * k0(lam0) + total + q_err,
        alpha=alpha, lam0=lam0, quadrature_error=q_err, conditional=sup.conditional,
    )


def _read_support(weights: np.ndarray | Sequence[float], error_rates: np.ndarray | Sequence[float] | float) -> _Support:
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    if w.size < 1:
        raise ValueError("panjang kode minimal 1")
    if (w < 0).any() or (w > 1).any():
        raise ValueError("bobot harus di antara 0 dan 1")
    e = _check_rates(np.broadcast_to(np.asarray(error_rates, dtype=np.float64), w.shape))
    keep = w > 0
    pairs, counts = np.unique(np.column_stack([w[keep], e[keep]]), axis=0, return_counts=True)
    return _Support(pairs[:, 0], pairs[:, 1], counts.astype(np.float64), float(w.size - keep.sum()), int(w.size), True)


def _law_support(law: ChannelLaw, length: int) -> _Support:
    if length < 1:
        raise ValueError("panjang kode minimal 1")
    w, e, q = (np.asarray(v, dtype=np.float64) for v in (law.weights, law.error_rates, law.probabilities))
    keep = (w > 0) & (q > 0)
    return _Support(w[keep], e[keep], q[keep], float(q[w == 0].sum()), int(length), False)


def read_miss_bound(
    params: TardosParams,
    weights: np.ndarray | Sequence[float],
    error_rates: np.ndarray | Sequence[float] | float = 0.0,
    coalition: int | None = None,
    eps1: float | None = None,
    z: float | None = None,
) -> ChannelMissBound:
    """Proven bound on P(no member of a c'-coalition reaches Z(p, w) | the channel's weights w).

    Args:
        params: code parameters (cutoff t and, unless overridden, eps1 and c').
        weights: the channel's weight for every code position (length m; 0 = erased), as the
            decoder computes them (``FusedEstimate.weights``).
        error_rates: probability that the decided bit is wrong given the weights, one per
            position or one for all (``calibrated_error_rates(weights)`` for calibrated LLRs).
        coalition: number of colluders c' (default ``params.c``).
        eps1: per-recipient target that sets Z(p, w) (default ``params.eps1``).
        z: a fixed threshold instead of Z(p, w).

    Holds for every strategy obeying the marking assumption, under conditions (C1) and (C2)
    of the module docstring. The weights must be the channel's: where the coalition erased a
    position the read has weight 0 instead, and a bound computed from such a read is not
    proven (``channel_miss_bound``, averaged over the law of the channel's weights, covers
    those erasures).
    """
    return _channel_bound(params, _read_support(weights, error_rates), coalition, eps1, z)


def channel_miss_bound(
    params: TardosParams,
    law: ChannelLaw,
    coalition: int | None = None,
    length: int | None = None,
    eps1: float | None = None,
    z: float | None = None,
) -> ChannelMissBound:
    """Proven bound on P(no member of a c'-coalition reaches Z(p, w)) when every position is
    read through ``law``, independently of the other positions.

    Args:
        params: code parameters (cutoff t and, unless overridden, m, eps1 and c').
        law: per-position law of (weight, flip rate) (:class:`ChannelLaw`).
        coalition: number of colluders c' (default ``params.c``).
        length: code length m (default ``params.length``).
        eps1: per-recipient target that sets Z(p, w) (default ``params.eps1``).
        z: a fixed threshold instead of Z(p, w).

    The probability is over the code, the coalition's randomness and the channel. Holds for
    every strategy obeying the marking assumption, including erasures by the coalition where
    its copies differ, under conditions (C1) and (C2) of the module docstring.
    """
    m = params.length if length is None else int(length)
    return _channel_bound(params, _law_support(law, m), coalition, eps1, z)


def proven_channel_miss_probability(
    params: TardosParams,
    law: ChannelLaw,
    length: int | None = None,
    eps1: float | None = None,
    z: float | None = None,
) -> float:
    """Maximum of :func:`channel_miss_bound` over c' = 1, ..., c (every coalition of at most c)."""
    return max(channel_miss_bound(params, law, k, length, eps1, z).bound for k in range(1, params.c + 1))


def proven_read_miss_probability(
    params: TardosParams,
    weights: np.ndarray | Sequence[float],
    error_rates: np.ndarray | Sequence[float] | float = 0.0,
    eps1: float | None = None,
    z: float | None = None,
) -> float:
    """Maximum of :func:`read_miss_bound` over c' = 1, ..., c (every coalition of at most c)."""
    sup = _read_support(weights, error_rates)
    return max(_channel_bound(params, sup, k, eps1, z).bound for k in range(1, params.c + 1))


def channel_min_length(
    c: int, eps: float, n_max: int, delta: float, law: ChannelLaw, eps1: float | None = None
) -> LengthRequirement:
    """Smallest code length whose proven miss bound through ``law`` (coalitions of at most c) is <= delta.

    Same search as :func:`min_length`, with :func:`channel_miss_bound` in place of
    :func:`miss_bound`.
    """
    if not 0.0 < delta < 1.0:
        raise ValueError("target delta harus di antara 0 dan 1")
    params = TardosParams(c=c, eps=eps, n_max=n_max)
    e1 = params.eps1 if eps1 is None else eps1

    def meets(m: int) -> bool:
        return all(channel_miss_bound(params, law, k, m, e1).bound <= delta for k in range(c, 0, -1))

    lo, hi = _bisect_length(meets, params.length)
    return LengthRequirement(
        c=c, eps=eps, n_max=n_max, delta=delta, length=hi, k_constant=hi / (c * c * math.log(1.0 / e1)),
        bound=proven_channel_miss_probability(params, law, length=hi, eps1=e1),
        bound_below=1.0 if lo == 0 else proven_channel_miss_probability(params, law, length=lo, eps1=e1),
    )
