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
    # The focused heading names the copy; the verdict stamp printed before it is its description,
    # and the bound is given a spoken form (a superscript exponent is not read as one).
    assert 'id="putusan-cap">Teridentifikasi' in r.text and 'aria-describedby="putusan-cap"' in r.text
    assert re.search(r'<b class="sr-only">paling besar [\d,]+ kali 10 pangkat minus \d+</b>', r.text)
    # The trace is logged in the registry before decoding and spends its share of eps.
    assert "pelacakan ke-1 atas dokumen ini" in r.text and "Ke-1, entri #" in r.text
    assert re.search(r"tapak verify --jangkar \d+:[0-9a-f]{64}", r.text)
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    pdf = client.get(f"/lacak/{tid}/berita-acara.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    r = client.post("/lacak", data={"dokumen": doc, "teks": "Teks ini tidak berasal dari dokumen mana pun."})
    assert "Tidak cukup bukti" in r.text and "Nama tidak disebutkan" in r.text
    assert "Ke-2, entri #" in r.text
    assert "tahap lanjutan hanya berjalan bila tahap 1 menuduh seseorang." in r.text and "tahap-tabel" not in r.text

    r = client.get("/registri")
    assert "Utuh" in r.text and "nota_dinas.pdf" in r.text
    assert "2 pelacakan" in r.text and "dilacak 2 kali" in r.text
    assert r.text.count("dilacak 2 kali") == 2  # also in the line shown when the columns fold away
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
    # generating removes the button that had focus: the review heading takes it instead
    assert 'id="tinjau-h" tabindex="-1" data-focus-fallback' in r.text
    unit, idx = re.findall(r"/varian/(u\d+)/(\d+)/disetujui", r.text)[0]
    r = client.post(f"/terbitkan/{sid}/varian/{unit}/{idx}/ditolak")
    assert f'id="v-{unit}-{idx}-no"' in r.text and 'aria-pressed="true"' in r.text
    assert "hx-confirm" in r.text
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    assert re.search(rf'id="v-{unit}-{idx}-no"\s+aria-pressed="true"', r.text)
    assert client.post(f"/terbitkan/{sid}/varian/{unit}/99/disetujui").status_code == 400


def test_model_variants_are_approved_one_by_one(client):
    from tapak.web.app import _STAGING

    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    units = re.findall(r'name="unit" value="(u\d+)"', r.text)
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    unit = re.findall(r"/varian/(u\d+)/(\d+)/disetujui", r.text)[0][0]
    assert f'id="all-{unit}"' in r.text  # curated phrase table: bulk approval offered
    for vs in _STAGING[sid].sets.values():
        vs.provider = "llamacpp"
    r = client.post(f"/terbitkan/{sid}/varian/{unit}/1/menunggu")  # re-render, nothing decided
    assert f'id="all-{unit}"' not in r.text and "ditinjau satu per satu" in r.text
    r = client.post(f"/terbitkan/{sid}/varian/{unit}/semua")
    assert r.status_code == 400 and "satu per satu" in r.text
    assert _STAGING[sid].sets[unit].pending()


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


def test_form_markup_for_assistive_technology(client):
    page = client.get("/terbitkan").text
    for name in ("dokumen", "penerima"):
        tag = re.search(rf'<input id="{name}"[^>]*>', page).group(0)
        # a required file input is reported invalid before anything is chosen (novalidate form;
        # the server reports a missing file next to the field)
        assert "required" not in tag
    # busy lines are read out through #status-global, not as live regions of their own
    assert 'role="status"' not in page and 'id="status-global" class="sr-only" aria-live="polite"' in page
    assert '<div class="banner" role="region" aria-label="Klasifikasi">RAHASIA</div>' in page


def test_oversized_master_is_a_field_error(client, monkeypatch):
    import importlib

    csv_bytes = (ROOT / "samples" / "recipients.csv").read_bytes()
    monkeypatch.setattr(importlib.import_module("tapak.web.app"), "MAX_UPLOAD", len(csv_bytes) + 100)
    files = {"dokumen": ("besar.pdf", b"%PDF-1.7\n" + b"x" * (len(csv_bytes) + 200), "application/pdf"),
             "penerima": ("recipients.csv", csv_bytes, "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and r.headers.get("HX-Reswap") == "none"
    assert re.search(r'id="err-dokumen" hx-swap-oob="innerHTML"><span class="field-error" role="alert">PDF ini terlalu besar', r.text)
    assert re.search(r'id="err-penerima" hx-swap-oob="innerHTML"></span>', r.text)


def test_evidence_errors_are_marked_on_their_field(client, monkeypatch):
    """An unknown file type or evidence over the limit is reported at the file field
    (berkas-err) of the re-rendered form; pasted text over 1 MB also marks the text field."""
    import importlib

    _issue_small()
    doc = re.search(r'<option value="([0-9a-f]{16})"', client.get("/lacak").text).group(1)
    page = client.get("/lacak").text
    assert 'aria-describedby="hint-bukti berkas-err bukti-err"' in page and 'aria-describedby="hint-teks teks-err bukti-err"' in page
    hx = {"HX-Request": "true"}
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("daftar.csv", b"a,b\n", "text/csv")}, headers=hx)
    assert r.headers.get("HX-Retarget") == "#form-lacak"
    assert '<span id="berkas-err"><span class="field-error" role="alert">daftar.csv: jenis berkas tidak dikenal' in r.text
    assert re.search(r'id="bukti"[^>]*aria-invalid="true"', r.text) and f'value="{doc}" selected' in r.text
    assert "dilacak" not in client.get("/registri").text  # refused before a trace number is used

    monkeypatch.setattr(importlib.import_module("tapak.web.app"), "MAX_UPLOAD", 1000)
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("foto.png", b"x" * 2000, "image/png")}, headers=hx)
    assert r.status_code == 200 and '<span id="berkas-err"><span class="field-error" role="alert">Bukti terlalu besar' in r.text

    r = client.post("/lacak", data={"dokumen": doc, "teks": "a" * 1_100_000}, headers=hx)
    assert r.status_code == 400 and r.headers["HX-Retarget"] == "#galat-global"
    assert '<span id="teks-err" hx-swap-oob="innerHTML"><span class="field-error">Teks yang ditempel terlalu panjang' in r.text


def test_false_accusation_bound_has_a_spoken_form():
    import math
    from types import SimpleNamespace

    from tapak.web.app import templates

    spoken, written = templates.env.globals["fap_lisan"], templates.env.globals["fap"]
    tiny = SimpleNamespace(false_accusation_probability=0.0, log10_false_accusation=-132.04)
    assert str(written(tiny, 20)) == "9,2 \u00d7 10<sup>\u2212133</sup>"
    assert spoken(tiny, 20) == "9,2 kali 10 pangkat minus 133"
    plain = SimpleNamespace(false_accusation_probability=0.35, log10_false_accusation=math.log10(0.35))
    assert spoken(plain, 20) == "0,35"


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


def _issue_small(n: int = 4):
    from tapak.config import load_settings
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.service import issue_document

    s = load_settings()
    out = issue_document(s, SAMPLE, read_recipients(ROOT / "samples" / "recipients.csv")[:n],
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


def test_visible_marks_caveat_is_split_from_the_notes():
    from tapak.decoder.accuse import VISIBLE_MARKS_NOTE
    from tapak.web.app import templates

    notes = ["catatan biasa", f"salinan #3: {VISIBLE_MARKS_NOTE}"]
    tpl = templates.env.from_string(
        "{% for n in peringatan_terlihat(notes) %}[P]{{ n }}{% endfor %}"
        "{% for n in notes if n not in peringatan_terlihat(notes) %}[C]{{ n }}{% endfor %}")
    out = tpl.render(notes=notes)
    assert out.startswith("[P]salinan #3: ") and out.endswith("[C]catatan biasa") and out.count("[P]") == 1
    src = (ROOT / "tapak" / "web" / "templates" / "_hasil_lacak.html").read_text(encoding="utf-8")
    assert src.index("peringatan_terlihat(a.notes)") < src.index('class="verdict-actions"')


# --- word choice (opt-in lexical channel) ----------------------------------------------------


def _analyse(client) -> tuple[str, str]:
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    assert r.status_code == 200
    return re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1), r.text


def _status(html: str) -> str:
    """Text of the live region update in a review response."""
    return re.search(r'<p id="semantik-status" hx-swap-oob="innerHTML">([^<]*)</p>', html).group(1)


def _publish_button(html: str) -> str:
    return re.search(r'<button class="btn btn-primary" type="submit"[^>]*>', html).group(0)


