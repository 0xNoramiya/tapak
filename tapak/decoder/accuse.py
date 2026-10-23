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

Staged accusation (``tapak.tardos.staged``, when the trace's ``TraceSpending`` names a stage
policy). Steps 1 to 4 are stage 1, with stage 1's part of the trace's eps. If stage 1 named
someone, stage 2 re-scores every other copy with weights computed from the leaked bits, the
bias vector, the decoder weights and the codewords of the copies already named (never the
codeword of the copy being scored), against its own threshold Z_2 with its own part of eps,
again fixed and recorded before any stage-2 score; stage 3 does the same with every copy named
so far, up to the policy's last stage, stopping at the first stage that names nobody new.
A copy named at stage s >= 2 is reported with its stage score, Z_s and its own bound, always
together with the copies named before it ("tahap 2: dituduh berdasarkan salinan yang sudah
dituduh"). The verdict and ``Attribution.accused`` are stage 1's; later stages are in
``Attribution.stages``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np

from tapak.decoder.erasure import ERASURE_NOTE, ErasureCheck
from tapak.decoder.fuse import FusedEstimate
from tapak.marker.plan import OCR_SUBCHANNELS
from tapak.tardos.accuse import log_tail_bound, scores, threshold
from tapak.tardos.params import TardosParams
from tapak.tardos.spending import TraceSpending
from tapak.tardos.staged import stage_weights

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
STAGE_THRESHOLD_RULE = (
    "Z_s = the same Chernoff threshold with stage weights w_i = b_i v(p_i, y_i) / V at positions where "
    "no copy named at an earlier stage holds the leaked bit (w_i = 0 elsewhere), computed from the bias "
    "vector, the decoder weights b, the leaked bits and the codewords of the copies named earlier; never "
    "from the codeword of a copy scored at this stage"
)
# Marks a copy named at a later stage, next to the copies it depends on.
STAGE_BASIS_TEXT = "dituduh berdasarkan salinan yang sudah dituduh"


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

    ``eps`` is the document's total budget and ``eps_share`` the part this trace spends.
    ``trace_no`` is the number of this trace of the document in the registry log (None: the
    trace is not logged and spends all of eps). ``stage`` is the stage of a staged accusation
    this threshold belongs to (1 for the ordinary accusation), ``stage_eps`` the part of the
    trace's share that this stage spends under ``stage_policy`` (None: a single-stage trace,
    which spends the whole share at stage 1). ``eps1 = stage eps / n_max``.
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
    stage: int = 1
    stage_eps: float | None = None
    stage_policy: str | None = None

    @property
    def spent(self) -> float:
        """eps spent by this trace (``eps_share``; all of ``eps`` when not recorded)."""
        return self.eps if self.eps_share is None else self.eps_share

    @property
    def share(self) -> float:
        """Fraction of the document's budget spent by this trace (1 when not logged)."""
        return self.spent / self.eps

    @property
    def stage_spent(self) -> float:
        """eps spent by this stage (``stage_eps``; the trace's whole share without a policy)."""
        return self.spent if self.stage_eps is None else self.stage_eps

    @property
    def stage_share(self) -> float:
        """Fraction of the document's budget spent by this stage; bounds are divided by it."""
        return self.stage_spent / self.eps

    def budget_text(self) -> str:
        """'pelacakan ke-2 dokumen ini, jatah eps = 1.52e-07 dari eps = 1e-06' or 'eps = 1e-06'.

        A staged trace adds the part of that share this stage spends.
        """
        text = (f"eps = {self.eps:g}" if self.trace_no is None else
                f"pelacakan ke-{self.trace_no} dokumen ini, jatah eps = {self.spent:.3g} dari eps = {self.eps:g}")
        if self.stage_eps is None:
            return text
        return (f"{text}; tahap {self.stage} memakai {self.stage_spent:.3g} dari jatah itu "
                f"(kebijakan {self.stage_policy})")


