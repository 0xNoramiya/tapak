"""Regression tests for the findings of the fix-verification review."""

from __future__ import annotations

import json

import numpy as np
import pymupdf
import pytest

from tapak.decoder.ch_shift import map_pages
from tapak.decoder.report import evidence_types_for, rerun_command
from tapak.decoder.image import collect_from_gray
from tapak.decoder.trace import TraceError, collect_file, collect_rasterized_pages, load_semantic, run_trace
from tapak.marker.issue import IssueSettings, read_recipients
from tapak.marker.layout import extract_layout
from tapak.tardos.attacks import STRATEGIES, STRATEGY_LABELS
from tests_support import RECIPIENTS, SAMPLE


def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    from tapak.config import load_settings

    return load_settings()


def _copy(issued, seq):
    out, manifest = issued
    return (out / manifest.copies[seq - 1].file).read_bytes()


# --- issuance: claims, interruptions and post-commit failures ------------------------------


def test_stale_claim_is_reclaimed_and_live_claim_refused(tmp_path, monkeypatch):
    import fcntl

    from tapak.marker.master import load_master
    from tapak.service import ensure_keys, issue_document

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    folder = s.workspaces / load_master(SAMPLE.read_bytes()).doc_hash[:16]
    folder.mkdir(parents=True)
    with open(folder / ".terbit.lock", "a+") as held:  # another issuance is running
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(FileExistsError, match="sedang diterbitkan"):
            issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji", keys)
    # The lock is released, as after a crash: the leftover folder is a stale claim.
    (folder / "sisa.tmp").write_text("x", encoding="utf-8")
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji", keys)
    assert (out.folder / "manifest.json").exists() and not (out.folder / "sisa.tmp").exists()
    with pytest.raises(FileExistsError, match="sudah diterbitkan"):
        issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji", keys)


def test_failure_after_registry_commit_keeps_the_workspace(tmp_path, monkeypatch):
    from tapak import service
    from tapak.registry.chain import Registry

    s = _settings(tmp_path, monkeypatch)
    keys = service.ensure_keys(s)
    real = service._write_atomic

    def fail_manifest(path, text):
        if path.name == "manifest.json" and path.parent.name != "salinan":
            raise OSError("disk penuh (uji)")
        real(path, text)

    monkeypatch.setattr(service, "_write_atomic", fail_manifest)
    with pytest.raises(RuntimeError, match="dipertahankan"):
        service.issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji", keys)
    folders = [p for p in s.workspaces.iterdir() if p.is_dir()]
    assert len(folders) == 1 and (folders[0] / "salinan" / "manifest.json").exists()
    monkeypatch.setattr(service, "_write_atomic", real)
    with pytest.raises(FileExistsError, match="sudah tercatat di registri"):  # never reclaimed as stale
        service.issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji", keys)
    with Registry.open(s.registry_path) as reg:  # the committed rows stay, matching the kept copies
        assert len(reg.entries()) == 3


