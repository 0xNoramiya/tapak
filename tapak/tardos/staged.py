"""Side-informed staged accusation ("pelacakan bertahap").

Stage 1 is the ordinary accusation of ``accuse.py``: the symmetric score with the decoder
weights b against the code-blind Chernoff threshold Z_1 = Z(p, b, eps1_1). It names the set
A_1 of copies with S_j >= Z_1. A coalition larger than the code was designed for is then
usually caught only in part. Later stages look for the rest, using the copies already named
as side information. They never weaken the false-accusation guarantee (proof below); what
they gain in detection is measured by simulation (``simulate.run_staged_simulation``).

Rule for stage s >= 2
---------------------
Let A = A_{s-1} be the copies named at stages 1 .. s-1 (stage s runs only when stage s-1
named someone new) and X_A their codewords. Position i is *unexplained* when b_i > 0 and no
copy in A holds the leaked bit there (x_{a,i} != y_i for every a in A). Stage s re-scores
every copy j that is not in A with

    S_j^(s) = sum_i w_i U(y_i, x_{j,i}, p_i),        w_i = b_i * v_i / V,

where v_i = 0 at explained positions, v_i = v(p_i, y_i) (derived below) at unexplained ones,
and V = ``WEIGHT_SCALE`` >= max v, so 0 <= w_i <= 1. The weight w_i is a function of
(y_i, p_i, b_i, X_{A,i}) only. Copy j is named at stage s when S_j^(s) >= Z_s, where
Z_s = ``accuse.threshold(p, eps1_s, w)`` is the same code-blind weighted Chernoff threshold
as at stage 1, with the stage's own per-copy target eps1_s (``spending.StagePolicy``). The
stages stop at the first stage that names nobody new, or after the policy's last stage.

Why the unexplained positions carry the evidence
------------------------------------------------
Suppose every copy in A is a colluder. The marking assumption says the leaked bit y_i is held
by at least one colluder. At an unexplained position no copy in A holds it, so at least one
colluder outside A does. At an explained position the marking assumption is already met by
A, and what the other colluders hold there depends on their strategy: under majority voting
they tend to agree with y_i, under minority voting they tend not to. The only information
that holds for every strategy is therefore at the unexplained positions.

Derivation of the weights
-------------------------
Reference model, fixed before any simulation was run; it affects detection only, never the
false-accusation guarantee: r = ``REFERENCE_REMAINING`` = 2 colluders remain outside A, their
bits are a priori independent Bernoulli(p_i), and nothing is known about them except the
marking assumption. Write q_y = P(X = y_i) (p_i if y_i = 1, else 1 - p_i) and
q = min(p_i, 1 - p_i).

1. Expected score contribution. If a remaining colluder holds y_i with probability pi_i, its
   expected score at i is mu_i = pi_i g - (1 - pi_i) h with g = sqrt((1-q_y)/q_y),
   h = sqrt(q_y/(1-q_y)), that is

       mu_i = (pi_i - q_y) / sqrt(q_y (1 - q_y)).

   (An innocent copy has pi_i = q_y: mean 0, variance 1.) At an explained position the model
   gives pi_i = q_y, so mu_i = 0. At an unexplained position at least one of the r remaining
   colluders holds y_i, so pi_i = q_y / (1 - (1 - q_y)^r) = 1 / (2 - q_y) for r = 2.

2. Weight for that contribution under the Chernoff threshold. The threshold is
   Z(w) = min_lam (sum_i log M_i(lam w_i) + L) / lam, L = ln(1/eps1), with M_i the worst-case
   innocent moment generating function of ``accuse._WorstCaseMgf`` (the leaked bit taken as
   the rarer symbol: U = +sqrt((1-q)/q) with probability q, -sqrt(q/(1-q)) otherwise). The
   expected score sum_i w_i mu_i reaches Z(w) exactly when, for some lam,
   sum_i [v_i mu_i - log M_i(v_i)] >= L with v_i = lam w_i. That separates by position, and
   each term is largest where (log M_i)'(v_i) = mu_i. (log M)'(v) is the mean of U under the
   tilted law, (rho - q) / sqrt(q(1-q)) with rho the tilted probability of the + outcome, so
   rho = q + (pi_i - q_y) and

       v = sqrt(q(1-q)) ln[ rho (1-q) / (q (1-rho)) ]          (v = 0 where mu_i <= 0).

   For r = 2 this has closed forms (equal at q = 1/2):

       y_i the rarer symbol  (q_y = q):      v = sqrt(q(1-q)) ln(1/q)
       y_i the common symbol (q_y = 1 - q):  v = sqrt(q(1-q)) ln[(1+2q)(1-q) / (1-2q^2)]

   Only the ratios of the v_i matter, since Z(c w) = c Z(w) and S(c w) = c S(w); dividing by
   V = max over 0 < q <= 1/2 of sqrt(q(1-q)) ln(1/q) (0.690916 at q = 0.104) keeps w in [0, 1].
   This is not the Gaussian choice w ~ mu: for a rare symbol mu ~ 1/sqrt(q) grows without
   bound, but an innocent copy's score there has a heavy upper tail that the Chernoff
   threshold pays for, and v ~ sqrt(q) ln(1/q) balances the two. Most weight goes to
   unexplained positions whose leaked bit is the rarer symbol with q around 0.02 to 0.4. The
   decoder weight b_i multiplies v_i, as at stage 1.

   For another number r' of remaining colluders, pi_i is about 1/r' for a rare symbol, so
   v is about sqrt(q) (ln(1/q) - ln(r' - 1)): the same shape, shifted. The reference r
   mainly decides how much weight goes to unexplained positions with q near 1/2.

False-accusation guarantee
--------------------------
Fix an innocent copy j (not in the coalition). Given p, its codeword x_j is independent of
everything else the decoder uses: the leaked word y, the decoder weights b (computed from the
evidence without codewords) and the other codewords X_{-j}.

Claim. Let A_s^{(-j)} be the sets named when the same procedure runs on the copies other
than j. Whenever j is not in A_{s-1}, A_{s-1} = A_{s-1}^{(-j)}.
Proof by induction. Z_1 depends on (p, b) only, and the stage-1 scores of the other copies do
not involve x_j, so A_1 minus {j} = A_1^{(-j)}. If A_{s-1} = A_{s-1}^{(-j)}, the stage-s
weights (from y, p, b and X_{A_{s-1}}), the threshold Z_s and the other copies' stage-s
scores are those of the run without j, so A_s minus {j} = A_s^{(-j)}; whether stage s runs
at all depends on these sets only. If j is not in A_s, A_s = A_s^{(-j)}.

So the event "j is named at stage s" implies j is not in A_{s-1} and
sum_i w_i^{(-j)} U(y_i, x_{j,i}, p_i) >= Z_s^{(-j)}, with w^{(-j)} and Z_s^{(-j)} functions of
(y, p, b, X_{-j}). Conditionally on those, the weighted Chernoff bound of ``accuse.py`` applies
(it holds for every y because it takes the worst leaked bit at each position, and for any
weights in [0, 1] that do not depend on x_j): P(j named at stage s) <= eps1_s. By the union
bound over stages, P(j named in this trace) <= sum_s eps1_s, and over at most n_max copies,
P(some innocent copy named in this trace) <= n_max sum_s eps1_s = sum_s eps_s, which the
policy makes equal to the trace's share.

Points checked:

* The weights use the codewords of copies named earlier, and those are recipient codes. That
  is allowed: the argument needs only that the weights and the threshold of a stage never
  use the codeword of the copy being tested. They do not, because a copy is scored at stage
  s only when it is not in A_{s-1}.
* A copy named at an earlier stage is not scored again, so it never gets a second chance at
  a lower threshold; its false-accusation probability is that of the stage that named it.
* A_{s-1} may contain an innocent copy (with probability inside the earlier stages' budget).
  The weights then rest on wrong side information, which can only cost detection: the
  argument above does not assume that A_{s-1} is part of the coalition.
* The stage budgets come from a fixed policy chosen before decoding and recorded with the
  trace in the registry, and the number of stages is bounded by it; stopping early only
  leaves budget unspent.
* A bit error of the channel (y_i held by no colluder) adds an unexplained position where
  nobody is forced to hold y_i. That costs detection, not the bound.
* The false-accusation probability reported for a copy named at stage s is (n - 1) times
  P(innocent score >= S_j^(s)) at that stage, divided by the stage's share of eps, so it is
  comparable with eps across stages and traces.
* The proven detection bound of ``detection.py`` is for stage 1 (with its own target);
  what the later stages add is only measured.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from tapak.tardos.accuse import scores, threshold

# Number of colluders assumed to remain outside the named set when the weights are derived
# (module docstring, "Reference model"). Fixed before any simulation; detection only.
REFERENCE_REMAINING = 2
# max over 0 < q <= 1/2 of sqrt(q(1-q)) ln(1/q) is 0.6909159 (at q = 0.10406); any value at
# least that keeps every weight in [0, 1].
WEIGHT_SCALE = 0.6909160


def unexplained_positions(y: np.ndarray, accused_codewords: np.ndarray) -> np.ndarray:
    """Boolean mask of positions where no named copy holds the leaked bit.

    ``accused_codewords`` has one row per copy named so far (shape a x m, a >= 0). With no
    named copy every position is unexplained.
    """
    y = np.asarray(y)
    xa = np.asarray(accused_codewords)
    if xa.ndim == 1:
        xa = xa[None, :]
    if xa.ndim != 2 or (xa.size and xa.shape[1] != y.shape[0]):
        raise ValueError("kata kode salinan yang sudah dituduh harus berukuran (a, m)")
    if xa.shape[0] == 0:
        return np.ones(y.shape[0], dtype=bool)
    return ~np.any(xa == y[None, :], axis=0)


def _agreement(q_y: np.ndarray, remaining: int) -> np.ndarray:
    """P(a remaining colluder holds y | at least one of ``remaining`` holds it)."""
    return q_y / -np.expm1(remaining * np.log1p(-q_y))


def _chernoff_weight(p: np.ndarray, y: np.ndarray, pi: np.ndarray) -> np.ndarray:
    """v = sqrt(q(1-q)) ln[rho(1-q)/(q(1-rho))], rho = q + (pi - q_y); 0 where pi <= q_y."""
    q = np.minimum(p, 1.0 - p)
    q_y = np.where(y > 0, p, 1.0 - p)
    rho = q + (pi - q_y)
    rho = np.minimum(rho, np.nextafter(1.0, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.sqrt(q * (1.0 - q)) * (np.log(rho) + np.log1p(-q) - np.log(q) - np.log1p(-rho))
    return np.where(rho > q, v, 0.0)


def side_information_weights(
    y: np.ndarray,
    p: np.ndarray,
    accused_codewords: np.ndarray,
    base_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Weights of a stage >= 2 from the leaked bits, the biases and the named copies' bits.

    w_i = b_i * v_i / WEIGHT_SCALE at unexplained positions (no named copy holds y_i) and 0
    elsewhere, with b the decoder weights (``base_weights``, default 1) and v the
    Chernoff-matched weight of the module docstring for ``REFERENCE_REMAINING`` remaining
    colluders. Each w_i depends on (y_i, p_i, b_i, accused_codewords[:, i]) only; the
    codeword of a copy that is scored with these weights is never an input.
    """
    y = np.asarray(y)
    p = np.asarray(p, dtype=np.float64)
    if y.shape != p.shape:
        raise ValueError("y dan p harus berukuran sama")
    b = np.ones_like(p) if base_weights is None else np.asarray(base_weights, dtype=np.float64)
    if b.shape != p.shape:
        raise ValueError("bobot dekoder dan p harus berukuran sama")
    q_y = np.where(y > 0, p, 1.0 - p)
    v = _chernoff_weight(p, y, _agreement(q_y, REFERENCE_REMAINING))
    w = b * v / WEIGHT_SCALE
    return np.where(unexplained_positions(y, accused_codewords) & (b > 0), np.clip(w, 0.0, 1.0), 0.0)