@dataclass
class ChannelEvidence:
    """Outcome of the accusation using one physical channel alone.

    ``subchannels`` lists the sub-channels that read something (for example ``lexical_ocr``
    when word choices were read from the OCR text of an image); it only labels the row.
    """

    channel: str
    n_observed: int
    threshold: float
    top_seq: int | None
    top_score: float
    accused_seqs: list[int]
    subchannels: list[str] = field(default_factory=list)

    @property
    def source_label(self) -> str:
        """How the channel was read when that is not the obvious way: "OCR gambar" when every
        read came from the OCR text of an image, "teks dan OCR gambar" when both; else ""."""
        ocr = [s for s in self.subchannels if s in OCR_SUBCHANNELS]
        if not ocr:
            return ""
        return "OCR gambar" if len(ocr) == len(self.subchannels) else "teks dan OCR gambar"

    @property
    def display_name(self) -> str:
        """Physical channel name with ``source_label`` in brackets, e.g. "leksikal (OCR gambar)"."""
        return f"{self.channel} ({self.source_label})" if self.source_label else self.channel


@dataclass
class StageAttribution:
    """A later stage (2, 3, ...) of a staged accusation.

    Attributes:
        stage: stage number (2 or more).
        threshold: Z of this stage with its own eps (``ThresholdRecord.stage`` = ``stage``),
            fixed before any score of this stage; ``n_observed`` counts the unexplained
            positions (weight > 0).
        basis: copy numbers named at earlier stages; their codewords set this stage's weights,
            and a name at this stage is never shown without them.
        candidates: every copy scored at this stage (all copies not in ``basis``), best first,
            with this stage's score, bound and false-accusation probability (divided by this
            stage's share of eps). ``channel_scores`` stay empty: stages run on the fused
            estimate only.
    """

    stage: int
    threshold: ThresholdRecord
    basis: list[int]
    candidates: list[CopyCandidate]

    @property
    def accused(self) -> list[CopyCandidate]:
        """Copies named at this stage, best first."""
        return [c for c in self.candidates if c.accused]

    def basis_text(self) -> str:
        """'tahap 2: dituduh berdasarkan salinan yang sudah dituduh #3, #7'."""
        return f"tahap {self.stage}: {STAGE_BASIS_TEXT} " + ", ".join(f"#{s}" for s in self.basis)


@dataclass
class Attribution:
    """Full, auditable result of a trace.

    ``verdict``, ``threshold`` and ``candidates`` are stage 1 (the ordinary accusation);
    ``stages`` holds the later stages of a staged accusation, in order (empty otherwise).
    ``erasure`` is the code-blind check for erasure aimed at agreeing positions
    (``decoder/erasure.py``), set by ``trace.run_trace``; it never changes the verdict.
    """

    verdict: str
    threshold: ThresholdRecord
    candidates: list[CopyCandidate]
    channels: list[ChannelEvidence]
    conflicts: dict[str, tuple[int, int]]
    notes: list[str] = field(default_factory=list)
    stages: list[StageAttribution] = field(default_factory=list)
    erasure: ErasureCheck | None = None

    @property
    def accused(self) -> list[CopyCandidate]:
        """Copies whose score reached the stage-1 threshold, best first."""
        return [c for c in self.candidates if c.accused]

    @property
    def named(self) -> list[tuple[int, CopyCandidate]]:
        """Every named copy with the stage that named it: stage 1 first, then stages 2, 3, ..."""
        return [(1, c) for c in self.accused] + [(st.stage, c) for st in self.stages for c in st.accused]

    @property
    def named_seqs(self) -> set[int]:
        """Copy numbers named at any stage."""
        return {c.copy.seq for _, c in self.named}

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
        shown = {ch.channel: ch.display_name for ch in self.channels}
        for c in self.accused:
            agreeing = ", ".join(shown.get(k, k) for k in c.channels_agreeing) or "-"
            lines.append(
                f"  Salinan #{c.copy.seq} ({c.copy.recipient_id}, {c.copy.nama}): skor {c.score:.1f} >= Z {t.threshold:.1f}; "
                f"peluang tuduhan salah <= {format_upper_bound(c.log10_false_accusation)}; "
                f"kanal yang sepakat secara independen: {len(c.channels_agreeing)} ({agreeing})"
            )
        for st in self.stages:
            ts = st.threshold
            lines.append(
                f"  Tahap {st.stage} (pelacakan bertahap), mencari anggota koalisi lain berdasarkan salinan yang "
                "sudah dituduh " + ", ".join(f"#{s}" for s in st.basis)
                + f": {ts.n_observed} posisi tidak dijelaskan salinan itu; ambang Z{st.stage} = {ts.threshold:.1f} "
                f"untuk jatah eps tahap ini {ts.stage_spent:.3g} (eps1 = {ts.eps1:.2e}), ditetapkan {ts.fixed_at} "
                "sebelum skor tahap ini dihitung"
            )
            for c in st.accused:
                lines.append(
                    f"    Salinan #{c.copy.seq} ({c.copy.recipient_id}, {c.copy.nama}): {st.basis_text()}; skor tahap "
                    f"{st.stage} {c.score:.1f} >= Z{st.stage} {ts.threshold:.1f}; peluang tuduhan salah <= "
                    f"{format_upper_bound(c.log10_false_accusation)}"
                )
            if not st.accused:
                lines.append(f"    Tidak ada salinan lain yang mencapai ambang tahap {st.stage}.")
        lines.extend(f"  PERHATIAN: {n}" for n in self.notes if is_caveat(n))
        if not self.accused:
            best = self.candidates[0] if self.candidates else None
            if best is not None:
                lines.append(
                    f"  Tidak ada salinan yang mencapai ambang. Skor tertinggi {best.score:.1f} < Z {t.threshold:.1f}; "
                    "nama tidak disebutkan."
                )
        for ch in self.channels:
            lines.append(
                f"  Kanal {ch.display_name}: {ch.n_observed} posisi, ambang {ch.threshold:.1f}, "
                f"menuduh {len(ch.accused_seqs)} salinan"
            )
        if self.erasure is not None:
            lines.append(f"  Pemeriksaan pola penghapusan disengaja: {self.erasure.text()}")
        lines.extend(f"  Catatan: {n}" for n in self.notes if not is_caveat(n))
        return lines