def test_recipient_ids_must_be_safe_for_file_names(tmp_path):
    for bad in ("../../etc/x", "a b", "", "-x"):
        p = tmp_path / "r.csv"
        p.write_text(f"recipient_id,nama\n{bad},Nama Fiktif\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_recipients(p)
    p.write_text("recipient_id,nama\nR-01.a_b,Nama Fiktif\n", encoding="utf-8")
    assert read_recipients(p)[0].recipient_id == "R-01.a_b"


def test_pdf_header_after_leading_bytes_is_accepted(tmp_path, secret, recipients, sample_pdf):
    from tapak.marker.issue import issue

    padded = tmp_path / "padded.pdf"
    padded.write_bytes(b"\r\n" * 20 + sample_pdf)
    manifest = issue(padded, recipients[:2], tmp_path / "out", secret, IssueSettings(workers=1))
    assert len(manifest.copies) == 2


# --- tracing ----------------------------------------------------------------------------------


def test_map_pages_is_one_to_one(issued, ctx):
    src = pymupdf.open(stream=_copy(issued, 2))
    out = pymupdf.open()
    out.insert_pdf(src, from_page=0, to_page=0)
    out.insert_pdf(src, from_page=0, to_page=0)  # the same page twice
    out.insert_pdf(src, from_page=1, to_page=1)
    pairs = map_pages(ctx.master.layout, extract_layout(out.tobytes()))
    assert len(set(pairs.values())) == len(pairs)
    assert pairs[2] == 1 and 0 in pairs.values()


def test_scanned_pdf_pages_are_decoded_as_images(issued, ctx):
    from tapak.marker.render import render_pages

    img = render_pages(_copy(issued, 5), 200, [0])[0]
    ok, png = __import__("cv2").imencode(".png", img)
    assert ok
    doc = pymupdf.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_image(page.rect, stream=png.tobytes())
    direct = collect_from_gray(img.astype(np.float32), ctx)  # the same page given as an image
    assert any(sb.meta.get("registered") is not False for sb in direct)
    obs, notes = collect_rasterized_pages(doc.tobytes(), ctx, "pindaian.pdf")
    assert obs and any("dibaca sebagai gambar" in n for n in notes)
    all_obs, all_notes = collect_file("pindaian.pdf", doc.tobytes(), ctx)
    assert [c.copy.seq for c in run_trace(all_obs, ctx, all_notes).accused] == [5]


def test_varian_json_is_found_next_to_the_workspace(tmp_path):
    (tmp_path / "salinan").mkdir()
    assert load_semantic(tmp_path / "salinan") is None
    (tmp_path / "varian.json").write_text("{bukan json", encoding="utf-8")
    with pytest.raises(TraceError, match="varian"):
        load_semantic(tmp_path / "salinan")


def test_docx_trace_fuses_every_evidence_file(tmp_path, monkeypatch):
    from tapak.decoder.ch_docx import extract_docx_text
    from tapak.marker.docx_marker import make_sample_docx
    from tapak.service import ensure_keys, issue_document, trace_evidence

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    docx = make_sample_docx(tmp_path / "nota.docx")
    out = issue_document(s, docx, read_recipients(RECIPIENTS)[:6], IssueSettings(workers=1), "uji", keys)
    copy = next(out.folder.rglob(out.manifest.copies[3].file)).read_bytes()
    text = extract_docx_text(copy)
    half = len(text) // 2
    one = trace_evidence(s, out.manifest.doc_hash, "a.txt", text[:half].encode("utf-8"))
    both = trace_evidence(s, out.manifest.doc_hash, "a.txt", text[:half].encode("utf-8"),
                          more=[("b.txt", text[half:].encode("utf-16"))])
    assert both.attribution.threshold.n_observed > one.attribution.threshold.n_observed
    assert [c.copy.seq for c in both.attribution.accused] == [4]
    assert both.evidence_names == ["a.txt", "b.txt"]
    assert any("2 berkas bukti digabung" in n for n in both.attribution.notes)


def test_report_rerun_command_lists_every_evidence_file(issued, ctx):
    from tapak.decoder.report import build_report_info

    info = build_report_info(ctx, "hal1.jpg", b"x", [], case_number="1", examiner_name="a", examiner_rank="b",
                             evidence_type=evidence_types_for(["hal 1.jpg", "hal2.pdf"]))
    info.evidence_names = ["hal 1.jpg", "hal2.pdf"]
    cmd = rerun_command(info)
    assert cmd.startswith("tapak trace 'hal 1.jpg' hal2.pdf --master ")
    assert info.evidence_type == "foto, berkas PDF"
    assert evidence_types_for(["a.jpg", "b.png"]) == "foto"


def test_strategy_labels_are_indonesian():
    assert set(STRATEGY_LABELS) == set(STRATEGIES)
    assert STRATEGY_LABELS["majority"] == "mayoritas"


# --- command line output --------------------------------------------------------------------


def test_cli_json_and_canary_lines_hide_copies_that_are_not_accused(tmp_path, monkeypatch, capsys):
    from tapak import cli
    from tapak.service import ensure_keys, issue_document

    s = _settings(tmp_path, monkeypatch)
    ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:4], IssueSettings(workers=1), "uji")
    copy = out.folder / "salinan" / out.manifest.copies[1].file
    monkeypatch.setattr("tapak.service.canary_alerts", lambda settings, manifest: [
        {"seq": 2, "recipient_id": "R002", "nama": "x", "time": "2026-01-01T00:00:00Z", "src_ip": "192.0.2.1"},
        {"seq": 3, "recipient_id": "R003", "nama": "y", "time": "2026-01-01T00:00:00Z", "src_ip": "192.0.2.2"},
    ])
    js = tmp_path / "hasil.json"
    assert cli.main(["trace", str(copy), "--doc", out.manifest.doc_hash, "--json", str(js)]) == 0
    printed = capsys.readouterr().out
    assert "salinan #2 (R002)" in printed and "R003" not in printed and "#3" not in printed
    assert "salinan lain (nomor tidak dicantumkan)" in printed
    assert "{" not in printed  # no raw diagnostic dictionaries
    data = json.loads(js.read_text(encoding="utf-8"))
    named = [c["copy"]["recipient_id"] for c in data["candidates"] if c["copy"]["recipient_id"]]
    assert named == ["R002"]


