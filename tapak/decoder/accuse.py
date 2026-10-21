"""Attribution: run the Tardos accusation on the fused estimate and explain the result.

Order of operations (this order is the audit guarantee):

1. The threshold Z is computed from (bias vector p, reliability weights, eps1) and
   recorded with a timestamp. Nothing about any recipient enters this step.
2. Only then are scores computed for every issued copy.
3. A copy is named only if its score reaches Z, and always together with its score, Z and
   the bound on the probability that an innocent recipient would score that high.
4. If no copy reaches Z the verdict is "tidak cukup bukti" and no name is given.

Per physical channel the same procedure runs on that channel alone, so the report can say
how many channels independently point at the same copy.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np

from tapak.decoder.fuse import FusedEstimate
from tapak.tardos.accuse import log_tail_bound, scores, threshold
from tapak.tardos.params import TardosParams

VERDICT_IDENTIFIED = "teridentifikasi"
VERDICT_INSUFFICIENT = "tidak cukup bukti"
THRESHOLD_RULE = (
    "Z = min_lambda (Lambda(lambda) + ln(1/eps1)) / lambda, Chernoff bound with the worst case "
    "leaked bit per position, computed from the bias vector and the decoder weights only"
)


@dataclass
class CopyRef:
    """Who received a copy (as recorded at issuance)."""

    seq: int
    copy_id: str
    recipient_id: str
    nama: str
    jabatan: str = ""
    satuan: str = ""


@dataclass
class CopyCandidate:
    """Score of one issued copy."""

    copy: CopyRef
    score: float
    log10_bound: float
    false_accusation_probability: float
    accused: bool
    log10_false_accusation: float = 0.0  # exact even when the probability underflows a float
    channel_scores: dict[str, float] = field(default_factory=dict)
    channels_agreeing: list[str] = field(default_factory=list)


@dataclass
class ThresholdRecord:
    """The pre-registered threshold and its inputs."""

    rule: str
    eps: float
    eps1: float
    n_max: int
    n_observed: int
    effective_positions: float
    threshold: float
    fixed_at: str


@dataclass
class ChannelEvidence:
    """Outcome of the accusation using one physical channel alone."""

    channel: str
    n_observed: int
    threshold: float
    top_seq: int | None
    top_score: float
    accused_seqs: list[int]


@dataclass
class Attribution:
    """Full, auditable result of a trace."""

    verdict: str
    threshold: ThresholdRecord
    candidates: list[CopyCandidate]
    channels: list[ChannelEvidence]
    conflicts: dict[str, tuple[int, int]]
    notes: list[str] = field(default_factory=list)

    @property
    def accused(self) -> list[CopyCandidate]:
        """Copies whose score reached the threshold, best first."""
        return [c for c in self.candidates if c.accused]

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return asdict(self)

    def summary_lines(self) -> list[str]:
        """Human-readable summary in Indonesian."""
        t = self.threshold
        lines = [
            f"Putusan: {self.verdict.upper()}",
            f"Posisi kode terbaca: {t.n_observed} (efektif {t.effective_positions:.0f}); "
            f"ambang Z = {t.threshold:.1f} untuk eps = {t.eps:g} (eps1 = {t.eps1:.2e}), "
            f"ditetapkan {t.fixed_at} sebelum skor dihitung",
        ]
        for c in self.accused:
            lines.append(
                f"  Salinan #{c.copy.seq} ({c.copy.recipient_id}, {c.copy.nama}): skor {c.score:.1f} >= Z {t.threshold:.1f}; "
                f"peluang tuduhan salah <= {format_upper_bound(c.log10_false_accusation)}; "
                f"kanal yang sepakat secara independen: {len(c.channels_agreeing)} ({', '.join(c.channels_agreeing) or '-'})"
            )
        if not self.accused:
            best = self.candidates[0] if self.candidates else None
            if best is not None:
                lines.append(
                    f"  Tidak ada salinan yang mencapai ambang. Skor tertinggi {best.score:.1f} < Z {t.threshold:.1f}; "
                    "nama tidak disebutkan."
                )
        for ch in self.channels:
            lines.append(
                f"  Kanal {ch.channel}: {ch.n_observed} posisi, ambang {ch.threshold:.1f}, "
                f"menuduh {len(ch.accused_seqs)} salinan"
            )
        lines.extend(f"  Catatan: {n}" for n in self.notes)
        return lines


def format_upper_bound(log10_p: float) -> str:
    """An upper bound written as m x 10^e, with the mantissa rounded UP (never understated)."""
    if log10_p == -math.inf:
        return "0"
    if log10_p >= 0:
        return "1"
    e = math.floor(log10_p)
    mant = math.ceil(10 ** (log10_p - e) * 100) / 100
    if mant >= 10:
        mant, e = mant / 10, e + 1
    return f"{mant:.2f}e{e:+03d}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _channel_evidence(name: str, est: FusedEstimate, p: np.ndarray, x: np.ndarray,
                      eps1: float, refs: list[CopyRef]) -> tuple[ChannelEvidence, np.ndarray, np.ndarray]:
    z = threshold(p, eps1, est.weights)
    s = scores(x, est.y, p, est.weights) if est.n_observed else np.zeros(len(refs))
    accused = s >= z
    top = int(np.argmax(s)) if len(s) else None
    return (
        ChannelEvidence(
            channel=name,
            n_observed=est.n_observed,
            threshold=z,
            top_seq=refs[top].seq if top is not None else None,
            top_score=float(s[top]) if top is not None else 0.0,
            accused_seqs=[refs[i].seq for i in np.nonzero(accused)[0]],
        ),
        s,
        accused,
    )


def attribute(
    fused: FusedEstimate,
    per_channel: dict[str, FusedEstimate],
    p: np.ndarray,
    codewords: np.ndarray,
    refs: list[CopyRef],
    params: TardosParams,
) -> Attribution:
    """Accuse according to the fixed rule and assemble the explanation."""
    if codewords.shape != (len(refs), params.length):
        raise ValueError("codewords must have shape (number of copies, m)")
    eps1 = params.eps1
    # Step 1: threshold first, from p and the decoder weights only.
    z = threshold(p, eps1, fused.weights)
    record = ThresholdRecord(
        rule=THRESHOLD_RULE, eps=params.eps, eps1=eps1, n_max=params.n_max,
        n_observed=fused.n_observed, effective_positions=float(np.sum(fused.weights**2)),
        threshold=z, fixed_at=_now(),
    )
    notes: list[str] = []
    if fused.n_observed == 0:
        notes.append("tidak ada tanda yang terbaca pada bukti")
    # Step 2: scores.
    s = scores(codewords, fused.y, p, fused.weights) if fused.n_observed else np.zeros(len(refs))
    n_others = max(len(refs) - 1, 1)

    channel_rows: list[ChannelEvidence] = []
    per_scores: dict[str, np.ndarray] = {}
    per_accused: dict[str, np.ndarray] = {}
    for name, est in sorted(per_channel.items()):
        ev, cs, ca = _channel_evidence(name, est, p, codewords, eps1, refs)
        channel_rows.append(ev)
        per_scores[name], per_accused[name] = cs, ca

    candidates = []
    for j, ref in enumerate(refs):
        lb = log_tail_bound(float(s[j]), p, fused.weights)
        fap = min(1.0, n_others * math.exp(lb)) if lb > -math.inf else 0.0
        log10_fap = min(0.0, math.log10(n_others) + lb / math.log(10)) if lb > -math.inf else -math.inf
        candidates.append(
            CopyCandidate(
                copy=ref,
                score=float(s[j]),
                log10_bound=lb / math.log(10) if lb > -math.inf else -math.inf,
                false_accusation_probability=fap,
                accused=bool(math.isfinite(z) and s[j] >= z),
                log10_false_accusation=log10_fap,
                channel_scores={k: float(v[j]) for k, v in per_scores.items()},
                channels_agreeing=[k for k, v in per_accused.items() if v[j]],
            )
        )
    candidates.sort(key=lambda c: c.score, reverse=True)
    verdict = VERDICT_IDENTIFIED if any(c.accused for c in candidates) else VERDICT_INSUFFICIENT
    for pair, (shared, disagree) in fused.conflicts.items():
        if shared >= 20 and disagree > 0.2 * shared:
            notes.append(f"kanal {pair} saling bertentangan pada {disagree} dari {shared} posisi; "
                         "kemungkinan salah satu kanal dimanipulasi")
    return Attribution(verdict=verdict, threshold=record, candidates=candidates,
                       channels=channel_rows, conflicts=fused.conflicts, notes=notes)
