"""Offline by default: nothing in TAPAK opens a network connection except to loopback, and no
library with built-in telemetry is loaded."""

from __future__ import annotations

import ipaddress
import socket
import sys

import numpy as np
import pytest

from tests_support import RECIPIENTS, SAMPLE


@pytest.fixture()
def no_network(monkeypatch):
    """Fail the test on any connection or datagram to a non-loopback address."""
    real_connect = socket.socket.connect
    real_sendto = socket.socket.sendto

    def _check(address):
        host = address[0] if isinstance(address, tuple) else None
        if host is None:
            return
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            raise AssertionError(f"koneksi keluar ke nama host {host!r}") from None
        if not ip.is_loopback:
            raise AssertionError(f"koneksi keluar ke {host}")

    def connect(self, address):
        _check(address)
        return real_connect(self, address)

    def sendto(self, data, *args):
        _check(args[-1])
        return real_sendto(self, data, *args)

    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if host not in (None, "localhost", "127.0.0.1", "::1"):
            raise AssertionError(f"resolusi DNS keluar untuk {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def test_no_telemetry_library_is_loaded():
    import tapak.cli  # noqa: F401
    import tapak.decoder.image  # noqa: F401
    import tapak.web.app  # noqa: F401

    assert "onnxruntime" not in sys.modules
    assert "torch" not in sys.modules


def test_full_pipeline_runs_without_network(tmp_path, monkeypatch, no_network):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    from tapak.config import load_settings
    from tapak.marker.issue import IssueSettings, read_recipients
    from tapak.marker.render import render_pages
    from tapak.photos import PhotoParams, photo_jpeg
    from tapak.service import ensure_keys, issue_document, trace_evidence, write_report

    s = load_settings()
    keys = ensure_keys(s)
    out = issue_document(s, SAMPLE, read_recipients(RECIPIENTS)[:5],
                         IssueSettings(workers=1, canary_domain="kanari.tapak.test"), "uji", keys)
    copy = (out.folder / "salinan" / out.manifest.copies[2].file).read_bytes()
    res = trace_evidence(s, out.manifest.doc_hash, "bocor.pdf", copy)
    assert [c.copy.seq for c in res.attribution.accused] == [3]
    photo, _ = photo_jpeg(render_pages(copy, 200, [0])[0], np.random.default_rng(2), PhotoParams(angle_deg=10.0))
    res2 = trace_evidence(s, out.manifest.doc_hash, "foto.jpg", photo)
    assert [c.copy.seq for c in res2.attribution.accused] == [3]
    assert write_report(res2).startswith(b"%PDF")