def test_cli_describes_file_errors_in_indonesian(tmp_path, capsys):
    from tapak import cli

    code = cli.main(["--data", str(tmp_path / "d"), "--keys", str(tmp_path / "k"), "trace",
                     str(tmp_path / "tidak_ada.pdf"), "--master", str(tmp_path / "x.pdf"),
                     "--manifest", str(tmp_path / "m.json")])
    err = capsys.readouterr().err
    assert code == 2 and "berkas tidak ditemukan" in err and "No such file" not in err


def test_cli_rejects_a_master_that_is_neither_pdf_nor_docx(tmp_path, issued, capsys, monkeypatch):
    from tapak import cli

    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "k"))
    from tapak.keys import code_secret_path, load_code_secret

    load_code_secret(code_secret_path(tmp_path / "k"), create=True)
    master = tmp_path / "induk.txt"
    master.write_text("bukan pdf", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(issued[1].to_json(), encoding="utf-8")
    evidence = tmp_path / "bukti.txt"
    evidence.write_text("isi", encoding="utf-8")
    code = cli.main(["trace", str(evidence), "--master", str(master), "--manifest", str(manifest)])
    assert code == 2 and "PDF atau DOCX" in capsys.readouterr().err


# --- registry, canary allowlist ------------------------------------------------------------


def test_edited_recipient_name_names_nobody(tmp_path, monkeypatch):
    from tapak.registry.chain import recipient_commitment
    from tapak.service import ensure_keys, issue_document, trace_evidence

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:4], IssueSettings(workers=1), "uji", keys)
    c = out.manifest.copies[2]
    assert recipient_commitment(keys.code_secret, out.manifest.doc_hash, c.copy_id, c.recipient.recipient_id,
                                c.recipient.nama, c.recipient.jabatan, c.recipient.satuan).startswith("hmac-sha256:")
    m = json.loads((out.folder / "manifest.json").read_text(encoding="utf-8"))
    m["copies"][2]["recipient"]["nama"] = "Kapten Inf Orang Tak Bersalah"  # recipient_id kept
    (out.folder / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    evidence = (out.folder / "salinan" / c.file).read_bytes()
    with pytest.raises(TraceError, match="tidak cocok dengan registri"):
        trace_evidence(s, out.manifest.doc_hash, "bocor.pdf", evidence)


def test_broken_registry_chain_names_nobody(tmp_path, monkeypatch):
    import sqlite3

    from tapak.service import ensure_keys, issue_document, trace_evidence

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:3], IssueSettings(workers=1), "uji", keys)
    con = sqlite3.connect(s.registry_path)
    con.execute("DROP TRIGGER IF EXISTS entries_no_update")
    con.execute("UPDATE entries SET created_at = '2020-01-01T00:00:00+00:00' WHERE seq = 2")
    con.commit()
    con.close()
    from tapak.registry.chain import Registry

    Registry.open(s.registry_path, repair_triggers=True).close()  # a careful tamperer restores them
    evidence = (out.folder / "salinan" / out.manifest.copies[0].file).read_bytes()
    with pytest.raises(TraceError, match="rantai registri gagal"):
        trace_evidence(s, out.manifest.doc_hash, "bocor.pdf", evidence)


def test_canary_allowlist_never_follows_a_planted_link(tmp_path, monkeypatch):
    from tapak.service import ensure_keys, issue_document

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s)
    secret_before = s.code_secret_path.read_bytes()
    s.canary_allow_dir.mkdir(parents=True)
    s.canary_allowlist.symlink_to(s.code_secret_path)  # planted by a compromised listener
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:3],
                         IssueSettings(workers=1, canary_domain="kanari.tapak.test"), "uji", keys)
    assert s.code_secret_path.read_bytes() == secret_before
    assert not s.canary_allowlist.is_symlink()
    lines = s.canary_allowlist.read_text(encoding="ascii").split()
    assert len(lines) == 3 and all(x.startswith("sha256:") for x in lines) and not out.warnings
    # The listener's own folder is separate: a link there is not read by the app either.
    s.canary_dir.mkdir(parents=True, exist_ok=True)
    s.canary_db.symlink_to(s.registry_path)
    from tapak.service import canary_alerts

    assert canary_alerts(s, out.manifest) == []


def test_allowlist_failure_after_commit_is_a_warning(tmp_path, monkeypatch):
    from tapak import service

    s = _settings(tmp_path, monkeypatch)
    keys = service.ensure_keys(s)

    def denied(settings):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(service, "publish_canary_allowlist", denied)
    out = service.issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:2],
                                 IssueSettings(workers=1, canary_domain="kanari.tapak.test"), "uji", keys)
    assert (out.folder / "manifest.json").exists()
    assert out.warnings and "kanari-izin" in out.warnings[0]


# --- web --------------------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    _settings(tmp_path, monkeypatch)
    monkeypatch.setenv("TAPAK_CANARY_DOMAIN", "kanari.tapak.test")
    from tapak.cli import main as cli_main
    from tapak.web.app import app

    assert cli_main(["keys", "init"]) == 0
    return TestClient(app, base_url="http://127.0.0.1")


