"""Alpha spending over repeated traces of one document.

The Chernoff threshold bounds the false-accusation probability of one trace by eps. Every
further trace of the same document (another photo, another subset or combination of the
evidence) is a new chance to accuse an innocent recipient, so k traces at eps each only
guarantee k * eps.

TAPAK therefore numbers the traces of each document in the registry and lets trace number k
(1, 2, 3, ...) spend only

    eps_k = eps * 6 / (pi^2 k^2)

of the document's budget eps. Because sum_{k >= 1} 1/k^2 = pi^2 / 6, the shares add up to
exactly eps however many traces follow, and by the union bound the probability that any
trace of the document ever accuses an innocent recipient stays at most eps, provided the
evidence of each trace is not picked from the scores shown by earlier traces (new evidence,
a plan fixed in advance and the decision to trace again or stop are fine). Within trace k
the per-recipient target is eps1_k = eps_k / n_max, as for a single trace.

The schedule is fixed policy and the trace number is taken from the registry before the
evidence is decoded, so nothing is tuned after seeing a result. The price is a slowly
rising threshold: ln(1/eps1_k) grows by only 2 ln(k) + ln(pi^2 / 6).

Stages within one trace. A trace may run the side-informed staged accusation of
``staged.py``: stage 1 is the ordinary accusation, later stages re-score the other copies
using the copies already named. Every stage that can name someone spends its own part of
the trace's share, fixed by a :class:`StagePolicy` before decoding and recorded with the
trace in the registry. Policy ``bertahap-v1`` gives stage 1 a fraction 0.9 of the share and
splits the remaining 0.1 over stages 2, 3 and 4 in proportion 1, 1/4, 1/9 (that is 36/49,
9/49 and 4/49 of it). The fractions add up to exactly 1, so the stages of a trace together
spend the trace's share and the schedule over traces above is unchanged. A trace without a
policy (``policy=None``, every trace logged before staging existed) has a single stage that
spends the whole share, exactly as before.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass


def _trace_number(k: object) -> int:
    try:
        n = operator.index(k)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(f"nomor pelacakan harus bilangan bulat, bukan {k!r}") from None
    if isinstance(k, bool) or n < 1:
        raise ValueError(f"nomor pelacakan harus bilangan bulat mulai dari 1, bukan {k!r}")
    return n


def spending_share(k: int) -> float:
    """Fraction of the budget eps that trace number ``k`` (1-based) may spend: 6 / (pi^2 k^2).

    Positive, decreasing in k, and summing to 1 over k = 1, 2, 3, ... (about 0.608 for the
    first trace, 0.152 for the second, 0.068 for the third).
    """
    n = _trace_number(k)
    return 6.0 / (math.pi**2 * n * n)


def eps_for_trace(eps: float, k: int) -> float:
    """False-accusation budget of trace number ``k`` of a document with total budget ``eps``."""
    if not 0.0 < eps < 1.0:
        raise ValueError("peluang tuduhan salah eps harus di antara 0 dan 1")
    return eps * spending_share(k)


@dataclass(frozen=True)
class StagePolicy:
    """How one trace's share of eps is split over the stages of a staged accusation.

    Attributes:
        name: identifier recorded in the registry (``stage_policy`` of a ``trace`` entry).
        first_stage: fraction of the trace's share spent by stage 1 (the ordinary accusation).
        max_stages: largest number of stages, stage 1 included.

    Stage s >= 2 gets (1 - first_stage) * (1 / (s-1)^2) / H, with H = sum of 1/k^2 for
    k = 1 .. max_stages - 1, so the fractions of all stages add up to exactly 1.
    """

    name: str
    first_stage: float
    max_stages: int

    def __post_init__(self) -> None:
        if not 0.0 < self.first_stage <= 1.0:
            raise ValueError("bagian tahap 1 harus di antara 0 dan 1")
        if isinstance(self.max_stages, bool) or not isinstance(self.max_stages, int) or self.max_stages < 1:
            raise ValueError("jumlah tahap maksimum harus bilangan bulat mulai dari 1")
        if (self.max_stages == 1) != (self.first_stage == 1.0):
            raise ValueError("kebijakan satu tahap harus memberi seluruh jatah ke tahap 1")

    def fractions(self) -> tuple[float, ...]:
        """Fraction of the trace's share per stage (stage 1 first); they sum to 1."""
        if self.max_stages == 1:
            return (1.0,)
        later = [1.0 / (k * k) for k in range(1, self.max_stages)]
        total = math.fsum(later)
        rest = 1.0 - self.first_stage
        return (self.first_stage,) + tuple(rest * v / total for v in later)