def _plain(html: str) -> str:
    """Response text with entities decoded and no-break spaces (number and unit) as spaces."""
    import html as html_lib

    return html_lib.unescape(html).replace("\u00a0", " ")


def test_word_choice_is_opt_in_and_scan_lists_points(client):
    from tapak.web.app import _STAGING

    sid, page = _analyse(client)
    # Off by default: an opt-in form with the plain policy sentence and the draft banner, no points.
    assert f'hx-post="/terbitkan/{sid}/leksikal"' in page and "Pindai titik pilihan kata" in page
    assert "DRAF, belum disahkan peninjau bahasa Tata Naskah Dinas" in page
    assert "dokumen induk tetap menjadi catatan resmi" in page and "berbeda kata" in page
    assert 'id="lx-l0-ok"' not in page and _STAGING[sid].lexical is None
    assert 'id="stat-ketik"' in page  # the plan tile for retype-surviving bits
    r = client.post(f"/terbitkan/{sid}/leksikal")
    assert r.status_code == 200
    sel = _STAGING[sid].lexical
    assert sel is not None and sel.points and not sel.carrying()
    rows = {re.search(r'id="lx-(l\d+)-ok"', li).group(1): li
            for li in re.findall(r'<li class="lex-point.*?</li>', r.text, re.S)}
    assert sorted(rows) == sorted(p.point_id for p in sel.points)
    # Every form a point may take is listed: in its rule's heading, or on the point when it
    # draws from fewer forms than the rule.
    headings = dict(re.findall(r'<h4 class="lex-rule-forms" id="lx-aturan-(l\d+)-h">([^<]*)</h4>', r.text))
    first_of_rule = {}
    for p in sel.points:
        first_of_rule.setdefault(p.rule_id, p.point_id)
    for p in sel.points:
        row = rows[p.point_id]
        assert re.search(rf'id="lx-{p.point_id}-ok"\s+aria-pressed="false"', row)
        assert f'<mark class="diff">{p.forms[0]}</mark>' in row  # the phrase, highlighted in its sentence
        listed = (headings[first_of_rule[p.rule_id]] + " / " + row).lower()
        assert all(f.lower().rstrip(",.;:") in listed for f in p.forms)
    # Only a rule with several points gets the bulk buttons; their names say which rule.
    for rule_id, first in first_of_rule.items():
        several = sum(q.rule_id == rule_id for q in sel.points) > 1
        assert (f'id="lx-aturan-{first}-ok"' in r.text) == several
        if several:
            forms = headings[first]
            assert f'aria-label="Semua titik \u201c{forms}\u201d"' in r.text
            assert f'titik \u201c{forms}\u201d sekaligus?' in r.text  # the confirmation quotes the forms
    assert 'class="lex-aside" role="group"' in r.text and "<aside" not in r.text  # no nested landmark
    assert 'id="lx-tinjau-h" tabindex="-1" data-autofocus' in r.text  # focus moves to the list
    text = _plain(r.text)
    assert "0 bit leksikal + 0 bit semantik" in text
    assert "belum mencapai 64 bit" in text and 'stamp-ok">Cukup untuk satu pembocor' not in r.text
    assert "peringatan tanda terlihat" in r.text  # a retyped-text name always carries the caveat
    assert _status(r.text).startswith(f"{len(sel.points)} dari {len(sel.points)} titik pilihan kata menunggu")
    assert _status(r.text).endswith("Belum cukup untuk satu pembocor.")  # the verdict is announced too
    assert "disabled" in _publish_button(r.text) and "setiap titik pilihan kata disetujui atau ditolak" in r.text
    assert 'id="stat-ketik" hx-swap-oob="true"' in r.text
    # Opting out again drops the scan and its decisions.
    r = client.post(f"/terbitkan/{sid}/leksikal/batal")
    assert _STAGING[sid].lexical is None and "Pindai titik pilihan kata" in r.text
    assert "disabled" not in _publish_button(r.text)


def test_word_choice_point_decisions_and_counter(client):
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    first, second = sel.points[0].point_id, sel.points[1].point_id
    r = client.post(f"/terbitkan/{sid}/leksikal/{first}/disetujui")
    assert r.status_code == 200
    assert re.search(rf'id="lx-{first}-ok"\s+aria-pressed="true"', r.text)
    assert re.search(rf'id="lx-{first}-no"\s+aria-pressed="false"', r.text)
    bits = sel.points[0].bits
    assert f"{bits} bit leksikal + 0 bit semantik" in r.text and f"{bits} bit leksikal + 0 bit semantik." in _status(r.text)
    assert "Contoh dua salinan" in r.text and "lex-sample-row" in r.text  # two sample copies of the approved rows
    r = client.post(f"/terbitkan/{sid}/leksikal/{second}/ditolak")
    assert re.search(rf'id="lx-{second}-no"\s+aria-pressed="true"', r.text)
    assert sel.point(second).status == "ditolak"
    assert client.post(f"/terbitkan/{sid}/leksikal/{first}/keliru").status_code == 400
    assert client.post(f"/terbitkan/{sid}/leksikal/l999/disetujui").status_code == 400


def test_word_choice_bulk_approval_needs_confirmation(client):
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    r = client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    rule = max({p.rule_id for p in sel.points}, key=lambda rid: sum(p.rule_id == rid for p in sel.points))
    of_rule = [p for p in sel.points if p.rule_id == rule]
    first = of_rule[0].point_id  # a rule is named by its first point: URLs carry no document phrase
    button = re.search(rf'<button[^>]*id="lx-aturan-{first}-ok"[^>]*>', r.text, re.S).group(0)
    assert "hx-confirm=" in button and "konfirmasi" in button
    assert f'hx-post="/terbitkan/{sid}/leksikal/aturan/{first}/disetujui"' in button
    reject = re.search(rf'<button[^>]*id="lx-aturan-{first}-no"[^>]*>', r.text, re.S).group(0)
    assert "hx-confirm" not in reject
    assert not re.search(r'hx-post="[^"]*/leksikal/aturan/(?!l\d+/)', r.text)
    # Without the confirmation the server refuses and nothing changes.
    r = client.post(f"/terbitkan/{sid}/leksikal/aturan/{first}/disetujui")
    assert r.status_code == 400 and "konfirmasi" in r.text
    assert all(p.status == "menunggu" for p in of_rule)
    # A point rejected first stays rejected: bulk approval takes only the pending points.
    client.post(f"/terbitkan/{sid}/leksikal/{first}/ditolak")
    r = client.post(f"/terbitkan/{sid}/leksikal/aturan/{of_rule[-1].point_id}/disetujui", data={"konfirmasi": "ya"})
    assert r.status_code == 200
    assert of_rule[0].status == "ditolak" and all(p.status == "disetujui" for p in of_rule[1:])
    assert all(p.status == "menunggu" for p in sel.points if p.rule_id != rule)
    # Rejecting a whole rule needs no confirmation.
    r = client.post(f"/terbitkan/{sid}/leksikal/aturan/{first}/ditolak")
    assert r.status_code == 200 and all(p.status == "ditolak" for p in of_rule)
    assert client.post(f"/terbitkan/{sid}/leksikal/aturan/l999/ditolak").status_code == 400
    assert client.post(f"/terbitkan/{sid}/leksikal/aturan/{first}/menunggu").status_code == 400


def test_word_choice_refusals_name_categories_only(client):
    from tapak.marker import lexical as lx
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    r = client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    assert sel.refused
    assert f'<summary>{sum(sel.refused.values())} frasa ditolak pemeriksaan otomatis</summary>' in r.text
    block = re.search(r'<ul class="lex-refused"[^>]*>(.*?)</ul>', r.text, re.S).group(1)
    categories = {getattr(lx, n) for n in dir(lx) if n.startswith("REFUSE_")}
    # the count is read as "<category>: <n> frasa", never as part of the category
    items = re.findall(r'<li><span>([^<]*)</span><span class="sr-only">: </span>'
                       r'<b class="tnum">(\d+)<span class="sr-only"> frasa</span></b></li>', block)
    assert len(items) == len(sel.refused) and re.sub(r"<li>.*?</li>", "", block).strip() == ""
    for label, n in items:
        category = label[:1].lower() + label[1:]
        assert label[:1].isupper() and category in categories and sel.refused[category] == int(n)


def test_sample_copy_rows_mark_point_words():
    from tapak.web.app import _sample_line

    a = [("Rapat", (0, 4, 0)), ("pada", None), ("saat", None), ("<b>", (0, 4, 3)), ("dan", None)]
    b = [("Rapat", (0, 4, 0)), ("ketika", None), ("<b>", (0, 4, 2)), ("dan", None)]
    differs = '<span class="sr-only"> (berbeda)</span>'  # not told by colour alone
    assert str(_sample_line(a, b)) == f'Rapat <mark class="diff">pada saat{differs}</mark> &lt;b&gt; <mark class="lex-same">dan</mark>'
    assert str(_sample_line(b, a)) == f'Rapat <mark class="diff">ketika{differs}</mark> &lt;b&gt; <mark class="lex-same">dan</mark>'