def is_caveat(note: str) -> bool:
    """True for a note shown as a warning next to the verdict rather than among the other notes:
    a name resting only on marks visible on paper, or a deliberate erasure pattern."""
    return VISIBLE_MARKS_NOTE in note or note.startswith(ERASURE_NOTE)


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
            subchannels=list(est.subchannels),
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

    When ``spending.policy`` names a stage policy, that part is split over the stages: stage 1
    (everything above) uses its own fraction, and if it names someone the later stages of
    ``tapak.tardos.staged`` run on the fused estimate, each with its own fraction, its own
    threshold fixed before its scores, and bounds divided by its own share.
    """
    if codewords.shape != (len(refs), params.length):
        raise ValueError("kata kode harus berukuran (jumlah salinan, m)")
    spending = TraceSpending.unlogged(params.eps) if spending is None else spending
    if not math.isclose(spending.eps, params.eps, rel_tol=1e-9):
        raise ValueError("jatah eps pelacakan tidak berasal dari eps dokumen ini")
    staged = spending.policy is not None
    eps1 = spending.stage_eps1(1, params.n_max)
    # Step 1: threshold first, from p and the decoder weights only.
    z = threshold(p, eps1, fused.weights)
    record = ThresholdRecord(
        rule=THRESHOLD_RULE, eps=params.eps, eps1=eps1, n_max=params.n_max,
        n_observed=fused.n_observed, effective_positions=float(np.sum(fused.weights**2)),
        threshold=z, fixed_at=_now(), trace_no=spending.trace_no, eps_share=spending.eps_share,
        stage_eps=spending.stage_eps[0] if staged else None, stage_policy=spending.policy,
    )
    notes: list[str] = []
    if fused.n_observed == 0:
        notes.append("tidak ada tanda yang terbaca pada bukti")
    # Step 2: scores.
    s = scores(codewords, fused.y, p, fused.weights) if fused.n_observed else np.zeros(len(refs))

    channel_rows: list[ChannelEvidence] = []
    per_scores: dict[str, np.ndarray] = {}
    per_accused: dict[str, np.ndarray] = {}
    for name, est in sorted(per_channel.items()):
        ev, cs, ca = _channel_evidence(name, est, p, codewords, eps1, refs)
        channel_rows.append(ev)
        per_scores[name], per_accused[name] = cs, ca

    accused1 = (s >= z) if math.isfinite(z) else np.zeros(len(refs), dtype=bool)
    candidates = [
        _candidate(ref, float(s[j]), bool(accused1[j]), p, fused.weights, len(refs), record.stage_share,
                   channel_scores={k: float(v[j]) for k, v in per_scores.items()},
                   channels_agreeing=[k for k, v in per_accused.items() if v[j]])
        for j, ref in enumerate(refs)
    ]
    candidates.sort(key=lambda c: c.score, reverse=True)
    verdict = VERDICT_IDENTIFIED if any(c.accused for c in candidates) else VERDICT_INSUFFICIENT
    stages = _later_stages(fused, p, codewords, refs, params, spending, accused1) if staged else []
    for pair, (shared, disagree) in fused.conflicts.items():
        if shared >= 20 and disagree > 0.2 * shared:
            notes.append(f"kanal {pair} saling bertentangan pada {disagree} dari {shared} posisi; "
                         "kemungkinan salah satu kanal dimanipulasi")
    return Attribution(verdict=verdict, threshold=record, candidates=candidates,
                       channels=channel_rows, conflicts=fused.conflicts, notes=notes, stages=stages)


def _candidate(ref: CopyRef, score: float, accused: bool, p: np.ndarray, weights: np.ndarray, n_copies: int,
               share: float, channel_scores: dict[str, float] | None = None,
               channels_agreeing: list[str] | None = None) -> CopyCandidate:
    """One scored copy with its bound; the false-accusation probability is divided by ``share``."""
    n_others = max(n_copies - 1, 1)
    lb = log_tail_bound(score, p, weights)
    fap = min(1.0, n_others * math.exp(lb) / share) if lb > -math.inf else 0.0
    log10_fap = (min(0.0, math.log10(n_others) + lb / math.log(10) - math.log10(share))
                 if lb > -math.inf else -math.inf)
    return CopyCandidate(
        copy=ref, score=score, log10_bound=lb / math.log(10) if lb > -math.inf else -math.inf,
        false_accusation_probability=fap, accused=accused, log10_false_accusation=log10_fap,
        channel_scores=channel_scores or {}, channels_agreeing=channels_agreeing or [],
    )


def _later_stages(fused: FusedEstimate, p: np.ndarray, codewords: np.ndarray, refs: list[CopyRef],
                  params: TardosParams, spending: TraceSpending, accused1: np.ndarray) -> list[StageAttribution]:
    """Stages 2, 3, ... of a staged accusation (``tapak.tardos.staged``), after stage 1.

    Each stage fixes its weights (from y, p, the decoder weights and the named copies' rows of
    ``codewords``) and its threshold, records the time, and only then scores the copies not
    named yet. Runs while the previous stage named someone, up to the policy's last stage.
    """
    named = np.asarray(accused1, dtype=bool).copy()
    shares = spending.stage_eps
    out: list[StageAttribution] = []
    for stage in range(2, len(shares) + 1):
        if not out and not named.any():
            break
        if out and not out[-1].accused:
            break
        basis = np.flatnonzero(named)
        w = stage_weights(stage, fused.y, p, codewords, basis, fused.weights)
        eps1 = spending.stage_eps1(stage, params.n_max)
        z = threshold(p, eps1, w)  # fixed before any score of this stage
        observed = int(np.count_nonzero(w > 0))
        record = ThresholdRecord(
            rule=STAGE_THRESHOLD_RULE, eps=params.eps, eps1=eps1, n_max=params.n_max, n_observed=observed,
            effective_positions=float(np.sum(w**2)), threshold=z, fixed_at=_now(), trace_no=spending.trace_no,
            eps_share=spending.eps_share, stage=stage, stage_eps=shares[stage - 1], stage_policy=spending.policy,
        )
        scored = np.flatnonzero(~named)
        s = scores(codewords[scored], fused.y, p, w) if observed else np.zeros(scored.size)
        hit = (s >= z) if math.isfinite(z) else np.zeros(scored.size, dtype=bool)
        candidates = [_candidate(refs[j], float(s[k]), bool(hit[k]), p, w, len(refs), record.stage_share)
                      for k, j in enumerate(scored)]
        candidates.sort(key=lambda c: c.score, reverse=True)
        out.append(StageAttribution(stage, record, [refs[j].seq for j in basis], candidates))
        named[scored[hit]] = True
    return out
