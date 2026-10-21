"""Regression tests for the findings of the final adversarial review."""

from __future__ import annotations

import json
import math

import numpy as np
import pymupdf
import pytest

from tapak.decoder.accuse import format_upper_bound
from tapak.decoder.ch_background import fit_mu
from tapak.decoder.ch_shift import map_pages
from tapak.decoder.trace import TraceError, collect_file, decode_text_evidence, trace_files
from tapak.marker.layout import extract_layout
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, photo_jpeg
from tests_support import RECIPIENTS, SAMPLE


def _copy(issued, seq):
    out, manifest = issued
    return (out / manifest.copies[seq - 1].file).read_bytes()


def test_format_upper_bound_rounds_up_and_survives_underflow():
    assert format_upper_bound(math.log10(2.341e-12)) == "2.35e-12"
    assert format_upper_bound(-339.3) == "5.02e-340"
    assert format_upper_bound(-math.inf) == "0" and format_upper_bound(0.5) == "1"


def test_fit_mu_with_known_sigma():
    rng = np.random.default_rng(0)
    t = rng.choice([-1.0, 1.0], 4000) * 0.3 + rng.normal(0, 0.1, 4000)
    assert fit_mu(t, 0.1) == pytest.approx(0.3, rel=0.05)
    assert fit_mu(rng.normal(0, 0.1, 4000), 0.1) < 0.05


def test_background_reports_nothing_without_a_pattern(ctx, sample_pdf):
    """Printed paper or an unmarked page: the decoy calibration finds no pattern."""
    printed = render_pages(sample_pdf, 200, [0])[0]  # the unmarked master: no pattern at all
    data, _ = photo_jpeg(printed, np.random.default_rng(5), PhotoParams(angle_deg=10.0))
    obs, notes = collect_file("foto.jpg", data, ctx)
    bg = next(o for o in obs if o.channel == "background")
    assert len(bg) == 0 and bg.meta["pattern_found"] is False
    assert any("pola latar tidak terdeteksi" in n for n in notes)


def test_trace_files_fuses_several_pages(issued, ctx):
    """Photos of both pages of a printed copy, fused: more positions than either page alone."""
    pdf = _copy(issued, 6)
    items = []
    for page in (0, 1):
        img = render_pages(pdf, 200, [page])[0].copy()
        img[img >= 240] = 255  # printed: the background pattern is gone
        data, _ = photo_jpeg(img, np.random.default_rng(page), PhotoParams(angle_deg=5.0, long_side=2600))
        items.append((f"hal{page + 1}.jpg", data))
    one, _ = trace_files(items[:1], ctx)
    both, obs = trace_files(items, ctx)
    assert both.threshold.n_observed > one.threshold.n_observed
    assert both.candidates[0].copy.seq == 6
    assert all(c.copy.seq == 6 for c in both.accused)
    assert any("digabung" in n for n in both.notes)


def test_decode_text_evidence_encodings():
    text = "Demikian nota dinas \u200cini"
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-32"):
        assert decode_text_evidence(text.encode(enc)) == text


def test_utf16_text_evidence_traces(issued, ctx):
    from tapak.decoder.ch_zerowidth import extract_pdf_text

    data = extract_pdf_text(_copy(issued, 4)).encode("utf-16")
    obs, _ = collect_file("bocor.txt", data, ctx)
    from tapak.decoder.trace import run_trace

    assert [c.copy.seq for c in run_trace(obs, ctx).accused] == [4]


def test_map_pages_with_cover_and_missing_page(issued, ctx):
    src = pymupdf.open(stream=_copy(issued, 3))
    out = pymupdf.open()
    out.new_page().insert_text((72, 100), "Sampul diteruskan", fontsize=14)
    out.insert_pdf(src, from_page=1, to_page=1)
    assert map_pages(ctx.master.layout, extract_layout(out.tobytes())) == {1: 1}
    obs, _ = collect_file("bocor.pdf", out.tobytes(), ctx)
    from tapak.decoder.trace import run_trace

    assert [c.copy.seq for c in run_trace(obs, ctx).accused] == [3]


def test_corrupt_pdf_evidence_is_an_indonesian_error(ctx):
    with pytest.raises(TraceError, match="bukan berkas PDF"):
        collect_file("x.pdf", b"not a pdf", ctx)
    with pytest.raises(TraceError, match="rusak"):
        collect_file("x.pdf", b"%PDF-1.7\n garbage", ctx)


def test_issue_refuses_non_pdf_and_scanned_pdf(tmp_path, secret, recipients):
    from tapak.marker.issue import issue

    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"hello")
    with pytest.raises(ValueError, match="bukan berkas PDF"):
        issue(bad, recipients[:2], tmp_path / "o1", secret)
    scan = pymupdf.open()
    page = scan.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.5, 0.5, 0.5))
    p = tmp_path / "scan.pdf"
    scan.save(p)
    with pytest.raises(ValueError, match="lapisan teks"):
        issue(p, recipients[:2], tmp_path / "o2", secret)


def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    from tapak.config import load_settings

    return load_settings()


def test_keys_held_elsewhere_are_never_replaced(tmp_path, monkeypatch):
    from tapak.registry.signing import Signer, export_public_key
    from tapak.service import ensure_keys

    s = _settings(tmp_path, monkeypatch)
    s.key_dir.mkdir(parents=True)
    elsewhere = Signer.generate()
    export_public_key(elsewhere, s.public_key_path)  # only the public key is on this machine
    keys = ensure_keys(s)  # even with create_signing_key=True
    assert keys.signer is None and keys.public_key_hex == elsewhere.public_key_hex
    assert not s.signing_key_path.exists()


def test_registry_failure_leaves_no_workspace(tmp_path, monkeypatch):
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.registry import chain
    from tapak.service import ensure_keys, issue_document, list_workspaces

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)

    def boom(*a, **k):
        raise chain.RegistryError("registri tidak dapat ditulis (uji)")

    monkeypatch.setattr(chain, "registry_from_manifest", boom)
    with pytest.raises(chain.RegistryError):
        issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:3], IssueSettings(workers=1), "uji", keys)
    assert list_workspaces(s) == [] and not any(s.workspaces.glob("*"))


def test_manifest_disagreeing_with_registry_names_nobody(tmp_path, monkeypatch):
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.service import ensure_keys, issue_document, trace_evidence

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:4], IssueSettings(workers=1), "uji", keys)
    m = json.loads((out.folder / "manifest.json").read_text(encoding="utf-8"))
    m["copies"][0]["recipient"], m["copies"][1]["recipient"] = m["copies"][1]["recipient"], m["copies"][0]["recipient"]
    (out.folder / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    evidence = (out.folder / "salinan" / out.manifest.copies[0].file).read_bytes()
    with pytest.raises(TraceError, match="tidak cocok dengan registri"):
        trace_evidence(s, out.manifest.doc_hash, "bocor.pdf", evidence)


def test_demo_refuses_foreign_folder(tmp_path):
    from tapak.demo import run_demo

    (tmp_path / "penting.txt").write_text("jangan dihapus", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_demo(tmp_path)
    assert (tmp_path / "penting.txt").exists()
