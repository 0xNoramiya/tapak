"""Export the trained decoder to ONNX for CPU inference with onnxruntime (TODO)."""

from __future__ import annotations

from tapak.learned_wm.model import require_torch


def export(checkpoint: str, out_path: str) -> None:  # pragma: no cover - scaffold
    """Export the decoder half of a checkpoint (not implemented yet)."""
    require_torch()
    raise NotImplementedError("TODO: ekspor ONNX belum diimplementasikan")
