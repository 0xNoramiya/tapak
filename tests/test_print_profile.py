"""Print background profile (opt-in, ``--latar cetak``): it survives a simulated print and
photo, keeps the screen path working, and leaves the default issuance unchanged."""

from __future__ import annotations

import json
from dataclasses import asdict

import numpy as np
import pytest

from tapak.decoder.image import collect_from_gray, collect_from_image
from tapak.decoder.rectify import load_gray
from tapak.decoder.trace import load_context, run_trace
from tapak.marker.background import (
    BACKGROUND_PROFILES,
    PRINT_BACKGROUND,
    PRINT_BACKGROUND_WARNING,
    SCREEN_BACKGROUND,
    BackgroundSettings,
    background_profile,
    profile_name,
)
from tapak.marker.issue import IssueSettings, issue
from tapak.marker.render import render_pages
from tapak.photos import PhotoParams, PrintParams, photo_jpeg, print_layers, print_page, printed_photo_jpeg

# The conditions the docs report: the laser preset (600 dpi device grid; a 300 dpi grid
# screens the faint tints far more coarsely than an office laser) and a WhatsApp standard photo.
LASER = PrintParams()
WHATSAPP = PhotoParams(sensor_long_side=2400, long_side=1600, angle_deg=10.0)


@pytest.fixture(scope="module")
def issued_print(tmp_path_factory, sample_pdf, secret, recipients):
    from conftest import SAMPLE

    out = tmp_path_factory.mktemp("issued_print")
    manifest = issue(SAMPLE, recipients, out, secret, IssueSettings(background=PRINT_BACKGROUND), issuer="pytest")
    return out, manifest


@pytest.fixture(scope="module")
def ctx_print(issued_print, sample_pdf, secret):
    return load_context(sample_pdf, issued_print[1], secret)


def _copy(issued, seq: int) -> bytes:
    out, manifest = issued
    return (out / manifest.copies[seq - 1].file).read_bytes()


def _ber(sb, codeword) -> float:
    return float(np.mean((sb.llr > 0) != (codeword[sb.positions] == 1)))


def test_profiles():
    assert SCREEN_BACKGROUND == BackgroundSettings() == IssueSettings().background
    assert (PRINT_BACKGROUND.base, PRINT_BACKGROUND.amplitude) == (242.0, 5.0)
    assert PRINT_BACKGROUND.base + PRINT_BACKGROUND.amplitude < 250  # every cell below the highlight cutoff
    assert background_profile("layar") is SCREEN_BACKGROUND and background_profile("cetak") is PRINT_BACKGROUND
    assert set(BACKGROUND_PROFILES) == {"layar", "cetak"}
    assert profile_name(PRINT_BACKGROUND) == "cetak" and profile_name(BackgroundSettings(base=250.0)) is None
    with pytest.raises(ValueError, match="profil latar"):
        background_profile("kertas")
    assert "abu-abu muda" in PRINT_BACKGROUND_WARNING and "tekstur" in PRINT_BACKGROUND_WARNING


def _without_file_id(data: bytes) -> bytes:
    """The PDF without its trailer /ID, whose second half MuPDF draws at random on every save
    (written as a hex or a literal string, so it is cut out by position: the last entry of the
    trailer dictionary)."""
    start = data.rindex(b"/ID[")
    end = data.rindex(b"]>>", start, data.rindex(b"startxref"))
    return data[:start] + data[end:]


# Default issuance as written by the code before the print profile existed (commit 6be81e2),
# recorded with PyMuPDF 1.28.2 from the sample tapak.samplegen writes: SHA-256 of copies 1 and
# 2 (copy ids 0 and 1, trailer /ID cut out).
GOLDEN_PYMUPDF = "1.28.2"
GOLDEN_SAMPLE_SHA256 = "fac9bba95c8bf9290395bc6078a3d640ab5587c347a2db8dcbc6791fd4e3a65d"
GOLDEN_DEFAULT_COPIES = ["65463815919bd413100c27033736219959586e0f2c9e178ee9d1017ceec483de",
                         "108d16546deb8a19a6f496bbd984883bc1755ecdf2e24253caa5edf306882f8b"]


