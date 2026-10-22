"""Monte Carlo simulation of collusion attacks against the Tardos code.

For every trial a fresh code (p, X) is drawn, a random coalition of size ``coalition``
forges a word with each strategy, and the accusation is run against all ``n`` users with
the threshold fixed beforehand. Reported per strategy:

* false-accusation rate: fraction of trials in which at least one innocent was accused;
* detection rate: fraction of trials in which at least one colluder was accused;
* all-caught rate: fraction of trials in which every colluder was accused.

On a noise-free read the probability of a miss (no colluder accused) is at most the proven
bound of ``detection.miss_bound``; for noisy reads the simulation is the only measure.

Zero false accusations in 1000 trials only shows the rate is below about 3e-3 (rule of
three). To check the bound itself, ``bound_check`` also counts how often innocent scores
exceed thresholds computed for loose targets (1e-2, 1e-3) that are testable by sampling.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from tapak.tardos.accuse import gaussian_threshold, scores, threshold
from tapak.tardos.attacks import STRATEGIES, add_channel_noise
from tapak.tardos.code import random_code
from tapak.tardos.detection import proven_miss_probability
from tapak.tardos.params import TardosParams


@dataclass
class StrategyResult:
    """Aggregated outcome of one collusion strategy over all trials."""

    strategy: str
    trials: int
    false_accusation_trials: int
    detected_trials: int
    all_caught_trials: int
    mean_threshold: float
    mean_top_colluder_score: float
    max_innocent_over_threshold: float

    @property
    def false_accusation_rate(self) -> float:
        """Fraction of trials with at least one innocent accused."""
        return self.false_accusation_trials / self.trials

    @property
    def detection_rate(self) -> float:
        """Fraction of trials with at least one colluder accused."""
        return self.detected_trials / self.trials

    @property
    def all_caught_rate(self) -> float:
        """Fraction of trials with every colluder accused."""
        return self.all_caught_trials / self.trials


@dataclass
class SimulationReport:
    """Full simulation output (serializable with :meth:`to_dict`)."""

    params: dict[str, object]
    n_users: int
    coalition: int
    trials: int
    ber: float
    erasure: float
    seed: int
    results: list[StrategyResult]
    bound_check: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly dictionary including the derived rates."""
        out = asdict(self)
        for r_dict, r in zip(out["results"], self.results):
            r_dict.update(
                false_accusation_rate=r.false_accusation_rate,
                detection_rate=r.detection_rate,
                all_caught_rate=r.all_caught_rate,
            )
        return out


