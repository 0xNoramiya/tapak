"""Every public function and class in tapak.tardos and tapak.decoder is exercised by a test.

``test_every_public_name_is_tested`` enforces the rule mechanically: a public name defined
in those packages must be referenced in at least one test module. The other tests here cover
helpers that the larger end-to-end tests only use indirectly.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import numpy as np

TESTS = Path(__file__).resolve().parent


def _public_names() -> list[str]:
    names = []
    for pkg in ("tapak.tardos", "tapak.decoder"):
        root = importlib.import_module(pkg)
        for info in pkgutil.iter_modules(root.__path__):
            mod = importlib.import_module(f"{pkg}.{info.name}")
            for name, obj in vars(mod).items():
                if name.startswith("_") or not (inspect.isfunction(obj) or inspect.isclass(obj)):
                    continue
                if getattr(obj, "__module__", None) == mod.__name__:
                    names.append(f"{mod.__name__}.{name}")
    return names


def test_every_public_name_is_tested():
    text = " ".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))
    missing = [n for n in _public_names() if not re.search(r"\b" + re.escape(n.rsplit(".", 1)[1]) + r"\b", text)]
    assert not missing, missing


def test_result_dataclasses(ctx):
    from tapak.decoder.fuse import FusedEstimate, fuse
    from tapak.decoder.rectify import Registration
    from tapak.decoder.trace import TraceContext
    from tapak.tardos.accuse import AccusationOutcome, accuse
    from tapak.tardos.params import TardosParams
    from tapak.tardos.simulate import SimulationReport, StrategyResult, TableRow, parameter_table, run_simulation

    params = TardosParams(c=2, eps=1e-3, n_max=8)
    rep = run_simulation(params, 8, trials=3, strategies=["majority"], seed=1)
    assert isinstance(rep, SimulationReport) and isinstance(rep.results[0], StrategyResult)
    assert isinstance(parameter_table(ns=(20,), cs=(2,))[0], TableRow)
    p = np.full(params.length, 0.5)
    x = (np.arange(8 * params.length).reshape(8, -1) % 2).astype(np.uint8)
    assert isinstance(accuse(x, x[0], p, params.eps1), AccusationOutcome)
    assert isinstance(fuse([], 10), FusedEstimate)
    assert isinstance(ctx, TraceContext)
    assert "rectified" in Registration.__dataclass_fields__


def test_signed_measurements_signs_follow_bits(issued_v1, ctx_v1):
    from tapak.decoder.ch_shift import measure_vector, signed_measurements

    ctx = ctx_v1  # signed_measurements reads geser-v1 slots
    out, manifest = issued_v1
    disp = measure_vector((out / manifest.copies[2].file).read_bytes(), ctx.master)
    pos, vals, kinds = signed_measurements(ctx.master, ctx.plan, disp)
    assert set(kinds) == {"kata", "baris"}
    x = ctx.codewords[2]
    assert all((v > 0) == (x[q] == 1) for q, v in zip(pos, vals))


def test_match_offset_subpixel():
    import cv2

    from tapak.decoder.ch_shift import match_offset

    rng = np.random.default_rng(0)
    base = cv2.GaussianBlur((rng.random((60, 120)) * 255).astype(np.float32), (0, 0), 1.5)
    shifted = cv2.warpAffine(base, np.float32([[1, 0, 1.3], [0, 1, -0.6]]), (120, 60), flags=cv2.INTER_CUBIC)
    m = 5
    dx, dy, peak = match_offset(base[10:50, 10:110], shifted[10 - m:50 + m, 10 - m:110 + m], m)
    assert abs(dx - 1.3) < 0.1 and abs(dy + 0.6) < 0.1 and peak > 0.9


def test_semantic_matching_helpers():
    from tapak.decoder.ch_semantic import alignment_ops, densest_edits, locate, semiglobal_distance

    assert semiglobal_distance("hormat", "dengan hormat kami") == 0
    ops = alignment_ops("hormat", "dengan hxrmat kami")
    assert ops == "MSMMMM" and sum(o != "M" for o in ops) == semiglobal_distance("hormat", "dengan hxrmat kami")
    assert densest_edits("MSSMMDM", window=3) == 2
    score, window = locate(["demikian untuk dilaksanakan"], "xx demikian untuk dilaksanakan yy")
    assert score > 95 and "demikian" in window


def test_report_font_and_fetcher():
    from tapak.decoder.report import font_face_css, local_url_fetcher

    css = font_face_css()
    assert "@font-face" in css and "file://" in css and "TAPAK Sans" in css
    assert local_url_fetcher() is not None


def test_load_semantic_and_background_from_pdf(issued, ctx, tmp_path):
    from tapak.decoder.trace import collect_background_from_pdf, load_semantic

    assert load_semantic(None) is None and load_semantic(tmp_path) is None
    out, manifest = issued
    sb = collect_background_from_pdf((out / manifest.copies[7].file).read_bytes(), ctx)[0]
    x = ctx.codewords[7]
    assert len(sb) > 3000 and np.mean((sb.llr > 0) == (x[sb.positions] == 1)) > 0.99
