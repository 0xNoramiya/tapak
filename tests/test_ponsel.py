"""Phone ISP and monitor photos (tapak.ponsel, opt-in in tapak.photos).

The default photo stream must not change: the golden hashes below were taken from the
simulator before tapak.ponsel existed (commit 0de1e97). They depend on the versions of
OpenCV, numpy and PyMuPDF in the environment (JPEG encoder, resampling, rendering); after an
upgrade, regenerate them from that commit, not from the current code.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace

import cv2
import numpy as np
import pytest

from tapak.marker.render import render_pages
from tapak.photos import (
    KIND_PHONE,
    KIND_SCREEN_PHOTO,
    PhotoParams,
    PrintParams,
    ScreenshotParams,
    decode_jpeg,
    main,
    make_photo_set,
    photo_jpeg,
    printed_photo_jpeg,
    screen_photo,
    screen_photo_jpeg,
    screenshot_jpeg,
    view_angle_deg,
)
from tapak.ponsel import (
    BAYER_RGGB_TO_BGR,
    ISP_PROFILES,
    ISP_STEPS,
    MONITORS,
    IspParams,
    Monitor,
    ScreenParams,
    angular_falloff,
    bayer_mosaic,
    demosaic_luma,
    draw_isp,
    guided_filter,
    highlight_shoulder,
    isp_process,
    isp_profile,
    local_tone_map,
    noise_reduction,
    render_display,
    sharpen_halo,
    subpixel_profiles,
    unsharp_amount,
    view_angles,
)

GOLDEN = {
    "photo_1": "8903c4d8cc235b952baf5d316f26ffae99965653bab437c6f75ff6ce22d4dde7",
    "photo_2": "0d522fa2909c6d2904a2d02faee6dc177c7db93503e75132da6f9c0397adef6d",
    "screenshot_3": "97a0f374a964c9d97e6fbe209cd9ed1af5579b885d143e420d90c1ead0be7236",
    "screenshot_4": "f2baedd45441c29416ece7e39658a86e64e266ff9a504a30c88e911b690ac0ab",
    "cetak_5": "f8ebaced0f09b723870f3c0ecdd5901d221ddd75912be9af06a7f8323c5dedd8",
}
SMALL = PhotoParams(sensor_long_side=1400, long_side=1000)
# A small, fast monitor photo: 1600 px camera frame, two samples per pixel.
FAST_SCREEN = ScreenParams(monitor="fhd24", distance_cm=30.0, sensor_long_side=1600, supersample=2)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def page(sample_pdf) -> np.ndarray:
    return render_pages(sample_pdf, 100, [0])[0]


def test_default_photo_stream_is_unchanged(sample_pdf, page):
    """Golden hashes from before the ISP and monitor existed: plain photos, screenshots and
    printed photos produce exactly the same JPEG bytes."""
    got = {}
    for seed, angle in ((1, 0.0), (2, 25.0)):
        data, meta = photo_jpeg(page, np.random.default_rng(seed), replace(SMALL, angle_deg=angle))
        got[f"photo_{seed}"] = _sha(data)
        assert meta["kind"] == "photo" and "isp_settings" not in meta and "isp" not in meta["params"]
    for seed in (3, 4):
        data, _ = screenshot_jpeg(page, np.random.default_rng(seed), ScreenshotParams(render_dpi=100.0))
        got[f"screenshot_{seed}"] = _sha(data)
    data, _ = printed_photo_jpeg(sample_pdf, 0, np.random.default_rng(5), PrintParams(device_dpi=300, out_dpi=150),
                                 SMALL)
    got["cetak_5"] = _sha(data)
    assert got == GOLDEN


def test_isp_profiles_and_steps():
    assert isp_profile("netral") is None and ISP_PROFILES["netral"] is None
    full = isp_profile("ponsel")
    assert isinstance(full, IspParams) and full.steps() == ISP_STEPS
    for step in ISP_STEPS:
        one = isp_profile(f"ponsel:{step}")
        assert one.steps() == (step,) and one.name == f"ponsel:{step}"
        assert one.nr_strength == full.nr_strength and one.camera_quality == full.camera_quality
        assert one == full.only(step)
    with pytest.raises(ValueError, match="tidak dikenal"):
        isp_profile("kamera")
    with pytest.raises(ValueError, match="langkah ISP"):
        full.only("hdr+")
    with pytest.raises(ValueError, match="netral"):
        isp_profile("netral:nr")
    # Every value is drawn whatever is switched on, so one-step variants share them.
    a = draw_isp(full, np.random.default_rng(4))
    b = draw_isp(full.only("nr"), np.random.default_rng(4))
    assert a == b and 2 <= a["frames"] <= 8 and 85 <= a["camera_quality"] <= 95


@pytest.mark.parametrize("profile", ["ponsel"] + [f"ponsel:{s}" for s in ISP_STEPS])
def test_isp_photo_is_deterministic_and_keeps_the_scene(page, profile):
    isp = isp_profile(profile)
    params = replace(SMALL, angle_deg=15.0)
    a, meta_a = photo_jpeg(page, np.random.default_rng(7), params, isp=isp, isp_rng=np.random.default_rng(70))
    b, meta_b = photo_jpeg(page, np.random.default_rng(7), params, isp=isp, isp_rng=np.random.default_rng(70))
    assert a == b and meta_a == meta_b
    assert json.loads(json.dumps(meta_a)) == meta_a
    c, _ = photo_jpeg(page, np.random.default_rng(7), params, isp=isp, isp_rng=np.random.default_rng(71))
    plain, meta_plain = photo_jpeg(page, np.random.default_rng(7), params)
    assert c != a and plain != a
    assert meta_a["kind"] == KIND_PHONE and meta_a["params"]["isp"]["profile"] == profile
    # Same generator state: the same scene, pose and framing as the plain photo.
    assert meta_a["homography"] == meta_plain["homography"] and meta_a["image_size"] == meta_plain["image_size"]
    shared = {k: v for k, v in meta_plain["params"].items() if k not in ("highlight_clip_frac", "paper_clip_frac")}
    assert {k: meta_a["params"][k] for k in shared} == shared
    # Without isp_rng the ISP draws from a jumped copy of the generator: still deterministic.
    d, _ = photo_jpeg(page, np.random.default_rng(7), params, isp=isp)
    e, _ = photo_jpeg(page, np.random.default_rng(7), params, isp=isp)
    assert d == e


def test_guided_filter_keeps_edges_and_flattens_low_contrast():
    rng = np.random.default_rng(1)
    img = np.full((200, 200), 200.0, np.float32)
    img[:, 100:] = 40.0  # an edge of 160 levels
    texture = rng.choice([-2.0, 2.0], (25, 25)).repeat(8, 0).repeat(8, 1).astype(np.float32)
    out = guided_filter(img + texture, 6, eps=25.0)
    assert abs(float(out[100, 90]) - 200) < 3 and abs(float(out[100, 110]) - 40) < 3  # edge kept
    flat = (out - img)[20:180, 10:80]
    assert flat.std() < 0.6 * texture[20:180, 10:80].std()  # +/-2 texture mostly gone
    sharp = guided_filter(img + texture, 6, eps=1e-4)
    assert np.allclose(sharp, img + texture, atol=0.05)  # tiny eps: identity


def test_noise_reduction_removes_the_faint_pattern_more_than_noise_alone_would():
    """Texture loss: the +/-2 cell pattern under noise is attenuated by the NR, and more so
    the stronger the threshold, while a text-like edge survives."""
    rng = np.random.default_rng(2)
    cells = rng.choice([-1.0, 1.0], (40, 40))
    pattern = cv2.resize(cells.astype(np.float32), (520, 520), interpolation=cv2.INTER_LINEAR)
    pattern *= np.float32(2.0)
    img = np.float32(230.0) + pattern + rng.normal(0, 3.0, pattern.shape).astype(np.float32)
    var = np.full(img.shape, 9.0, np.float32)
    gains = []
    for strength in (1.0, 2.5):
        out = noise_reduction(img, var, strength, 1.5, 8.0)
        gains.append(float(np.sum((out - 230.0) * pattern) / np.sum(pattern * pattern)))
    assert gains[0] < 0.95 and gains[1] < gains[0]


def test_local_tone_map_and_shoulder():
    img = np.full((300, 300), 300.0, np.float32)  # paper above white after the HDR gain
    img[100:200, 100:200] = 20.0
    out = local_tone_map(img, 30, 0.6, 1.2, 0.9)
    assert abs(float(np.percentile(out, 99.5)) - 0.9 * 255) < 3  # brightest large region at the target
    assert float(out[150, 150]) < float(out[20, 20])
    x = np.linspace(0, 400, 1000, dtype=np.float32)
    y = highlight_shoulder(x, 0.8)
    assert np.all(np.diff(y) >= 0) and y.max() <= 255.0 + 1e-3
    assert np.allclose(y[x <= 0.8 * 255], x[x <= 0.8 * 255])


def test_sharpening_overshoot_matches_its_target():
    """On a finely sampled edge (as Imatest measures it) the unsharp mask overshoots by the
    requested share of the edge height, for the profile's range of targets and radii."""
    k = 32  # samples per camera pixel
    for edge in (0.45, 1.2):
        for ratio in (1.0, 2.0):
            for target in (0.10, 0.40):
                x = np.zeros((3, 64 * k), np.float32)
                x[:, 32 * k:] = 1.0
                x = cv2.GaussianBlur(x, (0, 0), edge * k)
                amount = unsharp_amount(target, edge, ratio * edge)
                y = sharpen_halo(x * 200, amount, ratio * edge * k, 0.0) / 200
                assert float(y[1].max() - 1.0) == pytest.approx(target, rel=0.03)
    with_coring = sharpen_halo(np.full((20, 20), 100.0, np.float32) + np.eye(20, dtype=np.float32), 3.0, 1.0, 2.0)
    assert np.allclose(with_coring, np.full((20, 20), 100.0) + np.eye(20))  # detail below the coring stays


