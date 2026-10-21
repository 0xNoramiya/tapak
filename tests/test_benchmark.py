"""The photo benchmark reports photos of printed pages separately from screen photos."""

from __future__ import annotations

import json

import pytest

from tapak.benchmark import (
    MEDIUM_PRINT_1,
    MEDIUM_PRINT_2,
    MEDIUM_SCREEN,
    group_label,
    medium,
    print_pairs,
    summarize,
)


def _row(kind: str, outcome: str, angle: float | None = 10.0, pages: int = 1) -> dict:
    return {"kind": kind, "angle": angle, "pages": pages, "outcome": outcome}


def test_prints_are_never_counted_with_screen_photos():
    rows = [_row("photo", "benar"), _row("screenshot", "benar", None), _row("photo", "tidak cukup bukti", 30.0),
            _row("cetak", "tidak cukup bukti"), _row("cetak", "tidak cukup bukti", 30.0),
            _row("cetak", "benar", pages=2)]
    assert [medium(r) for r in rows] == [MEDIUM_SCREEN] * 3 + [MEDIUM_PRINT_1] * 2 + [MEDIUM_PRINT_2]
    totals = summarize(rows)
    assert list(totals) == [MEDIUM_SCREEN, MEDIUM_PRINT_1, MEDIUM_PRINT_2]
    assert totals[MEDIUM_SCREEN] == {"benar": 2, "tidak cukup bukti": 1}
    assert totals[MEDIUM_PRINT_1] == {"tidak cukup bukti": 2}
    assert totals[MEDIUM_PRINT_2] == {"benar": 1}
    assert summarize(rows[:3]).keys() == {MEDIUM_SCREEN}  # no print rows, no print totals
    labels = [group_label(r) for r in rows]
    assert labels[:3] == ["foto 10 derajat", "tangkapan layar", "foto 30 derajat"]
    assert labels[3:] == ["cetak 10 derajat", "cetak 30 derajat", "cetak 2 halaman"]
    # Old result files have no "pages" field: a print row there is a single page.
    assert medium({"kind": "cetak", "angle": 10.0, "outcome": "benar"}) == MEDIUM_PRINT_1


def test_print_pairs_join_pages_of_the_same_print():
    def item(page: int, angle: float, index: int, copy_id: str = "a", kind: str = "cetak") -> dict:
        return {"file": f"{kind}_s001_p{page}_a{angle:g}_{index}.jpg", "kind": kind, "copy_id": copy_id,
                "page": page, "angle": angle}

    entries = [item(1, 10, 0), item(2, 10, 0), item(1, 30, 0), item(2, 30, 0), item(1, 10, 1),
               item(1, 10, 0, "b"), item(2, 10, 0, "c"), item(1, 10, 0, kind="photo"), item(2, 10, 0, kind="photo")]
    pairs = print_pairs(entries)
    assert [(a["file"], b["file"]) for a, b in pairs] == [
        ("cetak_s001_p1_a10_0.jpg", "cetak_s001_p2_a10_0.jpg"), ("cetak_s001_p1_a30_0.jpg", "cetak_s001_p2_a30_0.jpg")]


@pytest.mark.slow
def test_benchmark_reports_printed_photos_separately(tmp_path, monkeypatch, capsys):
    from tapak.benchmark import main
    from tapak.config import load_settings
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.photos import PhotoParams, PrintParams, make_photo_set
    from tapak.service import ensure_keys, issue_document
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    s = load_settings()
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:4], IssueSettings(workers=1), "uji",
                         ensure_keys(s, create_signing_key=False), record=False)
    copies = out.folder / "salinan"
    photo = PhotoParams(sensor_long_side=2400)
    make_photo_set(copies, tmp_path / "layar", seqs=[2], per_copy=1, angles=(10,), screenshots=False,
                   photo_params=photo)
    make_photo_set(copies, tmp_path / "cetak", seqs=[2], per_copy=1, angles=(10,), screenshots=False,
                   all_pages=True, photo_params=photo, print_params=PrintParams(device_dpi=300, out_dpi=150))
    result = tmp_path / "bench.json"
    main(["--photos", str(tmp_path / "layar"), "--cetak", str(tmp_path / "cetak"), "--data", str(tmp_path / "data"),
          "--keys", str(tmp_path / "keys"), "--json", str(result)])
    rows = json.loads(result.read_text(encoding="utf-8"))["rows"]
    assert [(r["medium"], r["pages"]) for r in rows] == [
        (MEDIUM_SCREEN, 1), (MEDIUM_PRINT_1, 1), (MEDIUM_PRINT_1, 1), (MEDIUM_PRINT_2, 2)]
    assert rows[-1]["file"] == "cetak_s002_p1_a10_0.jpg + cetak_s002_p2_a10_0.jpg"
    assert all(r["outcome"] in ("benar", "tidak cukup bukti") for r in rows)
    text = capsys.readouterr().out
    assert f"Total {MEDIUM_SCREEN}: benar " in text and f"Total {MEDIUM_PRINT_1}: " in text
    assert f"Total {MEDIUM_PRINT_2}: " in text
