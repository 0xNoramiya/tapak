"""Channel 5: canary tokens in PDF/DOCX and the authoritative canary DNS listener."""

from __future__ import annotations

import io
import random
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import docx
import numpy as np
import pikepdf
import pymupdf
import pytest
from dnslib import QTYPE, RCODE, DNSRecord

from tapak.canary_dns import (
    CanaryDNSServer,
    HitLogger,
    anchor_head,
    chain_head,
    check_events_chain,
    events,
    init_store,
    read_anchors,
    record_event,
    simulate_open,
    verify_events_anchored,
    verify_events_chain,
)
from tapak.canary_dns.store import TRIGGERS, event_hash
from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.marker.canary import (
    MAX_ACTIONS,
    add_docx_canary,
    add_pdf_canary,
    add_pdf_canary_to_bytes,
    canary_hostname,
    canary_token,
    canary_url,
    find_canary_hosts,
    find_canary_tokens,
    pdf_canary_hook,
    token_from_qname,
)
from tapak.marker.master import load_master
from tapak.marker.render import CopyMarks, render_copy, render_pages
from tapak.registry.chain import Registry, sign_pending
from tapak.registry.signing import Signer, generate_signing_key

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "tapak.test"
DOC_HASH = "ab" * 32
TOKEN = "abcdefghijklmn23"
ACCEPT_S = 5.0
B32 = "abcdefghijklmnopqrstuvwxyz234567"


@pytest.fixture()
def db(tmp_path) -> Path:
    return tmp_path / "tapak.db"


@pytest.fixture()
def server(db):
    with CanaryDNSServer(DOMAIN, db, host="127.0.0.1", port=0) as srv:
        yield srv


def _query(srv: CanaryDNSServer, name: str, qtype: str = "A", tcp: bool = False) -> DNSRecord:
    q = DNSRecord.question(name, qtype)
    return DNSRecord.parse(q.send("127.0.0.1", srv.port, tcp=tcp, timeout=2))


def _query_like_a_resolver(srv: CanaryDNSServer, name: str, attempts: int = 4, timeout: float = 0.5) -> DNSRecord:
    """A recursive resolver retries a lost UDP query after a short timeout; so does this."""
    for k in range(attempts):
        try:
            return DNSRecord.parse(DNSRecord.question(name).send("127.0.0.1", srv.port, timeout=timeout))
        except TimeoutError:
            if k == attempts - 1:
                raise
    raise AssertionError("unreachable")


def _flush(srv: CanaryDNSServer, timeout: float = ACCEPT_S) -> dict[str, int]:
    """Wait until the writer thread has handled every queued hit; return the counters."""
    end = time.monotonic() + timeout
    while True:
        st = srv.stats()
        if st["written"] + st["failed"] + st["deduplicated"] + st["dropped"] >= st["received"]:
            return st
        assert time.monotonic() < end, f"writer did not catch up: {st}"
        time.sleep(0.01)


def _wait_for_event(db: Path, token: str, t0: float):
    """Poll the store until an event for ``token`` appears; return (events, elapsed)."""
    while True:
        found = events(db, token=token)
        elapsed = time.perf_counter() - t0
        if found or elapsed > ACCEPT_S:
            return found, elapsed
        time.sleep(0.02)


def _docx_bytes() -> bytes:
    d = docx.Document()
    d.add_heading("NOTA DINAS", level=1)
    d.add_paragraph("Kepada: Penerima Fiktif")
    d.add_paragraph("Isi nota dinas ini hanya untuk pengujian.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def _record(db: Path, n: int) -> None:
    for i in range(n):
        record_event(db, f"abcdefghijklmn2{i % 6 + 2}.c.tapak.test", f"abcdefghijklmn2{i % 6 + 2}",
                     "A", "192.0.2.1", 40000 + i)


def _rewrite_chain(db: Path, seq: int, **changes: object) -> None:
    """What an attacker with write access does: edit a row, recompute every hash, restore triggers."""
    con = sqlite3.connect(db)
    for name in TRIGGERS:
        con.execute(f"DROP TRIGGER {name}")
    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)
        con.execute(f"UPDATE canary_events SET {sets} WHERE seq = ?", (*changes.values(), seq))
    prev = "0" * 64
    rows = con.execute("SELECT seq, received_at, qname, token, qtype, src_ip, src_port "
                       "FROM canary_events ORDER BY seq").fetchall()
    for row in rows:
        h = event_hash(prev, *row)
        con.execute("UPDATE canary_events SET prev_hash = ?, hash = ? WHERE seq = ?", (prev, h, row[0]))
        prev = h
    for name, body in TRIGGERS.items():
        con.execute(f"CREATE TRIGGER {name} {body}")
    con.commit()
    con.close()