def test_isp_process_records_its_values_and_protects_highlights():
    rng = np.random.default_rng(3)
    raw = np.full((240, 320), 330.0, np.float32)  # paper overexposed by 30 %
    raw[100:140, 50:270] = 20.0
    normal = rng.standard_normal(raw.shape, dtype=np.float32)
    drawn: dict = {}
    hdr = isp_process(raw, normal, isp_profile("ponsel:hdr"), np.random.default_rng(5), noise_read=1.0,
                      noise_shot=0.02, base_sharpen=0.0, base_sharpen_sigma=1.0, tone_exponent=1.0, edge_sigma=1.0,
                      drawn=drawn)
    assert hdr.dtype == np.uint8 and drawn["isp"]["steps"] == ["hdr"]
    plain_drawn: dict = {}
    plain = isp_process(raw, normal, replace(IspParams(), multi_frame=False, local_tone=False, noise_reduction=False,
                                             sharpen=False, camera_jpeg=False), np.random.default_rng(5),
                        noise_read=1.0, noise_shot=0.02, base_sharpen=0.0, base_sharpen_sigma=1.0, tone_exponent=1.0,
                        edge_sigma=1.0, drawn=plain_drawn)
    assert plain_drawn["isp"]["raw_clip_frac"] > 0.5 and np.mean(plain[:80] == 255) > 0.99
    assert drawn["isp"]["underexpose_stops"] > 0.5  # this seed underexposes: the raw frame has headroom
    assert drawn["isp"]["raw_clip_frac"] < plain_drawn["isp"]["raw_clip_frac"]
    # HDR with local tone mapping places the brightest region below white: no clipped paper.
    tone_drawn: dict = {}
    toned = isp_process(raw, normal, replace(IspParams(), noise_reduction=False, sharpen=False, camera_jpeg=False),
                        np.random.default_rng(5), noise_read=1.0, noise_shot=0.02, base_sharpen=0.0,
                        base_sharpen_sigma=1.0, tone_exponent=1.0, edge_sigma=1.0, drawn=tone_drawn)
    assert np.mean(toned[:80] == 255) < 0.01
    assert abs(float(np.median(toned[:80])) - 255 * tone_drawn["isp"]["white_target"]) < 8