@dataclass
class Stage:
    """One stage of a staged accusation.

    Attributes:
        stage: stage number (1 = the ordinary accusation).
        eps1: per-copy target of this stage.
        weights: the weights used at this stage (decoder weights at stage 1).
        threshold: Z of this stage, from (p, weights, eps1) only.
        basis: indices of the copies named before this stage, whose codewords set the
            weights (empty at stage 1).
        scored: indices of the copies scored at this stage (every copy not in ``basis``).
        scores: their scores, in the order of ``scored``.
        accused: indices of the copies named at this stage (score >= threshold).
        n_observed: positions with non-zero weight.
    """

    stage: int
    eps1: float
    weights: np.ndarray
    threshold: float
    basis: np.ndarray
    scored: np.ndarray
    scores: np.ndarray
    accused: np.ndarray
    n_observed: int = field(default=0)


def stage_weights(
    stage: int,
    y: np.ndarray,
    p: np.ndarray,
    codewords: np.ndarray,
    basis: np.ndarray,
    base_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Weights of stage ``stage``: the decoder weights at stage 1, side-informed after it.

    ``basis`` holds the indices of the copies named before this stage; only their rows of
    ``codewords`` are read.
    """
    b = np.ones(len(p)) if base_weights is None else np.asarray(base_weights, dtype=np.float64)
    if stage == 1:
        return b
    basis = np.asarray(basis, dtype=np.int64)
    if basis.size == 0:
        raise ValueError("tahap lanjutan memerlukan sedikitnya satu salinan yang sudah dituduh")
    return side_information_weights(y, p, np.asarray(codewords)[basis], b)


def staged_accuse(
    codewords: np.ndarray,
    y: np.ndarray,
    p: np.ndarray,
    stage_eps1: Sequence[float],
    weights: np.ndarray | None = None,
) -> list[Stage]:
    """Run stage 1 and then the side-informed stages, one per entry of ``stage_eps1``.

    Each stage fixes its weights and threshold before any score of that stage is computed.
    The run stops after a stage that names nobody (no stage after it can differ) or after the
    last entry of ``stage_eps1``. Returns the stages that ran, stage 1 first.
    """
    x = np.asarray(codewords)
    if x.ndim != 2 or x.shape[1] != len(p):
        raise ValueError("kata kode harus berukuran (jumlah salinan, m)")
    if not stage_eps1:
        raise ValueError("sedikitnya satu tahap diperlukan")
    named = np.zeros(x.shape[0], dtype=bool)
    out: list[Stage] = []
    for k, eps1 in enumerate(stage_eps1, start=1):
        basis = np.flatnonzero(named)
        w = stage_weights(k, y, p, x, basis, weights)
        z = threshold(p, eps1, w)  # fixed before any score of this stage
        scored = np.flatnonzero(~named)
        observed = int(np.count_nonzero(w > 0))
        s = scores(x[scored].astype(np.float64), y, p, w) if observed else np.zeros(scored.size)
        hit = scored[s >= z] if math.isfinite(z) else scored[:0]
        out.append(Stage(k, float(eps1), w, float(z), basis, scored, s, hit, observed))
        if hit.size == 0:
            break
        named[hit] = True
    return out
