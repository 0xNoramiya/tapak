"""External anchor log (tapak.registry.anchor): entries deleted from the end of the registry,
rewritten or forked are refused before a trace; a missing log is refused too; crash windows are
handled deterministically; signatures; no document data in the log; verify, CLI, berita acara
and web. Every name, document and reason here is fictional."""

from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import threading

import pymupdf
import pytest

from tapak import cli
from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.decoder.trace import TraceError
from tapak.marker.issue import IssueSettings, read_recipients
from tapak.marker.layout import sha256_hex
from tapak.registry import anchor as anchor_mod
from tapak.registry.anchor import (
    MEDIA_MARKER,
    AnchorError,
    AnchorLog,
    AnchorRefused,
    AnchorStatus,
    AnchorUnavailable,
    AnchorWriteError,
    acknowledge,
    append_lines,
    clean_reason,
    compare_anchor,
    create_anchor_file,
    entry_body,
    line_text,
    location_warnings,
    mount_note,
    parse_anchor_bytes,
    parse_line,
    plan_acknowledgement,
    read_anchor_file,
    read_anchor_incremental,
    read_media_id,
    read_registry_rows,
    reason_digest,
    required_by,
    restart_note,
    rotate_log,
    seq_span,
    start_body,
    start_log,
    unconfigured_status,
    verify_line,
)
from tapak.registry.chain import (
    KIND_ANCHOR,
    KIND_LABELS,
    TRIGGERS,
    Registry,
    anchor_payload_problems,
    canonical_json,
    describe_entry,
)
from tapak.registry.signing import Signer
from tapak.registry.verify import verify_registry
from tests_support import RECIPIENTS, ROOT, SAMPLE

DOC = "d" * 64
EVIDENCE = ["a1" * 32]
SIGNER = Signer(bytes([7]) * 32)
PUB = SIGNER.public_key_hex
LINE_KEYS = {"v", "type", "log_id", "seq", "entry_hash", "kind", "created_at", "sig", "restart", "reason", "released",
             "media", "previous"}


def _new_registry(path, signer=SIGNER):
    with Registry.open(path) as reg:
        reg.record_document(doc_hash=DOC, doc_name="sha256:" + "0" * 64, params={"c": 3, "eps": 1e-6, "n_max": 5},
                            channels=["zw"], shift_mm={}, excluded_rows=[], plan_summary={},
                            threshold_rule="Chernoff", threshold_full=100.0, issuer="uji",
                            issued_at="2026-10-01T00:00:00+00:00", signer=signer)


@pytest.fixture()
def anchored(tmp_path):
    """A registry with one signed document entry and a started anchor log on 'separate' storage."""
    reg_path = tmp_path / "data" / "registry.db"
    _new_registry(reg_path)
    (tmp_path / "terpisah").mkdir()
    log_path = tmp_path / "terpisah" / "jangkar.log"
    start_log(reg_path, log_path, SIGNER, PUB)
    return reg_path, log_path


def _log(log_path, signer=SIGNER):
    return AnchorLog(log_path, signer=signer, public_key=PUB)


def _trace(reg_path, log_path, signer=SIGNER, evidence=EVIDENCE):
    """Append one trace entry through an anchored registry, as the service does."""
    log = _log(log_path, signer)
    with Registry.open(reg_path, anchor=log) as reg:
        entry = reg.record_trace(doc_hash=DOC, evidence_sha256=evidence, eps=1e-6, signer=signer)
    return entry, log.status


def _status(reg_path, log_path) -> AnchorStatus:
    return _log(log_path).inspect_registry_file(reg_path)


def _edit(reg_path, *statements):
    """Change the registry file the way someone working outside TAPAK would: triggers off, edit,
    triggers back, so the file opens normally again."""
    con = sqlite3.connect(reg_path)
    for name in TRIGGERS:
        con.execute(f"DROP TRIGGER {name}")
    for sql, args in statements:
        con.execute(sql, args)
    for name, body in TRIGGERS.items():
        con.execute(f"CREATE TRIGGER {name} {body}")
    con.commit()
    con.close()


def _drop_tail(reg_path, n=1):
    _edit(reg_path, ("DELETE FROM entries WHERE seq > (SELECT MAX(seq) FROM entries) - ?", (n,)))


def _lines(log_path):
    return [json.loads(t) for t in log_path.read_text(encoding="utf-8").splitlines()]


# --- appending and comparing ---------------------------------------------------------------------


def test_every_entry_gets_one_line_after_its_commit(anchored):
    reg_path, log_path = anchored
    lines = _lines(log_path)
    assert lines[0]["type"] == "start" and lines[0]["restart"] is False and lines[0]["reason"] is None
    assert [(line["seq"], line["kind"]) for line in lines[1:]] == [(1, "document"), (2, KIND_ANCHOR)]
    entry, status = _trace(reg_path, log_path)
    last = _lines(log_path)[-1]
    assert {k: last[k] for k in ("type", "seq", "entry_hash", "kind", "created_at", "log_id")} == {
        "type": "entry", "seq": entry.seq, "entry_hash": entry.entry_hash, "kind": "trace",
        "created_at": entry.created_at, "log_id": lines[0]["log_id"]}
    assert set(last) == {"v", "type", "log_id", "seq", "entry_hash", "kind", "created_at", "sig"}
    assert status.ok and status.recorded == [entry.seq] and status.anchored_seq == entry.seq == 3
    with Registry.open(reg_path) as reg:
        event = reg.entries(KIND_ANCHOR)[0]
    assert event.payload == {"event": "start", "log_id": lines[0]["log_id"], "released": [], "reason_sha256": None,
                             "created_at": event.created_at}
    assert KIND_LABELS[KIND_ANCHOR] == "log jangkar" and "peristiwa start" in describe_entry(event)
    assert verify_registry(reg_path, PUB).ok and required_by(read_registry_rows(reg_path)) == event.seq


def test_compare_reports_a_match_and_a_lag_never_an_alarm(anchored):
    reg_path, log_path = anchored
    st = _status(reg_path, log_path)
    assert st.ok and st.anchored_seq == st.registry_head == 2 and st.lag == 0 and st.signed_lines == 3
    assert st.describe() == "cocok dengan registri sampai entri #2"
    # An entry appended without the anchor hook (tapak canary-dns --anchor, for example) only lags.
    with Registry.open(reg_path) as reg:
        reg.append("canary_anchor", {"events_seq": 1, "events_hash": "0" * 64})
    st = _status(reg_path, log_path)
    assert st.ok and st.lag == 1 and "belum tercatat di log" in st.describe()
    entry, status = _trace(reg_path, log_path, signer=None)
    assert status.completed == [3] and status.recorded == [entry.seq] and _status(reg_path, log_path).lag == 0


def test_tail_deletion_is_refused_before_the_next_trace(anchored):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    second, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)  # the newest trace entry is gone; the next trace would get number 2 again
    assert verify_registry(reg_path, PUB).ok  # invisible to the chain alone
    st = _status(reg_path, log_path)
    assert not st.ok and st.releasable == [(second.seq, second.entry_hash)] and not st.blocking
    assert (f"log jangkar mencatat entri #{second.seq} (1 pelacakan) yang tidak ada lagi di registri; registri kini "
            f"berakhir di entri #{second.seq - 1}: entri dihapus dari ujung rantai") in st.problems[0]
    with pytest.raises(AnchorRefused) as refused:
        _trace(reg_path, log_path)
    text = str(refused.value)
    assert "tapak verify" in text and "tapak jangkar akui" in text and "jatah eps" in text
    with Registry.open(reg_path) as reg:
        assert len(reg.traces(DOC)) == 1  # nothing was appended


def test_rewritten_entry_is_refused(anchored):
    reg_path, log_path = anchored
    first, _ = _trace(reg_path, log_path)
    payload = dict(first.payload, evidence_sha256=["b2" * 32])
    _edit(reg_path, ("UPDATE entries SET payload = ? WHERE seq = ?", (canonical_json(payload).decode(), first.seq)))
    st = _status(reg_path, log_path)
    assert not st.ok and st.blocking and not st.releasable
    assert any(f"isi entri #{first.seq} diubah" in p for p in st.problems)
    with pytest.raises(AnchorRefused, match="diubah"):
        _trace(reg_path, log_path)
    with pytest.raises(AnchorError, match="harus diperbaiki"):  # an acknowledgement cannot release an edit
        plan_acknowledgement(reg_path, _log(log_path))


