"""Repeated traces of one document: the alpha-spending schedule, the registry trace log, and
how the per-trace budget reaches the threshold, the CLI and the berita acara."""

from __future__ import annotations

import json
import math
import sqlite3
import threading

import numpy as np
import pymupdf
import pytest

from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.decoder.trace import TraceError, check_evidence_types, run_trace
from tapak.marker.issue import IssueSettings, read_recipients
from tapak.marker.layout import sha256_hex
from tapak.registry.chain import (
    KIND_LABELS,
    KIND_TRACE,
    TRACE_FIELDS,
    Registry,
    describe_entry,
    trace_payload_problems,
)
from tapak.registry.signing import Signer
from tapak.registry.verify import verify_registry
from tapak.tardos.accuse import threshold
from tapak.tardos.spending import TraceSpending, eps_for_trace, spending_share
from tests_support import RECIPIENTS, SAMPLE

DOC = "d" * 64
OTHER_DOC = "e" * 64
EVIDENCE = ["a1" * 32, "b2" * 32]


# --- the schedule ----------------------------------------------------------------------------


def test_spending_shares_are_positive_decreasing_and_sum_to_one():
    shares = [spending_share(k) for k in range(1, 20001)]
    assert all(s > 0 for s in shares)
    assert all(a > b for a, b in zip(shares, shares[1:]))
    partial = np.cumsum(shares)
    assert (partial < 1.0).all()  # any number of traces stays inside eps
    assert partial[0] == pytest.approx(6 / math.pi**2) and partial[1] == pytest.approx(7.5 / math.pi**2)
    # The tail after n terms is about 6 / (pi^2 n): the sums approach 1.
    assert 1 - partial[-1] == pytest.approx(6 / (math.pi**2 * 20000), rel=1e-3)
    assert 1 - partial[-1] < 1e-4


def test_eps_for_trace_and_invalid_numbers():
    assert eps_for_trace(1e-6, 1) == pytest.approx(1e-6 * 6 / math.pi**2)
    assert eps_for_trace(1e-6, 3) == pytest.approx(1e-6 * 6 / (9 * math.pi**2))
    assert spending_share(np.int64(2)) == spending_share(2)
    for bad in (0, -1, 1.5, "1", True, None):
        with pytest.raises(ValueError):
            spending_share(bad)
    for eps in (0.0, 1.0, -1e-6):
        with pytest.raises(ValueError):
            eps_for_trace(eps, 1)


def test_trace_spending_logged_and_unlogged():
    first, second = TraceSpending.logged(1e-6, 1), TraceSpending.logged(1e-6, 2)
    assert first.trace_no == 1 and first.eps_share == eps_for_trace(1e-6, 1)
    assert second.eps_share < first.eps_share and second.share == pytest.approx(spending_share(2))
    assert second.eps1(20) == pytest.approx(second.eps_share / 20)
    loose = TraceSpending.unlogged(1e-6)
    assert loose.trace_no is None and loose.eps_share == 1e-6 and loose.share == 1.0
    with pytest.raises(ValueError):  # a share that is not the schedule's
        TraceSpending(1e-6, 1e-6, 2)
    with pytest.raises(ValueError):
        TraceSpending(1e-6, 5e-7, None)
    with pytest.raises(ValueError):
        TraceSpending.logged(1e-6, 0)
    with pytest.raises(ValueError):
        loose.eps1(0)


def test_threshold_rises_with_the_trace_number():
    rng = np.random.default_rng(3)
    p = rng.uniform(0.05, 0.95, 3000)
    w = rng.uniform(0, 1, 3000)
    zs = [threshold(p, TraceSpending.logged(1e-6, k).eps1(20), w) for k in (1, 2, 3, 10)]
    assert all(a < b for a, b in zip(zs, zs[1:]))
    assert threshold(p, TraceSpending.unlogged(1e-6).eps1(20), w) < zs[0]


def test_check_evidence_types():
    check_evidence_types(["foto.JPG", "bocor.pdf", "teks.txt", "tanpa_akhiran", "salinan.docx"])
    with pytest.raises(TraceError, match="jenis berkas tidak dikenal"):
        check_evidence_types(["foto.jpg", "program.exe"])


# --- the decoder uses the budget of the trace ---------------------------------------------------