def _truncate(db: Path, keep: int) -> None:
    """Cut the tail off the chain and restore the delete trigger."""
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER canary_events_no_delete")
    con.execute("DELETE FROM canary_events WHERE seq > ?", (keep,))
    con.execute(f"CREATE TRIGGER canary_events_no_delete {TRIGGERS['canary_events_no_delete']}")
    con.commit()
    con.close()


def _closed_by_peer(sock: socket.socket) -> bool:
    try:
        return sock.recv(1) == b""
    except ConnectionResetError:
        return True


# --- token and names ---------------------------------------------------------------------


def test_token_is_a_16_char_lowercase_base32_dns_label(secret):
    t = canary_token(secret, DOC_HASH, "0123456789abcdef")
    assert re.fullmatch(r"[a-z2-7]{16}", t)
    assert t == canary_token(secret, DOC_HASH, "0123456789abcdef")
    others = {canary_token(secret, DOC_HASH, f"{i:016x}") for i in range(200)}
    assert len(others) == 200
    assert canary_token(secret, "cd" * 32, "0123456789abcdef") != t
    assert canary_token(b"\x01" * 32, DOC_HASH, "0123456789abcdef") != t


def test_hostname_and_url_hold_no_secret(secret):
    t = canary_token(secret, DOC_HASH, "c1")
    assert canary_hostname(t, "Tapak.Test.") == f"{t}.c.tapak.test"
    url = canary_url(t, DOMAIN)
    assert url == f"http://{t}.c.tapak.test/"
    assert secret.hex() not in url and DOC_HASH not in url
    with pytest.raises(ValueError):
        canary_hostname("NOT-A-TOKEN", DOMAIN)
    with pytest.raises(ValueError):
        canary_url(t, "bad_domain!")


def test_token_from_qname_is_case_insensitive():
    assert token_from_qname(f"{TOKEN}.c.tapak.test.", DOMAIN) == TOKEN
    assert token_from_qname("AbCdEfGhIjKlMn23.C.TaPaK.TeSt", DOMAIN) == TOKEN
    assert token_from_qname(f"{TOKEN}.c.other.test", DOMAIN) is None
    assert token_from_qname(f"x.{TOKEN}.c.tapak.test", DOMAIN) is None
    assert token_from_qname("abcdefghijklmn01.c.tapak.test", DOMAIN) is None  # 0 and 1 are not base32
    assert token_from_qname("c.tapak.test", DOMAIN) is None


# --- PDF ---------------------------------------------------------------------------------


def test_pdf_hook_in_render_copy_keeps_rendering_and_text(sample_pdf, secret):
    master = load_master(sample_pdf)
    url = canary_url(canary_token(secret, master.doc_hash, "c1"), DOMAIN)
    plain = render_copy(master, CopyMarks())
    marked = render_copy(master, CopyMarks(doc_hooks=[pdf_canary_hook(url)]))
    before, after = render_pages(plain, 100), render_pages(marked, 100)
    assert len(before) == len(after) > 0
    for a, b in zip(before, after):
        assert np.array_equal(a, b)
    assert extract_pdf_text(marked) == extract_pdf_text(plain)
    assert find_canary_hosts(plain, "pdf") == []
    assert find_canary_hosts(marked, "pdf") == [url.split("/")[2]]
    assert find_canary_tokens(marked, "pdf", DOMAIN) == [canary_token(secret, master.doc_hash, "c1")]


def test_pdf_hook_chains_an_existing_open_action(sample_pdf):
    url = canary_url(TOKEN, DOMAIN)
    with pymupdf.open(stream=sample_pdf, filetype="pdf") as doc:
        cat = doc.pdf_catalog()
        doc.xref_set_key(cat, "OpenAction", f"[{doc[0].xref} 0 R /Fit]")
        add_pdf_canary(doc, url)
        data = doc.tobytes(garbage=3)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        kind, value = doc.xref_get_key(doc.pdf_catalog(), "OpenAction")
        action = doc.xref_object(int(value.split()[0]), compressed=True)
    assert kind == "xref"
    assert "/S/URI" in action and "/Next<</S/GoTo/D[" in action and "/Fit]" in action
    assert find_canary_hosts(data, "pdf") == [f"{TOKEN}.c.tapak.test"]


# --- DOCX --------------------------------------------------------------------------------


def test_docx_canary_is_an_external_linked_picture():
    plain = _docx_bytes()
    url = canary_url(TOKEN, DOMAIN)
    marked = add_docx_canary(plain, url)
    d = docx.Document(io.BytesIO(marked))
    assert [p.text for p in d.paragraphs] == [p.text for p in docx.Document(io.BytesIO(plain)).paragraphs]
    ext = [r for r in d.part.rels.values() if r.is_external and r.reltype.endswith("/image")]
    assert [r.target_ref for r in ext] == [url]
    assert len(d.inline_shapes) == 1
    assert f'r:link="{ext[0].rId}"' in d.inline_shapes[0]._inline.xml
    assert find_canary_hosts(plain, "docx") == []
    assert find_canary_hosts(marked, "docx") == [f"{TOKEN}.c.tapak.test"]
    with pytest.raises(ValueError):
        find_canary_hosts(marked, "xlsx")