def test_default_background_is_pinned():
    """The default pattern itself, written out: a change to it must fail here, not only change
    the default and the "layar" profile alike."""
    expected = {"cell_mm": 2.0, "cells_per_bit": 8, "amplitude": 2.0, "base": 253.0, "px_per_cell": 4}
    assert asdict(IssueSettings().background) == expected
    assert asdict(SCREEN_BACKGROUND) == expected and asdict(background_profile("layar")) == expected


def _issue_fixed_ids(monkeypatch, recipients, folder, settings) -> list[bytes]:
    """Issue two copies with copy ids 0 and 1; the copies' bytes without the trailer /ID."""
    import itertools

    import tapak.marker.issue as issue_mod
    from conftest import SAMPLE, SECRET

    counter = itertools.count()
    monkeypatch.setattr(issue_mod.secrets, "token_hex", lambda n: f"{next(counter):0{2 * n}x}")
    m = issue(SAMPLE, recipients[:2], folder, SECRET, settings, issuer="pytest")
    assert [c.copy_id for c in m.copies] == ["0000000000000000", "0000000000000001"]
    return [_without_file_id((folder / c.file).read_bytes()) for c in m.copies]


def test_default_issuance_is_bit_for_bit_unchanged(tmp_path, monkeypatch, recipients, sample_pdf):
    """A geser-v1 issuance with the screen profile, the setting of every document issued before
    the print profile and geser-v2, writes the same bytes as the code before both (golden
    hashes; skipped when PyMuPDF or the generated sample differ from the recording)."""
    from tapak.marker.pdf_shift import ShiftSettings

    import hashlib

    import pymupdf

    if pymupdf.VersionBind != GOLDEN_PYMUPDF or hashlib.sha256(sample_pdf).hexdigest() != GOLDEN_SAMPLE_SHA256:
        pytest.skip(f"golden hashes recorded with PyMuPDF {GOLDEN_PYMUPDF} and another sample PDF")
    files = _issue_fixed_ids(monkeypatch, recipients, tmp_path / "bawaan", IssueSettings(workers=1, shift=ShiftSettings()))
    assert [hashlib.sha256(f).hexdigest() for f in files] == GOLDEN_DEFAULT_COPIES


def test_layar_profile_is_the_default_and_cetak_differs(tmp_path, monkeypatch, recipients):
    """The explicit "layar" profile writes the same bytes as no choice; the print profile does not."""
    files = {name: _issue_fixed_ids(monkeypatch, recipients, tmp_path / name,
                                    IssueSettings(workers=1, background=background_profile(name)))
             for name in ("layar", "cetak")}
    files["bawaan"] = _issue_fixed_ids(monkeypatch, recipients, tmp_path / "bawaan", IssueSettings(workers=1))
    assert files["bawaan"] == files["layar"]
    assert all(a != b for a, b in zip(files["bawaan"], files["cetak"]))


def test_cli_and_service_offer_the_profile(tmp_path, capsys, monkeypatch):
    from tapak.cli import build_parser, main
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.chdir(tmp_path)  # any working directory: no path relative to the repository root

    args = build_parser().parse_args(["issue", "a.pdf", "b.csv"])
    assert args.latar == "layar"
    rc = main(["--data", str(tmp_path / "data"), "--keys", str(tmp_path / "keys"), "issue",
               str(SAMPLE), str(RECIPIENTS), "--no-registry", "--canary-domain", "",
               "--workers", "1", "--latar", "cetak"])
    out = capsys.readouterr().out
    assert rc == 0 and "profil cetak (242 +/- 5" in out and PRINT_BACKGROUND_WARNING in out
    manifest = json.loads(next((tmp_path / "data" / "dokumen").glob("*/manifest.json")).read_text())
    assert manifest["background"] == asdict(PRINT_BACKGROUND)