def run_simulation(
    params: TardosParams,
    n_users: int,
    coalition: int | None = None,
    trials: int = 1000,
    strategies: list[str] | None = None,
    seed: int = 2026,
    ber: float = 0.0,
    erasure: float = 0.0,
    bound_levels: tuple[float, ...] = (1e-2, 1e-3),
    length: int | None = None,
) -> SimulationReport:
    """Run the simulation; see the module docstring for what is measured.

    ``length`` overrides the code length (default ``params.length``), e.g. to compare the
    proven miss bound of ``detection.miss_bound`` with measured rates on short codes where
    misses are frequent. The threshold is computed for the code actually drawn.
    """
    coalition = params.c if coalition is None else coalition
    strategies = list(STRATEGIES) if strategies is None else strategies
    unknown = set(strategies) - set(STRATEGIES)
    if unknown:
        raise ValueError(f"strategi tidak dikenal: {sorted(unknown)} (pilihan: {sorted(STRATEGIES)})")
    if not 1 <= coalition < n_users:
        raise ValueError("ukuran koalisi harus antara 1 dan jumlah penerima dikurangi 1")

    rng = np.random.default_rng(seed)
    acc = {s: dict(fa=0, det=0, all=0, z=0.0, top=0.0, ratio=-math.inf) for s in strategies}
    exceed = {lvl: 0 for lvl in bound_levels}
    innocent_evals = 0

    for _ in range(trials):
        p, x_bits = random_code(params, n_users, rng, length)
        x = x_bits.astype(np.float64)
        members = rng.choice(n_users, size=coalition, replace=False)
        is_member = np.zeros(n_users, dtype=bool)
        is_member[members] = True
        z_full = threshold(p, params.eps1)
        loose = {lvl: threshold(p, lvl) for lvl in bound_levels}

        for name in strategies:
            y, w = STRATEGIES[name](x_bits[members], rng)
            y, w = add_channel_noise(y, w, rng, ber=ber, erasure=erasure)
            all_observed = bool(np.all(w == 1.0))
            z = z_full if all_observed else threshold(p, params.eps1, w)
            s = scores(x, y, p, w)
            accused = s >= z
            a = acc[name]
            a["fa"] += int(np.any(accused & ~is_member))
            a["det"] += int(np.any(accused & is_member))
            a["all"] += int(np.all(accused[is_member]))
            a["z"] += z
            a["top"] += float(np.max(s[is_member]))
            a["ratio"] = max(a["ratio"], float(np.max(s[~is_member]) / z))
            if all_observed:
                innocent = s[~is_member]
                innocent_evals += innocent.size
                for lvl in bound_levels:
                    exceed[lvl] += int(np.count_nonzero(innocent >= loose[lvl]))

    results = [
        StrategyResult(
            strategy=name,
            trials=trials,
            false_accusation_trials=acc[name]["fa"],
            detected_trials=acc[name]["det"],
            all_caught_trials=acc[name]["all"],
            mean_threshold=acc[name]["z"] / trials,
            mean_top_colluder_score=acc[name]["top"] / trials,
            max_innocent_over_threshold=acc[name]["ratio"],
        )
        for name in strategies
    ]
    bound_check = {
        f"{lvl:g}": {
            "target": lvl,
            "empirical": exceed[lvl] / innocent_evals if innocent_evals else float("nan"),
            "innocent_evaluations": float(innocent_evals),
        }
        for lvl in bound_levels
    }
    params_dict = params.to_dict()
    if length is not None:
        params_dict["length"] = int(length)
    return SimulationReport(
        params=params_dict,
        n_users=n_users,
        coalition=coalition,
        trials=trials,
        ber=ber,
        erasure=erasure,
        seed=seed,
        results=results,
        bound_check=bound_check,
    )


@dataclass
class TableRow:
    """One row of the parameter table."""

    n: int
    c: int
    eps1: float
    m_skoric: int
    m_tardos: int
    z_chernoff: float
    z_gaussian: float
    expected_top_colluder: float
    miss_bound: float


def parameter_table(
    ns: tuple[int, ...] = (20, 50, 100, 500),
    cs: tuple[int, ...] = (2, 3, 5),
    eps: float = 1e-6,
    seed: int = 7,
) -> list[TableRow]:
    """Code lengths and thresholds for the default (Skoric) constant, plus K=100 lengths.

    ``z_chernoff`` is the median over 5 bias draws of the rigorous threshold;
    ``expected_top_colluder`` is 2m/(pi c), the guaranteed average colluder score;
    ``miss_bound`` is the proven upper bound on the probability that a coalition of at most
    c recipients escapes a full hard-decision read at the default length (Z for eps1 = eps/N,
    see ``detection.proven_miss_probability``).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for n in ns:
        for c in cs:
            ps = TardosParams(c=c, eps=eps, n_max=n, constant="skoric")
            pt = TardosParams(c=c, eps=eps, n_max=n, constant="tardos")
            zs = [threshold(random_code(ps, 1, rng)[0], ps.eps1) for _ in range(5)]
            rows.append(
                TableRow(
                    n=n,
                    c=c,
                    eps1=ps.eps1,
                    m_skoric=ps.length,
                    m_tardos=pt.length,
                    z_chernoff=float(np.median(zs)),
                    z_gaussian=gaussian_threshold(ps.length, ps.eps1),
                    expected_top_colluder=2 * ps.length / (math.pi * c),
                    miss_bound=proven_miss_probability(ps),
                )
            )
    return rows