def test_word_choice_blocks_publishing_while_pending(client):
    from tapak.config import load_settings
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    r = client.post(f"/terbitkan/{sid}/leksikal/{sel.points[0].point_id}/disetujui")
    assert "disabled" in _publish_button(r.text)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert "diblokir" in r.text and "titik pilihan kata masih menunggu" in r.text
    assert "tapak leksikal" not in r.text  # no CLI hint in the web
    # pending points by the number the list shows ("Titik 2"), not by internal id
    assert f"(titik {', '.join(str(i + 1) for i in range(1, min(len(sel.points), 11)))}" in r.text
    assert not re.search(r"\bl\d+\b", re.search(r'id="semantik-galat"[^>]*>([^<]*)', r.text).group(1))
    assert r.headers.get("HX-Retarget") == "#semantik"
    assert not list(load_settings().workspaces.glob("*/manifest.json"))


def test_word_choice_publish_stores_selection_and_lacak_names_the_channel(client):
    import json

    from tapak.config import load_settings
    from tapak.marker.issue import IssueManifest
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    for p in sel.points:
        r = client.post(f"/terbitkan/{sid}/leksikal/{p.point_id}/disetujui")
    assert "Semua titik pilihan kata sudah ditinjau." in _status(r.text)
    assert "disabled" not in _publish_button(r.text)
    bits = sel.bits
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text
    assert f"{bits} bit leksikal + 0 bit semantik" in _plain(r.text) and "belum mencapai 64 bit" in _plain(r.text)
    assert 'stamp-warn">Belum cukup' in r.text and "pita bias" not in r.text
    assert r.text.index('class="issued-actions"') < r.text.index('class="issued-retype"')  # actions first
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    folder = load_settings().workspaces / doc
    stored = json.loads((folder / "leksikal.json").read_text(encoding="utf-8"))
    assert stored["format"] == "tapak-leksikal-1" and all(p["status"] == "disetujui" for p in stored["points"])
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.plan_summary["lexical"]["bits"] == bits and manifest.lexical_digest == sel.digest
    assert manifest.retype_positions
    # Lacak labels the channel: physical "Leksikal" in the evidence table, "Pilihan kata" per sub-channel.
    copy = client.get(f"/dokumen/{doc}/salinan/5")
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", copy.content, "application/pdf")})
    assert r.status_code == 200 and "Salinan #5" in r.text
    assert "<td>Leksikal</td>" in r.text and "<td>Pilihan kata</td>" in r.text


def test_word_choice_with_every_point_rejected_issues_without_the_channel(client):
    from tapak.config import load_settings
    from tapak.marker.issue import IssueManifest
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    client.post(f"/terbitkan/{sid}/leksikal")
    for point_id in {p.rule_id: p.point_id for p in _STAGING[sid].lexical.points}.values():
        r = client.post(f"/terbitkan/{sid}/leksikal/aturan/{point_id}/ditolak")
    assert "salinan diterbitkan tanpa kanal pilihan kata" in r.text
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    folder = load_settings().workspaces / doc
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.lexical_digest is None and not (folder / "leksikal.json").exists()
    assert "bit leksikal" not in r.text


def test_word_choice_decisions_are_frozen_while_issuing(client, monkeypatch):
    """A decision sent while the copies are issued is refused, and issuance uses the decisions
    as they were when it started: copies, manifest and leksikal.json always agree."""
    import json

    import tapak.service as service
    from tapak.config import load_settings
    from tapak.marker.issue import IssueManifest
    from tapak.web.app import _STAGING

    sid, page = _analyse(client)
    units = re.findall(r'name="unit" value="(u\d+)"', page)
    client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    st = _STAGING[sid]
    for unit, vs in st.sets.items():
        for i in vs.pending():
            client.post(f"/terbitkan/{sid}/varian/{unit}/{i}/disetujui")
    client.post(f"/terbitkan/{sid}/leksikal")
    for p in st.lexical.points:
        client.post(f"/terbitkan/{sid}/leksikal/{p.point_id}/disetujui")
    approved = st.lexical.digest
    first = st.lexical.points[0].point_id
    unit = next(iter(st.sets))
    real = service.issue_document
    seen = {}

    def racing(*args, **kwargs):
        seen["point"] = client.post(f"/terbitkan/{sid}/leksikal/{first}/ditolak")
        seen["rule"] = client.post(f"/terbitkan/{sid}/leksikal/aturan/{first}/ditolak").status_code
        seen["optout"] = client.post(f"/terbitkan/{sid}/leksikal/batal").status_code
        seen["variant"] = client.post(f"/terbitkan/{sid}/varian/{unit}/1/ditolak").status_code
        seen["publish"] = client.post(f"/terbitkan/{sid}/terbitkan").status_code
        # even a change that got past the guard does not reach this issuance
        st.lexical.set_status(first, "ditolak")
        st.sets[unit].set_status(1, "ditolak")
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "issue_document", racing)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text
    assert seen.pop("point").status_code == 409
    assert seen == {"rule": 409, "optout": 409, "variant": 409, "publish": 409}
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    folder = load_settings().workspaces / doc
    stored = json.loads((folder / "leksikal.json").read_text(encoding="utf-8"))
    assert all(p["status"] == "disetujui" for p in stored["points"])
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.lexical_digest == approved
    assert len(manifest.shift_excluded_rows) == len({(p["page"], p["row"]) for p in stored["points"]})
    variants = json.loads((folder / "varian.json").read_text(encoding="utf-8"))
    assert all(x == "disetujui" for v in variants["sets"] for x in v["status"][1:])


def test_publish_controls_disable_every_review_button(client):
    sid, _ = _analyse(client)
    r = client.post(f"/terbitkan/{sid}/leksikal")
    form = re.search(r'<form class="publish-form"[^>]*>', r.text).group(0)
    assert 'hx-disabled-elt="#semantik button"' in form
    assert '<h2 id="langkah4" tabindex="-1">' in r.text and 'href="#langkah4"' in r.text  # a way past the list


def test_review_actions_keep_the_session_alive(client):
    import os
    import time

    from tapak.web import app as webapp

    sid, _ = _analyse(client)
    st = webapp._STAGING[sid]
    long_ago = time.time() - webapp.STAGING_TTL_S - 60  # uploaded more than the idle limit ago
    os.utime(st.folder, (long_ago, long_ago))
    st.last_used = long_ago
    assert client.post(f"/terbitkan/{sid}/leksikal").status_code == 200
    webapp._expire_staging()  # what the next analysis by anyone runs
    assert sid in webapp._STAGING and st.folder.exists()
    st.last_used = long_ago  # idle for real: dropped
    webapp._expire_staging()
    assert sid not in webapp._STAGING and not st.folder.exists()


def test_word_choice_without_points_shows_only_the_outcome(client, monkeypatch):
    from tapak.marker import lexical as lx
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    real = lx.scan_candidates

    def nothing(master, lexicon=None, *args, **kwargs):
        sel = real(master, lexicon, *args, **kwargs)
        sel.points = []
        sel.refused = {lx.REFUSE_FIT: 3, lx.REFUSE_ORDER: 2}
        return sel

    monkeypatch.setattr(lx, "scan_candidates", nothing)
    r = client.post(f"/terbitkan/{sid}/leksikal")
    assert r.status_code == 200 and _STAGING[sid].lexical.points == []
    assert "Salinan diterbitkan tanpa kanal pilihan kata." in r.text
    assert _status(r.text) == "Tidak ada titik pilihan kata di dokumen ini. Salinan diterbitkan tanpa kanal pilihan kata."
    for absent in ('class="lex-counter"', 'class="meter', "lx-tinjau-h", "lx-batal", "Belum cukup", "peringatan tanda terlihat"):
        assert absent not in r.text, absent
    assert "<summary>5 frasa ditolak pemeriksaan otomatis</summary>" in r.text
    assert 'id="langkah-lx" tabindex="-1" data-autofocus' in r.text
    assert "disabled" not in _publish_button(r.text)


def test_variant_status_mentions_word_choice_still_pending(client):
    from tapak.web.app import _STAGING

    sid, page = _analyse(client)
    units = re.findall(r'name="unit" value="(u\d+)"', page)
    client.post(f"/terbitkan/{sid}/leksikal")
    n = len(_STAGING[sid].lexical.points)
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    for unit, idx in re.findall(r"/varian/(u\d+)/(\d+)/disetujui", r.text):
        r = client.post(f"/terbitkan/{sid}/varian/{unit}/{idx}/disetujui")
    assert _status(r.text) == f"Semua varian sudah ditinjau. {n} titik pilihan kata masih menunggu."


