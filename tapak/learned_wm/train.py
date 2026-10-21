"""Training loop for the learned watermark (TODO).

Loss = BCE(decoded bits, message) + lambda * L2(residual), with the residual clamped to
+/- 2 gray levels; curriculum on degradation strength.
"""

from __future__ import annotations

from tapak.learned_wm.model import require_torch


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - scaffold
    """Entry point (not implemented yet)."""
    require_torch()
    print("TODO: pelatihan model tanda air terlatih belum diimplementasikan")
    return 1