def test_monitors_and_screen_params():
    assert MONITORS["fhd24"].ppi == pytest.approx(92.56, abs=0.01)
    assert MONITORS["qhd27"].ppi == pytest.approx(108.79, abs=0.01)
    assert MONITORS["uhd27"].ppi == pytest.approx(163.18, abs=0.01)
    assert MONITORS["laptop13"].ppi == pytest.approx(226.98, abs=0.01)
    assert Monitor("x", 1000, 0, 10.0).ppi == 100.0
    with pytest.raises(ValueError, match="monitor tidak dikenal"):
        ScreenParams(monitor="crt")
    with pytest.raises(ValueError, match="supersample"):
        ScreenParams(supersample=0)
    with pytest.raises(ValueError, match="jarak"):
        ScreenParams(distance_cm=0)


def test_subpixel_profiles_are_white_balanced_stripes():
    tx, ty = subpixel_profiles(0.8, 0.85, 12, 12)
    assert tx.shape == (3, 256) and ty.shape == (256,)
    assert np.allclose(tx.mean(axis=1), 1.0, atol=1e-4) and abs(float(ty.mean()) - 1.0) < 1e-4
    t = (np.arange(256) + 0.5) / 256
    for c in range(3):  # stripe c is bright in its own third of the pixel
        inside = np.abs(t - (c + 0.5) / 3) < 0.1
        assert tx[c][inside].mean() > 2.0 and tx[c][~(np.abs(t - (c + 0.5) / 3) < 1 / 6)].mean() < 0.3
    assert ty[np.abs(t - 0.5) < 0.3].mean() > 1.05 and ty[(t < 0.03) | (t > 0.97)].mean() < 0.5  # black matrix
    flat_x, flat_y = subpixel_profiles(0.8, 0.85, 0, 0)
    assert np.all(flat_x == 1.0) and np.all(flat_y == 1.0)