# Fixed before any staged trace or simulation was run; see the module docstring.
STAGE_POLICIES: dict[str, StagePolicy] = {
    "bertahap-v1": StagePolicy("bertahap-v1", first_stage=0.9, max_stages=4),
}
DEFAULT_STAGE_POLICY = "bertahap-v1"


def stage_policy(name: str) -> StagePolicy:
    """The registered :class:`StagePolicy` called ``name``; ValueError for an unknown name."""
    policy = STAGE_POLICIES.get(name) if isinstance(name, str) else None
    if policy is None:
        raise ValueError(f"kebijakan tahap tidak dikenal: {name!r} (pilihan: {', '.join(sorted(STAGE_POLICIES))})")
    return policy


def split_stage_eps(eps_share: float, policy: str | None) -> tuple[float, ...]:
    """eps spent by each stage of a trace with share ``eps_share`` under ``policy``.

    ``policy=None`` is the single-stage accusation of every trace logged before staging
    existed: one stage spending the whole share.
    """
    if not 0.0 < eps_share < 1.0:
        raise ValueError("jatah eps pelacakan harus di antara 0 dan 1")
    if policy is None:
        return (eps_share,)
    return tuple(eps_share * f for f in stage_policy(policy).fractions())


@dataclass(frozen=True)
class TraceSpending:
    """The part of a document's false-accusation budget that one trace spends.

    Attributes:
        eps: the document's total budget (its code parameter).
        eps_share: what this trace spends; ``eps_for_trace(eps, trace_no)`` for a logged
            trace, all of ``eps`` for a trace that is not logged.
        trace_no: number of this trace of the document (1-based) in the registry log, or None
            when the trace is not logged and repeated traces are therefore not accounted for.
        policy: name of the :class:`StagePolicy` that splits ``eps_share`` over the stages of
            a staged accusation, or None for the single-stage accusation (all of
            ``eps_share`` at stage 1).
    """

    eps: float
    eps_share: float
    trace_no: int | None = None
    policy: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.eps < 1.0:
            raise ValueError("peluang tuduhan salah eps harus di antara 0 dan 1")
        expected = self.eps if self.trace_no is None else eps_for_trace(self.eps, self.trace_no)
        if not math.isclose(self.eps_share, expected, rel_tol=1e-9):
            raise ValueError("jatah eps pelacakan tidak sesuai jadwal 6 / (pi^2 k^2)")
        if self.policy is not None:
            stage_policy(self.policy)

    @classmethod
    def logged(cls, eps: float, trace_no: int, policy: str | None = None) -> "TraceSpending":
        """Trace number ``trace_no`` of the document, as recorded in the registry."""
        return cls(eps, eps_for_trace(eps, trace_no), _trace_number(trace_no), policy)

    @classmethod
    def unlogged(cls, eps: float, policy: str | None = None) -> "TraceSpending":
        """A trace that is not recorded anywhere: it spends the whole budget."""
        return cls(eps, eps, None, policy)

    @property
    def stage_eps(self) -> tuple[float, ...]:
        """eps spent by each stage (one entry, ``eps_share``, without a policy)."""
        return split_stage_eps(self.eps_share, self.policy)

    def stage_eps1(self, stage: int, n_max: int) -> float:
        """Per-copy target of stage ``stage`` (1-based): its eps over n_max."""
        if n_max < 1:
            raise ValueError("jumlah penerima maksimum n_max minimal 1")
        shares = self.stage_eps
        if isinstance(stage, bool) or not isinstance(stage, int) or not 1 <= stage <= len(shares):
            raise ValueError(f"tahap {stage!r} tidak ada dalam kebijakan pelacakan ini")
        return shares[stage - 1] / n_max

    @property
    def share(self) -> float:
        """eps_share / eps: 1 for an unlogged trace, ``spending_share(trace_no)`` otherwise."""
        return self.eps_share / self.eps

    def eps1(self, n_max: int) -> float:
        """Per-recipient target of this trace: eps_share / n_max (union bound over n_max)."""
        if n_max < 1:
            raise ValueError("jumlah penerima maksimum n_max minimal 1")
        return self.eps_share / n_max