def test_framework_errors_are_indonesian_notices(client):
    hx = {"HX-Request": "true"}
    r = client.post("/lacak", data={"dokumen": "x", "teks": "a" * 1_100_000}, headers=hx)
    assert r.status_code == 400 and r.headers["HX-Retarget"] == "#galat-global"
    assert "terlalu panjang" in r.text and "maximum" not in r.text
    r = client.post("/terbitkan/0123456789abcdef/varian/u1/abc/disetujui", headers=hx)
    assert r.status_code == 422 and "Isian tidak sah" in r.text and "detail" not in r.text
    r = client.post("/terbitkan/0123456789abcdef/varian", headers=hx)
    assert 'href="/terbitkan">Mulai lagi</a>' in r.text
    r = client.get("/tidak-ada")
    assert r.status_code == 404 and "Halaman tidak ditemukan" in r.text


def test_coalition_size_must_be_a_whole_number(client):
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", RECIPIENTS.read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "1e1", "eps": "1e-6"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200 and "bilangan bulat" in r.text and 'id="err-c"' in r.text


def test_same_origin_and_wildcard_hosts(client, monkeypatch):
    from tapak.web import app as web

    ok = client.post("/lacak", data={"dokumen": ""}, headers={"origin": "http://127.0.0.1"})
    assert ok.status_code == 200
    monkeypatch.setattr(web, "ALLOWED_HOSTS", ["127.0.0.1", "*.satuan.mil", "*"])
    assert web._host_allowed("tapak.satuan.mil") and not web._host_allowed("satuan.mil.evil.example")
    assert not web._host_allowed("evil.example")  # a bare "*" never accepts a foreign origin


def test_eps_label_is_indonesian():
    from tapak.web.app import _eps_label

    assert _eps_label(1e-4) == "1 dari 10.000" and _eps_label(1e-6) == "1 dari 1.000.000"
    assert _eps_label(1e-5) == "1 dari 100.000"


def test_trace_page_hides_names_of_copies_not_accused(client):
    from tapak.cli import main as cli_main

    assert cli_main(["issue", str(SAMPLE), str(RECIPIENTS), "--issuer", "uji", "--workers", "1"]) == 0
    from tapak.config import load_settings
    from tapak.service import list_workspaces

    doc = list_workspaces(load_settings())[0].doc_hash[:16]
    r = client.post("/lacak", data={"dokumen": doc},
                    files={"bukti": ("nota_dinas__salinan005_R005.txt", "teks tanpa tanda".encode(), "text/plain")})
    assert r.status_code == 200 and "tidak cukup bukti" in r.text.lower()
    assert "R005" not in r.text and "salinan005" not in r.text


def test_semantic_status_is_announced_outside_the_swap(client):
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", RECIPIENTS.read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6"})
    assert 'id="semantik-status" class="sr-only" aria-live="polite"' in r.text
    import re

    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    units = re.findall(r'name="unit" value="(u\d+)"', r.text)
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    assert '<p id="semantik-status" hx-swap-oob="innerHTML">' in r.text and "menunggu tinjauan" in r.text


def test_copy_download_never_serves_the_manifest(client, tmp_path):
    from tapak.cli import main as cli_main
    from tapak.config import load_settings
    from tapak.service import list_workspaces

    assert cli_main(["issue", str(SAMPLE), str(RECIPIENTS), "--issuer", "uji", "--workers", "1"]) == 0
    m = list_workspaces(load_settings())[0]
    folder = load_settings().workspaces / m.doc_hash[:16]
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    data["copies"][0]["file"] = "manifest.json"
    (folder / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert client.get(f"/dokumen/{m.doc_hash[:16]}/salinan/1").status_code == 400


def test_pattern_z_null_rate_does_not_grow_with_few_bits():
    from tapak.decoder.ch_background import SIGNAL_Z, pattern_z

    rng = np.random.default_rng(3)

    def stats(n, amp):
        s = rng.choice([-1, 1], n)
        pn, d = rng.choice([-1, 1], (n, 8)), rng.choice([-1, 1], (n, 8))
        v = pn * (s[:, None] * amp) + rng.normal(0, np.sqrt(8), (n, 8))
        t, td = (pn * v).mean(1), (d * pn * v).mean(1)
        return pattern_z(t, td, float(np.sqrt(np.median(td ** 2) / 0.4549)))

    for n in (100, 2000):  # no pattern: false detections stay near 1e-3 whatever n is
        assert np.mean([stats(n, 0.0) >= SIGNAL_Z for _ in range(400)]) < 0.01
    assert stats(2000, 0.6) >= SIGNAL_Z  # about 73 % of bits correct: clearly present
