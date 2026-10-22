"""Monte Carlo simulation of collusion attacks against the Tardos code.

For every trial a fresh code (p, X) is drawn, a random coalition of size ``coalition``
forges a word with each strategy, and the accusation is run against all ``n`` users with
the threshold fixed beforehand. Reported per strategy:

* false-accusation rate: fraction of trials in which at least one innocent was accused;
* detection rate: fraction of trials in which at least one colluder was accused;
* all-caught rate: fraction of trials in which every colluder was accused.

On a noise-free read the probability of a miss (no colluder accused) is at most the proven
bound of ``detection.miss_bound``; with the simulated channel (flips and erasures independent
of the code and of each other) it is at most ``detection.channel_miss_bound``.

Zero false accusations in 1000 trials only shows the rate is below about 3e-3 (rule of
three). To check the bound itself, ``bound_check`` also counts how often innocent scores
exceed thresholds computed for loose targets (1e-2, 1e-3) that are testable by sampling.

``run_staged_simulation`` compares, on the same code draws and leaked words, the single-stage
accusation (the whole budget at stage 1) with the staged accusation of ``staged.py`` under a
stage policy, counting members caught at every stage, innocents named at every stage, and how
often innocent scores of the later stages exceed their own thresholds at loose targets.
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
from tapak.tardos.spending import DEFAULT_STAGE_POLICY, split_stage_eps
from tapak.tardos.staged import staged_accuse


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
class StagedStrategyResult:
    """Single-stage versus staged accusation for one strategy, summed over all trials.

    ``single_*`` is the ordinary accusation with the whole budget at stage 1; ``staged_*``
    the staged accusation (stage 1 with its fraction, then the side-informed stages). Lists
    ``stage_*`` have one entry per stage of the policy (stage 1 first): ``stage_runs`` trials
    in which the stage ran, ``stage_members`` members newly named there, ``stage_innocents``
    innocents named there, ``stage_max_innocent_over_threshold`` the largest innocent score
    over that stage's (finite) threshold, ``stage_mean_threshold`` the mean finite threshold
    and ``stage_mean_positions`` the mean number of positions with non-zero weight.
    """

    strategy: str
    trials: int
    coalition: int
    single_members_caught: int
    single_detected_trials: int
    single_all_caught_trials: int
    single_false_accusation_trials: int
    staged_members_caught: int
    staged_detected_trials: int
    staged_all_caught_trials: int
    staged_false_accusation_trials: int
    stage_runs: list[int]
    stage_members: list[int]
    stage_innocents: list[int]
    stage_max_innocent_over_threshold: list[float]
    stage_mean_threshold: list[float]
    stage_mean_positions: list[float]
    single_max_innocent_over_threshold: float = -math.inf
    single_mean_threshold: float = 0.0

    @property
    def single_member_fraction(self) -> float:
        """Fraction of all coalition members named by the single-stage accusation."""
        return self.single_members_caught / (self.trials * self.coalition)

    @property
    def staged_member_fraction(self) -> float:
        """Fraction of all coalition members named at some stage."""
        return self.staged_members_caught / (self.trials * self.coalition)


@dataclass
class StagedSimulationReport:
    """Output of :func:`run_staged_simulation` (serializable with :meth:`to_dict`).

    ``stage_eps1`` is the per-copy target of every stage; ``single_eps1`` the single-stage
    target (the sum of the stage targets). ``bound_check`` holds, per loose target, how often
    an innocent copy's score at a stage >= 2 reached that stage's threshold recomputed for
    the target with the same weights (``exceed`` out of ``evaluations``).
    """

    params: dict[str, object]
    n_users: int
    coalition: int
    trials: int
    ber: float
    erasure: float
    seed: int
    policy: str
    single_eps1: float
    stage_eps1: list[float]
    results: list[StagedStrategyResult]
    bound_check: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly dictionary including the member fractions (non-finite numbers: None)."""
        out = asdict(self)
        for r_dict, r in zip(out["results"], self.results):
            r_dict.update(single_member_fraction=r.single_member_fraction,
                          staged_member_fraction=r.staged_member_fraction)
            for key, value in r_dict.items():
                if isinstance(value, float) and not math.isfinite(value):
                    r_dict[key] = None
                elif isinstance(value, list):
                    r_dict[key] = [None if isinstance(v, float) and not math.isfinite(v) else v for v in value]
        for b in out["bound_check"].values():
            if not math.isfinite(b["empirical"]):
                b["empirical"] = None
        return out


