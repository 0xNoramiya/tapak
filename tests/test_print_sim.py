"""Print simulator (photos.print_page): highlight dropout, tints that survive, determinism,
exact ground truth through print and photo, and the decoder on a printed page."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from tapak.marker.render import render_pages
from tapak.photos import (
    INKJET,
    KIND_PRINT,
    PhotoParams,
    PrintParams,
    make_photo_set,
    print_layers,
    print_page,
    printed_photo_jpeg,
)
from test_photos import _subpixel_offset

FAST = PrintParams(device_dpi=300, out_dpi=150)  # coarse device grid keeps the tests fast
SMALL = PhotoParams(sensor_long_side=1400, long_side=1000)


def _copy(issued, seq: int) -> bytes:
    out, manifest = issued
    return (out / manifest.copies[seq - 1].file).read_bytes()


@pytest.fixture(scope="module")
def layers(issued):
    return print_layers(_copy(issued, 1), 0, FAST.device_dpi)


def test_layers_separate_text_from_background(layers):
    text, background = layers
    assert text.shape == background.shape and text.dtype == np.float32
    assert text.max() == pytest.approx(1.0) and text.min() == 0.0
    # The issued background is the faint +/-2 pattern around 253 (rules and logos aside).
    blank = background[text < 0.01]
    assert np.percentile(blank, 5) >= 250 and blank.max() == 255


def test_printer_drops_the_faint_background_pattern(layers):
    """Gray levels at or above the cutoff print as plain paper: the issued +/-2 pattern leaves
    no trace on the sheet (limitation 3)."""
    text, background = layers
    with_pattern, _ = print_page(text, background, np.random.default_rng(4), FAST)
    paper = np.where(background >= FAST.white_cutoff, 255, background).astype(np.uint8)
    without, _ = print_page(text, paper, np.random.default_rng(4), FAST)
    assert np.abs(with_pattern - without).max() < 1e-3


def test_tints_below_the_cutoff_survive_with_dot_gain():
    text = np.zeros((400, 400), np.float32)
    background = np.full((400, 400), 255, np.uint8)
    background[:, :200] = 238
    background[:, 200:] = 246
    sheet, meta = print_page(text, background, np.random.default_rng(1), replace(FAST, out_dpi=300))
    dark, light = float(sheet[50:350, 40:160].mean()), float(sheet[50:350, 240:360].mean())
    assert light - dark > 4.0                 # the step of 8 levels is still on paper
    assert dark < 238 - 2.0                   # dot gain: darker than the nominal level
    assert set(meta["params"]) >= {"spot_sigma_um", "skew_deg", "paper_fine", "drum_jitter_um"}


def test_print_is_deterministic_and_seed_dependent(layers):
    text, background = layers
    a, ma = print_page(text, background, np.random.default_rng(9), FAST)
    b, mb = print_page(text, background, np.random.default_rng(9), FAST)
    c, _ = print_page(text, background, np.random.default_rng(10), FAST)
    assert np.array_equal(a, b) and ma == mb
    assert not np.array_equal(a, c)


@pytest.mark.parametrize("params", [replace(FAST, out_dpi=150), replace(INKJET, device_dpi=300, out_dpi=150)])
def test_printed_photo_homography_matches_content(issued, params):
    """The homography maps the unprinted page (at out_dpi) onto the photo of the printed
    sheet, including the print's skew, offset and scale (banding jitter of a few micrometres
    aside)."""
    pdf = _copy(issued, 2)
    data, meta = printed_photo_jpeg(pdf, 0, np.random.default_rng(3), replace(params, skew_deg=0.5, offset_mm=2.0),
                                    replace(SMALL, angle_deg=20.0))
    assert meta["kind"] == KIND_PRINT
    from tapak.photos import decode_jpeg

    img = decode_jpeg(data)
    page = render_pages(pdf, params.out_dpi, [0])[0]
    assert np.all(np.abs(_subpixel_offset(img, page, meta["homography"])) < 0.2)
    # Without the print transform the content is visibly off: the print step is accounted for.
    photo_only = np.asarray(meta["homography"]) @ np.linalg.inv(np.asarray(meta["print"]["to_sheet"]))
    assert np.abs(_subpixel_offset(img, page, photo_only)).max() > 0.3


def test_print_settings_are_validated():
    with pytest.raises(ValueError):
        PrintParams(screen="fm")
    with pytest.raises(ValueError):
        PrintParams(fit_scale=1.2)


@pytest.mark.slow
def test_printed_copy_loses_background_but_keeps_shifts(issued, ctx):
    """A photo of a printed copy: the background channel reports nothing, the shift channel
    still reads most of the page."""
    from tapak.decoder.image import collect_from_image

    data, _ = printed_photo_jpeg(_copy(issued, 5), 0, np.random.default_rng(12), PrintParams(),
                                 PhotoParams(angle_deg=10.0))
    obs = {sb.channel: sb for sb in collect_from_image(data, ctx)}
    assert obs["background"].meta["pattern_found"] is False and len(obs["background"]) == 0
    assert len(obs["shift"]) >= 60


def test_make_photo_set_with_print(issued, tmp_path):
    out_dir, _ = issued
    items = make_photo_set(out_dir, tmp_path / "foto", seqs=[3], per_copy=1, angles=(10,), screenshots=False,
                           long_side=900, photo_params=SMALL, print_params=FAST)
    assert [it["file"] for it in items] == ["cetak_s003_p1_a10_0.jpg"]
    truth = json.loads((tmp_path / "foto" / "truth.json").read_text())
    item = truth["items"][0]
    assert item["kind"] == KIND_PRINT and item["render_dpi"] == FAST.out_dpi
    assert "print" in item and "to_sheet" in item["print"]
    assert "Penerima" not in json.dumps(truth)
