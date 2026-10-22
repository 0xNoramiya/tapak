"""Shared fixtures: a fixed code secret, the sample PDF and one issuance run."""

from __future__ import annotations

from pathlib import Path

import pytest

from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, issue

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
SECRET = bytes(range(32))


@pytest.fixture(autouse=True)
def _no_inherited_anchor_log(monkeypatch):
    """No test writes to an anchor log it did not set up (TAPAK_ANCHOR_LOG from the shell, or
    left behind by `tapak --log-jangkar` in another test, which sets the variable)."""
    monkeypatch.delenv("TAPAK_ANCHOR_LOG", raising=False)


@pytest.fixture(scope="session")
def sample_pdf() -> bytes:
    if not SAMPLE.exists():
        from tapak.samplegen import main as gen

        gen(["--templates", str(ROOT / "samples" / "templates"), "--out", str(ROOT / "samples")])
    return SAMPLE.read_bytes()


@pytest.fixture(scope="session")
def secret() -> bytes:
    return SECRET


@pytest.fixture(scope="session")
def recipients() -> list[Recipient]:
    return [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji") for i in range(1, 21)]


@pytest.fixture(scope="session")
def issued(tmp_path_factory, sample_pdf, secret, recipients) -> tuple[Path, IssueManifest]:
    out = tmp_path_factory.mktemp("issued")
    manifest = issue(SAMPLE, recipients, out, secret, IssueSettings(), issuer="pytest")
    return out, manifest


@pytest.fixture(scope="session")
def ctx(issued, sample_pdf, secret):
    from tapak.decoder.trace import load_context

    return load_context(sample_pdf, issued[1], secret)
