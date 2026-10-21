"""End-to-end test of the web UI over HTTP: issue (with semantic review), trace, report, registry."""

from __future__ import annotations

import re
import sqlite3

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
    # The trace is logged in the registry before decoding and spends its share of eps.
    assert "pelacakan ke-1 atas dokumen ini" in r.text and "Ke-1, entri #" in r.text
    assert re.search(r"tapak verify --jangkar \d+:[0-9a-f]{64}", r.text)
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    pdf = client.get(f"/lacak/{tid}/berita-acara.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    r = client.post("/lacak", data={"dokumen": doc, "teks": "Teks ini tidak berasal dari dokumen mana pun."})
    assert "Tidak cukup bukti" in r.text and "Nama tidak disebutkan" in r.text
    assert "Ke-2, entri #" in r.text

    r = client.get("/registri")
    assert "Utuh" in r.text and "nota_dinas.pdf" in r.text
    assert "2 pelacakan" in r.text and "dilacak 2 kali" in r.text
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
    assert "sudah pernah diterbitkan" in r.text and f'href="/lacak?dokumen={doc}"' in r.text
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


def test_beranda_preview_and_preselect(client):
    """Home page, page-1 thumbnails, the Lacak preselect and the sidebar registry status."""
    r = client.get("/")
    assert r.status_code == 200 and "Beranda" in r.text and 'href="/terbitkan"' in r.text
    doc = _issue(client)
    r = client.get("/")
    assert "nota_dinas.pdf" in r.text and f"/dokumen/{doc}/pratinjau.png" in r.text
    png = client.get(f"/dokumen/{doc}/pratinjau.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert "no-store" in png.headers.get("cache-control", "")
    for bad in ("0123456789abcdef", "..%2F..%2Fetc", "ZZZZZZZZZZZZZZZZ"):
        assert client.get(f"/dokumen/{bad}/pratinjau.png").status_code == 404
    assert client.get("/terbitkan/0123456789abcdef/pratinjau.png").status_code == 404
    assert f'value="{doc}" selected' in client.get(f"/lacak?dokumen={doc}").text
    bad = client.get("/lacak?dokumen=../../etc")
    assert bad.status_code == 200 and "../../etc" not in bad.text
    status = client.get("/registri/status")
    assert status.status_code == 200 and "Utuh" in status.text


def test_publish_triggers_sidebar_refresh_and_staging_preview(client):
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    png = client.get(f"/terbitkan/{sid}/pratinjau.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and r.headers.get("HX-Trigger") == "registri-berubah"


def test_variant_diff_marks_only_changed_words():
    from tapak.web.app import templates

    beda = templates.env.filters["beda"]
    out = str(beda("Dengan hormat, bersama ini <kami>", "Dengan hormat, melalui surat ini <kami>"))
    assert '<mark class="diff">' in out and "&lt;kami&gt;" in out and "<kami>" not in out
    assert out.startswith("Dengan hormat,") and re.search(r'<mark class="diff">[^<]*melalui', out)


def test_download_names_security_headers_and_registry_without_key(client):
    """A non-Latin-1 document name still downloads as a ZIP; every response forbids framing;
    a registry whose public key is missing keeps its entry count; 404s name no server path."""
    from tapak.config import load_settings

    name = "nota \u2013 uji.pdf"
    files = {"dokumen": (name, SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    z = client.get(f"/dokumen/{doc}/salinan.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    disposition = z.headers["content-disposition"]
    assert "filename*=utf-8''nota%20%E2%80%93%20uji_salinan.zip" in disposition
    assert 'filename="nota uji_salinan.zip"' in disposition

    page = client.get("/")
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"

    s = load_settings()
    missing = client.get("/dokumen/0123456789abcdef/salinan.zip")
    assert missing.status_code == 404 and str(s.workspaces) not in missing.text

    s.public_key_path.rename(s.public_key_path.with_suffix(".bak"))
    status = client.get("/registri/status").text
    assert "Tanpa kunci" in status and re.search(r"\d+ entri", status) and "Belum ada" not in status


def _issue_small():
    from tapak.config import load_settings
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.service import issue_document

    s = load_settings()
    out = issue_document(s, SAMPLE, read_recipients(ROOT / "samples" / "recipients.csv")[:4],
                         IssueSettings(workers=1, canary_domain="kanari.tapak.test"), "uji")
    return s, out.manifest


def test_registri_page_with_unreadable_or_missing_public_key(client):
    """A malformed .pub is reported on /registri instead of a 500; a missing one is not shown
    as an empty registry and does not suggest creating a new signing key."""
    s, _ = _issue_small()
    good = s.public_key_path.read_text()
    s.public_key_path.write_text("zz-not-a-key\n")
    r = client.get("/registri")
    assert r.status_code == 200 and "Tak terbaca" in r.text and "zz-not-a-key" not in r.text
    s.public_key_path.unlink()
    r = client.get("/registri")
    assert r.status_code == 200 and "Rantai registri belum dapat diverifikasi" in r.text
    assert "Terbitkan dokumen pertama" not in r.text and "Jalankan" not in r.text
    s.public_key_path.write_text(good)
    assert "Rantai registri utuh" in client.get("/registri").text


def test_registri_checks_canary_log_and_lists_use_small_thumbnails(client):
    from tapak.canary_dns.store import record_event

    s, m = _issue_small()
    token = m.copies[1].canary_token
    for qtype in ("A", "AAAA"):  # one opening, two queries
        record_event(s.canary_db, f"{token}.c.kanari.tapak.test", token, qtype, "198.51.100.7", 5353)
    assert "Log utuh" in client.get("/registri").text
    home = client.get("/").text
    assert "dari 1 salinan" in home and "?ukuran=kecil" in home
    con = sqlite3.connect(s.canary_db)
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        con.execute(f"DROP TRIGGER {name}")
    con.execute("UPDATE canary_events SET src_ip = '10.0.0.9' WHERE seq = 1")
    con.commit()
    con.close()
    assert "Log rusak" in client.get("/registri").text
    doc = m.doc_hash[:16]
    small = client.get(f"/dokumen/{doc}/pratinjau.png?ukuran=kecil")
    full = client.get(f"/dokumen/{doc}/pratinjau.png")
    assert small.status_code == 200 and small.content.startswith(b"\x89PNG")
    assert len(small.content) < len(full.content) / 2