def test_fork_is_refused(anchored):
    reg_path, log_path = anchored
    first, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)
    with Registry.open(reg_path) as reg:  # a valid entry in its place, written without the anchor
        other = reg.record_trace(doc_hash=DOC, evidence_sha256=["c3" * 32], eps=1e-6)
    assert other.seq == first.seq and other.entry_hash != first.entry_hash
    assert verify_registry(reg_path, PUB, require_signed=False).ok
    st = _status(reg_path, log_path)
    assert not st.ok and st.releasable == [(first.seq, first.entry_hash)]
    assert any("diganti entri lain" in p and "bercabang" in p for p in st.problems)
    with pytest.raises(AnchorRefused, match="bercabang"):
        _trace(reg_path, log_path)


def test_missing_unreadable_or_unstarted_log_is_refused(anchored, tmp_path):
    reg_path, log_path = anchored
    moved = log_path.rename(log_path.with_name("dipindah.log"))
    st = _status(reg_path, log_path)
    assert st.missing and not st.ok and "tidak ditemukan" in st.problems[0] and "--ulang --alasan" in st.problems[0]
    assert st.unavailable == "missing" and st.describe().startswith("HILANG: log jangkar tidak ditemukan")
    assert any(line.strip() == "HILANG" for line in verify_registry(reg_path, PUB, anchor_log=log_path).lines())
    with pytest.raises(AnchorRefused, match="tidak ditemukan"):
        _trace(reg_path, log_path)
    assert not log_path.exists()  # a write never recreates a missing log
    log_path.mkdir()  # something else in its place
    st = _status(reg_path, log_path)
    assert st.missing and "bukan berkas biasa" in st.problems[0] and "jangan menghapus" in st.problems[0]
    assert st.unavailable == "unreadable" and st.describe().startswith("TIDAK TERBACA: ")
    log_path.rmdir()
    moved.rename(log_path)
    assert _status(reg_path, log_path).ok
    fresh = tmp_path / "baru.db"
    _new_registry(fresh)
    st = AnchorLog(tmp_path / "terpisah" / "belum.log").inspect_registry_file(fresh)
    assert st.missing and "belum dimulai" in st.problems[0] and "tapak jangkar mulai" in st.problems[0]
    assert st.unavailable == "not_started" and st.describe().startswith("BELUM DIMULAI: ")
    assert not AnchorLog(tmp_path / "terpisah" / "kosong.log", public_key=PUB).inspect_registry_file(
        tmp_path / "tidak-ada.db").ok


# --- crash windows ------------------------------------------------------------------------------------


def test_crash_between_commit_and_line_is_completed_on_the_next_write(anchored, monkeypatch):
    reg_path, log_path = anchored
    real = anchor_mod.append_lines

    def crash(path, lines):
        raise OSError(errno.EIO, "simulasi")

    monkeypatch.setattr(anchor_mod, "append_lines", crash)
    with pytest.raises(AnchorWriteError, match="sudah tercatat di registri") as failed:
        _trace(reg_path, log_path)
    lost = failed.value.entries[0]
    monkeypatch.setattr(anchor_mod, "append_lines", real)
    with Registry.open(reg_path) as reg:
        assert reg.head().entry_hash == lost.entry_hash  # committed before the line
    st = _status(reg_path, log_path)
    assert st.ok and st.lag == 1 and st.anchored_seq == lost.seq - 1  # one behind: completed, never an alarm
    rep = verify_registry(reg_path, PUB, anchor_log=log_path)
    assert rep.ok and any("belum tercatat di log jangkar" in w for w in rep.warnings)
    following, status = _trace(reg_path, log_path)
    assert status.completed == [lost.seq] and status.recorded == [following.seq]
    assert following.payload["trace_no"] == 2
    assert [line.get("seq") for line in _lines(log_path)][-2:] == [lost.seq, following.seq]


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores file modes")
def test_a_read_only_log_is_refused_before_the_trace_takes_a_number(anchored):
    reg_path, log_path = anchored
    with Registry.open(reg_path) as reg:
        head = reg.head().seq
    log_path.chmod(0o444)
    try:
        with pytest.raises(AnchorUnavailable, match="tidak dapat ditulis") as refused:
            _trace(reg_path, log_path)
        assert "ditolak sebelum entri baru dicatat" in str(refused.value)
        with Registry.open(reg_path) as reg:
            assert reg.head().seq == head and not reg.traces(DOC)  # nothing committed, no number used
    finally:
        log_path.chmod(0o644)
    entry, status = _trace(reg_path, log_path)
    assert status.ok and entry.payload["trace_no"] == 1


def test_a_line_ahead_of_the_registry_is_always_an_alarm(anchored):
    reg_path, log_path = anchored
    st = _status(reg_path, log_path)
    # As if a line had been written for an entry that a rollback then took back.
    append_lines(log_path, [line_text(entry_body(st.log_id, st.registry_head + 1, "trace",
                                                 "2026-10-22T08:00:00.000+00:00", "e" * 64))])
    st = _status(reg_path, log_path)
    assert not st.ok and f"#{st.registry_head + 1}" in st.problems[0] and "tidak ada lagi di registri" in st.problems[0]
    with pytest.raises(AnchorRefused):
        _trace(reg_path, log_path)