def test_attribution_uses_the_share_for_threshold_channels_and_probability(issued, ctx):
    out, manifest = issued
    text = extract_pdf_text((out / manifest.copies[4].file).read_bytes())
    from tapak.decoder.trace import collect_from_text

    obs = collect_from_text(text, ctx)
    eps = ctx.params.eps
    loose = run_trace(obs, ctx)
    second = run_trace(obs, ctx, spending=TraceSpending.logged(eps, 2))
    t1, t2 = loose.threshold, second.threshold
    assert t1.trace_no is None and t1.eps_share == eps and t1.eps1 == pytest.approx(eps / ctx.params.n_max)
    assert t2.trace_no == 2 and t2.eps_share == pytest.approx(eps_for_trace(eps, 2))
    assert t2.eps1 == pytest.approx(t2.eps_share / ctx.params.n_max) and t2.threshold > t1.threshold
    assert all(b.threshold > a.threshold for a, b in zip(loose.channels, second.channels)
               if math.isfinite(a.threshold))
    a, b = loose.accused[0], second.accused[0]
    assert a.copy.seq == b.copy.seq == 5 and a.score == b.score and a.log10_bound == b.log10_bound
    # The bound is divided by the share, so it covers every trace of the document together.
    assert b.log10_false_accusation == pytest.approx(a.log10_false_accusation - math.log10(spending_share(2)))
    assert "pelacakan ke-2 dokumen ini" in "\n".join(second.summary_lines())
    with pytest.raises(ValueError, match="eps dokumen"):
        run_trace(obs, ctx, spending=TraceSpending.logged(1e-3, 1))


# --- the registry log ---------------------------------------------------------------------------


def _registry_with_documents(path, signer=None):
    reg = Registry.open(path)
    for doc in (DOC, OTHER_DOC):
        reg.record_document(doc_hash=doc, doc_name="sha256:" + "0" * 64, params={"c": 3, "eps": 1e-6, "n_max": 5},
                            channels=["zw"], shift_mm={}, excluded_rows=[], plan_summary={},
                            threshold_rule="Chernoff", threshold_full=100.0, issuer="uji",
                            issued_at="2026-10-01T00:00:00+00:00", signer=signer)
    return reg


def test_trace_entries_are_numbered_per_document_signed_and_verified(tmp_path):
    signer = Signer(bytes([7]) * 32)
    with _registry_with_documents(tmp_path / "r.db", signer) as reg:
        a1 = reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, signer=signer)
        b1 = reg.record_trace(doc_hash=OTHER_DOC, evidence_sha256=EVIDENCE[:1], eps=1e-6, signer=signer)
        a2 = reg.record_trace(doc_hash=DOC, evidence_sha256=[e.upper() for e in EVIDENCE[:1]], eps=1e-6,
                              signer=signer)
        assert [e.payload["trace_no"] for e in (a1, b1, a2)] == [1, 1, 2]
        assert a2.payload["eps_share"] == eps_for_trace(1e-6, 2) < a1.payload["eps_share"]
        assert a2.payload["evidence_sha256"] == ["a1" * 32]  # hex is stored in lowercase
        assert a1.signed and a1.kind == KIND_TRACE and a1.payload["created_at"] == a1.created_at
        # Data minimization: hashes and numbers only.
        assert set(a1.payload) == TRACE_FIELDS
        assert [p["trace_no"] for p in reg.traces(DOC)] == [1, 2] and len(reg.traces(OTHER_DOC)) == 1
        assert "pelacakan ke-2, 1 berkas bukti" in describe_entry(a2)
        with pytest.raises(ValueError, match="tidak tercatat"):
            reg.record_trace(doc_hash="f" * 64, evidence_sha256=EVIDENCE, eps=1e-6)
    rep = verify_registry(tmp_path / "r.db", signer.public_key_hex)
    assert rep.ok, rep.problems
    assert rep.kinds == {"document": 2, "trace": 3} and rep.traces == {DOC: 2, OTHER_DOC: 1}
    assert KIND_LABELS[KIND_TRACE] == "pelacakan"
    assert any("pelacakan 3" in line for line in rep.lines())
    assert any(line.strip().startswith("Pelacakan") and "2 dokumen" in line for line in rep.lines())
    assert rep.to_dict()["traces"] == {DOC: 2, OTHER_DOC: 1}


def test_registry_without_trace_entries_still_verifies(tmp_path):
    signer = Signer(bytes([7]) * 32)
    _registry_with_documents(tmp_path / "r.db", signer).close()
    rep = verify_registry(tmp_path / "r.db", signer.public_key_hex)
    assert rep.ok and rep.traces == {} and "Pelacakan" not in "\n".join(rep.lines())


