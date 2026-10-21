"""Paths shared by test modules (importable because pytest puts tests/ on sys.path)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
RECIPIENTS = ROOT / "samples" / "recipients.csv"