class _FailingCommit:
    """A connection whose COMMIT fails (disk error), to check the anchor never sees that entry."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_a_rolled_back_or_failed_commit_never_reaches_the_log(anchored):
    reg_path, log_path = anchored
    before = log_path.read_bytes()
    with Registry.open(reg_path, anchor=_log(log_path)) as reg:
        with pytest.raises(RuntimeError, match="sengaja"):
            with reg.transaction():
                reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, signer=SIGNER)
                raise RuntimeError("sengaja dibatalkan")
        real, reg._conn = reg._conn, _FailingCommit(reg._conn)
        with pytest.raises(sqlite3.OperationalError):
            reg.record_trace(doc_hash=DOC, evidence_sha256=EVIDENCE, eps=1e-6, signer=SIGNER)
        reg._conn = real
        assert reg.traces(DOC) == [] and not reg._conn.in_transaction
    assert log_path.read_bytes() == before


def test_a_torn_last_line_is_ignored_then_closed(anchored):
    reg_path, log_path = anchored
    with open(log_path, "ab") as fh:
        fh.write(b'{"created_at":"2026-10-')  # the process died in the middle of a line
    st = _status(reg_path, log_path)
    assert st.ok and any("terpotong" in w for w in st.warnings)
    entry, status = _trace(reg_path, log_path)
    assert status.ok and '{"created_at":"2026-10-\n' in log_path.read_text(encoding="utf-8")
    st = _status(reg_path, log_path)
    assert st.ok and st.anchored_seq == entry.seq and any("tidak dapat dibaca dan diabaikan" in w for w in st.warnings)
    data = log_path.read_bytes()
    assert parse_anchor_bytes(log_path, data[:-1]).torn_tail is False  # a complete last line still counts
    assert parse_anchor_bytes(log_path, data[:-5]).torn_tail is True


def test_an_interrupted_start_is_finished_by_running_it_again(tmp_path, monkeypatch):
    reg_path, log_path = tmp_path / "r.db", tmp_path / "jangkar.log"
    _new_registry(reg_path)

    def crash(self, **kw):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as m:
        m.setattr(Registry, "record_anchor_event", crash)
        with pytest.raises(sqlite3.OperationalError):
            start_log(reg_path, log_path, SIGNER, PUB)
    assert log_path.exists() and required_by(read_registry_rows(reg_path)) is None
    st = _status(reg_path, log_path)
    assert not st.ok and "belum tercatat di registri" in st.problems[0]
    with pytest.raises(AnchorError, match="dengan --ulang|ulangi perintah yang sama"):
        start_log(reg_path, log_path, SIGNER, PUB, reason="alasan lain", restart=True)
    status = start_log(reg_path, log_path, SIGNER, PUB)
    assert status.ok and _status(reg_path, log_path).ok
    with pytest.raises(AnchorError, match="tidak perlu dimulai lagi"):
        start_log(reg_path, log_path, SIGNER, PUB)


def test_concurrent_anchored_writers_never_raise_a_false_alarm(anchored):
    reg_path, log_path = anchored
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(3):
                _trace(reg_path, log_path)
                assert _status(reg_path, log_path).ok  # read-only checks while others write
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    st = _status(reg_path, log_path)
    assert st.ok and st.lag == 0 and st.anchored_seq == st.registry_head == 11


# --- signatures and contents ------------------------------------------------------------------------


def test_lines_are_signed_and_a_forged_line_is_refused(anchored):
    reg_path, log_path = anchored
    entry, _ = _trace(reg_path, log_path)
    lines = [parse_line(t, i) for i, t in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1)]
    assert all(line is not None and verify_line(line, PUB) for line in lines)
    assert not verify_line(lines[-1], Signer(bytes([9]) * 32).public_key_hex)
    # A genuine pair, signed by another key: only the signature gives it away.
    st = _status(reg_path, log_path)
    forged = line_text(entry_body(st.log_id, entry.seq, "trace", entry.created_at, entry.entry_hash),
                       Signer(bytes([9]) * 32))
    append_lines(log_path, [forged])
    st = _status(reg_path, log_path)
    assert not st.ok and any("tanda tangan baris ke-" in p for p in st.problems)
    # Without the public key the signature cannot be checked: said so, never silently.
    st = AnchorLog(log_path).inspect_registry_file(reg_path)
    assert st.ok and any("tidak diperiksa" in w for w in st.warnings)


def test_unsigned_registry_gets_unsigned_lines(tmp_path):
    reg_path, log_path = tmp_path / "r.db", tmp_path / "jangkar.log"
    _new_registry(reg_path, signer=None)
    start_log(reg_path, log_path)
    entry, status = _trace(reg_path, log_path, signer=None)
    assert status.ok and all("sig" not in line for line in _lines(log_path))
    assert not entry.signed and AnchorLog(log_path).inspect_registry_file(reg_path).signed_lines == 0


def test_the_log_holds_no_document_or_recipient_data(tmp_path, monkeypatch, issued_base):
    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    from tapak.service import trace_evidence

    trace_evidence(s, doc, "bocor.txt", evidence)
    raw = log_path.read_bytes()
    for r in read_recipients(RECIPIENTS):
        assert r.nama.encode() not in raw and r.recipient_id.encode() not in raw
    words = {w for w in extract_pdf_text(SAMPLE.read_bytes()).split() if len(w) > 5 and w.isalpha()}
    assert len(words) > 20 and not [w for w in words if w.encode() in raw]
    assert doc.encode() not in raw and b"nota_dinas" not in raw and b"payload" not in raw
    for line in _lines(log_path):
        assert set(line) <= LINE_KEYS and line["v"] == 1


# --- validation helpers -------------------------------------------------------------------------------


def test_anchor_payload_and_line_validation():
    good = {"event": "ack", "log_id": "ab" * 16, "released": [[3, "c" * 64], [4, "d" * 64]],
            "reason_sha256": "e" * 64, "created_at": "2026-10-22T08:00:00.000+00:00"}
    assert anchor_payload_problems(good) == []
    assert anchor_payload_problems({**good, "event": "start", "released": [], "reason_sha256": None}) == []
    for change in ({"event": "hapus"}, {"event": ["ack"]}, {"log_id": "x"}, {"released": []},
                   {"released": [[4, "d" * 64], [3, "c" * 64]]}, {"released": [[0, "c" * 64]]},
                   {"released": [[True, "c" * 64]]}, {"reason_sha256": None}, {"reason_sha256": "alasan"},
                   {"created_at": "kemarin"}, {"nama": "Penerima Fiktif 1"}):
        assert anchor_payload_problems({**good, **change}), change
    assert anchor_payload_problems({**good, "event": "restart", "released": [], "reason_sha256": None})
    assert anchor_payload_problems("bukan objek")

    entry = line_text(entry_body("ab" * 16, 5, "trace", "2026-10-22T08:00:00.000+00:00", "f" * 64))
    assert entry.endswith("\n") and parse_line(entry[:-1], 1).seq == 5
    start = line_text(start_body("ab" * 16, "2026-10-22T08:00:00.000+00:00", True, "media rusak (uji)"))
    assert parse_line(start[:-1], 1).restart is True
    body = json.loads(entry)
    for change in ({"v": True}, {"v": 2}, {"type": "hapus"}, {"seq": 0}, {"seq": "5"}, {"entry_hash": "f"},
                   {"log_id": "AB" * 16}, {"created_at": "kemarin"}, {"kind": ""}, {"sig": None}, {"sig": "zz"},
                   {"nama": "Penerima Fiktif 1"}):
        assert parse_line(json.dumps({**body, **change}), 1) is None, change
    assert parse_line(json.dumps({**json.loads(start), "reason": None}), 1) is None  # a restart needs its reason
    assert parse_line("{bukan json", 1) is None and parse_line("[]", 1) is None

    assert clean_reason("  media   lama\nrusak ", required=True) == "media lama rusak"
    assert clean_reason(None, required=False) is None
    with pytest.raises(AnchorError, match="wajib"):
        clean_reason(" ", required=True)
    with pytest.raises(AnchorError, match="terlalu panjang"):
        clean_reason("x" * 301, required=True)
    assert reason_digest(None) is None and len(reason_digest("uji")) == 64
    assert seq_span([7, 3, 4, 5, 9]) == "#3..#5, #7, #9"
    assert unconfigured_status([]).describe().startswith("tidak diatur; entri yang dihapus dari ujung registri")


def test_location_inside_the_data_folder_is_warned_about(tmp_path):
    data = tmp_path / "data"
    reg_path = data / "registry.db"
    _new_registry(reg_path)
    status = start_log(reg_path, data / "jangkar.log", SIGNER, PUB, protected=[data])
    assert status.ok and any("tidak melindungi" in w for w in status.warnings)
    assert location_warnings(tmp_path / "lain" / "jangkar.log", [data]) == []
    with pytest.raises(AnchorError, match="tidak ada"):  # the separate storage is not mounted
        start_log(reg_path, tmp_path / "belum-dipasang" / "jangkar.log", SIGNER, PUB)
    with pytest.raises(FileExistsError):
        create_anchor_file(data / "jangkar.log", "x\n")


def test_read_anchor_file_and_compare_on_their_own(anchored):
    reg_path, log_path = anchored
    log = read_anchor_file(log_path)
    assert log.lines[0].type == "start" and not log.unreadable and not log.torn_tail
    st = compare_anchor(log, read_registry_rows(reg_path), PUB)
    assert st.ok and st.to_dict()["anchored_seq"] == 2 and st.summary().startswith("Log jangkar: cocok")
    assert not compare_anchor(log, [], PUB).ok  # the whole registry gone


# --- acknowledgement and restart -------------------------------------------------------------------


def test_acknowledgement_releases_only_what_is_gone_and_is_recorded(anchored, monkeypatch):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    second, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)
    plan = plan_acknowledgement(reg_path, _log(log_path))
    assert plan.releasable == [(second.seq, second.entry_hash)]
    with pytest.raises(AnchorError, match="wajib"):
        acknowledge(reg_path, _log(log_path), "")
    # The ack entry commits, then the process dies before its line: the alarm stays.
    real = anchor_mod.append_lines
    monkeypatch.setattr(anchor_mod, "append_lines", lambda path, lines: (_ for _ in ()).throw(OSError(errno.EIO, "x")))
    with pytest.raises(AnchorWriteError, match="jalankan perintah ini lagi"):
        acknowledge(reg_path, _log(log_path), "uji pemulihan fiktif")
    monkeypatch.setattr(anchor_mod, "append_lines", real)
    assert not _status(reg_path, log_path).ok
    status = acknowledge(reg_path, _log(log_path), "uji pemulihan fiktif")
    assert status.ok and len(status.acks) == 1 and status.released == [(second.seq, second.entry_hash)]
    assert status.released_traces == 1 and "1 entri pelacakan di antaranya hilang" in status.describe()
    with Registry.open(reg_path) as reg:
        events = [e.payload for e in reg.entries(KIND_ANCHOR)]
    assert [e["event"] for e in events] == ["start", "ack", "ack"]
    assert events[-1]["released"] == [[second.seq, second.entry_hash]]
    assert events[-1]["reason_sha256"] == reason_digest("uji pemulihan fiktif")
    assert _lines(log_path)[-1]["reason"] == "uji pemulihan fiktif"
    entry, after = _trace(reg_path, log_path)
    assert after.ok and entry.payload["trace_no"] == 2  # the lost trace's number is handed out again
    rep = verify_registry(reg_path, PUB, anchor_log=log_path)
    assert rep.ok and any("pengakuan pemulihan" in w and "jatah eps" in w for w in rep.warnings)
    with pytest.raises(AnchorError, match="tidak ada entri yang perlu diakui"):
        plan_acknowledgement(reg_path, _log(log_path))


def test_a_restart_after_a_tail_deletion_is_named_in_every_result(anchored, tmp_path):
    """Delete the newest trace, then start a new log elsewhere: the new log matches, but every
    result names the restart, and the old log still refuses without telling anyone to switch."""
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    _drop_tail(reg_path)
    new_path = tmp_path / "terpisah" / "baru.log"
    start_log(reg_path, new_path, SIGNER, PUB, reason="pindah lokasi (uji fiktif)", restart=True)
    entry, status = _trace(reg_path, new_path)
    assert entry.payload["trace_no"] == 1 and status.ok  # the number comes back: visible below
    with Registry.open(reg_path) as reg:
        restart_entry = [e for e in reg.entries(KIND_ANCHOR) if e.payload["event"] == "restart"][0]
    assert status.restarted == (restart_entry.seq, restart_entry.created_at)
    assert status.to_dict()["restarted"] == [restart_entry.seq, restart_entry.created_at]
    note = restart_note(*status.restarted)
    assert note in status.describe() and f"dimulai ulang di entri #{restart_entry.seq}" in note
    assert "tidak terlihat oleh log ini" in note
    rep = verify_registry(reg_path, PUB, anchor_log=new_path)
    assert rep.ok and f"log jangkar: {note}" in rep.warnings
    assert any(f"dimulai ulang di entri #{restart_entry.seq}" in line for line in rep.lines())
    old = _status(reg_path, log_path)
    assert not old.ok and old.restarted is None
    replaced = next(p for p in old.problems if "sudah diganti log lain" in p)
    assert "dengan sengaja" in replaced and "tapak verify" in replaced
    assert any("tidak ada lagi di registri" in p or "diganti entri lain" in p for p in old.problems)


def test_a_forged_acknowledgement_line_releases_nothing(anchored):
    reg_path, log_path = anchored
    entry, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)
    st = _status(reg_path, log_path)
    # An ack line that points at an existing entry that is not an acknowledgement.
    with Registry.open(reg_path) as reg:
        doc_entry = reg.get(1)
    body = entry_body(st.log_id, 1, "document", doc_entry.created_at, doc_entry.entry_hash)
    body.update(type="ack", released=[[entry.seq, entry.entry_hash]], reason="palsu")
    append_lines(log_path, [line_text(body)])
    st = _status(reg_path, log_path)
    assert not st.ok and not st.acks and any("baris pengakuan" in p for p in st.problems)


# --- the service, CLI, berita acara and web ----------------------------------------------------------


@pytest.fixture(scope="module")
def issued_base(tmp_path_factory):
    """One recorded, signed issuance (3 copies) without an anchor log, copied for each test."""
    base = tmp_path_factory.mktemp("jangkar-dasar")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TAPAK_DATA", str(base / "data"))
        mp.setenv("TAPAK_KEY_DIR", str(base / "keys"))
        mp.delenv("TAPAK_CANARY_DOMAIN", raising=False)
        mp.delenv("TAPAK_ANCHOR_LOG", raising=False)
        from tapak.config import load_settings
        from tapak.service import ensure_keys, issue_document

        s = load_settings()
        out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:3], IssueSettings(workers=1), "uji",
                             ensure_keys(s))
    text = extract_pdf_text((out.folder / "salinan" / out.manifest.copies[1].file).read_bytes())
    return base, out.manifest.doc_hash, text.encode("utf-8")


def _deployment(tmp_path, monkeypatch, issued_base, anchor=True):
    """A copy of the issuance with its own data, keys and, with ``anchor``, a started log."""
    from tapak.config import load_settings

    base, doc, evidence = issued_base
    shutil.copytree(base / "data", tmp_path / "data")
    shutil.copytree(base / "keys", tmp_path / "keys")
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    (tmp_path / "terpisah").mkdir()
    log_path = tmp_path / "terpisah" / "jangkar.log"
    if anchor:
        monkeypatch.setenv("TAPAK_ANCHOR_LOG", str(log_path))
        assert cli.main(["jangkar", "mulai"]) == 0
    return load_settings(), doc, evidence, log_path


def test_without_an_anchor_the_trace_result_gains_one_line(tmp_path, monkeypatch, issued_base, capsys):
    from tapak.service import trace_evidence, write_report

    s, doc, evidence, _ = _deployment(tmp_path, monkeypatch, issued_base, anchor=False)
    outcome = trace_evidence(s, doc, "bocor.txt", evidence)
    assert outcome.anchor_line().startswith("tidak diatur; entri yang dihapus dari ujung registri hanya terdeteksi "
                                            "dengan log jangkar")
    assert not any("jangkar" in n for n in outcome.attribution.notes)  # notes, verdict and bound unchanged
    path = tmp_path / "bocor.txt"
    path.write_bytes(evidence)
    capsys.readouterr()
    assert cli.main(["trace", str(path), "--doc", doc]) == 0
    printed = capsys.readouterr().out
    assert printed.count("Log jangkar:") == 1 and "hanya terdeteksi dengan log jangkar" in printed
    assert "LogjangkarTidakdiatur;entriyangdihapusdariujungregistri" in _report_text(write_report(outcome))
    assert not (tmp_path / "terpisah" / "jangkar.log").exists()
    # tapak verify without a log keeps its old note
    assert cli.main(["verify"]) == 0 and "--log-jangkar" in capsys.readouterr().out


def test_trace_with_an_anchor_is_refused_after_tail_deletion(tmp_path, monkeypatch, issued_base, capsys):
    from tapak.decoder import trace as trace_module
    from tapak.service import trace_evidence, write_report

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    first = trace_evidence(s, doc, "a.txt", evidence)
    assert first.anchor.ok and first.anchor.recorded == [first.trace_entry]
    assert first.anchor_line() == (f"cocok dengan registri sampai entri #{first.trace_entry}; entri baru "
                                   f"#{first.trace_entry} dicatat di log")
    assert f"LogjangkarCocokdenganregistrisampaientri#{first.trace_entry}" in _report_text(write_report(first))
    second = trace_evidence(s, doc, "a.txt", evidence)
    assert second.attribution.threshold.trace_no == 2
    _drop_tail(s.registry_path)

    def never(*a, **k):
        raise AssertionError("evidence decoded although the anchor log does not match")

    with monkeypatch.context() as m:
        m.setattr(trace_module, "trace_files", never)
        with pytest.raises(TraceError) as refused:
            trace_evidence(s, doc, "a.txt", evidence)
    text = str(refused.value)
    assert text.startswith("pelacakan ditolak: log jangkar") and "dihapus dari ujung rantai" in text
    assert "Periksa dengan tapak verify" in text and "Tidak ada nama yang disebut" in text
    with Registry.open(s.registry_path) as reg:
        assert len(reg.traces(doc)) == 1
    path = tmp_path / "a.txt"
    path.write_bytes(evidence)
    capsys.readouterr()
    assert cli.main(["trace", str(path), "--doc", doc]) == 2
    assert "pelacakan ditolak: log jangkar" in capsys.readouterr().err
    assert cli.main(["verify"]) == 1
    printed = capsys.readouterr().out
    assert "Log jangkar      :" in printed and "TIDAK COCOK" in printed and "dihapus dari ujung rantai" in printed
    assert cli.main(["jangkar", "status"]) == 1 and "TIDAK COCOK" in capsys.readouterr().out
    # The standalone verifier takes the log as well.
    from tapak.registry.verify import main as verify_main

    assert verify_main([str(s.registry_path), "--public-key", str(s.public_key_path), "--log-jangkar",
                        str(log_path)]) == 1

    # Recovery: shown first, recorded only with --ya.
    before = log_path.read_bytes()
    assert cli.main(["jangkar", "akui", "--alasan", "entri hilang, cadangan tidak ada (uji fiktif)"]) == 1
    assert "BELUM dicatat" in capsys.readouterr().out and log_path.read_bytes() == before
    assert cli.main(["jangkar", "akui", "--alasan", "entri hilang, cadangan tidak ada (uji fiktif)", "--ya"]) == 0
    assert "Pengakuan dicatat" in capsys.readouterr().out
    again = trace_evidence(s, doc, "a.txt", evidence)
    assert again.attribution.threshold.trace_no == 2 and "1 entri pelacakan di antaranya hilang" in again.anchor_line()


def _report_text(pdf_bytes: bytes) -> str:
    """Text of a berita acara without any whitespace (table cells and long lines wrap anywhere)."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        return "".join("".join(page.get_text() for page in pdf).split())


