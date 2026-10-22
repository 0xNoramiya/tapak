"""The photo benchmark reports photos of printed pages separately from screen photos."""

from __future__ import annotations

import json

import pytest

from tapak.benchmark import (
    MEDIA,
    MEDIUM_PHONE,
    MEDIUM_PRINT_1,
    MEDIUM_PRINT_2,
    MEDIUM_SCREEN,
    MEDIUM_SCREEN_PHOTO,
    check_issuance,
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


def test_phone_and_monitor_photos_have_their_own_totals():
    rows = [_row("photo", "benar"), _row("ponsel", "benar"), _row("ponsel", "tidak cukup bukti", 30.0),
            _row("fotolayar", "benar", 20.0), _row("cetak", "benar")]
    assert [medium(r) for r in rows] == [MEDIUM_SCREEN, MEDIUM_PHONE, MEDIUM_PHONE, MEDIUM_SCREEN_PHOTO,
                                         MEDIUM_PRINT_1]
    totals = summarize(rows)
    assert list(totals) == [MEDIUM_SCREEN, MEDIUM_PRINT_1, MEDIUM_PHONE, MEDIUM_SCREEN_PHOTO]
    assert totals[MEDIUM_SCREEN] == {"benar": 1}  # the plain photo is not mixed with the phone ISP set
    assert totals[MEDIUM_PHONE] == {"benar": 1, "tidak cukup bukti": 1}
    assert totals[MEDIUM_SCREEN_PHOTO] == {"benar": 1}
    assert [group_label(r) for r in rows[1:4]] == ["ponsel 10 derajat", "ponsel 30 derajat", "monitor 20 derajat"]
    assert len(set(MEDIA)) == len(MEDIA) == 5


def test_print_pairs_join_pages_of_the_same_print():
    def item(page: int, angle: float, index: int, copy_id: str = "a", kind: str = "cetak") -> dict:
        return {"file": f"{kind}_s001_p{page}_a{angle:g}_{index}.jpg", "kind": kind, "copy_id": copy_id,
                "page": page, "angle": angle}

    entries = [item(1, 10, 0), item(2, 10, 0), item(1, 30, 0), item(2, 30, 0), item(1, 10, 1),
               item(1, 10, 0, "b"), item(2, 10, 0, "c"), item(1, 10, 0, kind="photo"), item(2, 10, 0, kind="photo")]
    pairs = print_pairs(entries)
    assert [(a["file"], b["file"]) for a, b in pairs] == [
        ("cetak_s001_p1_a10_0.jpg", "cetak_s001_p2_a10_0.jpg"), ("cetak_s001_p1_a30_0.jpg", "cetak_s001_p2_a30_0.jpg")]


def test_photo_sets_from_another_issuance_are_refused(tmp_path):
    by_copy = {"aaaa": 1, "bbbb": 2}
    fresh = [{"file": "cetak_s001_p1_a10_0.jpg", "kind": "cetak", "copy_id": "aaaa", "seq": 1}]
    check_issuance(tmp_path, fresh, by_copy)  # every copy id known: nothing to say
    stale = fresh + [{"file": "cetak_s002_p1_a10_0.jpg", "kind": "cetak", "copy_id": "cccc", "seq": 2}]
    with pytest.raises(SystemExit, match=r"penerbitan lain \(1 dari 2 foto.*cetak_s002.*make photos-cetak"):
        check_issuance(tmp_path, stale, by_copy)
    screen = [{"file": "photo_s001_p1_a0_0.jpg", "kind": "photo", "copy_id": "dddd", "seq": 1}]
    with pytest.raises(SystemExit, match="jalankan ulang: make photos$"):
        check_issuance(tmp_path, screen, by_copy)
    for kind, target in (("ponsel", "make photos-ponsel"), ("fotolayar", "make photos-layar")):
        stale_set = [{"file": f"{kind}_s001_p1_a0_0.jpg", "kind": kind, "copy_id": "eeee", "seq": 1}]
        with pytest.raises(SystemExit, match=f"jalankan ulang: {target}$"):
            check_issuance(tmp_path, stale_set, by_copy)


def test_benchmark_stops_on_a_stale_printed_set(tmp_path, monkeypatch, capsys):
    """Printed photos left from an earlier issuance (out/ issued anew, samples/photos-cetak kept)
    stop the benchmark before any trace, instead of counting as "tidak cukup bukti"."""
    from tapak.benchmark import main
    from tapak.config import load_settings
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.service import ensure_keys, issue_document
    from tests_support import RECIPIENTS, SAMPLE

    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    s = load_settings()
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji",
                         ensure_keys(s, create_signing_key=False), record=False)
    layar, cetak = tmp_path / "layar", tmp_path / "cetak"
    layar.mkdir()
    cetak.mkdir()
    known = out.manifest.copies[0].copy_id
    (layar / "truth.json").write_text(json.dumps({"items": [
        {"file": "photo_s001_p1_a0_0.jpg", "kind": "photo", "copy_id": known, "seq": 1, "page": 1}]}))
    (cetak / "truth.json").write_text(json.dumps({"items": [
        {"file": "cetak_s001_p1_a10_0.jpg", "kind": "cetak", "copy_id": "06391e87968373f1", "seq": 1, "page": 1}]}))
    with pytest.raises(SystemExit, match=f"set foto {cetak} dibuat dari penerbitan lain"):
        main(["--photos", str(layar), "--cetak", str(cetak), "--data", str(tmp_path / "data"),
              "--keys", str(tmp_path / "keys"), "--ponsel", str(tmp_path / "none"), "--layar", str(tmp_path / "none")])
    assert "photo_s001" not in capsys.readouterr().out  # nothing was traced


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
          "--keys", str(tmp_path / "keys"), "--json", str(result), "--ponsel", str(tmp_path / "none"),
          "--layar", str(tmp_path / "none")])
    rows = json.loads(result.read_text(encoding="utf-8"))["rows"]
    assert [(r["medium"], r["pages"]) for r in rows] == [
        (MEDIUM_SCREEN, 1), (MEDIUM_PRINT_1, 1), (MEDIUM_PRINT_1, 1), (MEDIUM_PRINT_2, 2)]
    assert rows[-1]["file"] == "cetak_s002_p1_a10_0.jpg + cetak_s002_p2_a10_0.jpg"
    assert all(r["outcome"] in ("benar", "tidak cukup bukti") for r in rows)
    text = capsys.readouterr().out
    assert f"Total {MEDIUM_SCREEN}: benar " in text and f"Total {MEDIUM_PRINT_1}: " in text
    assert f"Total {MEDIUM_PRINT_2}: " in text