def test_concurrent_traces_never_share_a_number(tmp_path):
    _registry_with_documents(tmp_path / "r.db").close()
    numbers: list[int] = []
    lock = threading.Lock()

    def worker():
        for _ in range(3):
            with Registry.open(tmp_path / "r.db") as reg:
                n = reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6).payload["trace_no"]
            with lock:
                numbers.append(n)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(numbers) == list(range(1, 19))


def test_trace_payload_validation():
    good = {"doc_hash": DOC, "trace_no": 2, "evidence_sha256": EVIDENCE, "eps": 1e-6,
            "eps_share": eps_for_trace(1e-6, 2), "created_at": "2026-10-22T08:00:00.000+00:00"}
    assert trace_payload_problems(good) == []
    for change in ({"eps_share": 1e-6}, {"trace_no": 0}, {"trace_no": True}, {"evidence_sha256": []},
                   {"evidence_sha256": ["xyz"]}, {"doc_hash": "R001"}, {"eps": 2}, {"created_at": "kemarin"},
                   {"nama": "Penerima Fiktif 1"}, {"trace_no": 10**400}, {"eps": 10**400},
                   {"eps_share": 10**400}, {"eps_share": float("nan")}):
        assert trace_payload_problems({**good, **change}), change
    assert trace_payload_problems("bukan objek") and trace_payload_problems({"created_at": [[[]]]})


def test_append_refuses_a_malformed_trace_entry(tmp_path):
    with _registry_with_documents(tmp_path / "r.db") as reg:
        payload = {"doc_hash": DOC, "trace_no": 1, "evidence_sha256": EVIDENCE, "eps": 1e-6,
                   "eps_share": 1e-6, "created_at": "2026-10-22T08:00:00.000+00:00"}
        with pytest.raises(ValueError, match="eps_share"):
            reg.append(KIND_TRACE, payload)  # the whole eps for trace 1 is not the schedule
        with pytest.raises(ValueError, match="skema"):
            reg.append(KIND_TRACE, {**payload, "nama": "Penerima Fiktif 1"})


def _good_trace(reg, k, doc=DOC, eps=1e-6):
    stamp = reg.head().created_at
    return {"doc_hash": doc, "trace_no": k, "evidence_sha256": EVIDENCE, "eps": eps,
            "eps_share": eps_for_trace(eps, k), "created_at": stamp}


def test_verifier_catches_a_forged_trace_log(tmp_path):
    with _registry_with_documents(tmp_path / "r.db") as reg:
        reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6)
        reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6)
        pub = Signer(bytes([7]) * 32).public_key_hex
        assert verify_registry(tmp_path / "r.db", pub, require_signed=False).ok
        # A well-formed row that reuses an earlier number (to get a larger share again).
        forged = reg.append(KIND_TRACE, _good_trace(reg, 1), created_at=reg.head().created_at)
        rep = verify_registry(tmp_path / "r.db", pub, require_signed=False)
        assert not rep.ok and any(seq == forged.seq and "ke-1, seharusnya ke-3" in text for seq, text in rep.problems)
    with _registry_with_documents(tmp_path / "s.db") as reg:
        stray = reg.append(KIND_TRACE, _good_trace(reg, 1, doc="f" * 64), created_at=reg.head().created_at)
        other_eps = reg.append(KIND_TRACE, _good_trace(reg, 1, eps=0.5), created_at=reg.head().created_at)
        rep = verify_registry(tmp_path / "s.db", pub, require_signed=False)
        texts = dict(rep.problems)
        assert "tidak tercatat sebelumnya" in texts[stray.seq] and "berbeda dari eps" in texts[other_eps.seq]


def test_tampered_trace_entry_is_detected(tmp_path):
    signer = Signer(bytes([7]) * 32)
    with _registry_with_documents(tmp_path / "r.db", signer) as reg:
        reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, signer=signer)
        second = reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, signer=signer)
    con = sqlite3.connect(tmp_path / "r.db")
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        con.execute(f"DROP TRIGGER {name}")
    # Renumber trace 2 as trace 1 with the larger share, as someone wanting a lower threshold would.
    payload = dict(second.payload, trace_no=1, eps_share=eps_for_trace(1e-6, 1))
    from tapak.registry.chain import canonical_json

    con.execute("UPDATE entries SET payload = ? WHERE seq = ?", (canonical_json(payload).decode(), second.seq))
    con.commit()
    con.close()
    rep = verify_registry(tmp_path / "r.db", signer.public_key_hex)
    assert not rep.ok and second.seq in {seq for seq, _ in rep.problems}