def test_a_lost_log_is_refused_until_restarted_on_purpose(tmp_path, monkeypatch, issued_base, capsys):
    from tapak.service import trace_evidence

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    trace_evidence(s, doc, "a.txt", evidence)
    old = shutil.copy2(log_path, tmp_path / "log-lama.log")
    log_path.unlink()
    capsys.readouterr()
    assert cli.main(["jangkar", "status"]) == 1 and "tidak ditemukan" in capsys.readouterr().out
    with pytest.raises(TraceError, match="tidak ditemukan"):
        trace_evidence(s, doc, "a.txt", evidence)
    assert cli.main(["jangkar", "mulai"]) == 2 and "--ulang" in capsys.readouterr().err  # never silently
    assert cli.main(["jangkar", "mulai", "--ulang"]) == 2 and "alasan wajib" in capsys.readouterr().err
    assert cli.main(["jangkar", "mulai", "--ulang", "--alasan", "media lama rusak (uji fiktif)"]) == 0
    assert "dimulai ulang" in capsys.readouterr().out
    head = _lines(log_path)[0]
    assert head["restart"] is True and head["reason"] == "media lama rusak (uji fiktif)"
    outcome = trace_evidence(s, doc, "a.txt", evidence)
    assert outcome.anchor.ok and outcome.attribution.threshold.trace_no == 2
    with Registry.open(s.registry_path) as reg:
        assert [e.payload["event"] for e in reg.entries(KIND_ANCHOR)] == ["start", "restart"]
        restart_seq = reg.entries(KIND_ANCHOR)[-1].seq
    # The restart stays visible: trace line, berita acara and tapak verify name it.
    assert f"log ini dimulai ulang di entri #{restart_seq}" in outcome.anchor_line()
    from tapak.service import write_report

    assert f"logInidimulaiulangdientri#{restart_seq}".lower() in _report_text(write_report(outcome)).lower()
    capsys.readouterr()
    assert cli.main(["verify"]) == 0 and f"dimulai ulang di entri #{restart_seq}" in capsys.readouterr().out
    from fastapi.testclient import TestClient

    from tapak.web.app import app

    page = TestClient(app, base_url="http://127.0.0.1").get("/registri").text
    assert "<dt>Dimulai ulang</dt>" in page and f"Di entri #{restart_seq}," in page
    # The old log, put back in place of the new one, is recognised as replaced.
    monkeypatch.setenv("TAPAK_ANCHOR_LOG", str(old))
    assert cli.main(["jangkar", "status"]) == 1 and "sudah diganti log lain" in capsys.readouterr().out


