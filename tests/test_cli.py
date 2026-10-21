"""End-to-end tests of the command line interface and the demo scenario."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tapak.cli import main

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
RECIPIENTS = ROOT / "samples" / "recipients.csv"


def _run(tmp: Path, *argv: str) -> int:
    return main(["--data", str(tmp / "data"), "--keys", str(tmp / "keys"), *argv])


def test_cli_full_flow(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    assert _run(tmp_path, "keys", "init") == 0
    assert (tmp_path / "keys" / "code_secret.key").exists()
    assert (tmp_path / "keys" / "registry_signing.pub").exists()

    variants = tmp_path / "varian.json"
    assert _run(tmp_path, "semantic", "suggest", str(SAMPLE), "-o", str(variants)) == 0
    sel = json.loads(variants.read_text(encoding="utf-8"))
    assert sel["units"] and all(s["status"][1:] for s in sel["sets"])
    # Issuance is refused while variants await review.
    assert _run(tmp_path, "issue", str(SAMPLE), str(RECIPIENTS), "--semantic", str(variants)) == 2
    assert "diblokir" in capsys.readouterr().err
    assert _run(tmp_path, "semantic", "approve", str(variants), "--all") == 0

    assert _run(tmp_path, "issue", str(SAMPLE), str(RECIPIENTS), "--semantic", str(variants),
                "--canary-domain", "kanari.tapak.test", "--issuer", "Uji CLI") == 0
    out = capsys.readouterr().out
    assert "20 salinan ditulis" in out and "ditandatangani" in out
    # The same document cannot be issued twice into the same data folder.
    assert _run(tmp_path, "issue", str(SAMPLE), str(RECIPIENTS)) == 2
    capsys.readouterr()

    assert _run(tmp_path, "docs") == 0
    assert "nota_dinas.pdf" in capsys.readouterr().out

    copy = next((tmp_path / "data" / "dokumen").glob("*/salinan/*salinan009_*.pdf"))
    report = tmp_path / "ba.pdf"
    assert _run(tmp_path, "trace", str(copy), "--report", str(report)) == 0
    out = capsys.readouterr().out
    assert "Salinan #9" in out and "TERIDENTIFIKASI" in out and "rantai terverifikasi" in out
    assert report.read_bytes().startswith(b"%PDF")

    assert _run(tmp_path, "verify") == 0
    assert "UTUH" in capsys.readouterr().out
    assert _run(tmp_path, "registry", "export-merkle") == 0
    assert "merkle-" in capsys.readouterr().out


def test_cli_trace_requires_document(tmp_path, capsys):
    assert _run(tmp_path, "keys", "init") == 0
    f = tmp_path / "x.txt"
    f.write_text("teks", encoding="utf-8")
    assert _run(tmp_path, "trace", str(f)) == 2
    assert "pilih dokumen" in capsys.readouterr().err


@pytest.mark.slow
def test_demo_scenario_passes(tmp_path):
    from tapak.demo import run_demo

    assert run_demo(tmp_path / "demo") == 0
    assert (tmp_path / "demo" / "berita_acara_salinan13.pdf").exists()
