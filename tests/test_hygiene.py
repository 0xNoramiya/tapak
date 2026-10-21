"""Repository hygiene rules that a reviewer would otherwise have to check by eye."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".html", ".txt", ".toml", ".yml", ".yaml", ".json", ".csv", ".css", ".js", ".cfg"}
EM_DASH = chr(0x2014)
SKIP_PARTS = {".venv", ".git", ".claude", "__pycache__", ".pytest_cache", "out", "data", "node_modules"}


def _files(suffixes: set[str]):
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in suffixes and not (set(p.relative_to(ROOT).parts) & SKIP_PARTS):
            yield p


def test_python_sources_are_ascii():
    """Invisible or look-alike characters must appear only as escapes in source code."""
    offenders = []
    for p in _files({".py"}):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(ord(ch) > 126 for ch in line):
                offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


def test_no_em_dashes_anywhere():
    offenders = [str(p.relative_to(ROOT)) for p in _files(TEXT_SUFFIXES)
                 if EM_DASH in p.read_text(encoding="utf-8", errors="ignore")]
    assert not offenders, offenders
