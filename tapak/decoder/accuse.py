"""Attribution: run the Tardos accusation on the fused estimate and explain the result.

Order of operations (this order is the audit guarantee):

1. The threshold Z is computed from (bias vector p, reliability weights, eps1) and
   recorded with a timestamp. Nothing about any recipient enters this step. eps1 is the
   budget of this trace over n_max: trace number k of a document spends only
   eps * 6 / (pi^2 k^2) (see ``tapak.tardos.spending``), a trace that is not logged spends
   all of eps.
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
from tapak.tardos.spending import TraceSpending

VERDICT_IDENTIFIED = "teridentifikasi"
VERDICT_INSUFFICIENT = "tidak cukup bukti"
# Caveat added to a verdict whose named copy is supported only by marks a reader can see on
# paper (word choice, sentence variants): anyone who has read that copy can copy them into a
# retyped leak. The statistics are unchanged (the text does carry that copy's marks); what the
# name means is not. Shown next to the verdict in the berita acara.
VISIBLE_MARKS_NOTE = (
    "nama ini hanya didukung tanda yang terlihat di kertas (pilihan kata, varian kalimat); tanpa tanda itu "
    "salinan ini tidak mencapai ambang. Siapa pun yang pernah membaca salinan ini dapat meniru pilihan katanya "
    "saat mengetik ulang, jadi hasil ini menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan "
    "memerlukan bukti pendukung"
)
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
    """Score of one issued copy.

    ``log10_bound`` is log10 P(innocent score >= score) in this trace. The false-accusation
    probability is (copies - 1) times that bound, divided by the share of eps this trace
    spends (see :class:`ThresholdRecord`), so it holds for all traces of the document.
    """

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
    """The pre-registered threshold and its inputs.

    ``eps`` is the document's total budget, ``eps_share`` the part this trace spends and
    ``eps1 = eps_share / n_max``. ``trace_no`` is the number of this trace of the document in
    the registry log (None: the trace is not logged and spends all of eps).
    """

    rule: str
    eps: float
    eps1: float
    n_max: int
    n_observed: int
    effective_positions: float
    threshold: float
    fixed_at: str
    trace_no: int | None = None
    eps_share: float | None = None

    @property
    def spent(self) -> float:
        """eps spent by this trace (``eps_share``; all of ``eps`` when not recorded)."""
        return self.eps if self.eps_share is None else self.eps_share

    @property
    def share(self) -> float:
        """Fraction of the document's budget spent by this trace (1 when not logged)."""
        return self.spent / self.eps

    def budget_text(self) -> str:
        """'pelacakan ke-2 dokumen ini, jatah eps = 1.52e-07 dari eps = 1e-06' or 'eps = 1e-06'."""
        if self.trace_no is None:
            return f"eps = {self.eps:g}"
        return f"pelacakan ke-{self.trace_no} dokumen ini, jatah eps = {self.spent:.3g} dari eps = {self.eps:g}"


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
            f"ambang Z = {t.threshold:.1f} untuk {t.budget_text()} (eps1 = {t.eps1:.2e}), "
            f"ditetapkan {t.fixed_at} sebelum skor dihitung",
        ]
        for c in self.accused:
            lines.append(
                f"  Salinan #{c.copy.seq} ({c.copy.recipient_id}, {c.copy.nama}): skor {c.score:.1f} >= Z {t.threshold:.1f}; "
                f"peluang tuduhan salah <= {format_upper_bound(c.log10_false_accusation)}; "
                f"kanal yang sepakat secara independen: {len(c.channels_agreeing)} ({', '.join(c.channels_agreeing) or '-'})"
            )
        lines.extend(f"  PERHATIAN: {n}" for n in self.notes if VISIBLE_MARKS_NOTE in n)
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
        lines.extend(f"  Catatan: {n}" for n in self.notes if VISIBLE_MARKS_NOTE not in n)
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
    spending: TraceSpending | None = None,
) -> Attribution:
    """Accuse according to the fixed rule and assemble the explanation.

    ``spending`` is this trace's part of the budget (trace number known before decoding);
    None means a trace that is not logged, which spends all of ``params.eps``. The fused
    threshold, every channel threshold and the false-accusation probability of every copy
    use that same part: the probability is the per-trace bound divided by the share, so it
    covers every trace of the document together and stays comparable with eps.
    """
    if codewords.shape != (len(refs), params.length):
        raise ValueError("kata kode harus berukuran (jumlah salinan, m)")
    spending = TraceSpending.unlogged(params.eps) if spending is None else spending
    if not math.isclose(spending.eps, params.eps, rel_tol=1e-9):
        raise ValueError("jatah eps pelacakan tidak berasal dari eps dokumen ini")
    eps1 = spending.eps1(params.n_max)
    # Step 1: threshold first, from p and the decoder weights only.
    z = threshold(p, eps1, fused.weights)
    record = ThresholdRecord(
        rule=THRESHOLD_RULE, eps=params.eps, eps1=eps1, n_max=params.n_max,
        n_observed=fused.n_observed, effective_positions=float(np.sum(fused.weights**2)),
        threshold=z, fixed_at=_now(), trace_no=spending.trace_no, eps_share=spending.eps_share,
    )
    notes: list[str] = []
    if fused.n_observed == 0:
        notes.append("tidak ada tanda yang terbaca pada bukti")
    # Step 2: scores.
    s = scores(codewords, fused.y, p, fused.weights) if fused.n_observed else np.zeros(len(refs))
    n_others = max(len(refs) - 1, 1)
    log10_share = math.log10(spending.share)

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
        fap = min(1.0, n_others * math.exp(lb) / spending.share) if lb > -math.inf else 0.0
        log10_fap = (min(0.0, math.log10(n_others) + lb / math.log(10) - log10_share)
                     if lb > -math.inf else -math.inf)
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