# --- the service: logged before decoding, numbered, smaller share each time -----------------------


def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    from tapak.config import load_settings

    return load_settings()


def _issue(tmp_path, monkeypatch, n=4, record=True, signing_key=True, sign_now=True):
    from tapak.service import ensure_keys, issue_document

    s = _settings(tmp_path, monkeypatch)
    keys = ensure_keys(s, create_signing_key=signing_key)
    issue_keys = keys if sign_now else type(keys)(keys.code_secret, None, keys.public_key_hex)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:n], IssueSettings(workers=1), "uji", issue_keys,
                         record=record)
    text = extract_pdf_text((out.folder / "salinan" / out.manifest.copies[1].file).read_bytes())
    return s, keys, out, text.encode("utf-8")


def test_repeated_traces_are_logged_before_decoding_with_a_shrinking_share(tmp_path, monkeypatch, capsys):
    from tapak.decoder import trace as trace_module
    from tapak.service import UNLOGGED_TRACE_NOTE, trace_evidence

    s, keys, out, evidence = _issue(tmp_path, monkeypatch)
    doc = out.manifest.doc_hash
    seen: list[int] = []
    original = trace_module.trace_files

    def spy(items, ctx, spending=None):
        with Registry.open(s.registry_path) as reg:  # the entry exists before anything is decoded
            seen.append(len(reg.traces(doc)))
        assert spending is not None and spending.trace_no == seen[-1]
        return original(items, ctx, spending)

    monkeypatch.setattr(trace_module, "trace_files", spy)
    first = trace_evidence(s, doc, "bocor.txt", evidence, keys)
    second = trace_evidence(s, doc, "bocor.txt", evidence, keys)
    assert seen == [1, 2]
    t1, t2 = first.attribution.threshold, second.attribution.threshold
    assert (t1.trace_no, t2.trace_no) == (1, 2)
    assert t1.eps == t2.eps == out.manifest.tardos_params.eps
    assert t2.eps_share < t1.eps_share and t2.threshold > t1.threshold
    assert [c.copy.seq for c in first.attribution.accused] == [c.copy.seq for c in second.attribution.accused] == [2]
    assert first.trace_signed and second.trace_signed and second.trace_entry == first.trace_entry + 1
    assert UNLOGGED_TRACE_NOTE not in first.attribution.notes

    with Registry.open(s.registry_path) as reg:
        rows = reg.entries(KIND_TRACE)
    assert [r.payload["trace_no"] for r in rows] == [1, 2] and all(r.signed for r in rows)
    assert rows[0].payload["evidence_sha256"] == [sha256_hex(evidence)]
    rep = verify_registry(s.registry_path, s.public_key_path.read_text().strip())
    assert rep.ok and rep.traces == {doc: 2}
    # No names, no verdict, no content in the registry file.
    raw = s.registry_path.read_bytes()
    for r in read_recipients(RECIPIENTS)[:4]:
        assert r.nama.encode() not in raw
    assert b"teridentifikasi" not in raw and b"Fiktif" not in raw

    # The CLI says which trace this was and that it was logged.
    from tapak import cli

    path = tmp_path / "bocor.txt"
    path.write_bytes(evidence)
    capsys.readouterr()
    assert cli.main(["trace", str(path), "--doc", doc]) == 0
    printed = capsys.readouterr().out
    assert "pelacakan ke-3 dokumen ini, jatah eps" in printed and "dicatat sebelum dekode" in printed


def test_berita_acara_shows_the_trace_number_and_share(tmp_path, monkeypatch):
    from tapak.service import trace_evidence, write_report

    s, keys, out, evidence = _issue(tmp_path, monkeypatch, n=3)
    trace_evidence(s, out.manifest.doc_hash, "a.txt", evidence, keys)
    outcome = trace_evidence(s, out.manifest.doc_hash, "a.txt", evidence, keys)
    with pymupdf.open(stream=write_report(outcome), filetype="pdf") as pdf:
        text = " ".join(" ".join(page.get_text() for page in pdf).split())
    compact = text.replace(" ", "")  # long lines and commands may wrap anywhere
    assert "pelacakanke-2untukdokumenini,dicatatdiregistrisebelumdekode" in compact
    assert "15,2%darieps" in compact  # 6 / (pi^2 x 4)
    assert "--pelacakan-ke2" in compact


