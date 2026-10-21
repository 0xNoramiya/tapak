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
class TraceSpending:
    """The part of a document's false-accusation budget that one trace spends.

    Attributes:
        eps: the document's total budget (its code parameter).
        eps_share: what this trace spends; ``eps_for_trace(eps, trace_no)`` for a logged
            trace, all of ``eps`` for a trace that is not logged.
        trace_no: number of this trace of the document (1-based) in the registry log, or None
            when the trace is not logged and repeated traces are therefore not accounted for.
    """

    eps: float
    eps_share: float
    trace_no: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.eps < 1.0:
            raise ValueError("peluang tuduhan salah eps harus di antara 0 dan 1")
        expected = self.eps if self.trace_no is None else eps_for_trace(self.eps, self.trace_no)
        if not math.isclose(self.eps_share, expected, rel_tol=1e-9):
            raise ValueError("jatah eps pelacakan tidak sesuai jadwal 6 / (pi^2 k^2)")

    @classmethod
    def logged(cls, eps: float, trace_no: int) -> "TraceSpending":
        """Trace number ``trace_no`` of the document, as recorded in the registry."""
        return cls(eps, eps_for_trace(eps, trace_no), _trace_number(trace_no))

    @classmethod
    def unlogged(cls, eps: float) -> "TraceSpending":
        """A trace that is not recorded anywhere: it spends the whole budget."""
        return cls(eps, eps, None)

    @property
    def share(self) -> float:
        """eps_share / eps: 1 for an unlogged trace, ``spending_share(trace_no)`` otherwise."""
        return self.eps_share / self.eps

    def eps1(self, n_max: int) -> float:
        """Per-recipient target of this trace: eps_share / n_max (union bound over n_max)."""
        if n_max < 1:
            raise ValueError("jumlah penerima maksimum n_max minimal 1")
        return self.eps_share / n_max
