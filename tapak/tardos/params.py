"""Tardos code parameters.

The code length follows m = K * c^2 * ln(1/eps1), where eps1 is the per-recipient
false-accusation probability. TAPAK states the false-accusation target ``eps`` for the
whole recipient list and splits it with a union bound: eps1 = eps / n_max, so the
probability that *any* innocent recipient is accused is at most ``eps``.

Two constants are available:

* ``"skoric"`` (default): K = 2*pi^2 (about 19.74), derived by Skoric, Vladimirova, Celik
  and Talstra (IEEE Trans. Inf. Theory 2008, arXiv cs/0607131) under a Gaussian
  approximation for Tardos' original score, later shown sufficient for large c by
  Laarhoven and de Weger (2014). TAPAK uses the symmetric score of Skoric, Katzenbeisser
  and Celik (2008), whose constants are lower (pi^2 rigorous asymptotically, pi^2/2
  asymptotically optimal), so K = 2*pi^2 leaves a 2x to 4x margin for detection.
* ``"tardos"``: K = 100, Tardos' original constant (STOC 2003 / J. ACM 2008); it remains
  provably sufficient with the symmetric score.

Important: in TAPAK the *false-accusation* guarantee never depends on K or on any
approximation. The threshold is computed from a rigorous Chernoff bound on the actual bias
vector (see ``accuse.py``). K only influences the *detection* rate, which the simulation
measures.

The bias cutoff t = 1/(300 c) is Tardos' original choice.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

ConstantName = Literal["skoric", "tardos"]

CONSTANTS: dict[str, float] = {
    "skoric": 2.0 * math.pi**2,
    "tardos": 100.0,
}


@dataclass(frozen=True)
class TardosParams:
    """Parameters of one Tardos code (one code per issued document).

    Attributes:
        c: maximum coalition size the code is dimensioned for.
        eps: probability that at least one innocent recipient is accused.
        n_max: maximum number of recipients (copies) for this document.
        constant: which code-length constant to use (see module docstring).
    """

    c: int = 3
    eps: float = 1e-6
    n_max: int = 100
    constant: ConstantName = "skoric"

    def __post_init__(self) -> None:
        if self.c < 1:
            raise ValueError("ukuran koalisi c minimal 1")
        if not 0.0 < self.eps < 1.0:
            raise ValueError("peluang tuduhan salah eps harus di antara 0 dan 1")
        if self.n_max < 1:
            raise ValueError("jumlah penerima maksimum n_max minimal 1")
        if self.constant not in CONSTANTS:
            raise ValueError(f"konstanta panjang kode tidak dikenal: {self.constant!r} (pilih skoric atau tardos)")

    @property
    def eps1(self) -> float:
        """Per-recipient false-accusation probability (union bound over n_max)."""
        return self.eps / self.n_max

    @property
    def k_constant(self) -> float:
        """Numeric value of the code-length constant K."""
        return CONSTANTS[self.constant]

    @property
    def length(self) -> int:
        """Code length m = ceil(K * c^2 * ln(1/eps1))."""
        return math.ceil(self.k_constant * self.c**2 * math.log(1.0 / self.eps1))

    @property
    def cutoff(self) -> float:
        """Bias cutoff t: every p_i lies in [t, 1 - t]."""
        return 1.0 / (300.0 * self.c)

    def to_dict(self) -> dict[str, object]:
        """Serializable form including derived values, for manifests and logs."""
        d: dict[str, object] = asdict(self)
        d.update(eps1=self.eps1, length=self.length, cutoff=self.cutoff, k_constant=self.k_constant)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "TardosParams":
        """Inverse of :meth:`to_dict` (derived fields are ignored)."""
        return cls(
            c=int(d["c"]),  # type: ignore[arg-type]
            eps=float(d["eps"]),  # type: ignore[arg-type]
            n_max=int(d["n_max"]),  # type: ignore[arg-type]
            constant=str(d["constant"]),  # type: ignore[arg-type]
        )