def test_word_choice_sample_shows_the_most_different_pair_first(client):
    from tapak.web.app import _STAGING

    sid, _ = _analyse(client)
    client.post(f"/terbitkan/{sid}/leksikal")
    sel = _STAGING[sid].lexical
    for p in sel.points:
        r = client.post(f"/terbitkan/{sid}/leksikal/{p.point_id}/disetujui")
    pv = _STAGING[sid].lex_preview[1]
    assert pv["differ"] > 0 and pv["differing"]
    sample = r.text[r.text.index('id="lx-contoh-h"'):]
    assert f"berbeda pada {pv['differ']} dari {len(sel.points)} titik" in sample
    if pv["same"]:  # rows alike in both copies come last, folded
        assert sample.index("Baris yang berbeda") < sample.index(f"<summary>{len(pv['same'])} baris sama di kedua contoh</summary>")
    again = client.post(f"/terbitkan/{sid}/leksikal/{sel.points[0].point_id}/disetujui")
    assert again.text[again.text.index('id="lx-contoh-h"'):] == sample  # stable between clicks


# --- background profile (layar by default, cetak opt-in) and the progress header -------------


def _files() -> dict:
    return {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
            "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}


def _radio(html: str, value: str) -> str:
    return re.search(rf'<input type="radio" name="latar" value="{value}"[^>]*>', html).group(0)


def _choice(html: str, value: str) -> str:
    """The whole option card (label) of one background profile."""
    return re.search(rf'<label class="choice">\s*<input type="radio" name="latar" value="{value}".*?</label>',
                     html, re.S).group(0)


def test_background_profile_defaults_to_layar(client):
    from tapak.config import load_settings
    from tapak.marker.background import PRINT_BACKGROUND_WARNING, SCREEN_BACKGROUND, profile_name
    from tapak.marker.issue import IssueManifest

    page = client.get("/terbitkan").text
    assert "<legend" in page and ">Pola latar</legend>" in page
    assert " checked" in _radio(page, "layar") and " checked" not in _radio(page, "cetak")
    layar, cetak = _plain(_choice(page, "layar")), _plain(_choice(page, "cetak"))
    assert "Layar" in layar and "(bawaan)" in layar and "Tidak terlihat, tetapi hilang bila salinan dicetak." in layar
    assert "Bertahan di kertas dalam uji printer simulasi, tetapi halaman tampak abu-abu muda." in cetak
    # the print profile is never called invisible
    invisible = re.compile(r"\b(tidak|tak) terlihat", re.I)
    assert not invisible.search(cetak) and not invisible.search(PRINT_BACKGROUND_WARNING)
    # and the page says "not visible" only of the default profile (not in its header, say)
    assert [m.group(0) for m in invisible.finditer(_plain(page))] == ["Tidak terlihat"]
    # The warning is plain markup (shown by CSS while "Cetak" is checked) and describes that option.
    assert f'id="latar-peringatan">{PRINT_BACKGROUND_WARNING}</p>' in page
    assert 'aria-describedby="latar-cetak-ket latar-peringatan err-latar"' in _radio(page, "cetak")
    assert 'aria-describedby="latar-layar-ket err-latar"' in _radio(page, "layar")

    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6"})  # no choice sent
    assert r.status_code == 200 and 'class="ch-profil">profil layar</span>' in r.text
    assert PRINT_BACKGROUND_WARNING not in r.text and "uji printer simulasi" not in r.text
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text and "notice-warn" not in r.text
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    manifest = IssueManifest.from_json((load_settings().workspaces / doc / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.background_settings == SCREEN_BACKGROUND and profile_name(manifest.background_settings) == "layar"


def test_print_profile_warns_in_form_plan_and_result(client):
    from tapak.config import load_settings
    from tapak.marker.background import PRINT_BACKGROUND, PRINT_BACKGROUND_WARNING, profile_name
    from tapak.marker.issue import IssueManifest

    # A step-1 error re-renders the form (no htmx) with the choice kept and its warning shown.
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "0", "eps": "1e-6", "latar": "cetak"})
    assert "<form" in r.text and "antara 1 dan 10" in r.text
    assert " checked" in _radio(r.text, "cetak") and " checked" not in _radio(r.text, "layar")
    assert f'id="latar-peringatan">{PRINT_BACKGROUND_WARNING}</p>' in r.text

    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6", "latar": "cetak"})
    assert r.status_code == 200 and "Rencana penandaan" in r.text
    # The plan names the profile at the background channel, with the warning in the row below it.
    row = re.search(r'<tr class="has-note">.*?</tr>\s*<tr class="ch-peringatan">.*?</tr>', r.text, re.S).group(0)
    assert 'class="ch-profil">profil cetak</span>' in row and PRINT_BACKGROUND_WARNING in row
    assert "Pola latar" in row and "Bertahan: cetak dalam uji printer simulasi, layar" in row
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text
    # The outcome's warnings are listed before the downloads.
    assert f'<p class="notice notice-warn" role="alert">{PRINT_BACKGROUND_WARNING}</p>' in r.text
    assert r.text.index(PRINT_BACKGROUND_WARNING) < r.text.index('class="issued-actions"')
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    manifest = IssueManifest.from_json((load_settings().workspaces / doc / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.background_settings == PRINT_BACKGROUND and profile_name(manifest.background_settings) == "cetak"


def test_unknown_background_profile_is_a_field_error(client):
    from tapak.web.app import _STAGING

    before = set(_STAGING)
    hx = {"HX-Request": "true"}
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6", "latar": "kertas"}, headers=hx)
    assert r.status_code == 200 and r.headers.get("HX-Reswap") == "none" and "<form" not in r.text
    assert ('id="err-latar" hx-swap-oob="innerHTML"><span class="field-error" role="alert">'
            "Profil latar tidak dikenal: 'kertas'; pilih 'layar' atau 'cetak'.</span>") in _plain(r.text)
    assert re.search(r'id="err-dokumen" hx-swap-oob="innerHTML"></span>', r.text)
    # Without htmx the form comes back: the message next to the group, neither option checked.
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6", "latar": "x" * 5000})
    assert "<form" in r.text and "Profil latar tidak dikenal" in r.text and "x" * 33 not in r.text
    for value in ("layar", "cetak"):
        assert " checked" not in _radio(r.text, value) and 'aria-invalid="true"' in _radio(r.text, value)
    assert set(_STAGING) == before  # nothing staged


def test_shift_scheme_choice_defaults_to_v2(client):
    from tapak.config import load_settings
    from tapak.marker.issue import IssueManifest

    def radio(html: str, value: str) -> str:
        return re.search(rf'<input type="radio" name="geser" value="{value}"[^>]*>', html).group(0)

    page = client.get("/terbitkan").text
    assert ">Skema geser kata</legend>" in page
    assert " checked" in radio(page, "v2") and " checked" not in radio(page, "v1")
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6"})  # no choice sent
    assert r.status_code == 200 and 'class="ch-profil">skema v2</span>' in r.text
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6", "geser": "v1"})
    assert r.status_code == 200 and 'class="ch-profil">skema v1</span>' in r.text
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "20 salinan siap dibagikan" in r.text
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    manifest = IssueManifest.from_json((load_settings().workspaces / doc / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.shift_scheme is None and manifest.shift_settings.scheme == "geser-v1"
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6", "geser": "v9"})
    assert "<form" in r.text and "Pilih skema geser v1 atau v2." in r.text
    assert " checked" not in radio(r.text, "v1") and " checked" not in radio(r.text, "v2")


def test_stepper_step_three_covers_both_text_reviews(client):
    from tapak.web.app import ISSUE_STEPS, _STAGING

    assert ISSUE_STEPS == ("Dokumen", "Rencana", "Tinjau teks", "Terbitkan")
    templates_dir = ROOT / "tapak" / "web" / "templates"
    for name in ("_langkah1.html", "_rencana.html", "_semantik.html", "_hasil_terbit.html"):
        src = (templates_dir / name).read_text(encoding="utf-8")
        assert "{% for label in langkah_terbit %}" in src and '"Kalimat aman"' not in src
    labels = lambda html: re.findall(r'<span class="stepper-label">([^<]*)', html)  # noqa: E731
    assert labels(client.get("/terbitkan").text) == list(ISSUE_STEPS)
    sid, page = _analyse(client)
    current = '<li class="stepper-item" aria-current="step"><span class="stepper-num">3</span> <span class="stepper-label">Tinjau teks</span>'
    assert current in page
    # Only word-choice points pending (no sentence variants generated): step 3 is still the current one.
    r = client.post(f"/terbitkan/{sid}/leksikal")
    assert _STAGING[sid].lexical.pending() and not _STAGING[sid].sets
    stepper = re.search(r'<ol class="stepper alur-stepper" id="stepper"[^>]*hx-swap-oob="true">.*?</ol>', r.text, re.S).group(0)
    assert current in stepper and labels(stepper) == list(ISSUE_STEPS)


# --- scanned masters (halaman pindaian) ------------------------------------------------------


def _one_page(pdf: bytes, page: int = 0) -> bytes:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        doc.select([page])
        return doc.tobytes()


@pytest.fixture(scope="module")
def scans() -> dict[str, bytes]:
    """Fictional scans of the sample (samplegen.scanned_sample), small to stay fast: page 1 alone
    at 200 dpi (the lowest resolution accepted) with an invisible OCR layer, the two-page sample
    with only page 2 scanned, and page 1 at 150 dpi (refused)."""
    from tapak.samplegen import scanned_sample

    sample = SAMPLE.read_bytes()
    page1 = _one_page(sample)
    return {"pindaian": scanned_sample(page1, dpi=200, ocr_layer=True),
            "campuran": scanned_sample(sample, dpi=200, scan_pages={1}),
            "rendah": scanned_sample(page1, dpi=150)}


def _scan_files(pdf: bytes, name: str, n: int = 4) -> dict:
    """A scanned master and the first ``n`` recipients of the sample list."""
    rows = (ROOT / "samples" / "recipients.csv").read_text(encoding="utf-8").splitlines()[: n + 1]
    return {"dokumen": (name, pdf, "application/pdf"),
            "penerima": ("recipients.csv", ("\n".join(rows) + "\n").encode(), "text/csv")}


def _analyse_scan(client, pdf: bytes, name: str = "nota_pindaian.pdf") -> tuple[str, str]:
    r = client.post("/terbitkan/analisis", files=_scan_files(pdf, name), data={"c": "3", "eps": "1e-6"})
    assert r.status_code == 200 and "Rencana penandaan" in r.text, r.text[:400]
    return re.search(r"/terbitkan/([0-9a-f]{16})/terbitkan", r.text).group(1), r.text


def _source_words() -> set[str]:
    """Longer words of the sample's page 1 that neither the templates ("Rencana", "dengan") nor the
    recipient list ("Sintetis") contain: the scan shows them as ink and its OCR layer holds them
    as invisible text, but no page may print them."""
    from tapak.marker.layout import extract_layout

    sources = [*(ROOT / "tapak" / "web" / "templates").glob("*.html"), ROOT / "samples" / "recipients.csv"]
    ui = " ".join(p.read_text(encoding="utf-8") for p in sources)
    words = {w.text.strip(".,;:()") for w in extract_layout(_one_page(SAMPLE.read_bytes())).words()}
    return {w for w in words if len(w) >= 6 and w.isalpha() and not re.search(rf"\b{w}\b", ui)}


def test_scanned_master_is_accepted_and_the_plan_shows_page_modes(client, scans):
    from tapak.web.app import SCAN_GATE_LINES, _STAGING

    sid, page = _analyse_scan(client, scans["pindaian"])
    record = _STAGING[sid].scan
    assert record["pages"] == [0] and record["dpi"] == [200] and record["ocr_layer_dropped"] == [0]
    text = _plain(page)
    # page tile: scanned pages count Tesseract's word boxes, never words
    assert "1 halaman pindaian (200 dpi)" in text and "halaman teks" not in text
    assert re.search(r"\d+ kotak kata \(Tesseract\)", text) and not re.search(r"\d+ kata</span>", page)
    assert re.search(r'<li class="mode mode-pindaian">.*?<span>Halaman 1: pindaian, 200 dpi</span></li>', page)
    assert ("Halaman pindaian membawa kanal geser (kotak kata dari Tesseract, ditanam pada piksel gambar) dan pola "
            "latar; karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di sana") in text
    assert f"hanya hash daftar kotaknya yang dicatat ({record['boxes_sha256'][:16]}...)" in text
    assert "Lapisan teks OCR tak terlihat di halaman 1 tidak disalin ke salinan" in text
    # tracing needs the same word boxes; size and time are measured examples, never a promise for this file
    assert "kanal geser halaman pindaian dilewati dan hanya pola latarnya yang dibaca" in text
    assert "salinan bisa jauh lebih besar dari induk hasil pindai JPEG (contoh 300 dpi: sekitar 2,9 MB per halaman salinan" in text
    assert "Ukuran sebenarnya ditampilkan setelah terbit." in text and "4 kali" not in text
    assert "Waktu: 4 salinan \u00d7 1 halaman pindaian ditandai di piksel gambar" in text
    assert "dirender sama" not in text and "berselisih paling banyak 24 tingkat abu-abu" in SCAN_GATE_LINES[True]
    # the gate: pixel-identical scanned page only (the gray-level sentence is about text pages)
    assert f'id="gerbang-pindaian">{SCAN_GATE_LINES[True]}</span>' in page and "selisih maksimum" not in text
    # channels: shift and background in the page image; no text channel has slots on a scan
    assert "Bertahan: cetak, foto, tangkapan layar; di halaman pindaian: digeser di piksel gambar" in text
    assert "foto layar; di halaman pindaian: ditambahkan ke piksel kertas" in text
    assert '<span class="ch-name">Karakter tak terlihat' not in page and '<span class="ch-name">Huruf kembar' not in page
    # not one word of the document (scan or OCR layer) reaches the page
    leaked = sorted(w for w in _source_words() if re.search(rf"\b{w}\b", text))
    assert not leaked, leaked


def test_mixed_master_shows_text_and_scanned_pages(client, scans):
    from tapak.web.app import SCAN_GATE_LINES, _STAGING, _staging_master

    sid, page = _analyse_scan(client, scans["campuran"], "nota_campuran.pdf")
    text = _plain(page)
    assert "1 halaman teks, 1 halaman pindaian (200 dpi)" in text
    assert re.search(r"\d+ kata, \d+ kotak kata \(Tesseract\)", text)
    assert "<span>Halaman 1: teks</span>" in page and "<span>Halaman 2: pindaian, 200 dpi</span>" in page
    assert "Tanpa tanda, halaman teks digambar ulang identik dengan aslinya: selisih maksimum" in text
    assert SCAN_GATE_LINES[True] in text
    # the text channels stay on the text page, and step 3 still applies there
    assert '<span class="ch-name">Karakter tak terlihat' in page
    assert "salin-tempel, berkas diteruskan (halaman teks saja)" in text
    assert "is-na" not in page and "Tidak berlaku" not in text
    assert text.count("Hanya halaman teks. Halaman pindaian (halaman 2) tidak membawa kanal ini.") == 2
    # the word-choice preview plans on the issuance layout, scanned rows included
    master = _staging_master(_STAGING[sid])
    assert any(w.id[0] == 1 for w in master.shift_layout.words())
    assert not any(w.id[0] == 1 for w in master.layout.words())


def test_a_page_without_text_is_not_called_a_text_page(client, scans):
    import pymupdf

    with pymupdf.open(stream=scans["pindaian"], filetype="pdf") as doc:
        doc.new_page()  # a blank page after the scan: on the text path, but with no word to mark
        pdf = doc.tobytes()
    _, page = _analyse_scan(client, pdf, "nota_kosong.pdf")
    assert "<span>Halaman 1: pindaian, 200 dpi</span>" in page
    assert "<span>Halaman 2: tanpa teks, tidak ada kata untuk ditandai</span>" in page
    assert "<span>Halaman 2: teks</span>" not in page


def test_low_resolution_scan_and_unmarkable_pdf_are_refused_in_the_document_field(client, scans):
    import pymupdf

    from tapak.web.app import NOTHING_TO_MARK, _STAGING

    before = set(_STAGING)
    hx = {"HX-Request": "true"}
    r = client.post("/terbitkan/analisis", files=_scan_files(scans["rendah"], "nota_150dpi.pdf"),
                    data={"c": "3", "eps": "1e-6"}, headers=hx)
    assert r.status_code == 200 and r.headers.get("HX-Reswap") == "none" and "<form" not in r.text
    slot = re.search(r'id="err-dokumen" hx-swap-oob="innerHTML">(.*?)</span>\s*<span id="err-penerima"',
                     r.text, re.S).group(1)
    assert "Halaman 1 hasil pindaian beresolusi 150 dpi; TAPAK memerlukan minimal 200 dpi" in slot
    assert "Pindai ulang dokumen pada 300 dpi." in slot and 'class="field-error" role="alert"' in slot
    # neither a text layer nor a page-filling scan: nothing to mark
    with pymupdf.open() as doc:
        doc.new_page()
        blank = doc.tobytes()
    r = client.post("/terbitkan/analisis", files=_scan_files(blank, "kosong.pdf"), data={"c": "3", "eps": "1e-6"},
                    headers=hx)
    assert NOTHING_TO_MARK in r.text and NOTHING_TO_MARK.endswith("Tidak ada yang dapat ditandai.")
    assert set(_STAGING) == before


def test_missing_tesseract_is_reported_in_the_document_field(client, scans, monkeypatch):
    from tapak.marker import raster

    def no_tesseract(master):
        raise raster.OcrUnavailable("Tesseract tidak terpasang; halaman pindaian memerlukan tesseract-ocr dan "
                                    "tesseract-ocr-ind")

    monkeypatch.setattr(raster, "prepare_scans", no_tesseract)
    r = client.post("/terbitkan/analisis", files=_scan_files(scans["pindaian"], "nota_pindaian.pdf"),
                    data={"c": "3", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert r.headers.get("HX-Reswap") == "none"
    assert ('id="err-dokumen" hx-swap-oob="innerHTML"><span class="field-error" role="alert">Tesseract tidak '
            "terpasang; halaman pindaian memerlukan tesseract-ocr dan tesseract-ocr-ind.</span>") in r.text


def test_scan_gate_failure_refuses_the_master(client, scans, monkeypatch):
    from tapak.marker import render
    from tapak.marker.render import GateResult
    from tapak.web.app import SCAN_GATE_LINES

    monkeypatch.setattr(render, "visual_gate", lambda master: GateResult(False, 0, 0.0, 100, False))
    r = client.post("/terbitkan/analisis", files=_scan_files(scans["pindaian"], "nota_pindaian.pdf"),
                    data={"c": "3", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert r.headers.get("HX-Reswap") == "none" and SCAN_GATE_LINES[False] in r.text
    assert SCAN_GATE_LINES[False].endswith("penerbitan ditolak.") and "tingkat abu-abu" not in r.text


def test_all_scanned_master_marks_the_text_review_not_applicable(client, scans):
    from tapak.web.app import ISSUE_STEPS

    sid, page = _analyse_scan(client, scans["pindaian"])
    stepper = re.search(r'<ol class="stepper alur-stepper" id="stepper"[^>]*>.*?</ol>', page, re.S).group(0)
    assert re.findall(r'<span class="stepper-label">([^<]*)', stepper) == list(ISSUE_STEPS)
    items = re.findall(r'<li class="stepper-item[^"]*".*?</li>', stepper, re.S)
    assert 'class="stepper-item is-na"' in items[2] and "tidak berlaku</span>" in items[2]
    assert "(selesai)" not in items[2] and "aria-current" not in items[2] and "icon-minus" in items[2]
    assert 'aria-current="step"><span class="stepper-num">4</span>' in items[3]
    text = _plain(page)
    assert '<h2 id="langkah3">Tinjau teks</h2>' in page
    assert "Tidak berlaku: semua halaman dokumen ini hasil pindai." in text
    # neither safe sentences nor word choice are offered, and publishing is not blocked
    assert 'name="unit"' not in page and 'id="leksikal"' not in page and "Pindai titik pilihan kata" not in page
    assert "bit. Tidak berlaku: semua halaman dokumen ini hasil pindai." in text
    assert "disabled" not in _publish_button(page)
    r = client.post(f"/terbitkan/{sid}/leksikal", headers={"HX-Request": "true"})
    assert r.status_code == 400 and "Pilihan kata tidak berlaku: semua halaman dokumen ini hasil pindai." in r.text


def test_publishing_a_scanned_master_stores_the_scan_record_and_lacak_reads_it(client, scans, monkeypatch):
    import json

    from tapak.config import load_settings
    from tapak.marker.issue import IssueManifest
    from tapak.web.app import SCAN_GATE_LINES, _STAGING

    sid, page = _analyse_scan(client, scans["pindaian"])
    record = dict(_STAGING[sid].scan)
    assert "Halaman pindaian ditandai di piksel gambar" in page  # the publish busy line says it takes longer
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert r.status_code == 200 and "4 salinan siap dibagikan" in r.text
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    folder = load_settings().workspaces / doc
    manifest = IssueManifest.from_json((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.scan == record and manifest.gate["scan_identical"] is True
    with sqlite3.connect(load_settings().registry_path) as con:
        payloads = [json.loads(p) for (p,) in con.execute("SELECT payload FROM entries WHERE kind = 'document'")]
    assert payloads[-1]["scan"]["boxes_sha256"] == record["boxes_sha256"]
    # the result: page modes, the scan gate and the copy sizes measured on the files
    text = _plain(r.text)
    assert "Mode halaman: 1 halaman pindaian (halaman 1; 200 dpi)." in text and "0 halaman teks" not in text
    assert SCAN_GATE_LINES[True] in text
    sizes = [(folder / "salinan" / c.file).stat().st_size / 1e6 for c in manifest.copies]
    biggest = f"{max(sizes):.1f}".replace(".", ",")
    assert re.search(rf"Ukuran salinan: rata-rata \d+,\d MB, terbesar {biggest} MB \(dokumen induk \d+,\d MB\)", text)
    leaked = sorted(w for w in _source_words() if re.search(rf"\b{w}\b", text))
    assert not leaked, leaked
    # Lacak: the document is marked as having scanned pages (busy line), and a copy is read
    form = client.get(f"/lacak?dokumen={doc}").text
    assert re.search(rf'<option value="{doc}" selected data-pratinjau="[^"]*" data-pindaian>', form)
    assert "Dokumen ini memuat halaman pindaian: kotak katanya dibaca ulang dengan Tesseract" in form
    copy = client.get(f"/dokumen/{doc}/salinan/2")
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", copy.content, "application/pdf")})
    assert r.status_code == 200 and "Salinan #2" in r.text
    # the channel keeps its usual name; a sentence under the table says the scanned pages were covered
    assert re.search(r"<tr>\s*<td>Geser</td>", r.text)
    note = re.search(r'<p class="hint kanal-catatan" id="kanal-catatan">(.*?)</p>', r.text, re.S).group(1)
    assert "Kanal geser mencakup halaman pindaian: kotak katanya dibaca ulang dengan Tesseract dan cocok" in note
    assert "dipetakan ke halaman 1 (halaman pindaian, korelasi" in _plain(r.text)
    # word boxes that could not be found again (simulated): the sentence under the table says so
    import tapak.decoder.trace as trace

    skipped = f"{trace.SCAN_SHIFT_SKIPPED}: kotak kata tidak dapat dibaca ulang (simulasi)"
    monkeypatch.setattr(trace, "attach_recorded_scans", lambda master, manifest: skipped)
    r = client.post("/lacak", data={"dokumen": doc, "teks": "Teks ini tidak berasal dari dokumen mana pun."})
    assert r.status_code == 200 and f"<b>Perhatian:</b> {skipped}</p>" in r.text
    note = re.search(r'<p class="hint kanal-catatan" id="kanal-catatan">(.*?)</p>', r.text, re.S).group(1)
    assert "Kanal geser tidak membaca halaman pindaian (lihat peringatan di atas); pola latar halaman itu tetap dibaca." in note


def test_lacak_warns_next_to_the_verdict_when_scanned_shift_was_skipped(client, monkeypatch):
    import tapak.decoder.trace as trace
    from tapak.web.app import templates

    note = (f"{trace.SCAN_SHIFT_SKIPPED}: kotak kata hasil Tesseract berbeda dari saat penerbitan (sekarang "
            "tesseract 9, saat penerbitan tesseract 5); TAPAK tidak menebak letak kata, pola latar tetap dibaca")
    tpl = templates.env.from_string("{% for n in peringatan_terlihat(notes) %}[P]{{ n }}{% endfor %}")
    assert tpl.render(notes=["catatan biasa", note]) == f"[P]{note}"
    r = client.post("/terbitkan/analisis", files=_files(), data={"c": "3", "eps": "1e-6"})
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/terbitkan", r.text).group(1)
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    monkeypatch.setattr(trace, "attach_recorded_scans", lambda master, manifest: note)  # simulated drift
    r = client.post("/lacak", data={"dokumen": doc, "teks": "Teks ini tidak berasal dari dokumen mana pun."})
    assert r.status_code == 200 and "Tidak cukup bukti" in r.text
    verdict = r.text[:r.text.index('class="verdict-actions"')]
    assert f'<p class="notice notice-warn verdict-note"><b>Perhatian:</b> {note}</p>' in verdict
    assert r.text.count(trace.SCAN_SHIFT_SKIPPED) == 1  # not repeated among the notes
    assert not re.search(r'<ul class="notes">\s*</ul>', r.text)  # no empty notes list


# --- staged accusation (pelacakan bertahap) in the Lacak result ------------------------------


def _compact(text: str) -> str:
    """Markup or PDF text without tags and whitespace, for comparing numbers between the two."""
    return "".join(_plain(re.sub(r"<[^>]+>", "", text)).split())


def _coalition_composite(s, manifest):
    """Text of four copies (more than c = 3) spliced together: 70 % from one, 10 % from each of
    three others. A few coalitions are traced in-process with the budget of trace no. 1 (nothing
    is logged) until stage 1 names one copy and a later stage names another; one coalition does
    so with probability about 0,99. Returns the text, the coalition and the expected result."""
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tapak.decoder.trace import load_context, trace_files
    from tapak.service import TRACE_STAGE_POLICY, ensure_keys
    from tapak.tardos.spending import TraceSpending

    folder = s.workspaces / manifest.doc_hash[:16]
    words = {c.seq: extract_pdf_text((folder / "salinan" / c.file).read_bytes()).split() for c in manifest.copies}
    n = len(words[1])
    assert {len(w) for w in words.values()} == {n}  # the same words; only the invisible marks differ
    keys = ensure_keys(s, create_signing_key=False, create_secret=False)
    ctx = load_context((folder / "induk.pdf").read_bytes(), manifest, keys.code_secret, folder=folder)
    spending = TraceSpending.logged(manifest.tardos_params.eps, 1, TRACE_STAGE_POLICY)
    cuts = [0, round(0.7 * n), round(0.8 * n), round(0.9 * n), n]
    for coalition in ((1, 2, 3, 4), (3, 4, 5, 6), (5, 6, 1, 2)):
        text = " ".join(w for k, seq in enumerate(coalition) for w in words[seq][cuts[k]:cuts[k + 1]])
        a, _ = trace_files([("bocor.txt", text.encode())], ctx, spending)
        if len(a.accused) == 1 and any(st.accused for st in a.stages):
            return text, coalition, a
    pytest.fail("no coalition of four copies gave a later-stage name")


def test_lacak_shows_later_stages_resting_on_the_stage_one_names(client, monkeypatch):
    import pymupdf

    import tapak.service as service
    from tapak.canary_dns.store import record_event
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tapak.decoder.report import REDACTED, _strip_zeros, format_number, format_probability_html
    from tapak.web.app import _TRACES, _eps_label

    s, manifest = _issue_small(6)
    doc = manifest.doc_hash[:16]
    text, coalition, expected = _coalition_composite(s, manifest)
    by_seq = {c.seq: c for c in manifest.copies}
    rid = {seq: c.recipient.recipient_id for seq, c in by_seq.items()}
    outsider = next(seq for seq in by_seq if seq not in coalition)
    late = next(c.copy.seq for st in expected.stages for c in st.accused)
    for c in manifest.copies:  # a canary hit from every copy; only named copies may be numbered
        record_event(s.canary_db, f"{c.canary_token}.c.kanari.tapak.test", c.canary_token, "A", "198.51.100.7", 5353)
    # One channel alone also points at every coalition member and at the outsider, so the
    # per-channel table shows which of them it may number.
    real = service.trace_evidence

    def traced(*args, **kwargs):
        out = real(*args, **kwargs)
        out.attribution.channels[0].accused_seqs = sorted(set(coalition) | {outsider})
        return out

    monkeypatch.setattr(service, "trace_evidence", traced)
    # the leaker controls the file name: it names the later-stage copy and the outsider
    name = f"bocor_salinan{late:03d}_{rid[late]}_salinan{outsider:03d}_{rid[outsider]}.txt"
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": (name, text.encode("utf-8"), "text/plain")})
    assert r.status_code == 200
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    a = _TRACES[tid].attribution
    t = a.threshold
    later = [(st, c) for st in a.stages for c in st.accused]
    assert a.named_seqs == expected.named_seqs and t.trace_no == 1 and t.stage_policy
    first = a.accused[0]
    assert len(a.accused) == 1 and later and a.named_seqs <= set(coalition)

    # The verdict: the stage-1 name first, then every later name below it with its stage, its basis,
    # its stage score against its own threshold (never Z1) and its bound.
    verdict = r.text[:r.text.index('class="verdict-actions"')]
    stage1 = verdict.index(f'<span class="who-seq">Salinan #{first.copy.seq}</span>')
    assert 'id="putusan"' in verdict[:stage1] and stage1 < verdict.index('<div class="lanjut"')
    block = verdict[verdict.index('<div class="lanjut"'):]
    assert "Pelacakan bertahap" in block and "tidak dapat dibandingkan langsung dengan skor tahap 1" in block
    assert "Tahap lanjutan hanya berjalan karena tahap 1 menuduh salinan di atas." in block
    assert "Ambang Z <b>" not in block and "Kanal sepakat" not in block
    items = block.split('<div class="who who-lanjut">')[1:]
    assert len(items) == len(later)
    for (st, c), item in zip(later, items):
        assert (f'<span class="stamp stamp-ok">Tahap {st.stage}</span> <span class="who-seq">Salinan #{c.copy.seq}'
                f'</span> <span class="who-name">{c.copy.nama}</span>') in item
        assert st.basis_text() in item and set(st.basis) <= a.named_seqs - {c.copy.seq}
        assert f"Skor tahap {st.stage} <b>{format_number(c.score, 1)}</b>" in item
        assert f"Ambang Z{st.stage} <b>{format_number(st.threshold.threshold, 1)}</b>" in item
        assert str(format_probability_html(c.false_accusation_probability, c.log10_false_accusation)) in item
    # the collusion notice counts the named copies of every stage, not stage 1's alone, and does
    # not say that a later-stage copy passed the (stage-1) threshold
    assert "Lebih dari satu salinan dituduh, di tahap 1 dan di tahap lanjutan: pola ini sesuai dengan kolusi" in verdict
    assert "melewati ambang" not in verdict.lower()

    # File names, the per-channel table and the canary list number the named copies of every stage.
    kicker = re.search(r'<span class="mono keep-case">(.*?)</span>', r.text).group(1)
    assert kicker == f"bocor_salinan{late:03d}_{rid[late]}_salinan{REDACTED}_{REDACTED}.txt"
    assert rid[outsider] not in r.text
    kanal = r.text[r.text.index('id="kanal-h"'):r.text.index('id="skor-h"')]
    row = re.search(r"<tr>\s*<td>Teks</td>.*?</tr>", kanal, re.S).group(0)
    assert all(f"<b>#{seq}</b>" in row for seq in a.named_seqs) and f"#{outsider}" not in row
    assert f"{len(set(coalition) - a.named_seqs) + 1} salinan lain (nomor tidak dicantumkan)" in row
    canary = r.text[r.text.index('id="kanari-h"'):r.text.index('id="sah-h"')]
    assert all(f"Salinan #{seq}</span>" in canary for seq in a.named_seqs)
    assert all(f"Salinan #{seq}: {by_seq[seq].recipient.nama}" in canary for seq in a.named_seqs)
    for st, c in later:  # a later-stage name in the canary list comes with its basis
        item = re.search(rf"<li>Salinan #{c.copy.seq}: .*?</li>", canary).group(0)
        assert item.endswith(f"; {st.basis_text()}</li>"), item
    assert canary.count("Salinan lain") == len(by_seq) - len(a.named_seqs)

    # Bukti per kanal: stage 1's part of the budget, then one row per later stage.
    plain = _plain(kanal)
    frac1 = _strip_zeros(format_number(100 * t.stage_spent / t.spent, 2))
    # the trace's share as the berita acara writes it (60,79 %, not 60,8 %)
    assert f"Pelacakan ini memakai {_strip_zeros(format_number(100 * t.share, 2))} % dari batas" in plain
    assert (f"tahap 1 memakai {_strip_zeros(format_number(100 * t.stage_share, 2))} % dari batas peluang tuduhan "
            f"salah {_eps_label(t.eps)} ({frac1} % dari jatah pelacakan ini)") in plain
    assert "Bobotnya memakai kode salinan yang sudah dituduh, tidak pernah kode salinan yang sedang dinilai." in plain
    assert "tahap-catatan" not in kanal
    start = kanal.index('class="tahap-tabel"')
    rows = [_compact(x) for x in re.findall(r"<tr>\s*<td>.*?</tr>", kanal[start:kanal.index("</table>", start)], re.S)]
    assert len(rows) == len(a.stages)
    for st, cells in zip(a.stages, rows):
        ts = st.threshold
        z = format_number(ts.threshold, 1) if ts.threshold != float("inf") else "takhingga"
        frac = _strip_zeros(format_number(100 * ts.stage_spent / t.spent, 2))
        basis = ",".join(f"#{b}" for b in st.basis)
        named = ",".join(f"#{c.copy.seq}" for c in st.accused) or "tidakada"
        assert cells == f"{st.stage}dasar{basis}{format_number(ts.n_observed, 0)}{z}{frac}%{named}", cells

    # Peringkat skor (stage 1): a copy named later shows its name only with its basis, stage score
    # and Z_s; a screen reader hears each score as the stage-1 score.
    ranking = r.text[r.text.index('id="skor-h"'):]
    ranking = ranking[:ranking.index("</section>")]
    assert "Skor tahap 1." in ranking
    for st, c in later:
        assert (f'#{c.copy.seq} \u00b7 {c.copy.nama}</b><span class="sr-only">, di bawah ambang tahap 1,</span> '
                f'<span class="peringkat-tahap">{st.basis_text()}; skor tahap {format_number(c.score, 1)}, '
                f"ambang Z{st.stage} {format_number(st.threshold.threshold, 1)}</span>") in ranking
    assert ranking.count('<span class="sr-only">, skor tahap 1 </span>') == min(len(a.candidates), 6)
    assert ranking.count("Disembunyikan") == len(by_seq) - len(a.named_seqs)

    # Every number of the later stages is the one the berita acara prints for the same trace.
    with pymupdf.open(stream=client.get(f"/lacak/{tid}/berita-acara.pdf").content, filetype="pdf") as pdf:
        report = _compact("".join(page.get_text() for page in pdf))
        pages = pdf.page_count
    # A page break can fall inside a sentence: drop the running header and footer it brings in.
    report = re.sub(rf"RAHASIABAPDigital.*?RAHASIAHalaman\d+dari{pages}", "", report)
    assert f"tahap1memakai{frac1}%darijatahitu" in report
    for st in a.stages:
        ts = st.threshold
        assert f"Posisiyangbitnyatidakdimilikisalinantersebut:{format_number(ts.n_observed, 0)}." in report
        assert f"({_strip_zeros(format_number(100 * ts.stage_spent / t.spent, 2))}%darijatahpelacakan;" in report
        if ts.threshold != float("inf"):
            assert f"AmbangZ{st.stage}={format_number(ts.threshold, 1)}untuk" in report
    for st, c in later:
        bound = _compact(str(format_probability_html(c.false_accusation_probability, c.log10_false_accusation)))
        assert c.copy.nama.replace(" ", "") in report
        assert f"{format_number(c.score, 1)}{format_number(st.threshold.threshold, 1)}\u2264{bound}" in report

    # One leaker: no later stage names anyone; one quiet line, no table and no later names.
    monkeypatch.setattr(service, "trace_evidence", real)
    lone = by_seq[outsider]
    evidence = extract_pdf_text((s.workspaces / doc / "salinan" / lone.file).read_bytes())
    r = client.post("/lacak", data={"dokumen": doc, "teks": evidence})
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    a = _TRACES[tid].attribution
    assert [c.copy.seq for c in a.accused] == [lone.seq] and a.stages and not any(st.accused for st in a.stages)
    assert "tahap-tabel" not in r.text and 'class="lanjut"' not in r.text and "Tahap 2" not in r.text
    assert "Lebih dari satu salinan" not in r.text
    assert '<span class="sr-only">, skor </span>' in r.text and "skor tahap 1" not in r.text
    lines = [_plain(x) for x in re.findall(r'<p class="hint tahap-catatan">(.*?)</p>', r.text, re.S)]
    share1 = _strip_zeros(format_number(100 * a.threshold.stage_share, 2))
    assert lines == [f"Pelacakan bertahap: tahap 1 memakai {share1} % dari "
                     f"batas peluang tuduhan salah {_eps_label(a.threshold.eps)} (90 % dari jatah pelacakan ini); "
                     "tahap lanjutan tidak menuduh salinan lain."]


# --- erasure aimed at agreeing positions (tapak.collusion, decoder/erasure.py) ---------------


def test_lacak_warns_of_a_deliberate_erasure_pattern_without_changing_the_verdict(client):
    """Three copies combined by a coalition that flattens every mark where they agree: the
    result page shows the warning next to the verdict and the check in the validity box; an
    honest copy shows neither the warning nor a stamp. (With two copies and a random member per
    cell where they differ, no coherent background is left; the check then reads the shift
    units alone, which flag such a PDF only sometimes: ``research/kontradiksi``.)"""
    import numpy as np

    from tapak.collusion import attack
    from tapak.decoder.erasure import ERASURE_NOTE
    from tapak.decoder.manipulation import MANIPULATION_LEAD
    from tapak.marker.master import load_master

    s, manifest = _issue_small(6)
    doc = manifest.doc_hash[:16]
    folder = s.workspaces / doc
    pdfs = [(folder / "salinan" / manifest.copies[i].file).read_bytes() for i in (1, 2, 4)]
    forged, _, _ = attack(load_master((folder / "induk.pdf").read_bytes()), pdfs, "acak", 1.0,
                          rng=np.random.default_rng(4))
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", forged, "application/pdf")})
    assert r.status_code == 200
    verdict = r.text[:r.text.index('class="verdict-actions"')]
    assert '<p class="notice notice-warn verdict-note"><b>Perhatian:</b> ' + MANIPULATION_LEAD + ": " in verdict
    assert ERASURE_NOTE in verdict and r.text.count(ERASURE_NOTE) == 1 and r.text.count(MANIPULATION_LEAD) == 1
    box = r.text[r.text.index('id="sah-h"'):]
    assert "Pola penghapusan" in box and "Terdeteksi" in box and "posisi terukur" in box
    for seq in (1, 4, 6):  # nobody outside the coalition (copies 2, 3 and 5) is named
        assert f'<span class="who-seq">Salinan #{seq}</span>' not in verdict
    honest = client.post("/lacak", data={"dokumen": doc},
                         files={"bukti": ("bocor.pdf", pdfs[0], "application/pdf")}).text
    assert ERASURE_NOTE not in honest and "Pola penghapusan" in honest and "Terdeteksi" not in honest
    assert "Tanda terbalik" in honest and MANIPULATION_LEAD not in honest


def test_lacak_warns_of_a_clear_read_that_names_nobody(client):
    """Two copies whose agreeing marks are reversed (a coalition that knows TAPAK): every mark
    still reads clearly, nobody is named, and the page shows one warning under the verdict with
    the reversed marks and the bound, and both checks in the validity box. An honest copy is
    named, so the contradiction check does not run and neither the warning nor its row appears."""
    import numpy as np

    from tapak.collusion import attack
    from tapak.decoder.contradiction import CONTRADICTION_NOTE
    from tapak.decoder.manipulation import MANIPULATION_LEAD
    from tapak.decoder.reversal import REVERSAL_NOTE
    from tapak.marker.master import load_master

    s, manifest = _issue_small(6)
    doc = manifest.doc_hash[:16]
    folder = s.workspaces / doc
    pdfs = [(folder / "salinan" / manifest.copies[i].file).read_bytes() for i in (1, 4)]
    forged, _, _ = attack(load_master((folder / "induk.pdf").read_bytes()), pdfs, "acak", 1.0,
                          rng=np.random.default_rng(4), neutralize="balik")
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", forged, "application/pdf")})
    assert r.status_code == 200
    verdict = r.text[:r.text.index('class="verdict-actions"')]
    assert "Tidak cukup bukti" in verdict and 'class="who-seq"' not in verdict
    assert '<p class="notice notice-warn verdict-note"><b>Perhatian:</b> ' + MANIPULATION_LEAD + ": " in verdict
    assert r.text.count(MANIPULATION_LEAD) == 1 and r.text.count(CONTRADICTION_NOTE) == 1
    assert REVERSAL_NOTE in verdict and "koalisi lebih dari 3 orang" in verdict
    box = r.text[r.text.index('id="sah-h"'):]
    assert "Bacaan tanpa nama" in box and "Bertentangan" in box and "tidak lebih dari 10^-3" in box
    assert "Tanda terbalik" in box and "z tanda = -" in box and "ambang -3,90" in box
    honest = client.post("/lacak", data={"dokumen": doc},
                         files={"bukti": ("salinan.pdf", pdfs[0], "application/pdf")}).text
    assert CONTRADICTION_NOTE not in honest and "Bacaan tanpa nama" not in honest
    assert '<span class="who-seq">Salinan #2</span>' in honest