def test_service_warns_only_for_the_print_profile(tmp_path, monkeypatch):
    from tapak.config import load_settings
    from tapak.marker.issue import read_recipients
    from tapak.service import ensure_keys, issue_document
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    s = load_settings()
    keys = ensure_keys(s, create_signing_key=False)
    rec = read_recipients(RECIPIENTS)[:2]
    out = issue_document(s, SAMPLE, rec, IssueSettings(workers=1), "uji", keys, record=False, latar="cetak")
    assert out.warnings == [PRINT_BACKGROUND_WARNING]
    assert out.manifest.background_settings == PRINT_BACKGROUND
    with pytest.raises(ValueError, match="profil latar"):
        issue_document(s, SAMPLE, rec, IssueSettings(workers=1), "uji", keys, record=False, latar="kertas")
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data2"))  # the same document again, elsewhere
    plain = issue_document(load_settings(), SAMPLE, rec, IssueSettings(workers=1), "uji", keys, record=False,
                           latar="layar")
    assert plain.warnings == [] and plain.manifest.background_settings == SCREEN_BACKGROUND


def test_print_profile_survives_print_and_names_the_copy(issued_print, ctx_print):
    """Printed and photographed: the pattern is found, its bits are mostly right and one page
    names the copy, where the default profile leaves nothing on paper."""
    seq = 4
    data, _ = printed_photo_jpeg(_copy(issued_print, seq), 0, np.random.default_rng(21), LASER, WHATSAPP)
    obs = collect_from_image(data, ctx_print)
    bg = next(sb for sb in obs if sb.channel == "background")
    assert bg.meta["pattern_found"] is True
    assert _ber(bg, ctx_print.codewords[seq - 1]) < 0.05
    result = run_trace(obs, ctx_print)
    assert [c.copy.seq for c in result.accused] == [seq]


def test_print_profile_keeps_the_screen_path(issued_print, ctx_print):
    seq = 6
    page = render_pages(_copy(issued_print, seq), 200, [0])[0]
    data, _ = photo_jpeg(page, np.random.default_rng(5), PhotoParams(angle_deg=15.0))
    obs = collect_from_gray(load_gray(data), ctx_print)
    bg = next(sb for sb in obs if sb.channel == "background")
    assert bg.meta["pattern_found"] is True and _ber(bg, ctx_print.codewords[seq - 1]) < 0.05
    assert [c.copy.seq for c in run_trace(obs, ctx_print).accused] == [seq]


def _cut_rows(ctx, page: int, dpi: int) -> list[int]:
    boxes = sorted((r.bbox[1], r.bbox[3]) for r in ctx.master.layout.pages[page].rows)
    top, bottom = boxes[0][0], boxes[-1][1]
    gaps = [0.5 * (boxes[i][1] + boxes[i + 1][0]) for i in range(len(boxes) - 1) if boxes[i][1] < boxes[i + 1][0]]
    cuts = [min(gaps, key=lambda g: abs(g - (top + f * (bottom - top)))) for f in (1 / 3, 2 / 3)]
    return [int(round(c * dpi / 72.0)) for c in cuts]


@pytest.mark.slow
def test_print_profile_cut_and_paste_coalition_on_paper(issued_print, ctx_print):
    """c = 3: one sheet cut together from three copies (top, middle, bottom), printed and
    photographed. At least one member is named and no innocent."""
    coalition = (3, 11, 17)
    prm = LASER
    layers = [print_layers(_copy(issued_print, s), 0, prm.device_dpi) for s in coalition]
    c1, c2 = _cut_rows(ctx_print, 0, prm.device_dpi)
    text = np.vstack([layers[0][0][:c1], layers[1][0][c1:c2], layers[2][0][c2:]])
    background = np.vstack([layers[0][1][:c1], layers[1][1][c1:c2], layers[2][1][c2:]])
    rng = np.random.default_rng(31337)
    sheet, _ = print_page(text, background, rng, prm)
    data, _ = photo_jpeg(sheet, rng, WHATSAPP)
    result = run_trace(collect_from_gray(load_gray(data), ctx_print), ctx_print)
    accused = {c.copy.seq for c in result.accused}
    assert accused and accused <= set(coalition)
