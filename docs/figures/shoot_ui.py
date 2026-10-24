"""Real screenshots of the TAPAK web UI for the README (docs/img/ui-*.png).

Terbitkan: a private server on a throwaway data folder issues samples/nota_dinas.pdf to
samples/recipients.csv through the Terbitkan page (mock LLM, every variant approved); the plan
step is shot. Lacak: a second server opens a copy of the workspace that ``fig_alur.py`` made
(run it first) and traces that figure's synthetic phone photo of copy 13, so the screenshot
and the flow figure show the same trace and the same numbers. Each view is shot once per color
scheme from the same page, so the light and dark images show the same result. The page
background is made transparent, so only the cards show on GitHub's white or dark canvas.

Codewords come from the code secret and a random per-copy id; both are fixed here (and in
``fig_alur.py``), so the scores repeat run to run and only the timestamps change. Playwright is
not a TAPAK dependency, so the browser steps run in a second interpreter that has it::

    TAPAK_PW_PYTHON=/path/to/venv-with-playwright/bin/python \\
    TAPAK_CHROME=/path/to/chrome-linux64/chrome \\
        .venv/bin/python docs/figures/shoot_ui.py [--base http://127.0.0.1:8779]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # the server shoots this checkout's tapak, not the installed one
IMG_DIR = ROOT / "docs" / "img"
PREVIEW_DIR = Path(os.environ.get("TAPAK_FIG_PREVIEW", ROOT / "out" / "figures"))
WORK = ROOT / "out" / "figures-work" / "ui"
ALUR_DEMO = ROOT / "out" / "figures-work" / "alur" / "demo"  # written by fig_alur.py
SAMPLES = ROOT / "samples"
ISSUER = "Kasi Ops Brigif 9905 (fiktif)"
SCHEMES = ("light", "dark")
# 760 CSS px: the compact shell (the sidebar starts at 1024 px) with stacked cards (.split
# splits at 880 px), so text and tables wrap and the image stays legible when a phone scales
# it to 390 px. Shot at 2x for retina.
VIEWPORT = {"width": 760, "height": 900}
PAD = 24  # CSS px of transparent margin kept around the cropped region
CANVAS = {"light": "#ffffff", "dark": "#0d1117"}  # GitHub's README backgrounds, for previews


# --- browser side (runs under TAPAK_PW_PYTHON; imports only Playwright) -------------------

def _shoot(page, first: str, last: str, stem: str, work: Path) -> None:
    """Shoot ``first`` through ``last`` in both color schemes; other cards are hidden meanwhile.

    Hiding (visibility, so nothing moves) keeps neighbouring cards and the Terbitkan stepper
    out of the padding. The page is scrolled to the top first: the banner and the top bar are
    sticky, and a full-page shot taken at a scroll offset draws them over the clip.
    """
    page.add_style_tag(content="html, body { background: transparent !important; }")
    box = page.evaluate(
        """([a, b]) => {
            const r1 = document.querySelector(a), r2 = document.querySelector(b);
            window.scrollTo(0, 0);
            document.querySelectorAll('main section, #stepper').forEach(s => {
                const inside = r1.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING
                    && r2.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_PRECEDING;
                if (s !== r1 && s !== r2 && !inside) s.style.visibility = 'hidden';
            });
            if (document.activeElement) document.activeElement.blur();
            const t = r1.getBoundingClientRect(), u = r2.getBoundingClientRect();
            return {x: t.left + scrollX, y: t.top + scrollY, w: t.width, bottom: u.bottom + scrollY};
        }""", [first, last])
    clip = {"x": box["x"] - PAD, "y": box["y"] - PAD,
            "width": box["w"] + 2 * PAD, "height": box["bottom"] - box["y"] + 2 * PAD}
    for scheme in SCHEMES:
        page.emulate_media(color_scheme=scheme)
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_timeout(400)  # let color transitions finish
        page.screenshot(path=str(work / f"raw-{stem}-{scheme}.png"), clip=clip, full_page=True,
                        omit_background=True)
    page.emulate_media(color_scheme="light")
    page.evaluate("document.querySelectorAll('main section, #stepper').forEach(s => s.style.visibility = '')")


def capture(step: str, base: str, chrome: str, work: Path, photo: str | None) -> None:
    import re

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2, color_scheme="light")
        if step == "terbitkan":
            page.goto(f"{base}/terbitkan")
            page.set_input_files("#dokumen", str(SAMPLES / "nota_dinas.pdf"))
            page.set_input_files("#penerima", str(SAMPLES / "recipients.csv"))
            page.fill("#penerbit", ISSUER)
            page.click("#form-terbit button[type=submit]")
            page.wait_for_selector("#langkah2", timeout=120_000)
            plan = "section:has(> #langkah2)"
            _shoot(page, plan, plan, "terbitkan", work)
            # Semantic variants from the mock LLM, each approved (the demo's simulated reviewer).
            page.click("#semantik form button[type=submit]")
            page.wait_for_selector("[id^='all-']", timeout=120_000)
            pending = page.locator("[id^='all-']:not([aria-disabled='true'])")
            while pending.count():
                with page.expect_response(lambda r: r.url.endswith("/semua")):
                    pending.first.click()
                page.wait_for_timeout(300)
            page.get_by_role("button", name=re.compile(r"Terbitkan \d+ salinan")).click()
            page.wait_for_selector("#hasil-terbit", timeout=300_000)
        else:
            page.goto(f"{base}/lacak")
            page.set_input_files("#bukti", photo)
            page.click("#form-lacak button[type=submit]")
            page.wait_for_selector("#putusan", timeout=300_000)
            page.wait_for_timeout(500)
            facts = page.evaluate(
                """() => ({
                    kicker: document.querySelector('.verdict .kicker').innerText,
                    verdict: [...document.querySelectorAll('.verdict h2')].map(e => e.innerText),
                    facts: [...document.querySelectorAll('.verdict .facts span')].map(e => e.innerText),
                    channels: [...document.querySelectorAll('#hasil section.card tbody')[0]
                                .querySelectorAll('tr')].map(r => r.innerText),
                    lead: document.querySelector('#kanal-h + p').innerText,
                })""")
            (work / "facts.json").write_text(json.dumps(facts, indent=2, ensure_ascii=True))
            _shoot(page, "#hasil section.verdict", "#hasil section.card", "lacak", work)
        browser.close()


# --- TAPAK side (runs under the TAPAK venv) -----------------------------------------------

def _env(root: Path) -> None:
    os.environ["TAPAK_DATA"] = str(root / "data")
    os.environ["TAPAK_KEY_DIR"] = str(root / "keys")


def serve(base: str, root: Path) -> None:
    """``tapak web`` on ``root`` with fixed copy ids, so every run issues the same codewords."""
    import itertools
    import types

    import uvicorn

    from tapak.marker import issue

    _env(root)
    n = itertools.count(1)
    issue.secrets = types.SimpleNamespace(
        token_hex=lambda k=8: hashlib.sha256(f"readme ui copy {next(n)}".encode()).hexdigest()[: 2 * k])
    url = urlsplit(base)
    uvicorn.run("tapak.web.app:app", host=url.hostname, port=url.port, log_level="warning")


def _wait_ready(base: str, server: subprocess.Popen, timeout: float = 60.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if server.poll() is not None:
            raise RuntimeError(f"server exited with code {server.returncode}")
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"{base} not ready after {timeout:.0f} s")


def finish(stem: str) -> None:
    """Save the raw shots into docs/img (alpha kept); previews go on GitHub's canvas."""
    from PIL import Image

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for scheme in SCHEMES:
        out = IMG_DIR / f"ui-{stem}-{scheme}.png"
        im = Image.open(WORK / f"raw-{stem}-{scheme}.png").convert("RGBA")
        im.save(out, optimize=True)  # lossless: a 256-color palette merges white with --accent-soft
        canvas = Image.new("RGBA", im.size, CANVAS[scheme])
        Image.alpha_composite(canvas, im).convert("RGB").save(PREVIEW_DIR / out.name, optimize=True)
        print(f"{out.relative_to(ROOT)}: {im.width}x{im.height} px, {out.stat().st_size // 1024} KB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=os.environ.get("TAPAK_UI_BASE", "http://127.0.0.1:8779"),
                    help="where to run the private server (host and port are taken from it)")
    ap.add_argument("--chrome", default=os.environ.get("TAPAK_CHROME"), help="Chromium executable")
    ap.add_argument("--pw-python", default=os.environ.get("TAPAK_PW_PYTHON"),
                    help="Python interpreter with Playwright installed")
    ap.add_argument("--serve", help=argparse.SUPPRESS)  # data root for the server process
    ap.add_argument("--capture", choices=("terbitkan", "lacak"), help=argparse.SUPPRESS)
    ap.add_argument("--photo", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.serve:
        serve(args.base, Path(args.serve))
        return
    if not args.chrome:
        ap.error("set --chrome or TAPAK_CHROME")
    if args.capture:
        capture(args.capture, args.base, args.chrome, WORK, args.photo)
        return
    if not args.pw_python:
        ap.error("set --pw-python or TAPAK_PW_PYTHON")
    if not (ALUR_DEMO / "foto_bocor.jpg").is_file():
        ap.error(f"{ALUR_DEMO} not found; run docs/figures/fig_alur.py first")

    shutil.rmtree(WORK, ignore_errors=True)
    issued = WORK / "terbitkan"
    (issued / "keys").mkdir(parents=True)
    secret = hashlib.sha256(b"tapak readme ui code secret").hexdigest()
    (issued / "keys" / "code_secret.key").write_text(secret + "\n", encoding="ascii")
    _env(issued)
    checkout = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH"))))}
    subprocess.run([sys.executable, "-m", "tapak.cli", "keys", "init"], check=True, stdout=subprocess.DEVNULL, env=checkout)
    traced = WORK / "lacak"  # a copy, so tracing leaves fig_alur's workspace untouched
    shutil.copytree(ALUR_DEMO, traced)

    shoot = [args.pw_python, __file__, "--base", args.base, "--chrome", args.chrome]
    steps = ((issued, ["--capture", "terbitkan"]),
             (traced, ["--capture", "lacak", "--photo", str(traced / "foto_bocor.jpg")]))
    for root, capture_args in steps:
        server = subprocess.Popen([sys.executable, __file__, "--serve", str(root), "--base", args.base],
                                  cwd=WORK)
        try:
            _wait_ready(args.base, server)
            subprocess.run([*shoot, *capture_args], check=True)
        finally:
            server.terminate()
            server.wait(timeout=20)
    for stem in ("terbitkan", "lacak"):
        finish(stem)
    print(json.dumps(json.loads((WORK / "facts.json").read_text()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
