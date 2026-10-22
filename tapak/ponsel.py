"""Phone image processing and a simulated monitor for the photo simulator (opt-in).

``tapak.photos`` stays as it was unless one of these is asked for:

* ``IspParams`` (ISP profile "ponsel"): what a phone camera does to the sensor image before
  anyone sees it. A burst of deliberately underexposed frames is merged (multi-frame HDR),
  an edge-preserving noise reduction removes noise and, with it, low-contrast texture, a
  local tone mapper compresses large-scale contrast and rolls highlights off softly, an
  unsharp mask with coring sharpens edges with visible halos, and the camera writes a JPEG
  at its own quality before WhatsApp recompresses it. Profile "netral" is the simulator as
  it was (no ISP stage).
* ``ScreenParams`` (kind "fotolayar"): the copy shown in a PDF viewer on an LCD monitor and
  photographed. The display has RGB stripe subpixels with a black matrix at a chosen pixel
  density, a display gamma, a backlight with some falloff, an angular luminance falloff,
  ambient reflection and optional glare. The camera samples it through a lens and a Bayer
  colour filter array, so the subpixel grid aliases into moire.

This is a simulation. No phone, monitor or ISP was measured; every range below comes from a
cited source or is marked as an assumption. The sources (numbers in brackets) are listed at
the end of this docstring and summarized in docs/keamanan.md (batasan 10).

ISP ranges (``IspParams``):

* frames 2 to 8, merged in raw [1, 2]; underexposure 0 to 2 stops: HDR+ "deliberately
  under-expose[s]" its frames to avoid clipping highlights [1, 2], the amount is not given
  there, so the range is an assumption. Merging n frames divides the noise variance by n.
* noise model N(x) = sqrt(S x + O) per pixel, the two-parameter model phones report [3, 4]
  (the noise levels themselves are those of ``PhotoParams``).
* noise reduction: self-guided filter [5] at a fine and a coarse scale (radius 1 to 2 and 4 to
  10 px of a 12 MP frame); its threshold is 1 to 2.5 times the local noise level. Bilateral
  denoisers do best near twice the noise level [6]; phones are known for removing
  low-contrast texture this way ("texture loss", measured with dead-leaves charts [7, 8]).
* local tone mapping: base and detail layers in the log domain [9] (base radius 2 to 6 % of
  the frame; Durand and Dorsey use 2 % of the image size), base contrast times 0.5 to 0.85,
  detail times 1.0 to 1.3, the brightest large region placed at 85 to 97 % of white, then a
  soft highlight shoulder above a knee of 75 to 90 %: assumptions within that method.
* sharpening: unsharp mask with a radius of 1 to 2 times the lens blur, coring 0.5 to 2 gray
  levels, its amount set so that a step edge blurred by the lens overshoots by 10 to 40 %
  (on a finely sampled edge, as Imatest measures it).
  Imatest reports 7 % overshoot for a moderate unsharp mask on a DSLR, calls 35 % likely
  objectionable and notes "huge halos" on camera phones [10] (tests/test_ponsel.py checks
  the overshoot).
* camera JPEG quality 85 to 95, the "typical usage range" of Android's android.jpeg.quality,
  which also sets the HEIC quality [3]. HEIC itself is not simulated.

Display ranges (``ScreenParams``):

* monitors (pixel density from the geometry, sqrt(w^2 + h^2) / diagonal): 23.8 inch
  1920 x 1080 (92.6 ppi), 27 inch 2560 x 1440 (108.8 ppi), 27 inch 3840 x 2160 (163.2 ppi)
  and a 13.3 inch 2560 x 1600 laptop (227 ppi). In the Steam survey of September 2026,
  1920 x 1080 was the primary display of 47.9 % of users, 2560 x 1440 of 27.0 % and
  3840 x 2160 of 4.8 % [11] (a gaming audience, not offices).
* the page is shown "fit to page", 80 to 92 % of the screen height (assumption).
* display gamma 2.0 to 2.4 (sRGB is about 2.2 [12], BT.1886 2.4 [13]); white 100 to
  300 cd/m^2 (office screens mostly run a light background at 140 to 180 cd/m^2 [14]);
  contrast 800 to 3000 (IPS and VA panels, assumption).
* angular falloff: luminance at angle theta is exp(-ln(4/3) (theta / theta75)^2) per axis,
  theta75 being the angle where it falls to 75 %. RTINGS measures that angle (for lightness)
  at 39 to 42 degrees on an IPS monitor and 22 degrees from below on a weak panel, and calls
  more than 45 degrees good [15]; horizontal 35 to 50, vertical 22 to 45 degrees.
* backlight 0 to 20 % darker in the corners than in the centre (assumption).
* RGB vertical stripes, each a third of the pixel pitch; the lit share of a subpixel is 70 to
  90 % of its width and 75 to 92 % of its height (aperture ratio about 50 to 80 %,
  assumption).
* ambient reflection 0.5 to 4 % of white (a matte screen in a 500 lx office, assumption);
  glare (optional): a reflected luminaire, at most about 3000 cd/m^2 at the angles office
  lighting allows [14], times a front-surface reflectance of about 1 to 4 % (4 % is glass),
  so 5 to 50 % of white; its size is an assumption.
* camera: 12 MP frame (4032 x 3024), 26 mm equivalent main camera, distance 25 to 60 cm
  (assumption), lens blur sigma 0.45 to 0.9 px (MTF50 about 0.21 to 0.42 cycles per pixel;
  Imatest's unsharpened reference is 0.31 [10]), RGGB Bayer filter, edge-aware demosaicing
  (OpenCV), white balance on the display white, luma with BT.601 weights (as JPEG).

Not simulated: real phones and screens, HEIC, 6-bit + FRC panels (temporal dithering), PWM
backlight banding, subpixel text rendering (ClearType), OLED and PenTile layouts, colour
crosstalk between camera filters and display primaries, multi-frame super-resolution in
place of demosaicing, learned ISPs.

Sources:
[1] M. Delbracio, D. Kelly, M. S. Brown, P. Milanfar. Mobile computational photography: a
    tour. Annu. Rev. Vis. Sci. 7, 2021 (arXiv:2102.09000), section 3.3.3.
[2] S. W. Hasinoff et al. Burst photography for high dynamic range and low-light imaging on
    mobile cameras. ACM Trans. Graph. 35(6), 2016 (SIGGRAPH Asia).
[3] Android camera metadata (AOSP, camera/docs/metadata_definitions.xml):
    android.jpeg.quality and android.sensor.noiseProfile.
[4] A. Foi, M. Trimeche, V. Katkovnik, K. Egiazarian. Practical Poissonian-Gaussian noise
    modeling and fitting for single-image raw-data. IEEE Trans. Image Process. 17(10), 2008.
[5] K. He, J. Sun, X. Tang. Guided image filtering. IEEE TPAMI 35(6), 2013.
[6] M. Zhang, B. K. Gunturk. Multiresolution bilateral filtering for image denoising. IEEE
    Trans. Image Process. 17(12), 2008.
[7] F. Cao, F. Guichard, H. Hornung. Dead leaves model for measuring texture quality on a
    digital camera. Proc. SPIE 7537, 2010.
[8] IEEE 1858-2016, Camera Phone Image Quality (texture blur metric).
[9] F. Durand, J. Dorsey. Fast bilateral filtering for the display of high-dynamic-range
    images. ACM Trans. Graph. 21(3), 2002.
[10] Imatest documentation: Sharpening (imatest.com/docs/sharpening).
[11] Steam Hardware and Software Survey, September 2026 (store.steampowered.com/hwsurvey).
[12] IEC 61966-2-1:1999, sRGB.
[13] ITU-R BT.1886, reference EOTF for flat panel displays.
[14] Trilux, lighting of offices and VDU workstations: luminance thresholds (EN 12464-1).
[15] RTINGS, monitor viewing angle test (rtings.com/monitor/tests/picture-quality/viewing-angle).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

import cv2
import numpy as np

REFERENCE_LONG_SIDE = 4032  # pixel radii of the ISP are given for a 12 MP (4032 x 3024) frame
LUMA_WEIGHTS = (0.299, 0.587, 0.114)  # BT.601 luma of R, G, B (what a grayscale JPEG decode returns)
ISP_STEPS = ("nr", "hdr", "nada", "tajam", "jpeg")  # noise reduction, burst HDR, local tone, sharpening, JPEG


def _uniform(rng: np.random.Generator, bounds: tuple[float, float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


# ---------------------------------------------------------------------------------------
# ISP


@dataclass(frozen=True)
class IspParams:
    """Phone image processing after the sensor. A (low, high) pair is drawn uniformly; each
    step can be switched off (``only`` builds the one-step variants used for ablation).

    Attributes:
        name: profile name recorded in the photo meta.
        noise_reduction: edge-preserving noise reduction (guided filter, two scales).
        nr_strength: threshold of the filter in units of the local noise level.
        nr_radius_fine, nr_radius_coarse: filter radii in px of a 12 MP frame.
        multi_frame: burst of underexposed frames merged in raw (HDR+-like).
        frames: burst length.
        underexpose_stops: exposure of each frame below the camera's metered exposure.
        align_blur_px: blur from imperfect alignment of the frames (px of a 12 MP frame).
        local_tone: local tone mapping (log-domain base compression, detail boost).
        tone_radius_frac: base-layer radius relative to the frame long side.
        tone_compression: factor on the base layer's contrast.
        tone_detail: factor on the detail layer.
        white_target: where the brightest large region lands, relative to white.
        knee: start of the soft highlight shoulder (with multi_frame or local_tone).
        sharpen: unsharp mask with coring (replaces the mild sharpening of the base photo).
        sharpen_overshoot: overshoot of a lens-blurred step edge; sets the mask's amount.
        sharpen_radius: radius (Gaussian sigma) of the mask relative to the lens blur.
        sharpen_coring: detail below this many gray levels is not sharpened.
        camera_jpeg: the camera's own JPEG before WhatsApp.
        camera_quality: its quality.
    """

    name: str = "ponsel"
    noise_reduction: bool = True
    nr_strength: tuple[float, float] = (1.0, 2.5)
    nr_radius_fine: tuple[float, float] = (1.0, 2.0)
    nr_radius_coarse: tuple[float, float] = (4.0, 10.0)
    multi_frame: bool = True
    frames: tuple[int, int] = (2, 8)
    underexpose_stops: tuple[float, float] = (0.0, 2.0)
    align_blur_px: tuple[float, float] = (0.0, 0.3)
    local_tone: bool = True
    tone_radius_frac: tuple[float, float] = (0.02, 0.06)
    tone_compression: tuple[float, float] = (0.5, 0.85)
    tone_detail: tuple[float, float] = (1.0, 1.3)
    white_target: tuple[float, float] = (0.85, 0.97)
    knee: tuple[float, float] = (0.75, 0.90)
    sharpen: bool = True
    sharpen_overshoot: tuple[float, float] = (0.10, 0.40)
    sharpen_radius: tuple[float, float] = (1.0, 2.0)
    sharpen_coring: tuple[float, float] = (0.5, 2.0)
    camera_jpeg: bool = True
    camera_quality: tuple[int, int] = (85, 95)

    def steps(self) -> tuple[str, ...]:
        """The enabled steps, in the order of ISP_STEPS."""
        on = (self.noise_reduction, self.multi_frame, self.local_tone, self.sharpen, self.camera_jpeg)
        return tuple(s for s, flag in zip(ISP_STEPS, on) if flag)

    def only(self, step: str) -> "IspParams":
        """The same profile with only ``step`` (one of ISP_STEPS) switched on."""
        if step not in ISP_STEPS:
            raise ValueError(f"langkah ISP tidak dikenal: {step!r}; pilih salah satu dari {', '.join(ISP_STEPS)}")
        flags = dict(zip(("noise_reduction", "multi_frame", "local_tone", "sharpen", "camera_jpeg"),
                         (s == step for s in ISP_STEPS)))
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values.update(flags, name=f"{self.name}:{step}")
        return IspParams(**values)


ISP_PROFILES: dict[str, IspParams | None] = {"netral": None, "ponsel": IspParams()}


def isp_profile(name: str) -> IspParams | None:
    """The ISP profile ``name``: "netral" (None, the simulator as it was) or "ponsel"; a
    one-step variant is written "ponsel:nr" (steps in ISP_STEPS)."""
    base, _, step = name.partition(":")
    if base not in ISP_PROFILES:
        raise ValueError(f"profil ISP tidak dikenal: {name!r}; pilih 'netral' atau 'ponsel'")
    profile = ISP_PROFILES[base]
    if step:
        if profile is None:
            raise ValueError("profil netral tidak memiliki langkah ISP")
        return profile.only(step)
    return profile


def guided_filter(img: np.ndarray, radius: float, eps: float | np.ndarray) -> np.ndarray:
    """Self-guided edge-preserving smoothing (He, Sun and Tang).

    In every (2r + 1)^2 window the output is a linear function a * I + b of the input with
    a = var / (var + eps): windows whose variance is well above ``eps`` (edges, text) keep
    their contrast, flatter windows are replaced by their mean, low-contrast texture included.
    ``eps`` may be an array (a noise-dependent threshold per pixel).
    """
    img = np.asarray(img, dtype=np.float32)
    r = max(1, int(round(radius)))
    k = (2 * r + 1, 2 * r + 1)

    def box(a: np.ndarray) -> np.ndarray:
        return cv2.boxFilter(a, -1, k, borderType=cv2.BORDER_REFLECT)

    mean = box(img)
    var = np.maximum(box(img * img) - mean * mean, 0.0)
    a = var / (var + np.asarray(eps, dtype=np.float32) + np.float32(1e-12))
    b = mean - a * mean
    return box(a) * img + box(b)


def noise_reduction(img: np.ndarray, noise_var: np.ndarray, strength: float, radius_fine: float,
                    radius_coarse: float) -> np.ndarray:
    """Two-scale edge-preserving noise reduction driven by the noise profile.

    ``noise_var`` is the noise variance per pixel (from the camera's noise model at the local
    signal level). The fine pass uses the threshold (strength * sigma)^2; the coarse pass
    uses the noise left after the fine window, (strength * sigma / (2 r_fine + 1))^2, as
    multi-scale denoisers lower their threshold per scale.
    """
    eps = np.float32(strength * strength) * np.asarray(noise_var, dtype=np.float32)
    out = guided_filter(img, radius_fine, eps)
    width = 2 * max(1, int(round(radius_fine))) + 1
    return guided_filter(out, radius_coarse, eps / np.float32(width * width))


def local_tone_map(img: np.ndarray, radius: float, compression: float, detail: float,
                   white: float) -> np.ndarray:
    """Base and detail layers in the log domain (Durand and Dorsey), with an edge-aware base.

    log2(I / 255) is split into a base (guided filter of ``radius`` px) and the detail around
    it. The base's contrast is multiplied by ``compression`` about its 99.5th percentile,
    which lands at ``white`` (relative to 255); the detail is multiplied by ``detail``.
    """
    lg = np.log2(np.maximum(np.asarray(img, dtype=np.float32), np.float32(0.5)) / np.float32(255.0))
    base = guided_filter(lg, radius, 0.04)  # (0.2 stops)^2: text and page edges stay in the base
    top = float(np.percentile(base[::4, ::4], 99.5))
    out = np.float32(math.log2(white)) + (base - np.float32(top)) * np.float32(compression) \
        + (lg - base) * np.float32(detail)
    return np.float32(255.0) * np.exp2(out)


def highlight_shoulder(img: np.ndarray, knee: float) -> np.ndarray:
    """Soft highlight roll-off: identity below ``knee`` * 255, then a tanh shoulder towards 255."""
    x = np.asarray(img, dtype=np.float32) / np.float32(255.0)
    k = np.float32(knee)
    soft = k + (1 - k) * np.tanh((x - k) / (1 - k))
    return np.float32(255.0) * np.where(x <= k, x, soft)


def sharpen_halo(img: np.ndarray, amount: float, sigma: float, coring: float) -> np.ndarray:
    """Unsharp mask with coring: detail (image minus its Gaussian blur) below ``coring`` gray
    levels is left alone, larger detail is boosted by ``amount`` (overshoot and halos)."""
    img = np.asarray(img, dtype=np.float32)
    d = img - cv2.GaussianBlur(img, (0, 0), sigma)
    d = np.sign(d) * np.maximum(np.abs(d) - np.float32(coring), 0.0)
    return img + np.float32(amount) * d


def unsharp_amount(overshoot: float, edge_sigma: float, mask_sigma: float) -> float:
    """Amount of an unsharp mask (Gaussian ``mask_sigma``) that makes a step edge blurred by a
    Gaussian ``edge_sigma`` overshoot by ``overshoot`` of its height.

    The sharpened edge is E + A (E - E_blurred) with E = Phi(x / a) and E_blurred =
    Phi(x / b), a = edge_sigma, b = sqrt(a^2 + mask_sigma^2); its maximum minus 1 grows
    monotonically with A, so A is found by bisection on a fine grid of x (in units of a).
    """
    a = max(float(edge_sigma), 1e-3)
    ratio = math.hypot(a, float(mask_sigma)) / a
    x = np.linspace(0.0, 8.0 * ratio, 4001)
    sq2 = math.sqrt(2.0)
    e = 0.5 * (1.0 + np.vectorize(math.erf)(x / sq2))
    d = e - 0.5 * (1.0 + np.vectorize(math.erf)(x / (ratio * sq2)))
    lo, hi = 0.0, 1.0
    while float(np.max(e + hi * d)) - 1.0 < overshoot:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if float(np.max(e + mid * d)) - 1.0 < overshoot else (lo, mid)
    return 0.5 * (lo + hi)


def draw_isp(isp: IspParams, rng: np.random.Generator) -> dict[str, float]:
    """Every random value of the ISP, drawn in a fixed order whatever steps are enabled, so the
    one-step variants of a profile share their values with the full profile."""
    return {
        "frames": int(rng.integers(isp.frames[0], isp.frames[1] + 1)),
        "underexpose_stops": _uniform(rng, isp.underexpose_stops),
        "align_blur_px": _uniform(rng, isp.align_blur_px),
        "nr_strength": _uniform(rng, isp.nr_strength),
        "nr_radius_fine": _uniform(rng, isp.nr_radius_fine),
        "nr_radius_coarse": _uniform(rng, isp.nr_radius_coarse),
        "tone_radius_frac": _uniform(rng, isp.tone_radius_frac),
        "tone_compression": _uniform(rng, isp.tone_compression),
        "tone_detail": _uniform(rng, isp.tone_detail),
        "white_target": _uniform(rng, isp.white_target),
        "knee": _uniform(rng, isp.knee),
        "sharpen_overshoot": _uniform(rng, isp.sharpen_overshoot),
        "sharpen_radius": _uniform(rng, isp.sharpen_radius),
        "sharpen_coring": _uniform(rng, isp.sharpen_coring),
        "camera_quality": int(rng.integers(isp.camera_quality[0], isp.camera_quality[1] + 1)),
    }


def isp_process(raw: np.ndarray, normal: np.ndarray, isp: IspParams, rng: np.random.Generator, *,
                noise_read: float, noise_shot: float, base_sharpen: float, base_sharpen_sigma: float,
                tone_exponent: float, edge_sigma: float, drawn: dict[str, object],
                paper: np.ndarray | None = None, demosaic=None) -> np.ndarray:
    """Sensor noise plus the ISP on a camera frame; returns the uint8 image the camera saves.

    ``raw`` is the linear camera image before noise (gray levels at the metered exposure,
    may exceed 255), ``normal`` a standard normal field of the same shape: the photo
    generator draws it exactly as for the plain photo, so a photo with and without the ISP
    share their scene and noise. ``noise_read`` and ``noise_shot`` give the per-frame noise
    sigma^2 = read^2 + shot * x; ``base_sharpen`` and ``base_sharpen_sigma`` (px) are the plain
    photo's unsharp mask, used when the ISP's own sharpening is off; ``tone_exponent`` the
    plain photo's tone curve; ``edge_sigma`` the optical blur of the frame (px), to which the
    sharpening is tuned (``unsharp_amount``). ``demosaic`` (optional) turns the noisy raw frame into luma (a
    Bayer mosaic); without it the frame is already luma. ISP values are drawn from ``rng``
    and recorded in ``drawn["isp"]``, with ``raw_clip_frac`` and ``paper_raw_clip_frac``
    (share of raw pixels at saturation, overall and on the page's blank paper ``paper``).
    """
    v = draw_isp(isp, rng)
    scale = max(raw.shape) / REFERENCE_LONG_SIDE
    gain = 2.0 ** v["underexpose_stops"] if isp.multi_frame else 1.0
    frames = v["frames"] if isp.multi_frame else 1
    img = raw / np.float32(gain) if gain != 1.0 else raw.copy()
    var = (np.float32(noise_read ** 2) + np.float32(noise_shot) * np.clip(img, 0.0, None)) / np.float32(frames)
    img += np.sqrt(var) * normal
    del var
    if isp.multi_frame and v["align_blur_px"] * scale > 0.05:
        img = cv2.GaussianBlur(img, (0, 0), v["align_blur_px"] * scale)
    clipped = img >= 255.0
    v["raw_clip_frac"] = float(np.mean(clipped))
    v["paper_raw_clip_frac"] = float(np.mean(clipped[paper])) if paper is not None and paper.any() else 0.0
    del clipped
    img = np.clip(img, 0.0, 255.0)
    if demosaic is not None:
        img = demosaic(img)
    if isp.noise_reduction:
        mean = cv2.blur(img, (5, 5))
        noise_var = (np.float32(noise_read ** 2) + np.float32(noise_shot) * mean) / np.float32(frames)
        img = noise_reduction(img, noise_var, v["nr_strength"], v["nr_radius_fine"] * scale,
                              v["nr_radius_coarse"] * scale)
        del mean, noise_var
    if gain != 1.0:
        img *= np.float32(gain)
    if isp.local_tone:
        img = local_tone_map(img, v["tone_radius_frac"] * max(img.shape), v["tone_compression"],
                             v["tone_detail"], v["white_target"])
    if isp.multi_frame or isp.local_tone:
        img = highlight_shoulder(img, v["knee"])
    img = np.clip(img, 0.0, 255.0)
    img = np.float32(255.0) * np.power(img / np.float32(255.0), np.float32(tone_exponent))
    if isp.sharpen:
        mask_sigma = v["sharpen_radius"] * edge_sigma
        v["sharpen_amount"] = unsharp_amount(v["sharpen_overshoot"], edge_sigma, mask_sigma)
        img = sharpen_halo(img, v["sharpen_amount"], mask_sigma, v["sharpen_coring"])
    elif base_sharpen > 0.0:
        img += np.float32(base_sharpen) * (img - cv2.GaussianBlur(img, (0, 0), sigmaX=base_sharpen_sigma))
    v["final_clip_frac"] = float(np.mean(img >= 255.0))
    out = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    if isp.camera_jpeg:
        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, v["camera_quality"]])
        if not ok:
            raise RuntimeError("pengodean JPEG gagal")
        out = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    drawn["isp"] = {"profile": isp.name, "steps": list(isp.steps()), **v}
    return out


# ---------------------------------------------------------------------------------------
# Monitor


@dataclass(frozen=True)
class Monitor:
    """A monitor model: resolution and diagonal (inches)."""

    name: str
    width_px: int
    height_px: int
    diagonal_in: float

    @property
    def ppi(self) -> float:
        """Pixel density from the geometry: sqrt(w^2 + h^2) / diagonal."""
        return math.hypot(self.width_px, self.height_px) / self.diagonal_in


MONITORS: dict[str, Monitor] = {
    "fhd24": Monitor("fhd24", 1920, 1080, 23.8),
    "qhd27": Monitor("qhd27", 2560, 1440, 27.0),
    "uhd27": Monitor("uhd27", 3840, 2160, 27.0),
    "laptop13": Monitor("laptop13", 2560, 1600, 13.3),
}


@dataclass(frozen=True)
class ScreenParams:
    """Settings of a simulated monitor and of the phone that photographs it. A (low, high)
    pair is drawn uniformly; the sources are in the module docstring.

    Attributes:
        monitor: exact monitor name (MONITORS); None draws it from ``monitors``.
        monitors: monitors to draw from.
        distance_cm: exact camera distance to the page centre; None draws ``distance_range``.
        distance_range: range of distances (cm).
        page_height_frac: page height on screen relative to the screen height (zoom).
        dark_prob: probability of a dark viewer theme.
        gamma: display gamma (drive level to luminance).
        brightness_cd: white luminance (cd/m^2); dimmer screens need more camera gain (noise).
        contrast: full-on to full-off luminance ratio.
        backlight_falloff: luminance lost in the screen corners.
        falloff_deg_h, falloff_deg_v: angles where luminance drops to 75 % (per axis).
        subpixels: RGB stripes with black matrix; False shows an ideal uniform display.
        aperture_x, aperture_y: lit share of a subpixel's width and height.
        cfa: sample through an RGGB Bayer filter and demosaic; False samples luma directly.
        ambient: diffuse reflection of room light, share of white.
        glare: add a reflected luminaire.
        glare_peak: its peak, share of white.
        glare_size: its Gaussian radius, share of the screen height.
        room: luminance of the room around the monitor, share of white.
        bezel_cm: width of the black bezel.
        focal_rel: focal length relative to the frame long side (0.75: 26 mm equivalent).
        sensor_long_side: camera frame long side (px), 4032 for 12 MP.
        lens_sigma_px: Gaussian lens blur in camera pixels.
        motion_px: linear motion blur in camera pixels.
        supersample: samples per camera pixel and axis when integrating the display.
        max_fill: closest framing (page long side over frame); closer distances are clamped.
    """

    monitor: str | None = None
    monitors: tuple[str, ...] = ("fhd24", "qhd27", "uhd27", "laptop13")
    distance_cm: float | None = None
    distance_range: tuple[float, float] = (25.0, 60.0)
    page_height_frac: tuple[float, float] = (0.80, 0.92)
    dark_prob: float = 0.5
    gamma: tuple[float, float] = (2.0, 2.4)
    brightness_cd: tuple[float, float] = (100.0, 300.0)
    contrast: tuple[float, float] = (800.0, 3000.0)
    backlight_falloff: tuple[float, float] = (0.0, 0.2)
    falloff_deg_h: tuple[float, float] = (35.0, 50.0)
    falloff_deg_v: tuple[float, float] = (22.0, 45.0)
    subpixels: bool = True
    aperture_x: tuple[float, float] = (0.70, 0.90)
    aperture_y: tuple[float, float] = (0.75, 0.92)
    cfa: bool = True
    ambient: tuple[float, float] = (0.005, 0.04)
    glare: bool = False
    glare_peak: tuple[float, float] = (0.05, 0.5)
    glare_size: tuple[float, float] = (0.03, 0.15)
    room: tuple[float, float] = (0.01, 0.08)
    bezel_cm: tuple[float, float] = (0.5, 1.5)
    focal_rel: float = 0.75
    sensor_long_side: int = 4032
    lens_sigma_px: tuple[float, float] = (0.45, 0.9)
    motion_px: tuple[float, float] = (0.0, 2.5)
    supersample: int = 3
    max_fill: float = 0.95

    def __post_init__(self) -> None:
        unknown = [m for m in ((self.monitor,) if self.monitor else self.monitors) if m not in MONITORS]
        if unknown or not self.monitors:
            raise ValueError(f"monitor tidak dikenal: {', '.join(map(str, unknown))}; pilih dari {', '.join(MONITORS)}")
        if not 1 <= self.supersample <= 6:
            raise ValueError("supersample harus di antara 1 dan 6")
        if self.distance_cm is not None and self.distance_cm <= 0:
            raise ValueError("jarak kamera harus lebih dari 0 cm")


def subpixel_profiles(aperture_x: float, aperture_y: float, harmonics_x: int, harmonics_y: int,
                      samples: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Band-limited emission profiles over one pixel period (white balanced: mean 1).

    Returns (tx, ty): tx[c] (c = R, G, B) is the horizontal profile of stripe c, which is lit
    on a share ``aperture_x`` of its third of the pixel; ty the vertical profile (lit on
    ``aperture_y`` of the pitch, the black matrix at the pixel border). Both are Fourier
    series truncated after the given number of harmonics with Lanczos sigma factors, sampled
    at (i + 0.5) / samples of the period (coordinate 0 is the pixel's left or top edge).
    """
    t = (np.arange(samples) + 0.5) / samples
    tx = np.ones((3, samples))
    for c in range(3):
        w = aperture_x / 3.0
        centre = (c + 0.5) / 3.0
        for m in range(1, harmonics_x + 1):
            coef = np.sinc(m * w) * np.sinc(m / (harmonics_x + 1))  # / w: normalized to mean 1
            tx[c] += 2.0 * coef * np.cos(2 * np.pi * m * (t - centre))
    ty = np.ones(samples)
    for n in range(1, harmonics_y + 1):
        coef = np.sinc(n * aperture_y) * np.sinc(n / (harmonics_y + 1))
        ty += 2.0 * coef * np.cos(2 * np.pi * n * (t - 0.5))
    return tx.astype(np.float32), ty.astype(np.float32)


def _phase_index(frac: np.ndarray) -> np.ndarray:
    """Index 0..255 of the profile sample covering ``frac`` in [0, 1) (256 samples per period)."""
    return np.clip(frac * np.float32(256.0), 0, 255).astype(np.uint8)


def _lookup(table: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Values of a 256-sample profile at ``index`` (uint8), via an OpenCV look-up table."""
    return cv2.LUT(index, table.astype(np.float32).reshape(1, 256))


def view_angles(h_canvas_to_frame: np.ndarray, camera_matrix_frame: np.ndarray, shape: tuple[int, int],
                step: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Horizontal and vertical viewing angles (degrees) of every canvas pixel seen from the camera.

    ``camera_matrix_frame`` holds the pinhole intrinsics in camera frame pixels, so
    inv(K) @ H = [r1 r2 t] up to scale: the canvas axes and origin in camera coordinates.
    Angles are computed every ``step`` pixels and interpolated (they vary smoothly).
    """
    h, w = shape
    m = np.linalg.solve(np.asarray(camera_matrix_frame, dtype=np.float64), np.asarray(h_canvas_to_frame, dtype=np.float64))
    ys = np.arange(0, h + step, step, dtype=np.float64)
    xs = np.arange(0, w + step, step, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)
    pts = np.stack([gx, gy, np.ones_like(gx)], axis=-1) @ m.T  # camera coordinates (up to scale)
    if np.median(pts[..., 2]) < 0:
        pts, m = -pts, -m
    ex = m[:, 0] / np.linalg.norm(m[:, 0])
    ey = m[:, 1] / np.linalg.norm(m[:, 1])
    normal = np.cross(ex, ey)
    to_cam = -pts / np.linalg.norm(pts, axis=-1, keepdims=True)
    if np.median(to_cam @ normal) < 0:
        normal = -normal
    nz = to_cam @ normal
    ah = np.degrees(np.arctan2(to_cam @ ex, nz)).astype(np.float32)
    av = np.degrees(np.arctan2(to_cam @ ey, nz)).astype(np.float32)
    big = (w + step, h + step)
    ah = cv2.resize(ah, (big[0], big[1]), interpolation=cv2.INTER_LINEAR)[:h, :w]
    av = cv2.resize(av, (big[0], big[1]), interpolation=cv2.INTER_LINEAR)[:h, :w]
    return ah, av


def angular_falloff(angle_h: np.ndarray, angle_v: np.ndarray, deg75_h: float, deg75_v: float) -> np.ndarray:
    """Relative luminance seen at the given angles: exp(-ln(4/3) ((ah/h75)^2 + (av/v75)^2)),
    which is 75 % at h75 degrees horizontally (v75 vertically)."""
    k = np.float32(math.log(4.0 / 3.0))
    return np.exp(-k * ((angle_h / np.float32(deg75_h)) ** 2 + (angle_v / np.float32(deg75_v)) ** 2))


def render_display(canvas_lin: np.ndarray, reflect: np.ndarray, h_canvas_to_frame: np.ndarray,
                   frame_size: tuple[int, int], *, lens_sigma: float, motion_kernel: np.ndarray | None,
                   aperture: tuple[float, float], subpixels: bool, cfa: bool, room: float,
                   supersample: int = 3, strip: int = 48) -> np.ndarray:
    """The optical image a camera frame receives from a display (relative luminance, white 1).

    ``canvas_lin`` holds the linear luminance each screen pixel emits (gamma, backlight and
    angular falloff applied); every pixel emits only through its three subpixel stripes
    (``subpixel_profiles``), white balanced so that a white field gives 1 in every colour.
    ``reflect`` (smooth, canvas resolution) is light reflected by the front surface and is not
    masked. Outside the canvas the room has luminance ``room``. Each camera pixel integrates
    ``supersample`` x ``supersample`` samples after the lens blur (Gaussian ``lens_sigma``
    camera px), so the subpixel grid is sampled the way the sensor samples it and aliases
    where it should. The grid's harmonics are kept up to the supersampling limit at the most
    compressed part of the screen (beyond it the lens has removed them). The optional motion
    kernel (camera px, a few pixels next to the lens blur) is applied after sampling, which
    keeps the cost down and leaves slightly more aliasing in the motion direction.

    Returns (H, W) luma with ``cfa`` False, else (3, H, W) R, G, B before the colour filter.
    """
    cw, ch = frame_size
    s = int(supersample)
    hinv = np.linalg.inv(np.asarray(h_canvas_to_frame, dtype=np.float64))
    hc, wc = canvas_lin.shape

    # Smallest camera px per screen px over the visible screen: decides the harmonics.
    gx, gy = np.meshgrid(np.linspace(0, wc - 1, 9), np.linspace(0, hc - 1, 9))
    pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
    h = np.asarray(h_canvas_to_frame, dtype=np.float64)

    def fwd(p: np.ndarray) -> np.ndarray:
        q = np.hstack([p, np.ones((len(p), 1))]) @ h.T
        return q[:, :2] / q[:, 2:3]

    base = fwd(pts)
    jx = np.linalg.norm(fwd(pts + [1.0, 0.0]) - base, axis=1)
    jy = np.linalg.norm(fwd(pts + [0.0, 1.0]) - base, axis=1)
    inside = (base[:, 0] >= 0) & (base[:, 0] < cw) & (base[:, 1] >= 0) & (base[:, 1] < ch)
    if not inside.any():
        inside[:] = True
    r_min = float(min(jx[inside].min(), jy[inside].min()))

    # Below two supersamples per screen pixel the drive image is prefiltered (area average)
    # and read bilinearly; the grid itself cannot be represented there and is left out.
    src = canvas_lin
    to_src = np.eye(3)
    nearest = r_min * s >= 2.0
    if not nearest:
        f = max(r_min * s / 2.0, 1e-3)
        sw, sh = max(2, int(round(wc * f))), max(2, int(round(hc * f)))
        src = cv2.resize(canvas_lin, (sw, sh), interpolation=cv2.INTER_AREA)
        to_src = np.array([[sw / wc, 0.0, 0.5 * sw / wc - 0.5], [0.0, sh / hc, 0.5 * sh / hc - 0.5], [0, 0, 1.0]])
    harm = int(min(12, math.floor(r_min * s / 2.0 * 0.999))) if subpixels else 0
    tx, ty = subpixel_profiles(aperture[0], aperture[1], harm, harm)
    if not cfa:
        tx = (np.asarray(LUMA_WEIGHTS, dtype=np.float32)[:, None] * tx).sum(axis=0, keepdims=True)
    n_out = tx.shape[0]
    grid_on = subpixels and harm > 0

    margin = int(math.ceil(3.0 * lens_sigma + 2))
    out = np.empty((n_out, ch, cw), dtype=np.float32)
    hi = hinv.astype(np.float32)
    xs = ((np.arange(cw * s, dtype=np.float32) + np.float32(0.5)) / np.float32(s) - np.float32(0.5))[None, :]
    for y0 in range(0, ch, strip):
        y1 = min(ch, y0 + strip)
        ya, yb = max(0, y0 - margin), min(ch, y1 + margin)
        ys = ((np.arange(ya * s, yb * s, dtype=np.float32) + np.float32(0.5)) / np.float32(s) - np.float32(0.5))[:, None]
        den = hi[2, 0] * xs + hi[2, 1] * ys + hi[2, 2]
        X = (hi[0, 0] * xs + hi[0, 1] * ys + hi[0, 2]) / den
        Y = (hi[1, 0] * xs + hi[1, 1] * ys + hi[1, 2]) / den
        del den
        outside = (X <= -0.5) | (X >= wc - 0.5) | (Y <= -0.5) | (Y >= hc - 0.5)
        refl = cv2.remap(reflect, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if nearest:
            xr = np.floor(X + np.float32(0.5))
            yr = np.floor(Y + np.float32(0.5))
            # Pixel centres are whole numbers: INTER_NEAREST at the rounded centre reads that pixel.
            val = cv2.remap(src, xr, yr, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
            ix = _phase_index(X + np.float32(0.5) - xr) if grid_on else None
            iy = _phase_index(Y + np.float32(0.5) - yr) if grid_on else None
            del xr, yr
        else:
            val = cv2.remap(src, np.float32(to_src[0, 0]) * X + np.float32(to_src[0, 2]),
                            np.float32(to_src[1, 1]) * Y + np.float32(to_src[1, 2]), cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
            ix = iy = None
        del X, Y
        tyv = _lookup(ty, iy) if grid_on else None
        rows = yb - ya
        for c in range(n_out):
            lum = val * _lookup(tx[c], ix) * tyv if grid_on else val.copy()
            lum += refl
            lum[outside] = np.float32(room)
            if lens_sigma > 0:
                lum = cv2.GaussianBlur(lum, (0, 0), lens_sigma * s)
            small = cv2.resize(lum, (cw, rows), interpolation=cv2.INTER_AREA)  # s x s box average
            out[c, y0:y1] = small[y0 - ya:y1 - ya]
            del lum, small
        del val, refl, outside
    if motion_kernel is not None:  # applied after sampling (it is short next to the lens blur)
        for c in range(n_out):
            out[c] = cv2.filter2D(out[c], -1, motion_kernel)
    return out[0] if n_out == 1 else out


# OpenCV names Bayer patterns by the second row's first two pixels; this code turns an RGGB
# mosaic (R at even row and even column) into BGR. tests/test_ponsel.py checks the convention.
BAYER_RGGB_TO_BGR = cv2.COLOR_BayerBG2BGR_EA


def bayer_mosaic(rgb: np.ndarray) -> np.ndarray:
    """RGGB mosaic (H, W) of a (3, H, W) R, G, B image: R at even rows and columns, B at odd
    rows and columns, G elsewhere."""
    _, h, w = rgb.shape
    out = np.empty((h, w), dtype=np.float32)
    out[0::2, 0::2] = rgb[0, 0::2, 0::2]
    out[0::2, 1::2] = rgb[1, 0::2, 1::2]
    out[1::2, 0::2] = rgb[1, 1::2, 0::2]
    out[1::2, 1::2] = rgb[2, 1::2, 1::2]
    return out


def demosaic_luma(mosaic: np.ndarray) -> np.ndarray:
    """Edge-aware demosaicing of an RGGB mosaic (gray levels 0 to 255), then BT.601 luma."""
    m16 = np.clip(np.rint(np.asarray(mosaic, dtype=np.float32) * 256.0), 0, 65535).astype(np.uint16)
    bgr = cv2.demosaicing(m16, BAYER_RGGB_TO_BGR).astype(np.float32) / np.float32(256.0)
    r, g, b = LUMA_WEIGHTS
    return np.float32(b) * bgr[..., 0] + np.float32(g) * bgr[..., 1] + np.float32(r) * bgr[..., 2]
