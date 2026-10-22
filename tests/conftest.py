"""Shared fixtures: a fixed code secret, the sample PDF and one issuance run."""

from __future__ import annotations

from pathlib import Path

import pytest

from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, issue

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
SECRET = bytes(range(32))


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


@pytest.fixture(scope="session")
def issued_v1(tmp_path_factory, sample_pdf, secret, recipients) -> tuple[Path, IssueManifest]:
    """An issuance with shift scheme geser-v1, the scheme of every document issued before
    geser-v2 (for tests of geser-v1 behaviour, whatever the default scheme)."""
    from tapak.marker.pdf_shift import ShiftSettings

    out = tmp_path_factory.mktemp("issued_v1")
    manifest = issue(SAMPLE, recipients, out, secret, IssueSettings(shift=ShiftSettings()), issuer="pytest")
    return out, manifest


@pytest.fixture(scope="session")
def ctx_v1(issued_v1, sample_pdf, secret):
    from tapak.decoder.trace import load_context

    return load_context(sample_pdf, issued_v1[1], secret)