def test_unrecorded_document_spends_the_whole_eps_with_a_note(tmp_path, monkeypatch):
    from tapak.service import UNLOGGED_TRACE_NOTE, trace_evidence

    s, keys, out, evidence = _issue(tmp_path, monkeypatch, record=False, signing_key=False)
    assert not s.public_key_path.exists()
    outcome = trace_evidence(s, out.manifest.doc_hash, "a.txt", evidence, keys)
    t = outcome.attribution.threshold
    assert t.trace_no is None and t.eps_share == t.eps and outcome.trace_entry is None
    assert UNLOGGED_TRACE_NOTE in outcome.attribution.notes
    assert [c.copy.seq for c in outcome.attribution.accused] == [2]
    assert not s.registry_path.exists()  # nothing was created to log it in


def test_trace_entry_waits_unsigned_while_older_entries_await_review(tmp_path, monkeypatch):
    from tapak.service import UNSIGNED_TRACE_NOTE, trace_evidence

    s, keys, out, evidence = _issue(tmp_path, monkeypatch, sign_now=False)
    assert keys.signer is not None
    outcome = trace_evidence(s, out.manifest.doc_hash, "a.txt", evidence, keys)
    assert outcome.attribution.threshold.trace_no == 1 and not outcome.trace_signed
    assert UNSIGNED_TRACE_NOTE in outcome.attribution.notes


def test_a_trace_that_cannot_be_logged_is_not_performed(tmp_path, monkeypatch):
    from tapak.decoder import trace as trace_module
    from tapak.service import trace_evidence

    s, keys, out, evidence = _issue(tmp_path, monkeypatch, n=2)

    def locked(self, **kw):
        raise sqlite3.OperationalError("database is locked")

    def never(*a, **k):
        raise AssertionError("evidence decoded although the trace was not logged")

    monkeypatch.setattr(Registry, "record_trace", locked)
    monkeypatch.setattr(trace_module, "trace_files", never)
    with pytest.raises(TraceError, match="tidak dapat dicatat"):
        trace_evidence(s, out.manifest.doc_hash, "a.txt", evidence, keys)
    monkeypatch.undo()
    s = _settings(tmp_path, monkeypatch)
    with pytest.raises(TraceError, match="jenis berkas"):  # refused before a number is used
        trace_evidence(s, out.manifest.doc_hash, "a.exe", evidence, keys)
    with Registry.open(s.registry_path) as reg:
        assert reg.traces(out.manifest.doc_hash) == []


# --- loose mode -----------------------------------------------------------------------------------


def test_loose_mode_keeps_the_whole_eps_and_can_repeat_a_logged_trace(tmp_path, issued, secret, capsys):
    from tapak import cli
    from tapak.service import UNLOGGED_TRACE_NOTE

    out, manifest = issued
    mpath = tmp_path / "manifest.json"
    mpath.write_text(manifest.to_json(), encoding="utf-8")
    key = tmp_path / "rahasia.key"
    key.write_text(secret.hex(), encoding="ascii")
    evidence = tmp_path / "bocor.txt"
    evidence.write_text(extract_pdf_text((out / manifest.copies[2].file).read_bytes()), encoding="utf-8")
    base = ["--data", str(tmp_path / "data"), "trace", str(evidence), "--master", str(SAMPLE),
            "--manifest", str(mpath), "--secret", str(key)]

    assert cli.main(base + ["--json", str(tmp_path / "lepas.json")]) == 0
    printed = capsys.readouterr().out
    loose = json.loads((tmp_path / "lepas.json").read_text(encoding="utf-8"))
    assert loose["threshold"]["trace_no"] is None and loose["threshold"]["eps_share"] == manifest.tardos_params.eps
    assert UNLOGGED_TRACE_NOTE in loose["notes"] and "tidak dicatat di registri" in printed
    assert not (tmp_path / "data" / "registry.db").exists()

    assert cli.main(base + ["--pelacakan-ke", "2", "--json", str(tmp_path / "ulang.json")]) == 0
    capsys.readouterr()
    again = json.loads((tmp_path / "ulang.json").read_text(encoding="utf-8"))
    assert again["threshold"]["trace_no"] == 2
    assert again["threshold"]["threshold"] > loose["threshold"]["threshold"]
    assert UNLOGGED_TRACE_NOTE not in again["notes"]

    code = cli.main(["--data", str(tmp_path / "data"), "trace", str(evidence), "--doc", "a" * 16,
                     "--pelacakan-ke", "1"])
    assert code == 2 and "hanya untuk mode lepas" in capsys.readouterr().err