def test_a_process_without_the_log_is_refused_for_a_registry_that_uses_one(tmp_path, monkeypatch, issued_base,
                                                                          capsys):
    from tapak.config import load_settings
    from tapak.service import issue_document, trace_evidence

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    monkeypatch.delenv("TAPAK_ANCHOR_LOG")
    s = load_settings()
    with pytest.raises(TraceError, match="TAPAK_ANCHOR_LOG"):
        trace_evidence(s, doc, "a.txt", evidence)
    other = tmp_path / "lain.pdf"
    other.write_bytes(b"%PDF-1.4 dokumen lain (uji)")
    with pytest.raises(ValueError, match="penerbitan ditolak: registri ini memakai log jangkar"):
        issue_document(s, other, read_recipients(RECIPIENTS)[:2], IssueSettings(workers=1), "uji")
    assert not (s.workspaces / sha256_hex(other.read_bytes())[:16]).exists()  # refused before any copy
    capsys.readouterr()
    assert cli.main(["verify"]) == 3  # intact as far as checked, but tail deletion was not checked
    printed = capsys.readouterr().out
    assert "tetapi log itu tidak diberikan" in printed and "PENGHAPUSAN DARI UJUNG TIDAK DIPERIKSA" in printed
    assert cli.main(["jangkar", "status"]) == 1 and "TIDAK DIATUR" in capsys.readouterr().out
    # The location can be given for one command: globally, or to verify only.
    assert cli.main(["verify", "--log-jangkar", str(log_path)]) == 0
    printed = capsys.readouterr().out
    assert "Log jangkar      :" in printed and "cocok sampai entri #" in printed and "tidak diberikan" not in printed
    assert cli.main(["--log-jangkar", str(log_path), "jangkar", "status"]) == 0
    assert "cocok dengan registri" in capsys.readouterr().out


def test_issuance_writes_lines_and_a_failed_line_is_a_warning(tmp_path, monkeypatch, issued_base):
    from tapak.service import anchor_status, issue_document, trace_evidence

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    real = anchor_mod.append_lines
    monkeypatch.setattr(anchor_mod, "append_lines", lambda path, lines: (_ for _ in ()).throw(OSError(errno.ENOSPC, "x")))
    out = issue_document(s, ROOT / "samples" / "surat_telegram.pdf", read_recipients(RECIPIENTS)[:2],
                         IssueSettings(workers=1), "uji")
    assert out.registry_entries == 3 and (out.folder / "manifest.json").exists()  # committed and kept
    assert any("baris log jangkarnya tidak dapat ditulis" in w and "penyimpanan penuh" in w for w in out.warnings)
    monkeypatch.setattr(anchor_mod, "append_lines", real)
    st = anchor_status(s)
    assert st.ok and st.lag == 3 and st.signed_lines == st.lines
    outcome = trace_evidence(s, doc, "a.txt", evidence)
    assert outcome.anchor.completed and len(outcome.anchor.completed) == 3
    assert "baris yang tertinggal" in outcome.anchor_line()


def test_web_shows_the_anchor_and_refuses_after_tail_deletion(tmp_path, monkeypatch, issued_base):
    from fastapi.testclient import TestClient

    from tapak.web.app import app

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.get("/registri")
    assert r.status_code == 200 and 'id="jangkar-h">Log jangkar' in r.text and "stamp-ok\">Cocok" in r.text
    assert str(log_path) in r.text
    r = client.post("/lacak", data={"dokumen": doc[:16], "teks": evidence.decode("utf-8")})
    assert "<dt>Log jangkar</dt>" in r.text and "Cocok dengan registri sampai entri #" in r.text
    _drop_tail(s.registry_path)
    r = client.get("/registri")
    assert "Tidak cocok" in r.text and "dihapus dari ujung rantai" in r.text and "Rantai registri rusak" in r.text
    # the chain card names the anchor problem and points to the Log jangkar card, which tells it once
    from markupsafe import escape

    from tapak.service import anchor_status

    assert 'log jangkar: rinciannya di bagian <a class="link" href="#jangkar-h">Log jangkar</a> di bawah' in r.text
    assert all(r.text.count(str(escape(p))) == 1 for p in anchor_status(s).problems)
    r = client.post("/lacak", data={"dokumen": doc[:16], "teks": evidence.decode("utf-8")})
    assert "Pelacakan ditolak: log jangkar" in r.text and "tidak dapat dilakukan: pelacakan ditolak" not in r.text and "tapak verify" in r.text


