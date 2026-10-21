"""End-to-end test of the web UI over HTTP: issue (with semantic review), trace, report, registry."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("TAPAK_CANARY_DOMAIN", "kanari.tapak.test")
    from tapak.cli import main as cli_main
    from tapak.web.app import app

    assert cli_main(["keys", "init"]) == 0  # a deployment starts with `tapak keys init`
    return TestClient(app, base_url="http://127.0.0.1")


def _issue(client) -> str:
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files,
                    data={"c": "3", "eps": "1e-6", "penerbit": "Kasi Ops Fiktif", "kanari": "kanari.tapak.test"})
    assert r.status_code == 200 and "Rencana penandaan" in r.text
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    units = re.findall(r'name="unit" value="(u\d+)"', r.text)
    assert units
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    assert "menunggu tinjauan" in r.text
    assert re.search(r'type="submit"\s+disabled', r.text), "issue button must be disabled while variants pend"
    blocked = client.post(f"/terbitkan/{sid}/terbitkan")
    assert "diblokir" in blocked.text
    for unit, idx in re.findall(r"/varian/(u\d+)/(\d+)/disetujui", r.text):
        r = client.post(f"/terbitkan/{sid}/varian/{unit}/{idx}/disetujui")
    assert "Semua varian sudah ditinjau" in r.text
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text
    return re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)


def test_pages_render(client):
    for path in ("/terbitkan", "/lacak", "/registri"):
        r = client.get(path)
        assert r.status_code == 200 and "RAHASIA" in r.text and "TAPAK" in r.text
    assert client.get("/healthz").json() == {"status": "ok"}


def test_issue_validation_errors_inline(client):
    files = {"dokumen": ("x.pdf", b"not a pdf", "application/pdf")}
    # htmx request: only the error slots are updated out of band; the form (and chosen files) stay.
    r = client.post("/terbitkan/analisis", files=files, data={"c": "0", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert r.headers.get("HX-Reswap") == "none"
    assert 'id="err-dokumen" hx-swap-oob="innerHTML"' in r.text and "bukan PDF" in r.text
    assert "Pilih berkas CSV" in r.text and "antara 1 dan 10" in r.text
    assert "<form" not in r.text
    # Without htmx the whole form comes back with the messages next to the fields.
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    assert "<form" in r.text and "bukan PDF" in r.text


def test_issue_trace_report_registry(client):
    doc = _issue(client)
    z = client.get(f"/dokumen/{doc}/salinan.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    copy = client.get(f"/dokumen/{doc}/salinan/13")
    assert copy.status_code == 200 and copy.content.startswith(b"%PDF")
    assert client.get(f"/dokumen/{doc}/salinan/99").status_code == 404

    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", copy.content, "application/pdf")})
    assert r.status_code == 200
    assert "Salinan #13" in r.text and "Peluang tuduhan salah" in r.text
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    pdf = client.get(f"/lacak/{tid}/berita-acara.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    r = client.post("/lacak", data={"dokumen": doc, "teks": "Teks ini tidak berasal dari dokumen mana pun."})
    assert "Tidak cukup bukti" in r.text and "Nama tidak disebutkan" in r.text

    r = client.get("/registri")
    assert "Utuh" in r.text and "nota_dinas.pdf" in r.text
    r = client.post("/registri/merkle")
    assert "merkle-" in r.text


def test_errors_are_indonesian_notices_for_htmx(client):
    r = client.post("/terbitkan/0123456789abcdef/varian", headers={"HX-Request": "true"})
    assert r.status_code == 404 and r.headers.get("HX-Retarget") == "#galat-global"
    assert "Sesi penerbitan tidak ditemukan" in r.text and "notice-error" in r.text
    r = client.get("/dokumen/ZZZZ/salinan.zip", headers={"HX-Request": "true"})
    assert r.status_code == 404 and "tidak valid" in r.text


def test_reissue_detected_at_analysis_and_canary_rows_hide_names(client):
    doc = _issue(client)
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert "sudah pernah diterbitkan" in r.text and 'href="/lacak"' in r.text
    # A canary hit for copy 7: the registry page lists it by copy number, without the name.
    import os

    from tapak.canary_dns.store import record_event
    from tapak.config import load_settings
    from tapak.service import list_workspaces

    m = list_workspaces(load_settings())[0]
    token = m.copies[6].canary_token
    record_event(load_settings().canary_db, f"{token}.c.kanari.tapak.test", token, "A", "198.51.100.7", 5353)
    page = client.get("/registri").text
    assert "#7" in page and m.copies[6].recipient.nama not in page
    assert os.environ["TAPAK_DATA"]


def test_regenerating_variants_keeps_decisions(client):
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    units = re.findall(r'name="unit" value="(u\d+)"', r.text)
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    unit, idx = re.findall(r"/varian/(u\d+)/(\d+)/disetujui", r.text)[0]
    r = client.post(f"/terbitkan/{sid}/varian/{unit}/{idx}/ditolak")
    assert f'id="v-{unit}-{idx}-no"' in r.text and 'aria-pressed="true"' in r.text
    assert "hx-confirm" in r.text
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    assert re.search(rf'id="v-{unit}-{idx}-no"\s+aria-pressed="true"', r.text)
    assert client.post(f"/terbitkan/{sid}/varian/{unit}/99/disetujui").status_code == 400


def test_foreign_host_and_origin_refused(client):
    assert client.get("/terbitkan", headers={"host": "evil.example"}).status_code == 400
    r = client.post("/lacak", data={"dokumen": "", "teks": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_document_keys_cannot_escape_data_dir(client):
    for bad in ("..%2F..%2Fetc", "....", "ZZZZZZZZZZZZZZZZ", "%2e%2e"):
        r = client.get(f"/dokumen/{bad}/salinan.zip")
        assert r.status_code == 404
    r = client.post("/lacak", data={"dokumen": "../../../../etc/passwd", "teks": "abc"})
    assert "tidak valid" in r.text or "tidak dapat" in r.text


def test_lacak_requires_inputs(client):
    _issue(client)
    r = client.post("/lacak", data={"dokumen": ""})
    assert "Pilih dokumen" in r.text and "Unggah foto" in r.text
