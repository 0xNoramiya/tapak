"""Bundled fonts (DejaVu, Bitstream Vera license; see assets/fonts/LICENSE-DejaVu.txt)."""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

BUNDLED = {
    "DejaVuSans": "DejaVuSans.ttf",
    "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
}


def font_path(name: str) -> Path:
    """Path of a bundled font by PostScript-style name, e.g. ``DejaVuSans-Bold``."""
    try:
        return FONT_DIR / BUNDLED[name]
    except KeyError as exc:
        raise KeyError(f"font {name!r} tidak disertakan; tersedia: {sorted(BUNDLED)}") from exc


def strip_subset_tag(name: str) -> str:
    """Remove a PDF subset prefix such as ``ABCDEF+`` from a font name."""
    if len(name) > 7 and name[6] == "+" and name[:6].isalpha() and name[:6].isupper():
        return name[7:]
    return name
