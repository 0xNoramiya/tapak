"""Pages that do not lie in a plane (rectify.estimate_bend, Bend): a curled or cockled sheet is
registered through a smooth displacement field after the plane fit, a flat page keeps its plane
fit untouched, and another document does not come through."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from tapak.decoder import rectify
from tapak.decoder.rectify import Bend, estimate_bend, parabolic_peak, register, render_page, warp_to_page

A4 = (595.28, 841.89)
DPI = 150.0
TABLE = 40  # dark table around the sheet (px)


def _waves(shape: tuple[int, int], dpi: float, amplitude_mm: float = 1.2) -> np.ndarray:
    """A smooth displacement field (height, width, 2) in pixels: slow waves along both axes, as a
    curled sheet shows them."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    a = amplitude_mm * dpi / 25.4
    dx = a * np.sin(2 * np.pi * ys / (0.9 * h)) * np.cos(np.pi * xs / (1.4 * w))
    dy = 0.8 * a * np.sin(2 * np.pi * xs / (1.2 * w) + 0.7) * np.cos(np.pi * ys / (1.1 * h))
    return np.dstack([dx, dy]).astype(np.float32)


def _bent_photo(pdf: bytes, page: int = 0, dpi: float = DPI,
                amplitude_mm: float = 1.2) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(photo, displacement in page px, plane map page px -> photo px): the page with its content
    displaced by the waves, on a dark table."""
    flat = render_page(pdf, page, dpi)
    d = _waves(flat.shape, dpi, amplitude_mm)
    ys, xs = np.mgrid[0:flat.shape[0], 0:flat.shape[1]].astype(np.float32)
    # content of page point p shows at p + d(p); to first order the photo at q shows page q - d(q)
    bent = cv2.remap(flat, xs - d[..., 0], ys - d[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    photo = np.full((flat.shape[0] + 2 * TABLE, flat.shape[1] + 2 * TABLE), 45.0, dtype=np.float32)
    photo[TABLE:-TABLE, TABLE:-TABLE] = bent
    return photo, d, np.array([[1.0, 0.0, TABLE], [0.0, 1.0, TABLE], [0.0, 0.0, 1.0]])


def _text(pdf: bytes, shape: tuple[int, int], dpi: float = DPI) -> np.ndarray:
    """Pixels near text: where a displacement can be measured at all."""
    ink = rectify.master_ink(pdf, 0, dpi)[:shape[0], :shape[1]]
    return cv2.dilate((ink > 0.2).astype(np.uint8), np.ones((31, 31), np.uint8)) > 0


def test_parabolic_peak_finds_the_top_between_samples():
    curve = lambda x: 3.0 - 2.0 * (x - 0.3) ** 2  # noqa: E731 - its top is 0.3 right of the middle sample
    assert parabolic_peak(curve(-1), curve(0), curve(1)) == pytest.approx(0.3)
    assert parabolic_peak(1.0, 1.0, 1.0) == 0.0 and parabolic_peak(2.0, 1.0, 2.0) == 0.0  # flat, or no peak


def test_bend_validates_and_scales_to_a_page_frame():
    lattice = np.zeros((6, 4, 2), dtype=np.float32)
    lattice[..., 0] = 2.0  # points
    bend = Bend(lattice, A4)
    px = bend.pixels((1240, 1754))
    assert px.shape == (1754, 1240, 2)
    assert np.allclose(px[..., 0], 2.0 * 1240 / A4[0], atol=1e-3) and np.allclose(px[..., 1], 0.0)
    assert bend.largest_mm() == pytest.approx(2.0 * 25.4 / 72.0)
    with pytest.raises(ValueError):
        Bend(np.zeros((6, 4)), A4)
    with pytest.raises(ValueError):
        Bend(lattice, (0.0, 841.89))


def test_warp_to_page_with_a_bend_reads_the_page_where_it_is_shown(sample_pdf):
    photo, d, plane = _bent_photo(sample_pdf)
    flat = render_page(sample_pdf, 0, DPI)
    size = (flat.shape[1], flat.shape[0])
    lattice = cv2.resize(d, (60, 85), interpolation=cv2.INTER_AREA) * (72.0 / DPI)
    straight, valid = warp_to_page(photo, plane, size, Bend(lattice, A4))
    planar, _ = warp_to_page(photo, plane, size)
    near = _text(sample_pdf, flat.shape)
    assert valid.all()
    assert float(np.abs(straight - flat)[near].mean()) < 0.35 * float(np.abs(planar - flat)[near].mean())


def test_estimate_bend_recovers_a_smooth_displacement(sample_pdf):
    photo, d, plane = _bent_photo(sample_pdf)
    log: dict = {}
    found = estimate_bend(rectify._prep(photo), rectify.master_ink(sample_pdf, 0, DPI), plane, DPI, A4, log)
    assert found is not None
    fine, smooth, cc = found
    assert cc > 0.9
    assert len(log["levels"]) == len(rectify.BEND_LEVELS) and all(n["measured"] > 20 for n in log["levels"])
    near = _text(sample_pdf, d.shape[:2])
    mm = 25.4 / DPI
    size = (d.shape[1], d.shape[0])
    assert float(np.abs(fine.pixels(size) - d)[near].max()) * mm < 0.25
    assert float(np.sqrt(((fine.pixels(size) - d)[near] ** 2).mean())) * mm < 0.06
    # the field the decoders read through is the same shape, a little flattened by its averaging
    assert float(np.sqrt(((smooth.pixels(size) - d)[near] ** 2).mean())) * mm < 0.15
    assert 0.5 < smooth.largest_mm() <= fine.largest_mm() + 0.05


def test_estimate_bend_finds_nothing_on_a_blank_page():
    blank = np.zeros((600, 420), dtype=np.float32)
    assert estimate_bend(blank, blank, np.eye(3), 72.0, (420.0, 600.0)) is None


def test_register_takes_a_bent_page_that_the_plane_fit_alone_rejects(sample_pdf, monkeypatch):
    photo, _, _ = _bent_photo(sample_pdf, amplitude_mm=2.5)  # real sheets: 2 to 5 mm off the plane
    diag: dict = {}
    reg = register(photo, sample_pdf, [A4, A4], diag=diag, rescue=False)
    assert reg is not None and reg.page == 0
    assert reg.method.endswith("+lengkung") and reg.bend is not None
    assert diag["bend"]["plane"] < 0.75 <= reg.correlation == diag["bend"]["cc"]
    flat = render_page(sample_pdf, 0, reg.dpi)
    near = _text(sample_pdf, flat.shape, reg.dpi)
    planar, _ = warp_to_page(photo, reg.h_page_to_img, (flat.shape[1], flat.shape[0]))
    assert float(np.abs(reg.rectified - flat)[near].mean()) < 0.6 * float(np.abs(planar - flat)[near].mean())
    monkeypatch.setattr(rectify, "BEND_BELOW", 0.0)  # without the bend stage: not this page
    assert register(photo, sample_pdf, [A4, A4], rescue=False) is None


def test_register_keeps_the_plane_fit_of_a_flat_page(sample_pdf):
    flat = render_page(sample_pdf, 0, DPI)
    photo = np.full((flat.shape[0] + 2 * TABLE, flat.shape[1] + 2 * TABLE), 45.0, dtype=np.float32)
    photo[TABLE:-TABLE, TABLE:-TABLE] = flat
    diag: dict = {}
    reg = register(photo, sample_pdf, [A4, A4], diag=diag, rescue=False)
    assert reg is not None and reg.bend is None and "lengkung" not in reg.method
    assert reg.correlation >= rectify.BEND_BELOW and "bend" not in diag


def test_bend_does_not_register_another_page(sample_pdf):
    """Page 2 bent like page 1, offered as page 1 only: the bend follows no other text."""
    photo, _, plane = _bent_photo(sample_pdf, page=1)
    found = estimate_bend(rectify._prep(photo), rectify.master_ink(sample_pdf, 0, DPI), plane, DPI, A4)
    assert found is None or found[2] < 0.6


def test_a_sheet_of_paper_from_a_screen_profile_document_is_explained(sample_pdf, ctx):
    """A page that is not flat and shows no background pattern, traced against a document issued
    with the default profile: the notes say why a printout of such a copy is not traced."""
    from tapak import i18n
    from tapak.decoder.trace import collect_file

    def png(image: np.ndarray) -> bytes:
        return cv2.imencode(".png", np.clip(image, 0, 255).astype(np.uint8))[1].tobytes()

    photo, _, _ = _bent_photo(sample_pdf, amplitude_mm=2.5)
    _, notes = collect_file("foto.png", png(photo), ctx)
    note = next(n for n in notes if "tidak datar" in n)
    assert "+lengkung" in " ".join(notes) and "praktis tidak terlacak" in note
    token = i18n.use("en")
    try:
        assert "practically untraceable" in i18n.translate_text(note)
    finally:
        i18n.reset(token)
    flat = render_page(sample_pdf, 0, DPI)
    table = np.full((flat.shape[0] + 2 * TABLE, flat.shape[1] + 2 * TABLE), 45.0, dtype=np.float32)
    table[TABLE:-TABLE, TABLE:-TABLE] = flat
    _, notes = collect_file("foto.png", png(table), ctx)
    assert not any("tidak datar" in n for n in notes)