def test_bayer_convention_and_demosaic():
    rgb = np.zeros((3, 32, 32), np.float32)
    rgb[0], rgb[1], rgb[2] = 200.0, 50.0, 10.0
    mosaic = bayer_mosaic(rgb)
    assert mosaic[0, 0] == 200.0 and mosaic[0, 1] == 50.0 and mosaic[1, 0] == 50.0 and mosaic[1, 1] == 10.0
    bgr = cv2.demosaicing((mosaic * 256).astype(np.uint16), BAYER_RGGB_TO_BGR).astype(np.float32) / 256
    assert np.allclose(bgr[16, 16], [10.0, 50.0, 200.0], atol=0.5)
    assert float(demosaic_luma(mosaic)[16, 16]) == pytest.approx(0.299 * 200 + 0.587 * 50 + 0.114 * 10, abs=0.5)


def test_view_angles_and_falloff():
    k = np.array([[1000.0, 0, 500.0], [0, 1000.0, 400.0], [0, 0, 1.0]])
    h = k @ np.array([[1.0, 0, -500.0], [0, 1.0, -400.0], [0, 0, 1000.0]]) / 1000.0  # frontal, 1000 px away
    ah, av = view_angles(h, k, (801, 1001))
    assert abs(float(ah[400, 500])) < 0.5 and abs(float(av[400, 500])) < 0.5
    assert float(ah[400, 1000]) == pytest.approx(-math.degrees(math.atan(0.5)), abs=1.0)  # right edge: camera to its left
    assert float(abs(av[0, 500])) == pytest.approx(math.degrees(math.atan(0.4)), abs=1.0)
    f = angular_falloff(np.array([0.0, 40.0, 0.0]), np.array([0.0, 0.0, 30.0]), 40.0, 30.0)
    assert np.allclose(f, [1.0, 0.75, 0.75], atol=1e-6)


