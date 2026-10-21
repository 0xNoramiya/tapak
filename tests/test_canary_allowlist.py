"""The canary listener stores only tokens the issuer published (allowlist of digests)."""

from __future__ import annotations

import time

from tapak.canary_dns.server import CanaryDNSServer, simulate_open
from tapak.canary_dns.store import events
from tapak.marker.canary import add_pdf_canary_to_bytes, canary_url
from tapak.registry.chain import canary_token_digest
from tests_support import SAMPLE


def test_only_issued_tokens_are_logged(tmp_path):
    domain = "kanari.tapak.test"
    issued, other = "a" * 16, "b" * 16
    allow = tmp_path / "token_digests.txt"
    allow.write_text(canary_token_digest(issued) + "\n", encoding="ascii")
    db = tmp_path / "kanari.db"
    pdf_ok = add_pdf_canary_to_bytes(SAMPLE.read_bytes(), canary_url(issued, domain))
    pdf_other = add_pdf_canary_to_bytes(SAMPLE.read_bytes(), canary_url(other, domain))
    server = CanaryDNSServer(domain, db, host="127.0.0.1", port=0, allowlist=allow)
    server.start()
    try:
        simulate_open(pdf_other, "pdf", ("127.0.0.1", server.port), domain=domain)
        simulate_open(pdf_ok, "pdf", ("127.0.0.1", server.port), domain=domain)
        deadline = time.time() + 5
        while time.time() < deadline and not events(db):
            time.sleep(0.05)
    finally:
        server.stop()
    tokens = [e.token for e in events(db)]
    assert tokens == [issued]
    assert server.hits.stats().unknown == 1