def test_web_without_an_anchor_says_how_to_use_one(tmp_path, monkeypatch, issued_base):
    from fastapi.testclient import TestClient

    from tapak.web.app import app

    s, doc, evidence, _ = _deployment(tmp_path, monkeypatch, issued_base, anchor=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.get("/registri")
    assert "Belum dipakai" in r.text and "tapak --log-jangkar BERKAS jangkar mulai" in r.text
    r = client.post("/lacak", data={"dokumen": doc[:16], "teks": evidence.decode("utf-8")})
    assert "Tidak diatur; entri yang dihapus dari ujung registri hanya terdeteksi dengan log jangkar" in r.text


# --- size limit and rotation ---------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_the_size_limit_is_announced_and_a_rotation_continues_the_log(anchored, monkeypatch):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    size = log_path.stat().st_size
    monkeypatch.setattr(anchor_mod, "ROTATE_WARN_BYTES", size)
    st = _status(reg_path, log_path)
    assert st.ok and st.size == size and any("tapak jangkar rotasi BERKAS_BARU" in w for w in st.warnings)
    # The next trace still passes the check, and its line takes the log over the limit.
    monkeypatch.setattr(anchor_mod, "MAX_LOG_BYTES", size + 50)
    second, _ = _trace(reg_path, log_path)
    st = _status(reg_path, log_path)
    assert st.missing and "terlalu besar" in st.problems[0] and "tapak jangkar rotasi" in st.problems[0]
    assert st.unavailable == "too_large" and st.size == log_path.stat().st_size
    assert st.describe().startswith("TERLALU BESAR: ") and st.to_dict()["unavailable"] == "too_large"
    lines = verify_registry(reg_path, PUB, anchor_log=log_path).lines()
    assert any(line.strip() == "TERLALU BESAR" for line in lines) and not any("TIDAK COCOK" in line for line in lines)
    with pytest.raises(AnchorRefused, match="terlalu besar"):
        _trace(reg_path, log_path)
    # The rotation still reads the oversized log, and the new segment repeats nothing but the head.
    old_id, old_bytes = _lines(log_path)[0]["log_id"], log_path.read_bytes()
    monkeypatch.setattr(anchor_mod, "MAX_LOG_BYTES", len(old_bytes) - 1)  # the old log stays over the limit
    new_path = log_path.with_name("jangkar-2.log")
    status = rotate_log(reg_path, log_path, new_path, SIGNER, PUB, reason="batas ukuran (uji fiktif)")
    assert status.ok and status.lag == 0 and status.rotated is not None and status.rotated[2] == old_id
    head, anchor_line, rotate_line = _lines(new_path)
    assert head["previous"] == {"log_id": old_id, "bytes": len(old_bytes), "sha256": _sha(old_bytes),
                                "seq": second.seq, "entry_hash": second.entry_hash, "acks": [], "released_traces": 0}
    assert head["restart"] is False and head["reason"] == "batas ukuran (uji fiktif)" and head["media"]
    assert (anchor_line["seq"], anchor_line["entry_hash"]) == (second.seq, second.entry_hash)
    assert rotate_line["kind"] == KIND_ANCHOR and rotate_line["seq"] == status.rotated[0] == second.seq + 1
    assert log_path.read_bytes() == old_bytes  # the old segment is never written again
    with Registry.open(reg_path) as reg:
        event = reg.get(status.rotated[0]).payload
    assert event["event"] == "rotate" and event["log_id"] == head["log_id"]
    assert event["reason_sha256"] == reason_digest("batas ukuran (uji fiktif)")
    monkeypatch.setattr(anchor_mod, "MAX_LOG_BYTES", 256 * 1024 * 1024)
    old = _status(reg_path, log_path)
    assert not old.ok and any("sudah diteruskan ke segmen baru" in p and "segmen lama" in p for p in old.problems)
    entry, st = _trace(reg_path, new_path)
    assert st.ok and entry.payload["trace_no"] == 3 and st.rotated == status.rotated
    # A deletion that reaches below the rotation point is still refused: the head is anchored again.
    _drop_tail(reg_path, 3)
    st = _status(reg_path, new_path)
    assert not st.ok and st.releasable[0] == (second.seq, second.entry_hash)
    assert any("dihapus dari ujung" in p for p in st.problems)
    with pytest.raises(AnchorRefused):
        _trace(reg_path, new_path)


def test_the_chain_of_segments_is_checkable(anchored, tmp_path, capsys):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    second = log_path.with_name("jangkar-2.log")
    rotate_log(reg_path, log_path, second, SIGNER, PUB)
    _trace(reg_path, second)
    third = log_path.with_name("jangkar-3.log")
    rotate_log(reg_path, second, third, SIGNER, PUB)
    _trace(reg_path, third)
    rep = verify_registry(reg_path, PUB, anchor_log=third, anchor_segments=[log_path, second])
    assert rep.ok and rep.segments_checked == 2 and rep.anchor.rotated is not None
    assert any("segmen lanjutan sejak entri" in line for line in rep.lines())
    # A late line for an entry before the rotation (a writer finishing) is only a warning.
    with Registry.open(reg_path) as reg:
        early = reg.get(2)
    append_lines(second, [line_text(entry_body(_lines(second)[0]["log_id"], 2, early.kind, early.created_at,
                                               early.entry_hash), SIGNER)])
    rep = verify_registry(reg_path, PUB, anchor_log=third, anchor_segments=[log_path, second])
    assert rep.ok and any("ditulis setelah rotasi" in w for w in rep.warnings)
    # A shortened or edited old segment, or segments out of order, break the chain.
    cut = tmp_path / "terpotong.log"
    cut.write_bytes(log_path.read_bytes()[:-20])
    rep = verify_registry(reg_path, PUB, anchor_log=third, anchor_segments=[cut, second])
    assert not rep.ok and any("tidak sama dengan isi yang dicatat saat rotasi" in p for _, p in rep.problems)
    rep = verify_registry(reg_path, PUB, anchor_log=third, anchor_segments=[second, log_path])
    assert not rep.ok and any("urutkan --segmen-lama" in p for _, p in rep.problems)
    from tapak.registry.verify import main as verify_main

    capsys.readouterr()
    assert verify_main([str(reg_path), "--public-key", PUB, "--log-jangkar", str(third), "--segmen-lama",
                        str(log_path), "--segmen-lama", str(second)]) == 0
    assert "Segmen lama      : 2 dicocokkan" in capsys.readouterr().out
    with pytest.raises(SystemExit):  # an old segment alone means nothing
        verify_main([str(reg_path), "--public-key", PUB, "--segmen-lama", str(log_path)])


def _forge_rotation(reg_path, old_log, new_log, head, head_line=True):
    """What someone with the TAPAK account (registry, key, files on the log medium) could write by
    hand: a rotate entry and a segment committing to the old log as it is now and to ``head``."""
    old_id, log_id = _lines(old_log)[0]["log_id"], "f" * 32
    with Registry.open(reg_path) as reg:
        rot = reg.record_anchor_event(event="rotate", log_id=log_id, reason_sha256=None, signer=SIGNER)
    data = old_log.read_bytes()
    prev = anchor_mod.Previous(old_id, len(data), _sha(data), head.seq, head.entry_hash)
    text = line_text(start_body(log_id, rot.created_at, False, None, read_media_id(new_log.parent), prev), SIGNER)
    if head_line:
        text += line_text(entry_body(log_id, head.seq, head.kind, head.created_at, head.entry_hash), SIGNER)
    new_log.write_text(text + line_text(entry_body(log_id, rot.seq, rot.kind, rot.created_at, rot.entry_hash), SIGNER),
                       encoding="utf-8")
    return rot


def test_a_forged_rotation_is_named_and_exposed_by_the_old_segment(anchored):
    reg_path, log_path = anchored
    first, _ = _trace(reg_path, log_path)
    victim, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)  # the newest trace is gone, then a rotation is forged at the shorter head
    segment = log_path.with_name("palsu.log")
    rot = _forge_rotation(reg_path, log_path, segment, first)
    old = _status(reg_path, log_path)  # a process still on the old log: the deletion, and check before switching
    assert not old.ok and any("diganti entri lain" in p for p in old.problems)
    assert any(f"--segmen-lama {log_path}" in p for p in old.problems)
    # The forged segment alone looks like a genuine one, so every result names the rotation.
    st = _status(reg_path, segment)
    assert st.ok and st.rotated[0] == rot.seq and "tapak verify --segmen-lama" in st.describe()
    rep = verify_registry(reg_path, PUB, anchor_log=segment)
    assert rep.ok and any("tanpa --segmen-lama, rotasi itu tidak diperiksa" in w for w in rep.warnings)
    rep = verify_registry(reg_path, PUB, anchor_log=segment, anchor_segments=[log_path])
    assert not rep.ok and any(f"entri #{victim.seq} (1 pelacakan) yang tidak ada lagi" in p for _, p in rep.problems)


def test_a_forged_rotation_over_a_replacement_entry_is_exposed_by_the_old_segment(anchored):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    victim, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)
    with Registry.open(reg_path) as reg:  # a harmless looking entry takes the deleted trace's number
        dummy = reg.append("canary_anchor", {"events_seq": 1, "events_hash": "0" * 64}, signer=SIGNER)
    assert dummy.seq == victim.seq
    append_lines(log_path, [line_text(entry_body(_lines(log_path)[0]["log_id"], dummy.seq, dummy.kind,
                                                 dummy.created_at, dummy.entry_hash), SIGNER)])
    segment = log_path.with_name("palsu.log")
    _forge_rotation(reg_path, log_path, segment, dummy)
    assert _status(reg_path, segment).ok  # the old log ends at the head, so only its content tells
    rep = verify_registry(reg_path, PUB, anchor_log=segment, anchor_segments=[log_path])
    assert not rep.ok and any("tidak cocok dengan registri saat rotasi" in p and "diganti entri lain" in p
                              for _, p in rep.problems)


@pytest.mark.parametrize("forgery", ["head-too-old", "no-head-line"])
def test_a_segment_must_anchor_the_head_right_before_its_rotation(anchored, forgery):
    reg_path, log_path = anchored
    first, _ = _trace(reg_path, log_path)
    _trace(reg_path, log_path)
    _drop_tail(reg_path)
    with Registry.open(reg_path) as reg:
        head = reg.get(1) if forgery == "head-too-old" else first
    segment = log_path.with_name("palsu.log")
    _forge_rotation(reg_path, log_path, segment, head, head_line=forgery != "no-head-line")
    st = _status(reg_path, segment)
    expected = "tepat sesudah ujung yang diikatnya" if forgery == "head-too-old" else "tidak menjangkarkan ujung"
    assert not st.ok and any(expected in p for p in st.blocking)
    with pytest.raises(AnchorRefused, match=expected):
        _trace(reg_path, segment)


