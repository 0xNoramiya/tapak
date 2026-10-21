"""Append-only registry: hash chain, signatures, triggers, tamper detection, Merkle roots, CLI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from nacl.signing import VerifyKey

from tapak.registry.chain import (
    COPY_FIELDS,
    DOCUMENT_FIELDS,
    ZERO_HASH,
    Registry,
    RegistryError,
    canary_token_digest,
    canonical_json,
    compute_entry_hash,
    registry_from_manifest,
    sign_pending,
)
from tapak.registry.merkle import (
    check_daily_roots,
    daily_roots,
    export_daily_roots,
    merkle_proof,
    merkle_root,
    parse_root_file,
    tree_depth,
    verify_proof,
)
from tapak.registry.signing import (
    Signer,
    SigningKeyError,
    export_public_key,
    generate_signing_key,
    load_public_key,
    load_signer,
)
from tapak.registry.signing import main as signing_main
from tapak.registry.verify import main as verify_main
from tapak.registry.verify import verify_registry

DOC_HASH = "a" * 64
T0 = datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)  # a past date, so both days are closed
DAY1, DAY2 = "2026-03-03", "2026-03-04"
COLS = "seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer"
N_COPIES = 5
N_ENTRIES = 1 + N_COPIES
N = N_ENTRIES


@pytest.fixture
def signer() -> Signer:
    return Signer(bytes([7]) * 32)


@pytest.fixture
def attacker_signer() -> Signer:
    return Signer(bytes([9]) * 32)


def _doc_fields() -> dict:
    return dict(
        doc_hash=DOC_HASH, doc_name="nota_dinas.pdf",
        params={"c": 3, "eps": 1e-6, "n_max": N_COPIES, "constant": "skoric", "length": 1234},
        channels=["shift", "zw", "homoglyph"], shift_mm={"word_mm": 0.05, "row_mm": 0.05},
        excluded_rows=[[0, 2]], plan_summary={"zw": {"slots": 10, "bits": 40, "positions": 40, "pages": 1}},
        threshold_rule="Chernoff", threshold_full=321.5, issuer="pytest", issued_at=T0.isoformat(),
    )


def _copy_fields(i: int) -> dict:
    return dict(
        doc_hash=DOC_HASH, recipient_id=f"R{i:03d}", copy_id=f"{i:016x}", seq=i, code_digest=f"{i:064x}",
        channels_used=["shift", "zw"], file_sha256="c" * 64, issued_at=T0.isoformat(), issuer="pytest",
    )


def _build(path: Path, signer: Signer | None) -> Path:
    """Document + 5 copies over two UTC days: entries 1..4 on DAY1, 5..6 on DAY2."""
    with Registry.open(path) as reg:
        reg.record_document(**_doc_fields(), signer=signer, created_at=T0)
        for i in range(1, N_COPIES + 1):
            reg.record_copy(**_copy_fields(i), signer=signer, created_at=T0 + timedelta(hours=4 * i))
    return path


@pytest.fixture
def signed_db(tmp_path, signer) -> Path:
    return _build(tmp_path / "registry.db", signer)


@pytest.fixture
def unsigned_db(tmp_path) -> Path:
    return _build(tmp_path / "registry.db", None)


@contextmanager
def attacker(path: Path):
    """Raw sqlite3 access with the append-only triggers dropped, as an attacker would."""
    conn = sqlite3.connect(path)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row(conn: sqlite3.Connection, seq: int) -> tuple:
    return conn.execute(f"SELECT {COLS} FROM entries WHERE seq = ?", (seq,)).fetchone()


def _problem_seqs(report) -> set[int]:
    return {seq for seq, _ in report.problems}


def _forged_payload() -> dict:
    return {**_copy_fields(99), "semantic_variant_ids": [], "canary_token": None}


# ---- chain construction --------------------------------------------------------------


def test_chain_verifies_with_public_key_only(signed_db, signer):
    before = signed_db.read_bytes()
    rep = verify_registry(signed_db, signer.public_key_hex)
    assert rep.ok, rep.problems
    assert rep.entries == N_ENTRIES and rep.unsigned == 0 and rep.fully_signed
    assert rep.kinds == {"document": 1, "copy": N_COPIES}
    assert rep.head_seq == N_ENTRIES
    assert rep.verdict() == f"HASIL: UTUH, rantai hash dan semua tanda tangan sah untuk entri #1..#{N}"
    assert signed_db.read_bytes() == before  # verification opens the file read-only


def test_verify_cli_runs_without_config_or_secrets(signed_db, signer, tmp_path):
    """A fresh process in an empty directory, given only the file and the public key."""
    empty = tmp_path / "auditor"
    empty.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TAPAK")}
    env["TAPAK_KEY_DIR"] = str(empty / "no-keys-here")
    proc = subprocess.run(
        [sys.executable, "-m", "tapak.registry.verify", str(signed_db), "--public-key", signer.public_key_hex],
        cwd=empty, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "HASIL: UTUH" in proc.stdout
    assert not (empty / "no-keys-here").exists()


def test_entry_hash_and_signature_follow_the_spec(signed_db, signer):
    with Registry.open(signed_db) as reg:
        entries = reg.entries()
    first = entries[0]
    assert first.seq == 1 and first.prev_hash == ZERO_HASH
    body = {"seq": 1, "kind": "document", "payload": first.payload, "prev_hash": ZERO_HASH,
            "created_at": first.created_at}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(text).hexdigest() == first.entry_hash
    for prev, e in zip(entries, entries[1:]):
        assert e.prev_hash == prev.entry_hash and e.seq == prev.seq + 1
    for e in entries:
        assert e.signer == signer.public_key_hex
        VerifyKey(bytes.fromhex(signer.public_key_hex)).verify(bytes.fromhex(e.entry_hash),
                                                              bytes.fromhex(e.signature))


def test_canonical_json_and_known_answer_hash():
    assert canonical_json({"b": 1, "a": "\u00e9"}) == '{"a":"\u00e9","b":1}'.encode("utf-8")
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    # Known answer, computed independently with `sha256sum` over
    # {"created_at":"2026-01-01T00:00:00.000+00:00","kind":"k","payload":{"a":1},"prev_hash":"0...0","seq":1}
    stamp = "2026-01-01T00:00:00.000+00:00"
    base = compute_entry_hash(1, "k", {"a": 1}, ZERO_HASH, stamp)
    assert base == "1ea0c369364ba026c4e09e506c84c8a379e1d1420edc842f07a1efaf2c078f02"
    variants = [
        compute_entry_hash(2, "k", {"a": 1}, ZERO_HASH, stamp),
        compute_entry_hash(1, "j", {"a": 1}, ZERO_HASH, stamp),
        compute_entry_hash(1, "k", {"a": 2}, ZERO_HASH, stamp),
        compute_entry_hash(1, "k", {"a": 1}, "1" + ZERO_HASH[1:], stamp),
        compute_entry_hash(1, "k", {"a": 1}, ZERO_HASH, stamp.replace("00.000", "01.000")),
    ]
    assert base not in variants and len(set(variants)) == len(variants)  # every field is hashed


def test_payload_schema_and_data_minimization(tmp_path):
    with Registry.open(tmp_path / "r.db") as reg:
        bad = {**_copy_fields(1), "canary_token": None, "semantic_variant_ids": [], "nama": "Budi"}
        with pytest.raises(ValueError):
            reg.append("copy", bad)
        with pytest.raises(ValueError):
            reg.append("document", {"doc_hash": DOC_HASH})
        with pytest.raises(ValueError):
            reg.append("bad kind!", {})
        e = reg.append("audit_note", {"note": "kind generik tetap bisa ditambah"})
        assert e.kind == "audit_note"
        c = reg.record_copy(**_copy_fields(1))
        assert set(c.payload) == COPY_FIELDS
        assert c.payload["canary_token"] is None and c.payload["semantic_variant_ids"] == []
        d = reg.record_document(**{**_doc_fields(), "threshold_full": float("inf")})
        assert set(d.payload) == DOCUMENT_FIELDS and d.payload["threshold_full"] is None


def test_canary_token_is_stored_as_a_commitment(tmp_path):
    db = tmp_path / "r.db"
    token = "abcdefghijklmn23"
    with Registry.open(db) as reg:
        c = reg.record_copy(**_copy_fields(1), canary_token=token)
        assert c.payload["canary_token"] == canary_token_digest(token)
        assert c.payload["canary_token"] == "sha256:" + hashlib.sha256(token.encode()).hexdigest()
        assert reg.find_copy_by_canary(token.upper())["recipient_id"] == "R001"  # DNS is case-insensitive
        assert reg.find_copy_by_canary("zzzzzzzzzzzzzzzz") is None
        again = reg.record_copy(**_copy_fields(2), canary_token=c.payload["canary_token"])
        assert again.payload["canary_token"] == c.payload["canary_token"]  # a commitment is kept as is
        with pytest.raises(ValueError):
            reg.record_copy(**_copy_fields(3), canary_token="")
    assert token.encode() not in db.read_bytes()


def test_created_at_never_goes_back(tmp_path):
    with Registry.open(tmp_path / "r.db") as reg:
        reg.append("note", {"n": 1}, created_at=T0)
        with pytest.raises(RegistryError):
            reg.append("note", {"n": 2}, created_at=T0 - timedelta(seconds=1))
        with pytest.raises(ValueError):
            reg.append("note", {"n": 3}, created_at="2026-11-03T10:00:00")  # no timezone
        assert reg.append("note", {"n": 4}).seq == 2


def test_reading_helpers(signed_db, signer):
    with Registry.open(signed_db) as reg:
        assert reg.find_document(DOC_HASH)["doc_name"] == "nota_dinas.pdf"
        assert reg.find_document("f" * 64) is None
        copies = reg.copies(DOC_HASH)
        assert [c["seq"] for c in copies] == list(range(1, N_COPIES + 1))
        assert reg.get(2).payload["recipient_id"] == "R001"
        assert reg.get(99) is None
        assert len(reg.entries("copy")) == N_COPIES
        assert reg.pending() == [] and reg.last_signed_seq() == N
        reg.record_document(**{**_doc_fields(), "doc_name": "versi2.pdf"}, signer=signer)
        assert reg.find_document(DOC_HASH)["doc_name"] == "versi2.pdf"  # latest wins


# ---- triggers ------------------------------------------------------------------------


def test_triggers_block_update_delete_and_bad_insert(unsigned_db, signer):
    conn = sqlite3.connect(unsigned_db)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("UPDATE entries SET payload = '{}' WHERE seq = 2")
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("DELETE FROM entries WHERE seq = 2")
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("DELETE FROM entries")
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):  # signer alone
            conn.execute("UPDATE entries SET signer = 'x' WHERE seq = 2")
        # Filling a NULL signature (and signer) is allowed exactly once.
        conn.execute("UPDATE entries SET signature = 'aa', signer = 'bb' WHERE seq = 2")
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("UPDATE entries SET signature = 'cc', signer = 'bb' WHERE seq = 2")
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("UPDATE entries SET signature = 'cc', signer = 'dd', payload = '{}' WHERE seq = 3")
        # Inserts must extend the chain at its end.
        head = _row(conn, N_ENTRIES)
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, 'x', '{{}}', ?, 't', 'h', NULL, NULL)",
                         (N_ENTRIES + 2, head[5]))
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, 'x', '{{}}', ?, 't', 'h', NULL, NULL)",
                         (N_ENTRIES + 1, ZERO_HASH))
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute(f"INSERT OR REPLACE INTO entries ({COLS}) VALUES (3, 'x', '{{}}', ?, 't', 'h', NULL, NULL)",
                         (head[5],))
        conn.rollback()
    finally:
        conn.close()


def test_open_refuses_missing_or_disarmed_triggers(signed_db, signer):
    pub = signer.public_key_hex
    conn = sqlite3.connect(signed_db)
    conn.execute("DROP TRIGGER entries_no_delete")
    conn.commit()
    with pytest.raises(RegistryError, match="entries_no_delete hilang"):
        Registry.open(signed_db)  # never re-created silently
    rep = verify_registry(signed_db, pub)
    assert rep.ok and any("entries_no_delete hilang" in w for w in rep.warnings)
    # Same name, disarmed body: caught by comparing the stored SQL, not just the name.
    conn.execute("CREATE TRIGGER entries_no_delete BEFORE DELETE ON entries WHEN 0 "
                 "BEGIN SELECT RAISE(ABORT, 'registri hanya boleh ditambah'); END")
    conn.execute("CREATE TRIGGER entries_extra AFTER INSERT ON entries BEGIN SELECT 1; END")
    conn.commit()
    with pytest.raises(RegistryError, match="entries_no_delete diubah"):
        Registry.open(signed_db)
    warnings = " | ".join(verify_registry(signed_db, pub).warnings)
    assert "entries_no_delete diubah" in warnings and "entries_extra" in warnings
    conn.close()
    with Registry.open(signed_db, repair_triggers=True) as reg:
        assert reg.trigger_repairs == ["pemicu entries_no_delete diubah",
                                       "pemicu tak dikenal entries_extra pada tabel entri"]
    rep = verify_registry(signed_db, pub)
    assert rep.ok and rep.warnings == []
    conn = sqlite3.connect(signed_db)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="hanya boleh ditambah"):
            conn.execute("DELETE FROM entries WHERE seq = 1")
    finally:
        conn.close()


# ---- tamper detection ----------------------------------------------------------------


@pytest.mark.parametrize("seq", range(1, N_ENTRIES + 1))
def test_one_payload_byte_changed_in_any_row_is_detected(signed_db, signer, seq):
    with attacker(signed_db) as conn:
        payload = _row(conn, seq)[2]
        forged = payload.replace('"doc_hash":"a', '"doc_hash":"b', 1)
        assert len(forged) == len(payload) and forged != payload
        conn.execute("UPDATE entries SET payload = ? WHERE seq = ?", (forged, seq))
    rep = verify_registry(signed_db, signer.public_key_hex)
    assert not rep.ok
    assert any(s == seq and "hash entri" in text for s, text in rep.problems)
    assert any("pemicu" in w for w in rep.warnings)


def _tamper_prev_hash(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET prev_hash = ? WHERE seq = 4", ("1" * 64,))
    return {4}


def _tamper_entry_hash(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET entry_hash = ? WHERE seq = 2", ("2" * 64,))
    return {2, 3}


def _tamper_signature(conn, signer, attacker_signer):
    sig = _row(conn, 5)[6]
    conn.execute("UPDATE entries SET signature = ? WHERE seq = 5", (("0" if sig[0] != "0" else "1") + sig[1:],))
    return {5}


def _tamper_strip_signature(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET signature = NULL, signer = NULL WHERE seq = 3")
    return {3}


def _tamper_created_at(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET created_at = ? WHERE seq = 2", ("2026-03-03T09:30:00.000+00:00",))
    return {2}


def _tamper_kind(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET kind = 'document' WHERE seq = 3")
    return {3}


def _tamper_delete(conn, signer, attacker_signer):
    conn.execute("DELETE FROM entries WHERE seq = 3")
    return {4}


def _tamper_swap(conn, signer, attacker_signer):
    cols = "kind, payload, prev_hash, created_at, entry_hash, signature, signer"
    r2 = conn.execute(f"SELECT {cols} FROM entries WHERE seq = 2").fetchone()
    r3 = conn.execute(f"SELECT {cols} FROM entries WHERE seq = 3").fetchone()
    upd = ("UPDATE entries SET kind = ?, payload = ?, prev_hash = ?, created_at = ?, entry_hash = ?, "
           "signature = ?, signer = ? WHERE seq = ?")
    conn.execute(upd, (*r3, 2))
    conn.execute(upd, (*r2, 3))
    return {2, 3}


def _forged_row(seq, prev_hash, created_at, sign_with, signer_field):
    payload = _forged_payload()
    text = canonical_json(payload).decode("utf-8")
    h = compute_entry_hash(seq, "copy", payload, prev_hash, created_at)
    sig = sign_with.sign(bytes.fromhex(h)) if sign_with else None
    return (seq, "copy", text, prev_hash, created_at, h, sig, signer_field)


def _tamper_insert_end_attacker_key(conn, signer, attacker_signer):
    head = _row(conn, N_ENTRIES)
    row = _forged_row(N_ENTRIES + 1, head[5], "2026-03-05T10:00:00.000+00:00",
                      attacker_signer, attacker_signer.public_key_hex)
    conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    return {N_ENTRIES + 1}


def _tamper_insert_end_claimed_key(conn, signer, attacker_signer):
    head = _row(conn, N_ENTRIES)
    row = _forged_row(N_ENTRIES + 1, head[5], "2026-03-05T10:00:00.000+00:00",
                      attacker_signer, signer.public_key_hex)
    conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    return {N_ENTRIES + 1}


def _tamper_insert_middle(conn, signer, attacker_signer):
    conn.execute("UPDATE entries SET seq = seq + 1000 WHERE seq >= 4")
    conn.execute("UPDATE entries SET seq = seq - 999 WHERE seq >= 1000")
    row3 = _row(conn, 3)
    conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 _forged_row(4, row3[5], row3[4], attacker_signer, signer.public_key_hex))
    return {4, 5}


TAMPERS = [
    _tamper_prev_hash, _tamper_entry_hash, _tamper_signature, _tamper_strip_signature, _tamper_created_at,
    _tamper_kind, _tamper_delete, _tamper_swap, _tamper_insert_end_attacker_key,
    _tamper_insert_end_claimed_key, _tamper_insert_middle,
]


@pytest.mark.parametrize("tamper", TAMPERS, ids=[t.__name__[len("_tamper_"):] for t in TAMPERS])
def test_tampering_is_detected(signed_db, signer, attacker_signer, tamper):
    with attacker(signed_db) as conn:
        expected = tamper(conn, signer, attacker_signer)
    rep = verify_registry(signed_db, signer.public_key_hex)
    assert not rep.ok
    assert expected <= _problem_seqs(rep), rep.problems
    for _, text in rep.problems:  # Indonesian, ASCII-only descriptions
        assert text and text.isascii()


def _strip(conn, seq):
    conn.execute("UPDATE entries SET signature = NULL, signer = NULL WHERE seq = ?", (seq,))


def _strip_and_rewrite_last(conn):
    """Strip the last signature and change who received the copy, with a recomputed hash."""
    seq, kind, payload, prev, created_at, _, _, _ = _row(conn, N)
    obj = json.loads(payload)
    obj["recipient_id"] = "R999"
    h = compute_entry_hash(seq, kind, obj, prev, created_at)
    conn.execute("UPDATE entries SET payload = ?, entry_hash = ?, signature = NULL, signer = NULL WHERE seq = ?",
                 (canonical_json(obj).decode("utf-8"), h, seq))


def _append_forged_unsigned(conn):
    head = _row(conn, N)
    conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 _forged_row(N + 1, head[5], "2026-03-05T10:00:00.000+00:00", None, None))


# (id, tamper, outcome, problem seqs by default). Outcomes:
#   problem  - reported by default and also with unsigned entries allowed;
#   unsigned - reported by default (signatures required); allowed, the verdict names them;
#   anchor   - a valid shorter chain: only an anchor or a Merkle root file reveals it.
EDGE_CASES = [
    ("strip_sig_first", lambda c: _strip(c, 1), "problem", {1}),
    ("strip_sig_last", lambda c: _strip(c, N), "unsigned", {N}),
    ("strip_and_rewrite_last", _strip_and_rewrite_last, "unsigned", {N}),
    ("entry_hash_first", lambda c: c.execute("UPDATE entries SET entry_hash = ? WHERE seq = 1", ("2" * 64,)),
     "problem", {1, 2}),
    ("entry_hash_last", lambda c: c.execute("UPDATE entries SET entry_hash = ? WHERE seq = ?", ("2" * 64, N)),
     "problem", {N}),
    ("delete_first", lambda c: c.execute("DELETE FROM entries WHERE seq = 1"), "problem", {2}),
    ("delete_all", lambda c: c.execute("DELETE FROM entries"), "problem", {0}),
    ("append_forged_unsigned", _append_forged_unsigned, "unsigned", {N + 1}),
    ("delete_last", lambda c: c.execute("DELETE FROM entries WHERE seq = ?", (N,)), "anchor", set()),
]


@pytest.mark.parametrize("tamper, outcome, expected", [c[1:] for c in EDGE_CASES], ids=[c[0] for c in EDGE_CASES])
def test_tampering_first_and_last_rows(signed_db, signer, tmp_path, tamper, outcome, expected):
    pub = signer.public_key_hex
    roots = tmp_path / "akar"
    export_daily_roots(signed_db, roots)
    head = verify_registry(signed_db, pub)
    anchor = [(head.head_seq, head.head_hash)]
    with attacker(signed_db) as conn:
        tamper(conn)
    default = verify_registry(signed_db, pub)
    relaxed = verify_registry(signed_db, pub, require_signed=False)
    if outcome == "problem":
        assert not default.ok and expected <= _problem_seqs(default), default.problems
        assert not relaxed.ok
    elif outcome == "unsigned":
        assert not default.ok and expected <= _problem_seqs(default), default.problems
        assert any("belum bertanda tangan" in t for _, t in default.problems)
        assert relaxed.ok and relaxed.unsigned == 1
        assert relaxed.verdict().startswith("HASIL: RANTAI UTUH, TETAPI 1 entri")
        assert not any("semua tanda tangan sah" in line for line in relaxed.lines())
    else:
        assert default.ok  # the documented limit of a hash chain...
        assert any("ujung rantai tidak dapat dideteksi" in line for line in default.lines())  # ...stated
        caught = verify_registry(signed_db, pub, anchors=anchor)
        assert not caught.ok and any(s == N and "tidak ditemukan" in t for s, t in caught.problems)
        assert not verify_registry(signed_db, pub, merkle_dir=roots).ok


def test_swap_and_delete_are_explained(signed_db, signer, attacker_signer):
    with attacker(signed_db) as conn:
        _tamper_swap(conn, signer, attacker_signer)
    texts = " | ".join(t for _, t in verify_registry(signed_db, signer.public_key_hex).problems)
    assert "urutan diubah" in texts


def test_gap_is_reported(signed_db, signer, attacker_signer):
    with attacker(signed_db) as conn:
        _tamper_delete(conn, signer, attacker_signer)
    texts = [t for s, t in verify_registry(signed_db, signer.public_key_hex).problems if s == 4]
    assert any("melompat" in t for t in texts)


def test_rewritten_unsigned_chain_needs_signatures_or_merkle(unsigned_db, signer, tmp_path):
    """An attacker who recomputes every hash defeats an unsigned chain, not signatures or roots."""
    roots = tmp_path / "akar"
    export_daily_roots(unsigned_db, roots)
    with attacker(unsigned_db) as conn:
        prev = ZERO_HASH
        for seq in range(1, N_ENTRIES + 1):
            _, kind, payload, _, created_at, _, _, _ = _row(conn, seq)
            obj = json.loads(payload)
            if seq == 3:
                obj["recipient_id"] = "R999"
            h = compute_entry_hash(seq, kind, obj, prev, created_at)
            conn.execute("UPDATE entries SET payload = ?, prev_hash = ?, entry_hash = ? WHERE seq = ?",
                         (canonical_json(obj).decode("utf-8"), prev, h, seq))
            prev = h
    pub = signer.public_key_hex
    assert not verify_registry(unsigned_db, pub).ok  # default: unsigned entries are a problem
    assert verify_registry(unsigned_db, pub, require_signed=False).ok  # the chain alone is fooled
    rep = verify_registry(unsigned_db, pub, require_signed=False, merkle_dir=roots)
    assert not rep.ok
    assert any("akar Merkle tidak cocok" in t for _, t in rep.problems)


def test_malformed_rows_are_reported_not_crashing(signed_db, signer, tmp_path):
    with attacker(signed_db) as conn:
        conn.execute("UPDATE entries SET payload = ? WHERE seq = 2", ("[" * 100000 + "]" * 100000,))
        conn.execute("UPDATE entries SET payload = ? WHERE seq = 3", (b"\xff\x00",))
        conn.execute("UPDATE entries SET created_at = 12345, entry_hash = 'zz' WHERE seq = 4")
    rep = verify_registry(signed_db, signer.public_key_hex, merkle_dir=tmp_path / "tidak-ada")
    assert {2, 3, 4} <= _problem_seqs(rep)
    assert any(s == 2 and "bukan JSON yang sah" in t for s, t in rep.problems)
    assert verify_main([str(signed_db), "--public-key", signer.public_key_hex]) == 1
    with Registry.open(signed_db, repair_triggers=True) as reg:
        with pytest.raises(RegistryError):
            sign_pending(reg, signer)


def test_wrong_public_key_fails(signed_db, attacker_signer):
    rep = verify_registry(signed_db, attacker_signer.public_key_hex)
    assert not rep.ok
    assert _problem_seqs(rep) == set(range(1, N_ENTRIES + 1))
    assert all("kunci lain" in t for _, t in rep.problems)
    with pytest.raises(SigningKeyError):
        verify_registry(signed_db, "not-a-key")


# ---- signing -------------------------------------------------------------------------


def test_signed_append_does_not_launder_a_forged_row(signed_db, signer, capsys):
    """A correctly chained unsigned row inserted with the triggers in place stays unsigned."""
    conn = sqlite3.connect(signed_db)
    head = _row(conn, N)
    conn.execute(f"INSERT INTO entries ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 _forged_row(N + 1, head[5], "2026-03-05T10:00:00.000+00:00", None, None))
    conn.commit()
    conn.close()
    with Registry.open(signed_db) as reg:  # triggers are intact, so the file opens normally
        with pytest.raises(RegistryError, match="belum bertanda tangan"):
            reg.append("note", {"n": 1}, signer=signer)
        assert [e.seq for e in reg.pending()] == [N + 1]
        assert len(reg.entries()) == N + 1  # the refused append left nothing behind
    rep = verify_registry(signed_db, signer.public_key_hex)
    assert not rep.ok and N + 1 in _problem_seqs(rep)
    capsys.readouterr()
    assert signing_main(["sign-pending", str(signed_db), "--daftar"]) == 0  # the review shows the forged row
    out = capsys.readouterr().out
    assert f"Entri bertanda tangan terakhir: #{N}" in out
    assert f"#{N + 1}  salinan" in out and "recipient_id R099" in out and "copy_id 0000000000000063" in out


def test_sign_pending_up_to_reviewed_entry(unsigned_db, signer):
    pub = signer.public_key_hex
    rep = verify_registry(unsigned_db, pub, require_signed=False)
    assert rep.ok and rep.unsigned == N_ENTRIES and rep.warnings
    assert not verify_registry(unsigned_db, pub).ok
    with Registry.open(unsigned_db) as reg:
        assert sign_pending(reg, signer, up_to=3) == 3
        assert [e.seq for e in reg.pending()] == [4, 5, 6]
        assert sign_pending(reg, signer, up_to=3) == 0
        assert sign_pending(reg, signer) == 3
        assert sign_pending(reg, signer) == 0
        e = reg.append("note", {"n": 1}, signer=signer)  # nothing pending: only the new entry is signed
        assert e.signed
        reg.append("note", {"n": 2})
        with pytest.raises(RegistryError):
            reg.append("note", {"n": 3}, signer=signer)
        assert len(reg.entries()) == N + 2
    assert not verify_registry(unsigned_db, pub).ok
    rep = verify_registry(unsigned_db, pub, require_signed=False)
    assert rep.ok and (rep.unsigned_first, rep.unsigned_last) == (N + 2, N + 2)


def test_sign_pending_refuses_a_tampered_chain(unsigned_db, signer):
    with attacker(unsigned_db) as conn:
        conn.execute("UPDATE entries SET payload = replace(payload, 'R002', 'R009') WHERE seq = 3")
    with Registry.open(unsigned_db, repair_triggers=True) as reg:
        with pytest.raises(RegistryError):
            sign_pending(reg, signer)
        assert not any(e.signed for e in reg.entries())


def test_sign_pending_refuses_stripped_or_bad_signatures(tmp_path, signer, attacker_signer):
    db = _build(tmp_path / "a.db", signer)
    with attacker(db) as conn:
        _strip(conn, 3)  # an unsigned entry before signed ones: a removed signature
    with Registry.open(db, repair_triggers=True) as reg:
        with pytest.raises(RegistryError, match="tanda tangan dihapus"):
            sign_pending(reg, signer)
    db = _build(tmp_path / "b.db", signer)
    with attacker(db) as conn:
        _tamper_signature(conn, signer, attacker_signer)
    with Registry.open(db, repair_triggers=True) as reg:
        reg.append("note", {"n": 1})
        with pytest.raises(RegistryError, match="tanda tangan entri #5 tidak sah"):
            sign_pending(reg, signer)
        assert [e.seq for e in reg.pending()] == [N + 1]


# ---- keys ----------------------------------------------------------------------------


def test_signing_key_files(tmp_path):
    key = tmp_path / "keys" / "registry_signing.key"
    s = generate_signing_key(key)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert key.read_text() == f"ed25519-seed:{s.seed_hex()}\n"
    pub = key.with_suffix(".pub")
    assert pub.read_text().strip() == s.public_key_hex
    assert load_signer(key).public_key_hex == s.public_key_hex
    legacy = tmp_path / "legacy.key"
    legacy.write_text(s.seed_hex() + "\n")  # bare hex seed of earlier versions
    assert load_signer(legacy).public_key_hex == s.public_key_hex
    assert load_public_key(pub) == load_public_key(s.public_key_hex.upper()) == s.public_key_hex
    with pytest.raises(SigningKeyError):
        generate_signing_key(key)  # never silently replaced
    with pytest.raises(FileNotFoundError):
        load_signer(tmp_path / "missing.key")
    created = load_signer(tmp_path / "new" / "k.key", create=True)
    assert (tmp_path / "new" / "k.pub").read_text().strip() == created.public_key_hex
    assert s.seed_hex() not in repr(s)


def test_private_key_file_is_never_accepted_as_public_key(tmp_path, signer, capsys):
    key = tmp_path / "keys" / "registry_signing.key"
    s = generate_signing_key(key)
    renamed = tmp_path / "kunci.txt"
    renamed.write_bytes(key.read_bytes())
    legacy = tmp_path / "lama.key"
    legacy.write_text(s.seed_hex() + "\n")
    for value in (key, renamed, legacy, f"ed25519-seed:{s.seed_hex()}"):
        with pytest.raises(SigningKeyError, match="PRIVAT"):
            load_public_key(value)
    db = _build(tmp_path / "r.db", s)
    capsys.readouterr()
    assert verify_main([str(db), "--public-key", str(key)]) == 1
    captured = capsys.readouterr()
    assert "PRIVAT" in captured.err
    assert s.seed_hex() not in captured.out + captured.err


def test_key_file_edge_cases(tmp_path, signer):
    old = tmp_path / "a.key"
    old.write_text("kunci lama\n")
    os.chmod(old, 0o644)
    s = generate_signing_key(old, overwrite=True)
    assert stat.S_IMODE(old.stat().st_mode) == 0o600 and load_signer(old).public_key_hex == s.public_key_hex
    with pytest.raises(SigningKeyError, match=".pub"):
        generate_signing_key(tmp_path / "b.pub")
    with pytest.raises(SigningKeyError, match="berbeda"):
        generate_signing_key(tmp_path / "c.key", public_path=tmp_path / "c.key")
    assert not (tmp_path / "c.key").exists()
    with pytest.raises(SigningKeyError):
        export_public_key(signer, tmp_path / "d.key")
    assert signing_main(["generate", "--key", str(tmp_path / "e.key"), "--public", str(tmp_path / "e.key")]) == 1
    assert not (tmp_path / "e.key").exists()


# ---- signing CLI ---------------------------------------------------------------------


def test_signing_cli_review_then_sign(tmp_path, capsys):
    key = tmp_path / "k" / "registry_signing.key"
    pub = key.with_suffix(".pub")
    assert signing_main(["generate", "--key", str(key)]) == 0
    db = _build(tmp_path / "r.db", None)
    capsys.readouterr()
    assert signing_main(["sign-pending", str(db), "--daftar"]) == 0
    out = capsys.readouterr().out
    assert "Entri bertanda tangan terakhir: belum ada" in out and "Entri belum bertanda tangan: 6" in out
    assert "#1  dokumen" in out and "doc_hash aaaaaaaaaaaaaaaa" in out and "doc_name nota_dinas.pdf" in out
    assert "#2  salinan" in out and "recipient_id R001" in out and "copy_id 0000000000000001" in out
    assert signing_main(["sign-pending", str(db), "--key", str(key)]) == 1  # no --sampai: nothing signed
    assert "--sampai" in capsys.readouterr().err
    assert verify_registry(db, load_public_key(pub), require_signed=False).unsigned == N
    assert signing_main(["sign-pending", str(db), "--key", str(key), "--sampai", "4"]) == 0
    out = capsys.readouterr().out
    assert "4 entri sampai #4 ditandatangani" in out and "(#5..#6) belum diperiksa" in out
    assert verify_main([str(db), "--public-key", str(pub)]) == 1
    assert signing_main(["sign-pending", str(db), "--key", str(key), "--sampai", "6"]) == 0
    assert verify_main([str(db), "--public-key", str(pub)]) == 0
    assert signing_main(["generate", "--key", str(key)]) == 1
    assert "Gagal" in capsys.readouterr().err


def test_signing_cli_errors_are_indonesian(tmp_path, signer, capsys):
    key = tmp_path / "k.key"
    generate_signing_key(key)
    junk = tmp_path / "bukan.db"
    junk.write_bytes(b"ini bukan berkas sqlite " * 100)
    capsys.readouterr()
    assert signing_main(["sign-pending", str(junk), "--key", str(key), "--sampai", "1"]) == 1
    err = capsys.readouterr().err
    assert "Gagal: registri tidak dapat dibuka" in err and "Traceback" not in err
    assert signing_main(["sign-pending", str(tmp_path / "tidak-ada.db"), "--daftar"]) == 1
    assert "tidak ditemukan" in capsys.readouterr().err
    for argv, text in ([[], "argumen wajib belum diisi"],
                       [["sign-pending"], "argumen wajib belum diisi"],
                       [["sign-pending", "r.db", "--sampai", "x"], "tidak sah untuk --sampai"],
                       [["hapus"], "tidak sah"]):
        with pytest.raises(SystemExit) as exc:
            signing_main(argv)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert text in err and "Penggunaan:" in err and "usage:" not in err and "error:" not in err


# ---- Merkle --------------------------------------------------------------------------


def _hashes(n: int) -> list[str]:
    return [hashlib.sha256(str(i).encode()).hexdigest() for i in range(n)]


def _node(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(a + b).digest()


def test_merkle_root_matches_hand_computation():
    h = _hashes(3)
    raw = [bytes.fromhex(x) for x in h]
    assert merkle_root(h[:1]) == h[0]  # a single leaf is its own root
    assert merkle_root(h[:2]) == _node(raw[0], raw[1]).hex()
    assert merkle_root(h) == _node(_node(raw[0], raw[1]), _node(raw[2], raw[2])).hex()  # odd leaf duplicated
    with pytest.raises(ValueError):
        merkle_root([])
    with pytest.raises(ValueError):
        merkle_root(["zz"])
    assert [tree_depth(n) for n in (1, 2, 3, 4, 5, 8, 9)] == [0, 1, 2, 2, 3, 3, 4]


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 13])
def test_merkle_proofs_verify(n):
    h = _hashes(n)
    root = merkle_root(h)
    assert merkle_root(list(h)) == root  # stable
    for i in range(n):
        proof = merkle_proof(h, i)
        assert verify_proof(h[i], proof, root)
        assert verify_proof(h[i], proof, root, index=i, count=n)
        assert not verify_proof(_hashes(n + 1)[-1], proof, root)
        if proof:
            sib, side = proof[0]
            assert not verify_proof(h[i], [("0" * 64, side)] + proof[1:], root)
            if sib != h[i]:  # a duplicated odd leaf is its own sibling: side does not matter
                assert not verify_proof(h[i], [(sib, "R" if side == "L" else "L")] + proof[1:], root)
        assert not verify_proof(h[i], [("zz", "L")], root) and not verify_proof(h[i], [("0" * 64, "X")], root)


def test_proof_shape_is_pinned_by_index_and_count():
    h2 = _hashes(2)
    root2 = merkle_root(h2)
    assert verify_proof(root2, [], root2)  # without index/count an inner node passes as a leaf...
    assert not verify_proof(root2, [], root2, index=0, count=2)  # ...with them it does not
    h4 = _hashes(4)
    root4 = merkle_root(h4)
    raw = [bytes.fromhex(x) for x in h4]
    left, right = _node(raw[0], raw[1]).hex(), _node(raw[2], raw[3]).hex()
    assert verify_proof(left, [(right, "R")], root4)
    assert not verify_proof(left, [(right, "R")], root4, index=0, count=4)
    proof = merkle_proof(h4, 2)
    assert verify_proof(h4[2], proof, root4, index=2, count=4)
    assert not verify_proof(h4[2], proof, root4, index=1, count=4)
    assert not verify_proof(h4[2], proof, root4, index=4, count=4)


def test_export_daily_roots(signed_db, signer, tmp_path):
    out = tmp_path / "akar"
    paths = export_daily_roots(signed_db, out)
    assert [p.name for p in paths] == [f"merkle-{DAY1}.txt", f"merkle-{DAY2}.txt"]
    d1, d2 = (parse_root_file(p.read_text()) for p in paths)
    assert list(d1) == ["date", "entries", "first_seq", "last_seq", "root", "previous_root_file_sha256"]
    assert d1 == {**d1, "date": DAY1, "entries": "4", "first_seq": "1", "last_seq": "4",
                  "previous_root_file_sha256": ZERO_HASH}
    assert d2["first_seq"] == "5" and d2["last_seq"] == "6"
    assert d2["previous_root_file_sha256"] == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    with Registry.open(signed_db) as reg:
        entries = reg.entries()
    assert d1["root"] == merkle_root([e.entry_hash for e in entries[:4]])
    raw = [bytes.fromhex(e.entry_hash) for e in entries[4:6]]
    assert d2["root"] == _node(raw[0], raw[1]).hex()  # plain SHA-256(left || right), as specified
    first = [p.read_bytes() for p in paths]
    export_daily_roots(signed_db, out)  # re-export leaves the files byte-identical
    assert [p.read_bytes() for p in paths] == first
    assert check_daily_roots(signed_db, out) == (2, [])
    rep = verify_registry(signed_db, signer.public_key_hex, merkle_dir=out)
    assert rep.ok and rep.merkle_files == 2


def test_export_skips_running_day_and_never_rewrites(signed_db, signer, tmp_path):
    out = tmp_path / "akar"
    paths = export_daily_roots(signed_db, out, today=DAY2)  # DAY2 is still running
    assert [p.name for p in paths] == [f"merkle-{DAY1}.txt"]
    first = (out / f"merkle-{DAY1}.txt").read_bytes()
    offsite = tmp_path / "salinan-luar"  # copied off the machine, as the docs advise
    shutil.copytree(out, offsite)
    with Registry.open(signed_db) as reg:
        reg.append("note", {"n": 1}, signer=signer, created_at=T0 + timedelta(hours=23))  # still DAY2
    paths = export_daily_roots(signed_db, out, today="2026-03-05")
    assert [p.name for p in paths] == [f"merkle-{DAY1}.txt", f"merkle-{DAY2}.txt"]
    assert (out / f"merkle-{DAY1}.txt").read_bytes() == first
    assert parse_root_file((out / f"merkle-{DAY2}.txt").read_text())["entries"] == "3"
    shutil.copy(out / f"merkle-{DAY2}.txt", offsite)
    assert check_daily_roots(signed_db, offsite) == (2, [])  # the old copy still chains
    with attacker(signed_db) as conn:
        conn.execute("UPDATE entries SET entry_hash = ? WHERE seq = 2", ("2" * 64,))
    with pytest.raises(RegistryError, match="tidak pernah ditulis ulang"):
        export_daily_roots(signed_db, out, today="2026-03-05")
    assert (out / f"merkle-{DAY1}.txt").read_bytes() == first


def test_partial_file_for_running_day(signed_db, signer, tmp_path):
    out = tmp_path / "akar"
    paths = export_daily_roots(signed_db, out, today=DAY2, include_partial=True)
    assert [p.name for p in paths] == [f"merkle-{DAY1}.txt", f"merkle-{DAY2}.partial.txt"]
    partial = out / f"merkle-{DAY2}.partial.txt"
    final1 = (out / f"merkle-{DAY1}.txt").read_bytes()
    assert parse_root_file(partial.read_text())["previous_root_file_sha256"] == hashlib.sha256(final1).hexdigest()
    assert check_daily_roots(signed_db, out) == (2, [])
    with Registry.open(signed_db) as reg:
        reg.append("note", {"n": 1}, signer=signer, created_at=T0 + timedelta(hours=23))
    export_daily_roots(signed_db, out, today=DAY2, include_partial=True)  # a partial file is refreshed
    assert parse_root_file(partial.read_text())["entries"] == "3"
    assert check_daily_roots(signed_db, out) == (2, [])
    export_daily_roots(signed_db, out, today="2026-03-05")  # the day ends: final file, partial removed
    assert not partial.exists()
    assert parse_root_file((out / f"merkle-{DAY2}.txt").read_text())["entries"] == "3"
    assert check_daily_roots(signed_db, out) == (2, [])


def test_root_file_name_must_match_its_date(signed_db, tmp_path):
    out = tmp_path / "akar"
    export_daily_roots(signed_db, out)
    shutil.copy(out / f"merkle-{DAY1}.txt", out / "merkle-2026-12-31.txt")
    _, problems = check_daily_roots(signed_db, out)
    assert any("merkle-2026-12-31.txt: nama berkas tidak sesuai tanggal" in t for _, t in problems)
    (out / "merkle-2026-12-31.txt").unlink()
    (out / "merkle-catatan.txt").write_text("bukan akar\n")
    _, problems = check_daily_roots(signed_db, out)
    assert problems == [(0, "merkle-catatan.txt: nama berkas tidak sesuai pola merkle-YYYY-MM-DD.txt")]


def test_entry_added_to_a_closed_day_is_reported(signed_db, signer, tmp_path):
    out = tmp_path / "akar"
    export_daily_roots(signed_db, out)
    with Registry.open(signed_db) as reg:  # backdated into DAY2, whose file is already out
        reg.append("note", {"n": 1}, signer=signer, created_at=T0 + timedelta(hours=23))
    _, problems = check_daily_roots(signed_db, out)
    assert any(s == N + 1 and "setelah hari ditutup" in t for s, t in problems)
    with pytest.raises(RegistryError):
        export_daily_roots(signed_db, out)


def test_daily_roots_group_by_utc_date(tmp_path):
    with Registry.open(tmp_path / "r.db") as reg:
        reg.append("note", {"n": 1}, created_at="2026-11-03T23:30:00-02:00")  # 2026-11-04 01:30 UTC
        reg.append("note", {"n": 2}, created_at="2026-11-04T02:00:00+00:00")
    roots = daily_roots(tmp_path / "r.db")
    assert [(r.date, r.entries, r.first_seq, r.last_seq) for r in roots] == [("2026-11-04", 2, 1, 2)]


# ---- verify CLI ----------------------------------------------------------------------


def test_verify_cli_exit_codes(signed_db, signer, attacker_signer, tmp_path, capsys):
    pub = tmp_path / "registry_signing.pub"
    pub.write_text(signer.public_key_hex + "\n")
    assert verify_main([str(signed_db), "--public-key", str(pub)]) == 0
    assert "HASIL: UTUH" in capsys.readouterr().out
    assert verify_main([str(signed_db), "--public-key", signer.public_key_hex]) == 0
    roots = tmp_path / "akar"
    export_daily_roots(signed_db, roots)
    assert verify_main([str(signed_db), "--public-key", str(pub), "--merkle-dir", str(roots)]) == 0
    capsys.readouterr()
    assert verify_main([str(signed_db), "--public-key", attacker_signer.public_key_hex]) == 1
    assert "TIDAK UTUH" in capsys.readouterr().out
    assert verify_main([str(tmp_path / "tidak-ada.db"), "--public-key", str(pub)]) == 1
    assert verify_main([str(signed_db), "--public-key", "bukan-kunci"]) == 1
    with attacker(signed_db) as conn:
        _tamper_signature(conn, signer, attacker_signer)
    assert verify_main([str(signed_db), "--public-key", str(pub)]) == 1
    out = capsys.readouterr().out
    assert "entri #5" in out and "tanda tangan tidak sah" in out


def test_verify_cli_unsigned_anchors_and_bad_input(unsigned_db, signer, tmp_path, capsys):
    key = signer.public_key_hex
    allow = "--izinkan-belum-bertanda-tangan"
    assert verify_main([str(unsigned_db), "--public-key", key]) == 1
    assert "belum bertanda tangan" in capsys.readouterr().out
    assert verify_main([str(unsigned_db), "--public-key", key, allow]) == 0
    out = capsys.readouterr().out
    assert "HASIL: RANTAI UTUH, TETAPI 6 entri (#1..#6) belum bertanda tangan" in out
    assert "semua tanda tangan sah" not in out
    head = verify_registry(unsigned_db, key, require_signed=False)
    anchor = f"{head.head_seq}:{head.head_hash}"
    assert verify_main([str(unsigned_db), "--public-key", key, allow, "--jangkar", anchor]) == 0
    assert "Jangkar          : 1 dicocokkan" in capsys.readouterr().out
    with attacker(unsigned_db) as conn:
        conn.execute("DELETE FROM entries WHERE seq = ?", (N,))
    assert verify_main([str(unsigned_db), "--public-key", key, allow, "--jangkar", anchor]) == 1
    assert f"jangkar #{N} tidak ditemukan" in capsys.readouterr().out
    for bad in ("6:xyz", "0:" + "a" * 64, "\u00b2:" + "a" * 64):  # malformed, zero, a non-ASCII digit
        assert verify_main([str(unsigned_db), "--public-key", key, "--jangkar", bad]) == 1
        assert "Gagal: jangkar harus berbentuk NOMOR:HASH" in capsys.readouterr().err
    bad_pub = tmp_path / "rusak.pub"
    bad_pub.write_bytes("kunci \u00e9".encode("utf-8"))
    assert verify_main([str(unsigned_db), "--public-key", str(bad_pub)]) == 1
    err = capsys.readouterr().err
    assert "Gagal: berkas kunci berisi karakter yang tidak sah" in err and "Traceback" not in err
    empty = tmp_path / "kosong.db"
    Registry.open(empty).close()
    assert verify_main([str(empty), "--public-key", key]) == 1
    assert "registri kosong" in capsys.readouterr().out
    junk = tmp_path / "bukan.db"
    junk.write_bytes(b"ini bukan berkas sqlite " * 100)
    assert verify_main([str(junk), "--public-key", key]) == 1
    assert "bukan registri TAPAK yang dapat dibaca" in capsys.readouterr().out


def test_verify_cli_usage_errors_exit_1_in_indonesian(signed_db, signer, capsys):
    for argv, text in ([[], "argumen wajib belum diisi"],
                       [[str(signed_db), "--public-key", signer.public_key_hex, "--tidak-ada"], "argumen tidak dikenal"],
                       [[str(signed_db), "--public-key"], "membutuhkan satu nilai"]):
        with pytest.raises(SystemExit) as exc:
            verify_main(argv)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Penggunaan: tapak-verify-registry" in err and text in err
        assert "usage:" not in err and "error:" not in err
    with pytest.raises(SystemExit) as exc:
        verify_main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Penggunaan:" in out and "tampilkan bantuan" in out and "show this help" not in out
    proc = subprocess.run([sys.executable, "-m", "tapak.registry.verify"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1 and "Gagal: argumen wajib belum diisi" in proc.stderr


# ---- issuance manifest ---------------------------------------------------------------


def _manifest():
    from tapak.marker.issue import IssuedCopy, IssueManifest, Recipient
    from tapak.tardos.params import TardosParams

    params = TardosParams(c=3, eps=1e-6, n_max=3)
    copies = [
        IssuedCopy(seq=i, copy_id=f"{i:016x}", recipient=Recipient(f"R{i:03d}", f"Penerima Rahasia {i}",
                                                                   "Kepala Seksi Rahasia", "Satuan Uji"),
                   file=f"x{i}.pdf", file_sha256="c" * 64, code_digest=f"{i:064x}", channels_used=["shift", "zw"],
                   canary_token=f"tokenkanari{i}aaaaa"[:16])
        for i in range(1, 4)
    ]
    manifest = IssueManifest(
        doc_hash=DOC_HASH, doc_name="nota_dinas.pdf", issued_at=T0.isoformat(), issuer="pytest",
        params=params.to_dict(), shift_mm={"word_mm": 0.05, "row_mm": 0.05},
        channels=["shift", "zw", "homoglyph"], excluded_rows=[], plan_summary={"zw": {"slots": 1}},
        threshold_full=88.25, gate={"passed": True}, copies=copies)
    return manifest, params


def test_registry_from_manifest(tmp_path, signer):
    manifest, params = _manifest()
    db = tmp_path / "r.db"
    with Registry.open(db) as reg:
        entries = registry_from_manifest(manifest, reg, signer)
        assert [e.kind for e in entries] == ["document", "copy", "copy", "copy"]
        doc = reg.find_document(DOC_HASH)
        assert doc["params"]["length"] == params.length and doc["threshold_full"] == 88.25
        assert "Z = min_lambda" in doc["threshold_rule"]
        got = reg.copies(DOC_HASH)
        assert [c["recipient_id"] for c in got] == ["R001", "R002", "R003"]
        assert all(set(c) == COPY_FIELDS for c in got)
        token = manifest.copies[1].canary_token
        assert got[1]["canary_token"] == canary_token_digest(token)
        assert reg.find_copy_by_canary(token)["copy_id"] == manifest.copies[1].copy_id
        with pytest.raises(RegistryError):
            registry_from_manifest(manifest, reg, signer)  # same copies twice
        assert len(reg.entries()) == 4
    raw = db.read_bytes()
    assert b"Penerima Rahasia" not in raw and b"Kepala Seksi" not in raw  # names never stored
    assert token.encode() not in raw  # canary tokens only as commitments
    assert verify_registry(db, signer.public_key_hex).ok


def test_registry_from_manifest_refuses_signing_over_pending_entries(tmp_path, signer):
    manifest, _ = _manifest()
    with Registry.open(tmp_path / "r.db") as reg:
        reg.append("note", {"n": 1})  # unsigned, not yet reviewed
        with pytest.raises(RegistryError, match="belum bertanda tangan"):
            registry_from_manifest(manifest, reg, signer)
        assert len(reg.entries()) == 1  # all or nothing