def run_staged_simulation(
    params: TardosParams,
    n_users: int,
    coalition: int,
    trials: int = 1000,
    strategies: list[str] | None = None,
    seed: int = 2026,
    ber: float = 0.0,
    erasure: float = 0.0,
    policy: str = DEFAULT_STAGE_POLICY,
    eps_share: float | None = None,
    bound_levels: tuple[float, ...] = (1e-2, 1e-3),
) -> StagedSimulationReport:
    """Simulate the single-stage and the staged accusation on the same codes and leaks.

    ``eps_share`` is the budget of the simulated trace (default ``params.eps``, a trace that
    spends the whole budget); the single-stage accusation spends all of it at stage 1, the
    staged one splits it with ``policy``. Per-copy targets divide by ``params.n_max``.
    """
    strategies = list(STRATEGIES) if strategies is None else strategies
    unknown = set(strategies) - set(STRATEGIES)
    if unknown:
        raise ValueError(f"strategi tidak dikenal: {sorted(unknown)} (pilihan: {sorted(STRATEGIES)})")
    if not 1 <= coalition < n_users:
        raise ValueError("ukuran koalisi harus antara 1 dan jumlah penerima dikurangi 1")
    share = params.eps if eps_share is None else float(eps_share)
    stage_e1 = [e / params.n_max for e in split_stage_eps(share, policy)]
    single_e1 = share / params.n_max
    k = len(stage_e1)
    rng = np.random.default_rng(seed)
    acc = {s: {"single": [0, 0, 0, 0], "staged": [0, 0, 0, 0], "runs": [0] * k, "members": [0] * k,
               "innocents": [0] * k, "ratio": [-math.inf] * k, "z": [0.0] * k, "nz": [0] * k, "pos": [0] * k,
               "sratio": -math.inf, "sz": 0.0} for s in strategies}
    exceed = {lvl: 0 for lvl in bound_levels}
    evaluations = 0

    for _ in range(trials):
        p, x_bits = random_code(params, n_users, rng)
        x = x_bits.astype(np.float64)
        members = rng.choice(n_users, size=coalition, replace=False)
        is_member = np.zeros(n_users, dtype=bool)
        is_member[members] = True
        z_single_full = threshold(p, single_e1)
        for name in strategies:
            y, w = STRATEGIES[name](x_bits[members], rng)
            y, w = add_channel_noise(y, w, rng, ber=ber, erasure=erasure)
            a = acc[name]
            z = z_single_full if bool(np.all(w == 1.0)) else threshold(p, single_e1, w)
            s = scores(x, y, p, w)
            single = (s >= z) if math.isfinite(z) else np.zeros(n_users, dtype=bool)
            _tally(a["single"], single, is_member)
            a["sz"] += z
            if math.isfinite(z):
                a["sratio"] = max(a["sratio"], float(np.max(s[~is_member]) / z))
            named = np.zeros(n_users, dtype=bool)
            for st in staged_accuse(x_bits, y, p, stage_e1, w):
                i = st.stage - 1
                a["runs"][i] += 1
                a["pos"][i] += st.n_observed
                a["members"][i] += int(np.count_nonzero(is_member[st.accused]))
                a["innocents"][i] += int(np.count_nonzero(~is_member[st.accused]))
                innocent = ~is_member[st.scored]
                if math.isfinite(st.threshold):
                    a["z"][i] += st.threshold
                    a["nz"][i] += 1
                    if innocent.any():
                        a["ratio"][i] = max(a["ratio"][i], float(np.max(st.scores[innocent]) / st.threshold))
                if st.stage >= 2 and st.n_observed and innocent.any():
                    evaluations += int(np.count_nonzero(innocent))
                    for lvl in bound_levels:
                        exceed[lvl] += int(np.count_nonzero(st.scores[innocent] >= threshold(p, lvl, st.weights)))
                named[st.accused] = True
            _tally(a["staged"], named, is_member)

    results = []
    for name in strategies:
        a = acc[name]
        results.append(StagedStrategyResult(
            strategy=name, trials=trials, coalition=coalition,
            single_members_caught=a["single"][0], single_detected_trials=a["single"][1],
            single_all_caught_trials=a["single"][2], single_false_accusation_trials=a["single"][3],
            staged_members_caught=a["staged"][0], staged_detected_trials=a["staged"][1],
            staged_all_caught_trials=a["staged"][2], staged_false_accusation_trials=a["staged"][3],
            stage_runs=a["runs"], stage_members=a["members"], stage_innocents=a["innocents"],
            stage_max_innocent_over_threshold=a["ratio"],
            stage_mean_threshold=[z / n if n else math.nan for z, n in zip(a["z"], a["nz"])],
            stage_mean_positions=[q / n if n else math.nan for q, n in zip(a["pos"], a["runs"])],
            single_max_innocent_over_threshold=a["sratio"], single_mean_threshold=a["sz"] / trials,
        ))
    bound_check = {
        f"{lvl:g}": {"target": lvl, "exceed": float(exceed[lvl]), "evaluations": float(evaluations),
                     "empirical": exceed[lvl] / evaluations if evaluations else float("nan")}
        for lvl in bound_levels
    }
    return StagedSimulationReport(
        params=params.to_dict(), n_users=n_users, coalition=coalition, trials=trials, ber=ber, erasure=erasure,
        seed=seed, policy=policy, single_eps1=single_e1, stage_eps1=stage_e1, results=results,
        bound_check=bound_check,
    )


def _tally(counts: list[int], named: np.ndarray, is_member: np.ndarray) -> None:
    """Add (members named, at least one, all, any innocent) of one trial to ``counts``."""
    hits = int(np.count_nonzero(named & is_member))
    counts[0] += hits
    counts[1] += int(hits > 0)
    counts[2] += int(hits == int(is_member.sum()))
    counts[3] += int(np.any(named & ~is_member))


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