def test_a_rotation_keeps_acknowledgements_and_a_restart_visible(anchored, tmp_path):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    second, _ = _trace(reg_path, log_path)
    _drop_tail(reg_path)
    acknowledge(reg_path, _log(log_path), "uji pemulihan fiktif")
    segment = log_path.with_name("jangkar-2.log")
    status = rotate_log(reg_path, log_path, segment, SIGNER, PUB)
    assert status.ok and len(status.acks) == 1 and status.released == [(second.seq, second.entry_hash)]
    assert status.released_traces == 1 and "1 entri pelacakan di antaranya hilang" in status.describe()
    assert _lines(segment)[0]["previous"]["acks"] == [status.acks[0][0]]
    # A segment that claims an acknowledgement the registry does not hold is refused.
    lines = segment.read_text(encoding="utf-8").splitlines(keepends=True)
    forged = json.loads(lines[0])
    forged.pop("sig")
    forged["previous"]["acks"] = [1]
    segment.write_text(canonical_json(forged).decode() + "\n" + "".join(lines[1:]), encoding="utf-8")
    st = _status(reg_path, segment)
    assert not st.ok and any("menyebut pengakuan di entri #1" in p for p in st.problems)
    # One that leaves the acknowledgement out cannot hide it: the registry names it anyway.
    forged["previous"]["acks"] = []
    segment.write_text(canonical_json(forged).decode() + "\n" + "".join(lines[1:]), encoding="utf-8")
    st = _status(reg_path, segment)
    assert st.ok and len(st.acks) == 1 and st.released == [(second.seq, second.entry_hash)]
    segment.write_text("".join(lines), encoding="utf-8")
    assert _status(reg_path, segment).ok
    # A restart stays named in every result after a later rotation.
    restarted = tmp_path / "terpisah" / "ulang.log"
    start_log(reg_path, restarted, SIGNER, PUB, reason="pindah lokasi (uji fiktif)", restart=True)
    third = tmp_path / "terpisah" / "ulang-2.log"
    status = rotate_log(reg_path, restarted, third, SIGNER, PUB)
    assert status.ok and status.restarted is not None and restart_note(*status.restarted) in status.describe()
    assert not status.acks  # the acknowledgement belonged to the log that the restart replaced


def test_a_rotation_is_refused_on_a_mismatch_and_works_from_a_finalised_segment(anchored, tmp_path):
    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    _drop_tail(reg_path)
    with pytest.raises(AnchorRefused, match="dihapus dari ujung"):  # a rotation never hides an alarm
        rotate_log(reg_path, log_path, log_path.with_name("baru.log"), SIGNER, PUB)
    assert not log_path.with_name("baru.log").exists()
    reg_path, log_path = tmp_path / "r2.db", tmp_path / "terpisah" / "kedua.log"
    _new_registry(reg_path)
    start_log(reg_path, log_path, SIGNER, PUB)
    log_path.with_name("ada.log").write_text("x\n", encoding="utf-8")
    with pytest.raises(AnchorError, match="sudah ada dan tidak ditimpa"):
        rotate_log(reg_path, log_path, log_path.with_name("ada.log"), SIGNER, PUB)
    other = tmp_path / "media-lain"
    other.mkdir()
    with pytest.raises(AnchorError, match="tidak memuat penanda media"):
        rotate_log(reg_path, log_path, other / "segmen.log", SIGNER, PUB)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        log_path.chmod(0o444)  # a full or finalised medium: nothing is missing, so nothing is written
    try:
        status = rotate_log(reg_path, log_path, other / "segmen.log", SIGNER, PUB, mark_media=True)
    finally:
        log_path.chmod(0o644)
    assert status.ok and read_media_id(other) == _lines(other / "segmen.log")[0]["media"]


def test_rotation_through_the_cli(tmp_path, monkeypatch, issued_base, capsys):
    from tapak.service import trace_evidence

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    trace_evidence(s, doc, "a.txt", evidence)
    new_path = log_path.with_name("jangkar-2.log")
    capsys.readouterr()
    assert cli.main(["jangkar", "rotasi", str(new_path), "--alasan", "rotasi tahunan (uji fiktif)"]) == 0
    printed = capsys.readouterr().out
    assert "diteruskan ke segmen baru" in printed and "Ubah TAPAK_ANCHOR_LOG" in printed
    assert "bukan titik kait" in printed  # tmp_path is not a separate mount
    assert cli.main(["jangkar", "status"]) == 1 and "sudah diteruskan ke segmen baru" in capsys.readouterr().out
    with pytest.raises(TraceError) as refused:  # a process left on the old segment: a setting to change
        trace_evidence(s, doc, "a.txt", evidence)
    assert "sudah diteruskan ke segmen baru" in str(refused.value) and "tapak jangkar akui" not in str(refused.value)
    monkeypatch.setenv("TAPAK_ANCHOR_LOG", str(new_path))
    assert cli.main(["jangkar", "status"]) == 0
    printed = capsys.readouterr().out
    assert "Segmen     : lanjutan log id" in printed and "Ukuran     :" in printed and "Dapat ditulis: ya" in printed
    from tapak.config import load_settings

    s = load_settings()
    outcome = trace_evidence(s, doc, "a.txt", evidence)
    assert outcome.anchor.ok and outcome.attribution.threshold.trace_no == 2
    assert cli.main(["verify", "--segmen-lama", str(log_path)]) == 0
    assert "Segmen lama      : 1 dicocokkan" in capsys.readouterr().out
    from fastapi.testclient import TestClient

    from tapak.web.app import app

    page = TestClient(app, base_url="http://127.0.0.1").get("/registri").text
    assert "<dt>Segmen</dt>" in page and "Lanjutan log" in page


# --- incremental checks ------------------------------------------------------------------------------


def _same_as_full(reg_path, log_path):
    """The incremental check of ``log_path`` and a full one, against the same registry rows."""
    rows = read_registry_rows(reg_path)
    fast = compare_anchor(read_anchor_incremental(log_path), rows, PUB)
    full = compare_anchor(read_anchor_file(log_path), rows, PUB)
    assert fast.to_dict() == full.to_dict()
    return fast


def test_the_incremental_check_equals_a_full_check(anchored, monkeypatch):
    reg_path, log_path = anchored
    assert _same_as_full(reg_path, log_path).ok
    for _ in range(3):
        _trace(reg_path, log_path)
    assert _same_as_full(reg_path, log_path).ok
    # Only the lines appended since the last check are parsed and verified.
    parsed, verified = [], []
    real_parse, real_verify = anchor_mod.parse_line, anchor_mod.verify_line
    monkeypatch.setattr(anchor_mod, "parse_line", lambda text, n: parsed.append(n) or real_parse(text, n))
    monkeypatch.setattr(anchor_mod, "verify_line",
                        lambda line, key: verified.append(line.number) or real_verify(line, key))
    compare_anchor(read_anchor_incremental(log_path), read_registry_rows(reg_path), PUB)
    assert parsed == [] and verified == []
    entry, _ = _trace(reg_path, log_path)
    parsed.clear()
    verified.clear()
    st = compare_anchor(read_anchor_incremental(log_path), read_registry_rows(reg_path), PUB)
    count = len(_lines(log_path))
    assert st.ok and st.anchored_seq == entry.seq and parsed == [count] and verified == [count]
    monkeypatch.undo()
    # A torn line, then the line that closes it.
    with open(log_path, "ab") as fh:
        fh.write(b'{"created_at":"2026-10-')
    assert any("terpotong" in w for w in _same_as_full(reg_path, log_path).warnings)
    _trace(reg_path, log_path)
    assert any("tidak dapat dibaca" in w for w in _same_as_full(reg_path, log_path).warnings)
    # An early line rewritten in place, same length and same last line: still an alarm.
    data = log_path.read_bytes()
    lines = data.split(b"\n")
    target = json.loads(lines[1])
    flipped = target["entry_hash"][:-1] + ("0" if target["entry_hash"][-1] != "0" else "1")
    lines[1] = lines[1].replace(target["entry_hash"].encode(), flipped.encode())
    log_path.write_bytes(b"\n".join(lines))
    assert log_path.stat().st_size == len(data)
    st = _same_as_full(reg_path, log_path)
    assert not st.ok and any("diganti entri lain" in p for p in st.problems)
    assert any("tanda tangan baris ke-2" in p for p in st.problems)
    log_path.write_bytes(data)
    assert _same_as_full(reg_path, log_path).ok
    # An older, shorter copy of the log still looks like a crash lag: the documented gap.
    log_path.write_bytes(data[:data.rfind(b"\n", 0, len(data) - 1) + 1])
    st = _same_as_full(reg_path, log_path)
    assert st.ok and st.lag == 1
    log_path.write_bytes(data)
    # A registry row edited in place keeps its hash: the kept row results do not hide it.
    _same_as_full(reg_path, log_path)
    first = read_registry_rows(reg_path)[2]
    payload = dict(json.loads(first[2]), evidence_sha256=["b2" * 32])
    _edit(reg_path, ("UPDATE entries SET payload = ? WHERE seq = ?", (canonical_json(payload).decode(), first[0])))
    st = _same_as_full(reg_path, log_path)
    assert not st.ok and any(f"isi entri #{first[0]} diubah" in p for p in st.problems)


