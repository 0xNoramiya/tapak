"""Differentiable photo-degradation layer for training (TODO).

Planned operations, mirroring ``tapak/photos.py`` but in torch so gradients flow: random
perspective (kornia-style homography warp), Gaussian and motion blur, brightness/contrast
and shading fields, additive and shot noise, and a differentiable JPEG approximation
(DCT quantization with straight-through rounding).
"""

from __future__ import annotations

from tapak.learned_wm.model import require_torch


def degrade(batch: "torch.Tensor", strength: float = 1.0) -> "torch.Tensor":  # pragma: no cover - scaffold
    """Apply random degradations to a batch of images in [0, 1] (not implemented yet)."""
    require_torch()
    raise NotImplementedError("TODO: degradasi terdiferensiasi belum diimplementasikan")