def test_render_display_without_grid_is_uniform_and_room_outside():
    canvas = np.ones((300, 400), np.float32)
    h = np.array([[2.0, 0, 50.0], [0, 2.0, 40.0], [0, 0, 1.0]])  # 2 camera px per screen px
    out = render_display(canvas, np.zeros_like(canvas), h, (900, 700), lens_sigma=0.5, motion_kernel=None,
                         aperture=(0.8, 0.85), subpixels=False, cfa=False, room=0.05)
    assert out.shape == (700, 900)
    assert np.allclose(out[200:500, 200:700], 1.0, atol=1e-4) and np.allclose(out[690:, :], 0.05, atol=1e-4)
    rgb = render_display(canvas, np.zeros_like(canvas), h, (900, 700), lens_sigma=0.5, motion_kernel=None,
                         aperture=(0.8, 0.85), subpixels=True, cfa=True, room=0.05)
    assert rgb.shape == (3, 700, 900)
    centre = rgb[:, 200:500, 200:700]
    assert np.allclose(centre.mean(axis=(1, 2)), 1.0, atol=0.02)  # white balanced
    assert centre[1].std() > 0.2  # the stripes are resolved at 2 camera px per screen px


def test_screen_photo_is_deterministic_and_records_the_monitor(page):
    params = replace(SMALL, angle_deg=20.0)
    a, meta_a = screen_photo_jpeg(page, np.random.default_rng(11), params, FAST_SCREEN, render_dpi=100.0)
    b, meta_b = screen_photo_jpeg(page, np.random.default_rng(11), params, FAST_SCREEN, render_dpi=100.0)
    assert a == b and meta_a == meta_b and json.loads(json.dumps(meta_a)) == meta_a
    c, _ = screen_photo_jpeg(page, np.random.default_rng(12), params, FAST_SCREEN, render_dpi=100.0)
    assert c != a
    p, meta_p = screen_photo_jpeg(page, np.random.default_rng(11), params, FAST_SCREEN, isp=isp_profile("ponsel"),
                                  isp_rng=np.random.default_rng(13), render_dpi=100.0)
    q, _ = screen_photo_jpeg(page, np.random.default_rng(11), params, FAST_SCREEN, isp=isp_profile("ponsel"),
                             isp_rng=np.random.default_rng(13), render_dpi=100.0)
    assert p == q and p != a
    assert meta_a["kind"] == meta_p["kind"] == KIND_SCREEN_PHOTO
    assert meta_a["homography"] == meta_p["homography"]  # the ISP does not move the scene
    assert meta_a["isp_settings"] is None and meta_p["isp_settings"]["name"] == "ponsel"
    s = meta_a["screen"]
    assert s["monitor"] == "fhd24" and s["ppi"] == pytest.approx(92.56, abs=0.01) and s["distance_cm"] == 30.0
    assert 0 < s["fill"] <= FAST_SCREEN.max_fill and len(s["grid_frequency"]) == 2
    assert view_angle_deg(meta_a["homography"], meta_a["camera_matrix"]) == pytest.approx(20.0, abs=1e-6)
    img, meta = screen_photo(page, np.random.default_rng(11), params, FAST_SCREEN, render_dpi=100.0)
    assert np.array_equal(img, decode_jpeg(a)) and meta == meta_a


def test_screen_photo_homography_maps_the_page(page):
    """The page corners land where the homography puts them: bright page inside, darker
    viewer background just outside."""
    params = replace(SMALL, angle_deg=10.0, crop_max_frac=0.0)
    img, meta = screen_photo(page, np.random.default_rng(5), params,
                             replace(FAST_SCREEN, dark_prob=1.0, subpixels=False), render_dpi=100.0)
    hom = np.array(meta["homography"])
    h, w = page.shape
    for (xi, yi), (xo, yo) in (((0.1, 0.03), (0.1, -0.03)), ((0.97, 0.5), (1.03, 0.5)), ((0.5, 0.98), (0.5, 1.02))):
        pin = hom @ np.array([xi * (w - 1), yi * (h - 1), 1.0])
        pout = hom @ np.array([xo * (w - 1), yo * (h - 1), 1.0])
        vin = img[int(pin[1] / pin[2]), int(pin[0] / pin[2])]
        vout = img[int(pout[1] / pout[2]), int(pout[0] / pout[2])]
        assert int(vin) > int(vout) + 60