# --- writability, media marker, verify without the log -------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores file modes")
def test_status_reports_a_log_that_cannot_be_written(tmp_path, monkeypatch, issued_base, capsys):
    from fastapi.testclient import TestClient

    from tapak.service import anchor_status, trace_evidence
    from tapak.web.app import app

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    log_path.chmod(0o444)
    try:
        capsys.readouterr()
        assert cli.main(["jangkar", "status"]) == 1
        printed = capsys.readouterr().out
        assert "Dapat ditulis: tidak" in printed and "tidak dapat ditulis (tidak ada izin)" in printed
        st = anchor_status(s)
        assert st.unwritable and st.problems == st.storage and "tidak cocok dengan registri" not in st.refusal()
        with pytest.raises(TraceError, match="tidak dapat ditulis"):
            trace_evidence(s, doc, "a.txt", evidence)
        page = TestClient(app, base_url="http://127.0.0.1").get("/registri").text
        assert "Tidak dapat ditulis" in page and "penyimpanan log ini diperbaiki" in page
        # A third party with a read-only copy of the log can still verify.
        assert verify_registry(s.registry_path, s.public_key_path.read_text().strip(), anchor_log=log_path).ok
    finally:
        log_path.chmod(0o644)
    assert cli.main(["jangkar", "status"]) == 0 and "Dapat ditulis: ya" in capsys.readouterr().out


def test_registri_page_names_why_the_log_cannot_be_read(tmp_path, monkeypatch, issued_base, capsys):
    """A log over the size limit is not "Hilang": the page says it is too large and how to rotate
    it; a missing, unreadable or not yet started log gets its own label too."""
    from fastapi.testclient import TestClient

    from tapak.web.app import app

    s, doc, evidence, log_path = _deployment(tmp_path, monkeypatch, issued_base)
    client = TestClient(app, base_url="http://127.0.0.1")

    def stamp() -> tuple[str, str]:
        """The danger stamp of the anchor card ("" when there is none) and the card's HTML."""
        page = client.get("/registri").text
        card = page[page.index('id="jangkar-h"'):]
        card = card[:card.index("</section>")]
        if 'stamp-danger">' not in card:
            return "", card
        return card.split('stamp-danger">', 1)[1].split("<", 1)[0], card

    limit = anchor_mod.MAX_LOG_BYTES
    monkeypatch.setattr(anchor_mod, "MAX_LOG_BYTES", log_path.stat().st_size - 1)
    label, card = stamp()
    assert label == "Terlalu besar" and "Hilang" not in card
    assert "ditolak sampai log ini diteruskan ke segmen baru" in card
    assert "tapak jangkar rotasi BERKAS_BARU" in card and "terlalu besar" in card
    capsys.readouterr()
    assert cli.main(["jangkar", "status"]) == 1
    printed = capsys.readouterr().out
    assert "Keadaan    : TERLALU BESAR: log jangkar" in printed and "TIDAK COCOK" not in printed
    assert "di atas batas" in printed and "tapak jangkar rotasi BERKAS_BARU" in printed
    monkeypatch.setattr(anchor_mod, "MAX_LOG_BYTES", limit)
    label, card = stamp()
    assert label == "" and 'stamp-ok">Cocok' in card

    moved = log_path.rename(log_path.with_name("dipindah.log"))
    label, card = stamp()
    assert label == "Hilang" and "ditolak sampai log ini dapat dibaca lagi" in card
    log_path.mkdir()  # something else in its place
    assert stamp()[0] == "Tidak terbaca"
    log_path.rmdir()
    moved.rename(log_path)
    assert stamp()[0] == ""
    # A registry that does not use a log yet, with a location set: not started, not lost.
    (tmp_path / "kosong").mkdir()
    _new_registry(tmp_path / "kosong" / "registry.db")
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "kosong"))
    monkeypatch.setenv("TAPAK_ANCHOR_LOG", str(tmp_path / "terpisah" / "belum.log"))
    label, card = stamp()
    assert label == "Belum dimulai" and "ditolak sampai log dimulai dengan" in card


def test_the_media_marker_must_sit_next_to_the_log(anchored, tmp_path):
    reg_path, log_path = anchored
    marker = log_path.parent / MEDIA_MARKER
    assert _lines(log_path)[0]["media"] == read_media_id(log_path.parent) == json.loads(marker.read_text())["media_id"]
    # The log copied to a folder without the marker, as on the local disk under a mount point.
    local = tmp_path / "disk-lokal"
    local.mkdir()
    shutil.copy2(log_path, local / "jangkar.log")
    st = _status(reg_path, local / "jangkar.log")
    assert not st.ok and st.problems == st.storage and "penanda media" in st.problems[0]
    with pytest.raises(AnchorRefused, match="penanda media"):
        _trace(reg_path, local / "jangkar.log")
    # A restart into a folder without a marker is refused unless the medium is marked on purpose.
    log_path.unlink()
    with pytest.raises(AnchorError, match="belum dipasang"):
        start_log(reg_path, local / "baru.log", SIGNER, PUB, reason="media hilang (uji fiktif)", restart=True)
    assert not (local / "baru.log").exists() and not (local / MEDIA_MARKER).exists()
    status = start_log(reg_path, local / "baru.log", SIGNER, PUB, reason="media hilang (uji fiktif)", restart=True,
                       mark_media=True)
    assert status.ok and _lines(local / "baru.log")[0]["media"] == read_media_id(local)
    # A damaged marker is never replaced silently.
    (local / MEDIA_MARKER).write_text("rusak", encoding="utf-8")
    assert not _status(reg_path, local / "baru.log").ok
    with pytest.raises(AnchorError, match="rusak"):
        rotate_log(reg_path, local / "baru.log", local / "baru-2.log", SIGNER, PUB, mark_media=True)
    # Logs started before the marker existed carry no media id and need none.
    old_start = parse_line(line_text(start_body("ab" * 16, "2026-10-22T08:00:00.000+00:00", False, None))[:-1], 1)
    assert old_start.media is None and anchor_mod._media_problem(tmp_path / "x.log", old_start) is None
    assert "bukan titik kait" in mount_note(local / "baru.log") and mount_note("/jangkar.log") is None


def test_verify_without_the_log_says_tail_deletion_was_not_checked(anchored, tmp_path, capsys):
    from tapak.registry.verify import EXIT_TAIL_UNCHECKED
    from tapak.registry.verify import main as verify_main

    reg_path, log_path = anchored
    _trace(reg_path, log_path)
    rep = verify_registry(reg_path, PUB)
    assert rep.ok and rep.tail_unchecked and rep.exit_code() == EXIT_TAIL_UNCHECKED == 3
    assert rep.to_dict()["tail_unchecked"] and "PENGHAPUSAN DARI UJUNG TIDAK DIPERIKSA" in rep.verdict()
    capsys.readouterr()
    assert verify_main([str(reg_path), "--public-key", PUB]) == 3
    printed = capsys.readouterr().out
    assert "PENGHAPUSAN DARI UJUNG TIDAK DIPERIKSA" in printed and "hanya berlaku untuk entri yang masih ada" in printed
    assert "Catatan: tanpa --jangkar" not in printed
    _drop_tail(reg_path)  # the deleted trace is invisible without the log: still 3, never 0
    assert verify_main([str(reg_path), "--public-key", PUB]) == 3
    assert verify_main([str(reg_path), "--public-key", PUB, "--log-jangkar", str(log_path)]) == 1
    plain = tmp_path / "tanpa-log.db"
    _new_registry(plain)
    assert verify_main([str(plain), "--public-key", PUB]) == 0  # no anchor log recorded: nothing missing
