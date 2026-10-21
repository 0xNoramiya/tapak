"""Tiny StegaStamp-style encoder and decoder (requires the optional PyTorch extra).

Encoder: (cover patch, message bits) -> residual added to the patch, kept within
+/- ``max_amplitude`` gray levels. Decoder: (degraded patch) -> one logit per bit.
"""

from __future__ import annotations

try:  # pragma: no cover - optional dependency
    import torch
    from torch import nn
except ImportError:  # pragma: no cover
    torch = None
    nn = None


def require_torch() -> None:
    """Raise a clear message if PyTorch is not installed."""
    if torch is None:
        raise RuntimeError("PyTorch tidak terpasang; jalankan: pip install -e .[learned]")


if nn is not None:  # pragma: no cover - exercised only with the extra installed

    class TinyStegaStamp(nn.Module):
        """Encoder and decoder for ``n_bits`` per 128x128 patch."""

        def __init__(self, n_bits: int = 64, max_amplitude: float = 2.0 / 255.0) -> None:
            super().__init__()
            self.n_bits = n_bits
            self.max_amplitude = max_amplitude
            self.msg = nn.Linear(n_bits, 16 * 16)
            self.enc = nn.Sequential(
                nn.Conv2d(2, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 1, 1), nn.Tanh(),
            )
            self.dec = nn.Sequential(
                nn.Conv2d(1, 32, 3, stride=2, padding=1), nn.ReLU(),
                nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
                nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.ReLU(),
                nn.AdaptiveAvgPool2d(4), nn.Flatten(), nn.Linear(64 * 16, n_bits),
            )

        def encode(self, cover: "torch.Tensor", bits: "torch.Tensor") -> "torch.Tensor":
            m = self.msg(bits * 2 - 1).view(-1, 1, 16, 16)
            m = nn.functional.interpolate(m, size=cover.shape[-2:], mode="bilinear", align_corners=False)
            residual = self.enc(torch.cat([cover, m], dim=1)) * self.max_amplitude
            return (cover + residual).clamp(0, 1)

        def decode(self, image: "torch.Tensor") -> "torch.Tensor":
            return self.dec(image)