def _peak(img: np.ndarray, meta: dict, page_shape: tuple[int, int], n: int = 256) -> tuple[float, float, float, np.ndarray]:
    hom = np.array(meta["homography"])
    c = hom @ np.array([(page_shape[1] - 1) / 2, (page_shape[0] - 1) / 2, 1.0])
    cx, cy = int(c[0] / c[2]), int(c[1] / c[2])
    patch = img[cy - n // 2:cy + n // 2, cx - n // 2:cx + n // 2].astype(float)
    patch -= patch.mean()
    win = np.hanning(n)[:, None] * np.hanning(n)[None, :]
    spec = np.abs(np.fft.fftshift(np.fft.fft2(patch * win)))
    k = n // 2
    spec[k - 4:k + 5, k - 4:k + 5] = 0.0
    freqs = np.abs(np.fft.fftshift(np.fft.fftfreq(n)))
    row = spec[k - 1:k + 2].max(axis=0)
    col = spec[:, k - 1:k + 2].max(axis=1)
    return float(freqs[np.argmax(row)]), float(freqs[np.argmax(col)]), float(row.max() / np.median(spec)), spec


@pytest.mark.parametrize("cfa", [False, True])
def test_moire_appears_at_the_predicted_alias_frequency(cfa):
    """A blank white page on the 23.8 inch monitor, photographed head-on with a sharp lens,
    about 1.8 camera px per screen px and no WhatsApp downscale: the subpixel grid (1 cycle
    per screen pixel) lies above the sensor's Nyquist limit and must alias to
    |f - round(f)|, f being the grid frequency in output pixels. Without subpixels the peak
    is absent."""
    page = np.full((1170, 827), 255, np.uint8)
    params = PhotoParams(angle_deg=0.0, max_roll_deg=0.0, crop_max_frac=0.0, sensor_long_side=2016, long_side=2016)
    screen = ScreenParams(monitor="fhd24", distance_cm=23.0, sensor_long_side=2016, lens_sigma_px=(0.45, 0.45),
                          motion_px=(0.0, 0.0), cfa=cfa)
    img, meta = screen_photo(page, np.random.default_rng(3), params, screen, render_dpi=100.0)
    f = meta["screen"]["grid_frequency"]
    assert 0.5 < f[0] < 0.62 and 0.5 < f[1] < 0.62  # above Nyquist, so it aliases
    want = [abs(v - round(v)) for v in f]
    fx, fy, snr, spec = _peak(img, meta, page.shape)
    assert abs(fx - want[0]) <= 1.5 / 256 and abs(fy - want[1]) <= 1.5 / 256
    assert snr > 50
    ideal, meta_i = screen_photo(page, np.random.default_rng(3), params, replace(screen, subpixels=False),
                                 render_dpi=100.0)
    _, _, snr_ideal, spec_i = _peak(ideal, meta_i, page.shape)
    k = 128
    at = (k + int(round(want[0] * 256)), k)
    assert spec_i[at[1] - 1:at[1] + 2, at[0] - 1:at[0] + 2].max() < 0.1 * spec[at[1] - 1:at[1] + 2, at[0] - 1:at[0] + 2].max()
    assert snr_ideal < 0.2 * snr


def test_make_photo_set_phone_and_monitor_kinds(issued, tmp_path):
    issued_dir, _ = issued
    plain_dir, phone_dir = tmp_path / "plain", tmp_path / "ponsel"
    fast = PhotoParams(sensor_long_side=1200)
    make_photo_set(issued_dir, plain_dir, seqs=[2], per_copy=1, angles=(10,), dpi=100, long_side=800,
                   screenshots=False, photo_params=fast)
    items = make_photo_set(issued_dir, phone_dir, seqs=[2], per_copy=1, angles=(10,), dpi=100, long_side=800,
                           screenshots=False, photo_params=fast, isp=ISP_PROFILES["ponsel"])
    assert [it["file"] for it in items] == ["ponsel_s002_p1_a10_0.jpg"]
    assert items[0]["kind"] == KIND_PHONE and items[0]["isp"] == "ponsel"
    plain = json.loads((plain_dir / "truth.json").read_text())["items"][0]
    assert "isp" not in plain and plain["homography"] == items[0]["homography"]  # same scene as make photos
    screen_dir = tmp_path / "layar"
    items = make_photo_set(issued_dir, screen_dir, seqs=[2], per_copy=1, angles=(10,), dpi=100, long_side=800,
                           screenshots=False, photo_params=fast, screen_params=FAST_SCREEN)
    assert [it["file"] for it in items] == ["fotolayar_s002_p1_a10_0.jpg"]
    assert items[0]["kind"] == KIND_SCREEN_PHOTO and items[0]["isp"] == "netral" and items[0]["screen"]["monitor"] == "fhd24"
    with pytest.raises(ValueError, match="foto cetak"):
        make_photo_set(issued_dir, tmp_path / "x", seqs=[2], per_copy=1, angles=(10,), screenshots=False,
                       print_params=PrintParams(), isp=ISP_PROFILES["ponsel"])


@pytest.mark.slow
def test_main_cli_phone_and_monitor(issued, tmp_path, capsys):
    issued_dir, _ = issued
    assert main(["--issued", str(issued_dir), "--out", str(tmp_path / "p"), "--seqs", "3", "--per-copy", "1",
                 "--angles", "0", "--no-screenshots", "--isp", "ponsel", "--long-side", "800"]) == 0
    assert (tmp_path / "p" / "ponsel_s003_p1_a0_0.jpg").exists()
    assert main(["--issued", str(issued_dir), "--out", str(tmp_path / "l"), "--seqs", "3", "--per-copy", "1",
                 "--angles", "0", "--no-screenshots", "--layar", "--silau", "--isp", "ponsel"]) == 0
    truth = json.loads((tmp_path / "l" / "truth.json").read_text())
    assert truth["items"][0]["kind"] == KIND_SCREEN_PHOTO and truth["items"][0]["params"]["glare"] is True
    with pytest.raises(SystemExit):
        main(["--issued", str(issued_dir), "--out", str(tmp_path / "z"), "--silau"])
    assert "Selesai: 1 foto" in capsys.readouterr().out


def _trace(data: bytes, ctx):
    from tapak.decoder.image import collect_from_image
    from tapak.decoder.trace import run_trace

    return run_trace(collect_from_image(data, ctx), ctx)


@pytest.mark.slow
def test_phone_isp_photo_end_to_end(issued, ctx):
    from tapak.decoder.accuse import VERDICT_IDENTIFIED

    out, manifest = issued
    seq = 5
    page = render_pages((out / manifest.copies[seq - 1].file).read_bytes(), 200, [0])[0]
    data, meta = photo_jpeg(page, np.random.default_rng(21), PhotoParams(angle_deg=15.0), isp=isp_profile("ponsel"),
                            isp_rng=np.random.default_rng(22))
    assert meta["params"]["isp"]["steps"] == list(ISP_STEPS)
    result = _trace(data, ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]


@pytest.mark.slow
def test_monitor_photo_end_to_end(issued, ctx):
    from tapak.decoder.accuse import VERDICT_IDENTIFIED

    out, manifest = issued
    seq = 6
    page = render_pages((out / manifest.copies[seq - 1].file).read_bytes(), 200, [0])[0]
    data, meta = screen_photo_jpeg(page, np.random.default_rng(23), PhotoParams(angle_deg=10.0),
                                   ScreenParams(monitor="qhd27", distance_cm=30.0), isp=isp_profile("ponsel"),
                                   isp_rng=np.random.default_rng(24))
    assert meta["screen"]["grid_frequency"][0] > 0.5  # the grid aliases in this photo
    result = _trace(data, ctx)
    assert result.verdict == VERDICT_IDENTIFIED and [c.copy.seq for c in result.accused] == [seq]


@pytest.mark.slow
def test_unmarked_master_through_new_kinds_accuses_nobody(sample_pdf, ctx):
    page = render_pages(sample_pdf, 200, [0])[0]
    images = [photo_jpeg(page, np.random.default_rng(31), PhotoParams(angle_deg=20.0), isp=isp_profile("ponsel"))[0],
              screen_photo_jpeg(page, np.random.default_rng(32), PhotoParams(angle_deg=0.0),
                                ScreenParams(monitor="fhd24", distance_cm=30.0))[0],
              screen_photo_jpeg(page, np.random.default_rng(33), PhotoParams(angle_deg=20.0),
                                ScreenParams(monitor="uhd27", distance_cm=45.0), isp=isp_profile("ponsel"))[0]]
    for data in images:
        assert _trace(data, ctx).accused == []