# --- reading untrusted files -------------------------------------------------------------


def test_find_canary_hosts_rejects_unreadable_files_in_indonesian():
    with pytest.raises(ValueError, match="berkas PDF tidak dapat dibaca"):
        find_canary_hosts(b"bukan pdf sama sekali", "pdf")
    with pytest.raises(ValueError, match="berkas DOCX tidak dapat dibaca"):
        find_canary_hosts(b"bukan zip", "docx")


def test_long_next_chain_is_walked_without_recursion():
    pdf = pikepdf.new()
    pdf.add_blank_page()
    nxt = None
    for i in range(3000):  # the old recursive walk raised RecursionError here
        action = pikepdf.Dictionary(Type=pikepdf.Name.Action, S=pikepdf.Name.URI,
                                    URI=pikepdf.String(f"http://h{i}.example/"))
        if nxt is not None:
            action.Next = nxt
        nxt = pdf.make_indirect(action)
    pdf.Root.OpenAction = nxt
    buf = io.BytesIO()
    pdf.save(buf)
    hosts = find_canary_hosts(buf.getvalue(), "pdf")
    assert len(hosts) == MAX_ACTIONS and hosts[0] == "h2999.example"


def test_oversized_rels_part_is_skipped():
    marked = add_docx_canary(_docx_bytes(), canary_url(TOKEN, DOMAIN))
    buf = io.BytesIO(marked)
    big = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
           'relationships"><Relationship Id="rX" TargetMode="External" Target="http://big.example/" '
           'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"/>'
           + " " * 2_000_000 + "</Relationships>")
    with zipfile.ZipFile(buf, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/_rels/big.xml.rels", big)
    assert find_canary_hosts(buf.getvalue(), "docx") == [f"{TOKEN}.c.tapak.test"]


# --- acceptance: a query is logged within 5 s of opening a copy --------------------------


def test_acceptance_pdf_open_logged_within_5s(server, db, sample_pdf, secret):
    token = canary_token(secret, DOC_HASH, "pdf-copy")
    copy = add_pdf_canary_to_bytes(sample_pdf, canary_url(token, DOMAIN))
    t0 = time.perf_counter()
    assert simulate_open(copy, "pdf", ("127.0.0.1", server.port)) == [canary_hostname(token, DOMAIN)]
    found, elapsed = _wait_for_event(db, token, t0)
    assert found, "no canary event logged"
    assert elapsed < ACCEPT_S
    assert found[0].token == token and found[0].qtype == "A" and found[0].src_ip == "127.0.0.1"


def test_acceptance_docx_open_logged_within_5s(server, db, secret):
    token = canary_token(secret, DOC_HASH, "docx-copy")
    copy = add_docx_canary(_docx_bytes(), canary_url(token, DOMAIN))
    t0 = time.perf_counter()
    assert simulate_open(copy, "docx", ("127.0.0.1", server.port)) == [canary_hostname(token, DOMAIN)]
    found, elapsed = _wait_for_event(db, token, t0)
    assert found, "no canary event logged"
    assert elapsed < ACCEPT_S
    assert found[0].token == token


def test_repeated_opens_fire_again_with_ttl_zero(db, sample_pdf):
    copy = add_pdf_canary_to_bytes(sample_pdf, canary_url(TOKEN, DOMAIN))
    with CanaryDNSServer(DOMAIN, db, host="127.0.0.1", port=0, dedupe_s=0) as srv:
        for _ in range(3):
            simulate_open(copy, "pdf", ("127.0.0.1", srv.port))
        reply = _query(srv, canary_hostname(TOKEN, DOMAIN))
        _flush(srv)
    assert len(events(db, token=TOKEN)) == 4
    assert reply.rr[0].ttl == 0


def test_identical_hits_within_the_dedupe_window_are_logged_once(server, db, sample_pdf, tmp_path):
    copy = add_pdf_canary_to_bytes(sample_pdf, canary_url(TOKEN, DOMAIN))
    simulate_open(copy, "pdf", ("127.0.0.1", server.port))
    simulate_open(copy, "pdf", ("127.0.0.1", server.port))  # e.g. a resolver retry
    st = _flush(server)
    assert len(events(db, token=TOKEN)) == 1 and st["deduplicated"] == 1
    # unit level: other query types are separate keys, and the window expires
    hits = HitLogger(tmp_path / "unit.db", dedupe_s=0.2)
    hits.submit("q", TOKEN, "A", "192.0.2.1", 1)
    hits.submit("q", TOKEN, "A", "192.0.2.1", 2)
    hits.submit("q", TOKEN, "AAAA", "192.0.2.1", 3)
    time.sleep(0.25)
    hits.submit("q", TOKEN, "A", "192.0.2.1", 4)
    hits.start()
    hits.stop()
    assert [e.src_port for e in events(tmp_path / "unit.db")] == [1, 3, 4]
    assert hits.stats().deduplicated == 1


# --- DNS behaviour -----------------------------------------------------------------------


def test_dns_0x20_case_randomization(server, db):
    mixed = "AbCdEfGhIjKlMn23.C.TaPaK.tEsT"
    reply = _query(server, mixed)
    assert reply.header.rcode == RCODE.NOERROR and reply.header.aa == 1
    assert str(reply.q.qname) == mixed + "."  # question echoed with the same case
    assert str(reply.rr[0].rname) == mixed + "."
    assert str(reply.rr[0].rdata) == "127.0.0.1" and reply.rr[0].ttl == 0
    _flush(server)
    ev = events(db, token=TOKEN)
    assert len(ev) == 1 and ev[0].token == TOKEN and ev[0].qname == f"{TOKEN}.c.tapak.test"
    # simulate_open with random case is logged under the lowercase token too
    other = "zyxwvutsrqponm76"
    copy = add_docx_canary(_docx_bytes(), canary_url(other, DOMAIN))
    simulate_open(copy, "docx", ("127.0.0.1", server.port), randomize_case=True)
    _flush(server)
    assert [e.token for e in events(db, token=other)] == [other]


def test_other_zones_are_refused_and_not_logged(server, db):
    for name in ("example.com", f"{TOKEN}.c.other.test", "tapak.test.evil.example"):
        reply = _query(server, name)
        assert reply.header.rcode == RCODE.REFUSED
        assert reply.header.aa == 0 and not reply.rr
    assert _flush(server)["received"] == 0
    assert events(db) == []


def test_apex_and_zone_structure(server, db):
    soa = _query(server, DOMAIN, "SOA")
    assert soa.header.rcode == RCODE.NOERROR and soa.rr[0].rtype == QTYPE.SOA
    assert soa.rr[0].rdata.times[-1] == 0  # negative answers are not cached either
    ns = _query(server, DOMAIN, "NS")
    assert ns.rr[0].rtype == QTYPE.NS and str(ns.rr[0].rdata) == "ns1.tapak.test."
    ns1 = _query(server, "ns1.tapak.test")
    assert str(ns1.rr[0].rdata) == "127.0.0.1"  # ns_ip defaults to the concrete listen address
    # c.<domain> must answer NOERROR (empty) so QNAME-minimizing resolvers continue
    parent = _query(server, "c.tapak.test")
    assert parent.header.rcode == RCODE.NOERROR and not parent.rr
    junk = _query(server, "not-a-token.c.tapak.test")
    assert junk.header.rcode == RCODE.NXDOMAIN and junk.header.aa == 1
    assert events(db) == []


def test_ns_ip_is_separate_from_answer_ip(db):
    with CanaryDNSServer(DOMAIN, db, host="127.0.0.1", port=0, answer_ip="192.0.2.10",
                         ns_ip="198.51.100.53") as srv:
        assert str(_query(srv, "ns1.tapak.test").rr[0].rdata) == "198.51.100.53"
        assert str(_query(srv, canary_hostname(TOKEN, DOMAIN)).rr[0].rdata) == "192.0.2.10"


def test_public_listener_rejects_a_loopback_ns_ip_and_warns_without_one(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        CanaryDNSServer(DOMAIN, tmp_path / "x.db", host="0.0.0.0", port=53, ns_ip="127.0.0.1")
    srv = CanaryDNSServer(DOMAIN, tmp_path / "x.db", host="0.0.0.0", port=53)  # not started
    assert srv.resolver.ns_ip is None and any("--ns-ip" in w for w in srv.warnings)
    assert CanaryDNSServer(DOMAIN, tmp_path / "x.db", host="203.0.113.5", port=53).resolver.ns_ip == "203.0.113.5"


def test_tcp_can_listen_on_another_address(db):
    # Fly.io: UDP arrives only at fly-global-services, TCP at the machine's own address.
    host = canary_hostname(TOKEN, DOMAIN)
    with CanaryDNSServer(DOMAIN, db, host="127.0.0.1", port=0, tcp_host="0.0.0.0") as srv:
        assert srv.tcp_host == "0.0.0.0"
        assert str(_query(srv, host).rr[0].rdata) == "127.0.0.1"
        tcp = DNSRecord.parse(DNSRecord.question(host).send("127.0.0.2", srv.port, tcp=True, timeout=2))
        assert str(tcp.rr[0].rdata) == "127.0.0.1"
        with pytest.raises(TimeoutError):  # UDP stays on 127.0.0.1 only
            DNSRecord.question(host).send("127.0.0.2", srv.port, timeout=0.5)


def test_tcp_and_non_a_queries_are_logged(server, db):
    host = canary_hostname(TOKEN, DOMAIN)
    tcp = _query(server, host, tcp=True)
    assert str(tcp.rr[0].rdata) == "127.0.0.1"
    aaaa = _query(server, host, "AAAA")
    assert aaaa.header.rcode == RCODE.NOERROR and not aaaa.rr
    _flush(server)
    assert [e.qtype for e in events(db, token=TOKEN)] == ["A", "AAAA"]


def test_non_query_opcodes_and_bad_settings_are_rejected(server, db, tmp_path):
    notify = DNSRecord.question(canary_hostname(TOKEN, DOMAIN))
    notify.header.opcode = 4  # NOTIFY
    reply = DNSRecord.parse(notify.send("127.0.0.1", server.port, timeout=2))
    assert reply.header.rcode == RCODE.NOTIMP and events(db) == []
    y = tmp_path / "y.db"
    for kwargs, msg in [({"answer_ip": "bukan-ip"}, "IPv4"), ({"ns_ip": "bukan-ip"}, "IPv4"),
                        ({"ttl": -1}, "TTL"), ({"ttl": 2**31}, "TTL"), ({"port": 70000}, "port")]:
        with pytest.raises(ValueError, match=msg):
            CanaryDNSServer(DOMAIN, y, host="127.0.0.1", **kwargs)
    with pytest.raises(ValueError):
        CanaryDNSServer("bad_domain!", y)
    assert not y.exists()


def test_simulate_open_without_listener_returns_nothing(sample_pdf, tmp_path):
    with CanaryDNSServer(DOMAIN, tmp_path / "x.db", host="127.0.0.1", port=0) as srv:
        port = srv.port
    copy = add_pdf_canary_to_bytes(sample_pdf, canary_url(TOKEN, DOMAIN))
    assert simulate_open(copy, "pdf", ("127.0.0.1", port), timeout=0.5) == []
    assert simulate_open(sample_pdf, "pdf", ("127.0.0.1", port), timeout=0.5) == []


def test_simulate_open_survives_a_malformed_reply(sample_pdf):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(3)

    def answer_garbage() -> None:
        try:
            _, addr = sock.recvfrom(512)
            sock.sendto(b"\x12", addr)  # far too short for a DNS header
        except OSError:
            pass

    t = threading.Thread(target=answer_garbage, daemon=True)
    t.start()
    copy = add_pdf_canary_to_bytes(sample_pdf, canary_url(TOKEN, DOMAIN))
    try:
        assert simulate_open(copy, "pdf", ("127.0.0.1", sock.getsockname()[1]), timeout=2) == []
    finally:
        t.join(3)
        sock.close()


def test_simulate_open_with_domain_skips_foreign_hosts(server, db, sample_pdf):
    hostile = add_pdf_canary_to_bytes(sample_pdf, "http://attacker.example/")
    copy = add_pdf_canary_to_bytes(hostile, canary_url(TOKEN, DOMAIN))  # chained with /Next
    hosts = find_canary_hosts(copy, "pdf")
    assert set(hosts) == {"attacker.example", f"{TOKEN}.c.tapak.test"}
    assert simulate_open(copy, "pdf", ("127.0.0.1", server.port), domain=DOMAIN) == [f"{TOKEN}.c.tapak.test"]


# --- availability ------------------------------------------------------------------------


def test_flood_of_random_tokens_does_not_delay_a_genuine_hit(server, db):
    rng = random.Random(7)
    flood = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(400):
        tok = "".join(rng.choice(B32) for _ in range(16))
        flood.sendto(DNSRecord.question(f"{tok}.c.{DOMAIN}").pack(), ("127.0.0.1", server.port))
    flood.close()
    genuine = "zzzzzzzzzzzzzz22"
    t0 = time.perf_counter()
    # The kernel may drop the first try while the socket buffer is still full from the
    # burst (no UDP server can prevent that); the retry must then be answered at once.
    reply = _query_like_a_resolver(server, canary_hostname(genuine, DOMAIN))
    assert reply.rr and time.perf_counter() - t0 < 2.0
    found, elapsed = _wait_for_event(db, genuine, t0)
    assert found and elapsed < ACCEPT_S
    st = _flush(server)
    assert st["failed"] == 0 and st["written"] + st["deduplicated"] + st["dropped"] == st["received"]
    assert threading.active_count() < 20  # UDP is served by one thread, not one per packet
    assert verify_events_chain(db)


def test_full_queue_drops_are_counted(tmp_path):
    hits = HitLogger(tmp_path / "q.db", dedupe_s=0, queue_size=3)  # writer not started yet
    for i in range(5):
        hits.submit("q", TOKEN, "A", "192.0.2.1", i)
    assert hits.stats().dropped == 2 and hits.stats().received == 5
    hits.start()
    hits.stop()
    assert hits.stats().written == 3 and len(events(tmp_path / "q.db")) == 3


def test_idle_tcp_clients_are_cut_off_and_capped(db):
    with CanaryDNSServer(DOMAIN, db, host="127.0.0.1", port=0, tcp_timeout=1.5, max_tcp=2) as srv:
        idle = [socket.create_connection(("127.0.0.1", srv.port)) for _ in range(2)]
        time.sleep(0.3)  # let the server accept both
        extra = socket.create_connection(("127.0.0.1", srv.port))
        try:
            extra.settimeout(3)
            t0 = time.perf_counter()
            assert _closed_by_peer(extra)
            assert time.perf_counter() - t0 < 1.0  # refused at once, not after the timeout
            for c in idle:
                c.settimeout(4)
                assert _closed_by_peer(c)  # cut off after tcp_timeout
            assert srv.stats()["tcp_rejected"] == 1
            time.sleep(0.2)
            assert _query(srv, canary_hostname(TOKEN, DOMAIN), tcp=True).rr  # slots free again
        finally:
            for c in idle + [extra]:
                c.close()


# --- event store -------------------------------------------------------------------------


def test_event_hash_chain(db):
    init_store(db)
    assert verify_events_chain(db) and chain_head(db) == (0, "0" * 64)
    _record(db, 5)
    assert verify_events_chain(db)
    rows = events(db)
    assert [e.seq for e in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == "0" * 64
    assert all(b.prev_hash == a.hash for a, b in zip(rows, rows[1:]))
    assert chain_head(db) == (5, rows[-1].hash)
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE canary_events SET src_ip = '198.51.100.7' WHERE seq = 2")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM canary_events WHERE seq = 3")
    # a naive edit (hashes not recomputed, trigger restored) is caught by the plain chain
    con.execute("DROP TRIGGER canary_events_no_update")
    con.execute("UPDATE canary_events SET src_ip = '198.51.100.7' WHERE seq = 2")
    con.execute(f"CREATE TRIGGER canary_events_no_update {TRIGGERS['canary_events_no_update']}")
    con.commit()
    con.close()
    report = check_events_chain(db)
    assert not report.ok and any("#2" in p and "hash" in p for p in report.problems)


def test_verify_fails_when_the_log_is_missing_and_creates_nothing(tmp_path):
    missing = tmp_path / "tidak" / "ada.db"
    assert not verify_events_chain(missing)
    assert "tidak ditemukan" in check_events_chain(missing).problems[0]
    assert events(missing) == [] and chain_head(missing) == (0, "0" * 64)
    assert not missing.exists() and not missing.parent.exists()


def test_verify_fails_on_a_dropped_table(db):
    _record(db, 3)
    con = sqlite3.connect(db)
    con.execute("DROP TABLE canary_events")
    con.commit()
    con.close()
    report = check_events_chain(db)
    assert not report.ok and "tabel canary_events tidak ada" in report.problems[0]
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'canary_events'").fetchall() == []
    con.close()


def test_missing_or_altered_trigger_is_reported_not_repaired(db):
    _record(db, 3)
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER canary_events_no_delete")
    con.execute("DROP TRIGGER canary_events_no_update")
    con.execute("CREATE TRIGGER canary_events_no_update BEFORE UPDATE ON canary_events BEGIN SELECT 1; END")
    con.commit()
    con.close()
    report = check_events_chain(db)
    assert not report.ok
    assert any("canary_events_no_delete hilang" in p for p in report.problems)
    assert any("canary_events_no_update telah diubah" in p for p in report.problems)
    record_event(db, f"{TOKEN}.c.tapak.test", TOKEN, "A", "192.0.2.9", 1)  # writing still works ...
    assert "canary_events_no_delete hilang" in " ".join(init_store(db))  # ... and repairs nothing
    assert not verify_events_chain(db)


def test_event_chain_detects_a_deleted_row(tmp_path):
    db = tmp_path / "del.db"
    _record(db, 5)
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER canary_events_no_delete")
    con.execute("DELETE FROM canary_events WHERE seq = 3")
    con.execute(f"CREATE TRIGGER canary_events_no_delete {TRIGGERS['canary_events_no_delete']}")
    con.commit()
    con.close()
    report = check_events_chain(db)
    assert not report.ok and any("melompat" in p for p in report.problems)


def test_anchor_catches_a_recomputed_chain_and_a_truncated_tail(tmp_path):
    from tapak.registry.verify import verify_registry

    signer = Signer.generate()
    db = tmp_path / "registry.db"  # events and registry share one file, as in deployment
    _record(db, 5)
    assert anchor_head(db, signer) == chain_head(db)
    assert read_anchors(db, signer.public_key_hex) == ([chain_head(db)], 0)
    assert verify_events_anchored(db, signer.public_key_hex).ok
    assert verify_registry(db, signer.public_key_hex).ok  # the registry accepts the anchor entry
    _record(db, 2)
    report = verify_events_anchored(db, signer.public_key_hex)
    assert report.ok and any("#6 sampai #7 belum dijangkarkan" in w for w in report.warnings)

    rewritten = tmp_path / "rewritten.db"
    rewritten.write_bytes(db.read_bytes())
    _rewrite_chain(rewritten, 2, src_ip="10.9.9.9")
    assert verify_events_chain(rewritten)  # the unkeyed chain alone is fooled ...
    report = verify_events_anchored(rewritten, signer.public_key_hex)
    assert not report.ok and any("ditulis ulang" in p for p in report.problems)  # ... the anchor is not

    _truncate(db, 3)
    assert verify_events_chain(db)
    report = verify_events_anchored(db, signer.public_key_hex)
    assert not report.ok and any("dipotong" in p for p in report.problems)
    assert not verify_events_chain(db, expected_head=read_anchors(db, signer.public_key_hex)[0][0])


def test_anchoring_an_unchanged_head_writes_nothing(tmp_path):
    db = tmp_path / "registry.db"
    _record(db, 2)
    anchor_head(db)
    anchor_head(db)  # an hourly run without new events
    with Registry.open(db) as reg:
        assert len(reg.entries("canary_anchor")) == 1
    _record(db, 1)
    assert anchor_head(db) == chain_head(db)
    with Registry.open(db) as reg:
        assert [e.payload["events_seq"] for e in reg.entries("canary_anchor")] == [2, 3]


def test_unsigned_anchor_counts_only_after_the_key_holder_signs(tmp_path):
    signer = Signer.generate()
    db = tmp_path / "registry.db"
    _record(db, 2)
    anchor_head(db)  # listener side: no private key
    assert read_anchors(db, signer.public_key_hex) == ([], 0)
    assert any("belum ada jangkar" in w for w in verify_events_anchored(db, signer.public_key_hex).warnings)
    with Registry.open(db) as reg:
        assert sign_pending(reg, signer) == 1
    assert read_anchors(db, signer.public_key_hex) == ([(2, events(db)[-1].hash)], 0)
    assert read_anchors(db, Signer.generate().public_key_hex) == ([], 1)  # wrong key: not trusted
    _rewrite_chain(db, 1, qtype="AAAA")
    assert not verify_events_anchored(db, signer.public_key_hex).ok
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER canary_events_no_update")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="tidak utuh"):  # never anchor a damaged log
        anchor_head(db)


def test_store_shares_the_db_file_and_logs_only_minimal_fields(db):
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE registry_rows (id INTEGER PRIMARY KEY, note TEXT)")
    con.execute("INSERT INTO registry_rows (note) VALUES ('milik registri')")
    con.commit()
    _record(db, 2)
    assert con.execute("SELECT note FROM registry_rows").fetchall() == [("milik registri",)]
    cols = [r[1] for r in con.execute("PRAGMA table_info(canary_events)")]
    con.close()
    assert cols == ["seq", "received_at", "qname", "token", "qtype", "src_ip", "src_port", "prev_hash", "hash"]
    assert verify_events_chain(db)


def test_events_filters_by_token_and_time(db):
    record_event(db, "abcdefghijklmn22.c.tapak.test", "abcdefghijklmn22", "A", "192.0.2.1", 1,
                 received_at="2026-01-01T00:00:00Z")
    record_event(db, "abcdefghijklmn23.c.tapak.test", "abcdefghijklmn23", "A", "192.0.2.2", 2)
    assert events(db)[0].received_at == "2026-01-01T00:00:00.000000+00:00"
    assert events(db)[1].received_at.endswith("+00:00")
    assert [e.src_port for e in events(db, token="ABCDEFGHIJKLMN23")] == [2]
    assert [e.src_port for e in events(db, since=datetime(2026, 6, 1, tzinfo=timezone.utc))] == [2]
    # the same instant written three ways selects the first event too
    for since in ("2026-01-01T00:00:00Z", "2026-01-01T07:00:00+07:00", "2026-01-01T00:00:00"):
        assert len(events(db, since=since)) == 2
    assert len(events(db, since="2026-01-01T00:00:00.000001Z")) == 1
    with pytest.raises(ValueError, match="ISO 8601"):
        events(db, since="kemarin")


def test_concurrent_threads_keep_one_chain(db):
    threads = [threading.Thread(target=_record, args=(db, 10)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(events(db)) == 40 and verify_events_chain(db)


def test_two_processes_writing_at_once_keep_one_chain(db):
    code = ("import sys, time\n"
            "from tapak.canary_dns.store import record_event\n"
            "time.sleep(max(0.0, float(sys.argv[3]) - time.time()))\n"
            "for i in range(30):\n"
            "    record_event(sys.argv[1], 'abcdefghijklmn22.c.tapak.test', 'abcdefghijklmn22', 'A',\n"
            "                 '192.0.2.' + sys.argv[2], i)\n")
    start_at = str(time.time() + 3.0)  # both start writing at the same moment (also racing to create)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(db), str(k), start_at], cwd=ROOT)
             for k in (1, 2)]
    for p in procs:
        assert p.wait(timeout=60) == 0
    rows = events(db)
    assert len(rows) == 60 and verify_events_chain(db)
    assert {r.src_ip for r in rows} == {"192.0.2.1", "192.0.2.2"}


# --- command line ------------------------------------------------------------------------


def test_cli_runs_listener_and_prints_hits(tmp_path):
    db = tmp_path / "cli.db"
    proc = subprocess.Popen(
        [sys.executable, "-m", "tapak.canary_dns", "--domain", DOMAIN, "--db", str(db),
         "--host", "127.0.0.1", "--port", "0"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    try:
        first = proc.stdout.readline()
        assert "Pendengar DNS kanari aktif" in first, first + proc.stderr.read()
        assert "ns1 127.0.0.1" in first
        port = int(re.search(r"127\.0\.0\.1:(\d+)", first).group(1))
        q = DNSRecord.question(canary_hostname(TOKEN, DOMAIN).upper(), "A")
        DNSRecord.parse(q.send("127.0.0.1", port, timeout=2))
        hit = proc.stdout.readline()
        assert "KANARI TERPICU" in hit and TOKEN in hit and "127.0.0.1" in hit
        proc.send_signal(signal.SIGTERM)
        rest, _ = proc.communicate(timeout=10)
        assert proc.returncode == 0 and "berhenti" in rest and "dicatat 1" in rest
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert [e.token for e in events(db)] == [TOKEN]


def test_cli_rejects_bad_domain(tmp_path, capsys):
    from tapak.canary_dns.__main__ import main

    assert main(["--domain", "bad_domain!", "--db", str(tmp_path / "x.db"), "--port", "0"]) == 2
    assert "domain kanari tidak valid" in capsys.readouterr().err
    assert main(["--domain", "", "--db", str(tmp_path / "x.db"), "--port", "0"]) == 2
    assert "--domain wajib diisi" in capsys.readouterr().err


@pytest.mark.parametrize("argv, expected", [
    (["--port", "70000"], "opsi --port: port harus bilangan bulat 0 sampai 65535"),
    (["--port"], "opsi --port: memerlukan satu nilai"),
    (["--ttl", "-1"], "opsi --ttl: TTL harus bilangan bulat"),
    (["--bogus"], "argumen tidak dikenal: --bogus"),
    (["--anchor", "--verify"], "tidak boleh dipakai bersamaan"),
])
def test_cli_usage_errors_are_indonesian_and_return_2(argv, expected, tmp_path, capsys):
    from tapak.canary_dns.__main__ import main

    assert main(argv + ["--db", str(tmp_path / "x.db")]) == 2
    err = capsys.readouterr().err
    assert expected in err and "error:" not in err and "usage:" not in err


def test_cli_help_is_indonesian(capsys):
    from tapak.canary_dns.__main__ import main

    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("penggunaan: ") and "opsi:" in out and "--ns-ip" in out
    assert "usage:" not in out and "options:" not in out and "show this help" not in out


def test_cli_anchor_and_verify(tmp_path, capsys):
    from tapak.canary_dns.__main__ import main

    db, key = tmp_path / "registry.db", tmp_path / "kunci" / "registry.key"
    generate_signing_key(key)
    pub = key.with_suffix(".pub")
    _record(db, 3)
    reg = ["--registry", str(db)]  # events and anchors in one file for this test
    assert main(["--anchor", "--db", str(db), "--signing-key", str(key), *reg]) == 0
    assert "dijangkarkan dan ditandatangani" in capsys.readouterr().out
    assert main(["--verify", "--db", str(db), "--public-key", str(pub), *reg]) == 0
    assert "UTUH" in capsys.readouterr().out
    _rewrite_chain(db, 2, src_ip="10.9.9.9")
    assert main(["--verify", "--db", str(db), "--public-key", str(pub), *reg]) == 1
    out = capsys.readouterr().out
    assert "RUSAK" in out and "ditulis ulang" in out
