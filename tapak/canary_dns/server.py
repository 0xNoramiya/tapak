"""Authoritative DNS listener for the canary domain (channel 5).

The listener is the authoritative name server of the canary domain ``<domain>``: the
parent zone delegates ``<domain>`` to ``ns1.<domain>`` (NS record plus glue at the
registrar, glue = the listener's public IPv4). Every copy's canary name
``<token>.c.<domain>`` therefore ends up here whenever a resolver outside the unit's
network looks it up.

Two different addresses, do not mix them up:

* ``answer_ip`` is what canary names resolve to. The default 127.0.0.1 sends the
  viewer's follow-up connection to the opener's own machine, so nothing leaves it.
* ``ns_ip`` is the address of the listener itself, served for ``ns1.<domain>``. It must
  be the public IPv4 that the registrar glue points to. Resolvers that prefer the
  child zone's own records (BIND, hardened Unbound) replace the glue with this answer;
  a wrong value (for example loopback) would make them send later canary lookups to
  their own machine and the canary would stop firing. It defaults to ``host`` when
  ``host`` is a concrete IPv4 address. A wildcard listener on port 53 refuses a loopback
  ``ns_ip``; without one it starts, answers ``ns1.<domain>`` with no address and lists
  a warning in :attr:`CanaryDNSServer.warnings`.

Answers:

* ``<token>.c.<domain>`` (any letter case, so DNS 0x20 case randomization works): the
  query is logged; type A (or ANY) is answered with ``answer_ip``, other types get an
  empty answer. TTL is ``ttl`` (default 0) and the negative-caching TTL in the SOA is
  the same, so resolvers do not cache and every new open fires again.
* ``c.<domain>``: empty answer (NOERROR). Resolvers that use QNAME minimization ask for
  this name first and would stop on an error.
* ``<domain>`` (apex): SOA and NS records; ``ns1.<domain>`` type A: ``ns_ip``.
* any other name below ``<domain>``: NXDOMAIN, not logged.
* any name outside ``<domain>``: REFUSED (the listener is not an open resolver).

The task asked for REFUSED on "any other name". Names inside the zone get NXDOMAIN or an
empty NOERROR instead, because that is what an authoritative server must say about its
own zone; REFUSED there would break QNAME minimization and delegation checks.

Availability: the answer never waits for the disk. A hit is put on a bounded queue and
one writer thread appends queued hits to SQLite in batches over one connection
(:class:`HitLogger`). When the queue is full the hit is answered but not logged and
counted as dropped. Identical hits (same token, source address and query type) within
``dedupe_s`` seconds are logged once, which also folds resolver retries together. UDP is
served by a single thread (answering is fast because it does no I/O), so a flood cannot
spawn threads. TCP gets one thread per connection, at most ``max_tcp`` at a time, and
each connection is closed after ``tcp_timeout`` seconds.

What is logged: query name (lowercased), token, query type, source address and port, and
the time. The source address is normally the recursive resolver used by the machine that
opened the copy (an ISP or public resolver), not the machine itself. Events are not
authenticated: anyone holding a copy can read its token and send queries for it, UDP
source addresses can be spoofed, and every well-formed token is logged, issued or not.
An event shows that some host sent this query, not who opened the file.
"""

from __future__ import annotations

import ipaddress
import logging
import queue
import random
import socket
import socketserver
import sqlite3
import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from dnslib import NS, OPCODE, QTYPE, RCODE, RR, SOA, A, DNSError, DNSRecord
from dnslib.server import BaseResolver, DNSHandler, DNSServer

from tapak.canary_dns.store import CanaryEvent, NewEvent, append_events, connect_writer, init_store, utc_now
from tapak.marker.canary import CANARY_LABEL, find_canary_hosts, normalize_domain, token_from_qname

log = logging.getLogger(__name__)

NS_TTL = 300  # seconds, for the apex NS record and the name server address
MAX_TTL = 2**31 - 1  # RFC 2181: TTLs are 31-bit
POLL_S = 0.1  # seconds, how often the serve loops check for stop()
BATCH_MAX = 256  # events written per transaction at most
MAX_RECENT = 10_000  # (token, source, type) keys remembered for deduplication
UDP_RCVBUF = 4 * 1024 * 1024  # bytes requested for the UDP receive buffer
PROXY_V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"  # PROXY protocol v2; v1 is a text line "PROXY ..."
PROXY_V1_MAX = 107  # bytes of a v1 header line, CRLF included


def _ipv4(value: str, what: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError:
        raise ValueError(f"{what} bukan alamat IPv4 yang sah: {value!r}") from None


def _is_wildcard(host: str) -> bool:
    return host in ("", "0.0.0.0", "::")


class _QuietLogger:
    """dnslib logger that prints nothing (dnslib's default prints every packet)."""

    def log_recv(self, handler: DNSHandler, data: bytes) -> None:  # noqa: D102
        pass

    def log_send(self, handler: DNSHandler, data: bytes) -> None:  # noqa: D102
        pass

    def log_request(self, handler: DNSHandler, request: DNSRecord) -> None:  # noqa: D102
        pass

    def log_reply(self, handler: DNSHandler, reply: DNSRecord) -> None:  # noqa: D102
        pass

    def log_truncated(self, handler: DNSHandler, reply: DNSRecord) -> None:  # noqa: D102
        pass

    def log_data(self, dnsobj: DNSRecord) -> None:  # noqa: D102
        pass

    def log_error(self, handler: DNSHandler, e: Exception) -> None:  # noqa: D102
        log.debug("paket DNS tidak valid dari %s: %s", handler.client_address[0], e)


@dataclass
class HitStats:
    """Counters of the logging path (since start)."""

    received: int = 0  # canary-name queries answered
    deduplicated: int = 0  # not logged: identical hit within dedupe_s
    unknown: int = 0  # not logged: token not in the allowlist of issued tokens
    rate_limited: int = 0  # not logged: source exceeded its per-minute budget
    dropped: int = 0  # not logged: queue full
    written: int = 0  # appended to the store
    failed: int = 0  # not logged: the store write raised


class HitLogger:
    """Deduplication, a bounded queue and one writer thread between DNS answers and SQLite."""

    def __init__(self, db_path: str | Path, on_hit: Callable[[CanaryEvent], None] | None = None,
                 dedupe_s: float = 1.0, queue_size: int = 10_000, allowlist: str | Path | None = None,
                 per_source_per_min: int = 0) -> None:
        """``allowlist``: file of ``sha256:`` token digests written by the issuer; when given,
        queries for any other token are answered but never stored, so nobody can grow the log
        with made-up names. ``per_source_per_min`` (0 = off) caps stored hits per source address.
        It is off by default on purpose: genuine hits usually arrive through shared public
        resolvers, and a flood through the same resolver would otherwise suppress them."""
        if dedupe_s < 0:
            raise ValueError(f"jendela deduplikasi tidak boleh negatif: {dedupe_s!r}")
        if queue_size < 1:
            raise ValueError(f"ukuran antrean minimal 1: {queue_size!r}")
        self.db_path = db_path
        self.on_hit = on_hit
        self.dedupe_s = dedupe_s
        self._queue: queue.Queue[NewEvent | None] = queue.Queue(maxsize=queue_size)
        self._recent: OrderedDict[tuple[str, str, str], float] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = HitStats()
        self._thread: threading.Thread | None = None
        self.allowlist = Path(allowlist) if allowlist else None
        self._allowed: frozenset[str] | None = None
        self._allowed_mtime = -1.0
        self._allowed_checked = 0.0
        self.per_source_per_min = per_source_per_min
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def _is_known(self, token: str) -> bool:
        """True if the token's digest is in the allowlist (reloaded when the file changes).

        With no allowlist configured, or while the file does not exist yet (the listener may
        start before the first issuance), every token is accepted: losing a genuine hit to a
        missing file would be worse than logging a stray one.
        """
        if self.allowlist is None:
            return True
        now = time.monotonic()
        if now - self._allowed_checked > 1.0:
            self._allowed_checked = now
            try:
                mtime = self.allowlist.stat().st_mtime
            except OSError:
                mtime = -1.0
            if mtime != self._allowed_mtime:
                self._allowed_mtime = mtime
                try:
                    self._allowed = frozenset(self.allowlist.read_text(encoding="ascii").split())
                except OSError:
                    self._allowed = None  # no file (yet): accept everything
        if self._allowed is None:
            return True
        from tapak.registry.chain import canary_token_digest

        return canary_token_digest(token) in self._allowed

    def _within_budget(self, src_ip: str, now: float) -> bool:
        """Token bucket per source address (bounded table)."""
        if self.per_source_per_min <= 0:
            return True
        rate = self.per_source_per_min / 60.0
        tokens, last = self._buckets.pop(src_ip, (float(self.per_source_per_min), now))
        tokens = min(float(self.per_source_per_min), tokens + (now - last) * rate)
        ok = tokens >= 1.0
        self._buckets[src_ip] = (tokens - 1.0 if ok else tokens, now)
        while len(self._buckets) > MAX_RECENT:
            self._buckets.popitem(last=False)
        return ok

    def stats(self) -> HitStats:
        """A snapshot of the counters."""
        with self._lock:
            return HitStats(**asdict(self._stats))

    def _is_duplicate(self, key: tuple[str, str, str], now: float) -> bool:
        """At most one logged hit per key per ``dedupe_s`` seconds (caller holds the lock)."""
        while self._recent:
            oldest_key, oldest_t = next(iter(self._recent.items()))
            if now - oldest_t < self.dedupe_s and len(self._recent) < MAX_RECENT:
                break
            del self._recent[oldest_key]
        if key in self._recent:
            return True
        self._recent[key] = now
        return False

    def submit(self, qname: str, token: str, qtype: str, src_ip: str, src_port: int) -> None:
        """Queue one hit without blocking; called on the answer path."""
        item = NewEvent(utc_now(), qname, token, qtype, src_ip, int(src_port))
        with self._lock:
            self._stats.received += 1
            if not self._is_known(token):
                self._stats.unknown += 1
                return
            if not self._within_budget(src_ip, time.monotonic()):
                self._stats.rate_limited += 1
                return
            if self.dedupe_s > 0 and self._is_duplicate((token, src_ip, qtype), time.monotonic()):
                self._stats.deduplicated += 1
                return
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._stats.dropped += 1

    def start(self) -> None:
        """Start the writer thread."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="kanari-penulis", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Write what is still queued, then stop the writer thread."""
        if self._thread is None:
            return
        try:
            self._queue.put(None, timeout=timeout)  # None marks the end; items before it are written
        except queue.Full:
            log.warning("antrean kanari penuh saat berhenti; sebagian kejadian tidak tercatat")
        self._thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        con = None
        done = False
        while not done:
            item = self._queue.get()
            if item is None:
                break
            batch = [item]
            while len(batch) < BATCH_MAX:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    done = True
                    break
                batch.append(nxt)
            con = self._write(con, batch)
        if con is not None:
            con.close()

    def _write(self, con: sqlite3.Connection | None, batch: list[NewEvent]) -> sqlite3.Connection | None:
        """Append one batch; return the connection to reuse (None after a failure)."""
        try:
            if con is None:
                con = connect_writer(self.db_path)
            written = append_events(con, batch)
        except Exception:  # noqa: BLE001 - keep serving; the failure is counted and logged
            log.exception("gagal mencatat %d kejadian kanari", len(batch))
            with self._lock:
                self._stats.failed += len(batch)
            if con is not None:
                con.close()
            return None
        with self._lock:
            self._stats.written += len(written)
        if self.on_hit is not None:
            for ev in written:
                try:
                    self.on_hit(ev)
                except Exception:  # noqa: BLE001 - a display failure must not stop logging
                    log.exception("fungsi on_hit gagal untuk catatan #%d", ev.seq)
        return con


class CanaryResolver(BaseResolver):
    """Answers queries for the canary domain; reports every canary-name lookup to ``on_query``.

    ``on_query(qname, token, qtype, src_ip, src_port)`` must not block (the server passes
    :meth:`HitLogger.submit`). The resolver itself does no I/O.
    """

    def __init__(self, domain: str, answer_ip: str = "127.0.0.1", ns_ip: str | None = None, ttl: int = 0,
                 on_query: Callable[[str, str, str, str, int], None] | None = None) -> None:
        self.domain = normalize_domain(domain)
        self.canary_zone = f"{CANARY_LABEL}.{self.domain}"
        self.ns_name = f"ns1.{self.domain}"
        self.answer_ip = _ipv4(answer_ip, "alamat jawaban (answer_ip)")
        self.ns_ip = _ipv4(ns_ip, "alamat server nama (ns_ip)") if ns_ip is not None else None
        if not isinstance(ttl, int) or not 0 <= ttl <= MAX_TTL:
            raise ValueError(f"TTL harus antara 0 dan {MAX_TTL}: {ttl!r}")
        self.ttl = ttl
        self.on_query = on_query

    def _soa(self, rname: object) -> RR:
        times = (1, 3600, 600, 86400, self.ttl)  # serial, refresh, retry, expire, negative TTL
        return RR(rname, QTYPE.SOA, ttl=self.ttl, rdata=SOA(self.ns_name, f"hostmaster.{self.domain}", times))

    def resolve(self, request: DNSRecord, handler: DNSHandler) -> DNSRecord:
        """Build the answer for one query (see module docstring for the rules)."""
        reply = request.reply(ra=0, aa=1)
        if request.header.opcode != OPCODE.QUERY:
            reply.header.rcode = RCODE.NOTIMP
            return reply
        if len(request.questions) != 1:
            reply.header.rcode = RCODE.FORMERR
            return reply
        q = request.q
        name = str(q.qname).rstrip(".").lower()
        if name != self.domain and not name.endswith("." + self.domain):
            reply.header.aa = 0
            reply.header.rcode = RCODE.REFUSED
            return reply

        token = token_from_qname(name, self.domain)
        if token is not None:
            if self.on_query is not None:
                ip, port = handler.client_address[0], int(handler.client_address[1])
                self.on_query(name, token, QTYPE.get(q.qtype, f"TYPE{q.qtype}"), ip, port)
            if q.qtype in (QTYPE.A, QTYPE.ANY):
                reply.add_answer(RR(q.qname, QTYPE.A, ttl=self.ttl, rdata=A(self.answer_ip)))
            else:
                reply.add_auth(self._soa(self.domain))
        elif name == self.domain:
            if q.qtype in (QTYPE.SOA, QTYPE.ANY):
                reply.add_answer(self._soa(q.qname))
            if q.qtype in (QTYPE.NS, QTYPE.ANY):
                reply.add_answer(RR(q.qname, QTYPE.NS, ttl=NS_TTL, rdata=NS(self.ns_name)))
            if not reply.rr:
                reply.add_auth(self._soa(self.domain))
        elif name == self.ns_name and q.qtype in (QTYPE.A, QTYPE.ANY) and self.ns_ip is not None:
            reply.add_answer(RR(q.qname, QTYPE.A, ttl=NS_TTL, rdata=A(self.ns_ip)))
        elif name in (self.ns_name, self.canary_zone):
            reply.add_auth(self._soa(self.domain))
        else:
            reply.header.rcode = RCODE.NXDOMAIN
            reply.add_auth(self._soa(self.domain))
        return reply


class _UDPServer(socketserver.UDPServer):
    """Single-threaded UDP server: answering does no I/O, so one thread keeps up."""

    allow_reuse_address = False  # SO_REUSEADDR on UDP would let another process share the port

    def __init__(self, server_address: tuple[str, int], handler: type[DNSHandler]) -> None:
        if ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(server_address, handler)

    def server_bind(self) -> None:
        """Ask for a large receive buffer so a burst is absorbed (the kernel caps it at rmem_max)."""
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_RCVBUF)
        except OSError:
            pass
        super().server_bind()

    def handle_error(self, request: object, client_address: tuple[str, int]) -> None:
        log.warning("gagal menjawab paket DNS dari %s", client_address[0], exc_info=True)


class _TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """One thread per TCP connection, at most ``slots`` at a time; extra connections are closed."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    slots: threading.BoundedSemaphore | None = None  # set by CanaryDNSServer before serving
    tcp_timeout = 5.0
    rejected = 0
    proxy_protocol = False  # a PROXY protocol header in front of every query names the client

    def __init__(self, server_address: tuple[str, int], handler: type[DNSHandler]) -> None:
        if ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(server_address, handler)

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if self.slots is not None and not self.slots.acquire(blocking=False):
            self.rejected += 1
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            if self.slots is not None:
                self.slots.release()

    def handle_error(self, request: object, client_address: tuple[str, int]) -> None:
        log.warning("gagal menjawab koneksi DNS TCP dari %s", client_address[0], exc_info=True)


class _TCPHandler(DNSHandler):
    """One length-prefixed query per connection, read within ``tcp_timeout`` seconds in total."""

    def _recv_exact(self, n: int, deadline: float) -> bytes:
        buf = b""
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("batas waktu TCP habis")
            self.request.settimeout(left)
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("koneksi ditutup klien")
            buf += chunk
        return buf

    def _proxied_client(self, deadline: float) -> tuple[str, int]:
        """The client a PROXY protocol header (v1 or v2) names; a missing or malformed header
        drops the connection (ValueError). A v2 LOCAL header (the proxy's own health check)
        keeps the connection's address."""
        head = self._recv_exact(12, deadline)
        if head == PROXY_V2_SIGNATURE:
            ver_cmd, family, length = struct.unpack("!BBH", self._recv_exact(4, deadline))
            body = self._recv_exact(length, deadline)
            if ver_cmd >> 4 != 2:
                raise ValueError("versi PROXY v2 tidak dikenal")
            if ver_cmd & 0xF == 0:
                return self.client_address[0], int(self.client_address[1])
            if family == 0x11 and length >= 12:
                return socket.inet_ntop(socket.AF_INET, body[:4]), struct.unpack("!H", body[8:10])[0]
            if family == 0x21 and length >= 36:
                return socket.inet_ntop(socket.AF_INET6, body[:16]), struct.unpack("!H", body[32:34])[0]
            raise ValueError("keluarga alamat PROXY v2 tidak didukung")
        if not head.startswith(b"PROXY "):
            raise ValueError("header PROXY tidak ada")
        line = head
        while not line.endswith(b"\r\n"):
            if len(line) >= PROXY_V1_MAX:
                raise ValueError("header PROXY v1 terlalu panjang")
            line += self._recv_exact(1, deadline)
        parts = line[:-2].decode("ascii").split(" ")
        if len(parts) == 6 and parts[1] in ("TCP4", "TCP6"):
            return str(ipaddress.ip_address(parts[2])), int(parts[4])
        raise ValueError("header PROXY v1 tidak sah")

    def handle(self) -> None:
        """Read one query, answer it, close (a slow or idle client is cut off at the deadline)."""
        self.protocol = "tcp"
        deadline = time.monotonic() + self.server.tcp_timeout
        try:
            if self.server.proxy_protocol:
                self.client_address = self._proxied_client(deadline)
            (length,) = struct.unpack("!H", self._recv_exact(2, deadline))
            reply = self.get_reply(self._recv_exact(length, deadline))
            self.request.settimeout(max(0.1, deadline - time.monotonic()))
            self.request.sendall(struct.pack("!H", len(reply)) + reply)
        except (OSError, DNSError, ValueError) as exc:
            log.debug("koneksi DNS TCP dari %s dihentikan: %s", self.client_address[0], exc)


class CanaryDNSServer:
    """Threaded UDP and TCP listener around :class:`CanaryResolver` and :class:`HitLogger`.

    ``port=0`` picks a free port (the same one for UDP and TCP); read it from ``port``
    after :meth:`start`. Usable as a context manager. ``on_hit`` runs on the writer
    thread after each event is stored. ``tcp_host`` binds TCP to another address than UDP
    (Fly.io delivers UDP only to ``fly-global-services`` and TCP to the machine's own address).
    With ``proxy_protocol`` every TCP connection must start with a PROXY protocol header (v1 or
    v2), whose client address is logged instead of the proxy's; enable it only behind a proxy
    that always sends one, or anyone could name any source address.
    """

    def __init__(self, domain: str, db_path: str | Path, host: str = "0.0.0.0", port: int = 53,
                 answer_ip: str = "127.0.0.1", ttl: int = 0,
                 on_hit: Callable[[CanaryEvent], None] | None = None, *, ns_ip: str | None = None,
                 dedupe_s: float = 1.0, queue_size: int = 10_000, tcp_timeout: float = 5.0,
                 max_tcp: int = 64, allowlist: str | Path | None = None,
                 per_source_per_min: int = 0, tcp_host: str | None = None, proxy_protocol: bool = False) -> None:
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError(f"port harus antara 0 dan 65535: {port!r}")
        if tcp_timeout <= 0 or max_tcp < 1:
            raise ValueError("tcp_timeout harus positif dan max_tcp minimal 1")
        self.warnings: list[str] = []
        if ns_ip is None and not _is_wildcard(host):
            try:
                ns_ip = str(ipaddress.IPv4Address(host))
            except ValueError:
                pass  # a host name or an IPv6 address: no default
        if port == 53 and _is_wildcard(host):
            if ns_ip is not None and ipaddress.IPv4Address(_ipv4(ns_ip, "alamat server nama (ns_ip)")).is_loopback:
                raise ValueError(f"ns_ip {ns_ip} adalah loopback; pendengar publik di port 53 memerlukan "
                                 "alamat IPv4 publiknya sendiri (sama dengan glue di registrar)")
            if ns_ip is None:
                self.warnings.append(f"ns_ip tidak diisi: ns1.{normalize_domain(domain)} dijawab tanpa alamat. "
                                     "Untuk delegasi sungguhan isi --ns-ip dengan alamat IPv4 publik "
                                     "pendengar (sama dengan glue di registrar)")
        self.hits = HitLogger(db_path, on_hit, dedupe_s, queue_size, allowlist, per_source_per_min)
        self.resolver = CanaryResolver(domain, answer_ip, ns_ip, ttl, on_query=self.hits.submit)
        self.db_path = db_path
        self.host = host
        self.tcp_host = tcp_host or host
        self.proxy_protocol = proxy_protocol
        self.port = port
        self.tcp_timeout = tcp_timeout
        self.max_tcp = max_tcp
        self._servers: list[DNSServer] = []
        self._threads: list[threading.Thread] = []
        self._tcp_rejected = 0  # from servers already stopped

    @property
    def domain(self) -> str:
        """Normalized canary domain."""
        return self.resolver.domain

    def stats(self) -> dict[str, int]:
        """Logging counters plus TCP connections refused because all slots were busy."""
        out = asdict(self.hits.stats())
        out["tcp_rejected"] = self._tcp_rejected + (self._servers[1].server.rejected if self._servers else 0)
        return out

    def _bind(self, port: int) -> list[DNSServer]:
        udp = DNSServer(self.resolver, address=self.host, port=port, logger=_QuietLogger(), server=_UDPServer)
        actual = udp.server.server_address[1]
        try:
            tcp = DNSServer(self.resolver, address=self.tcp_host, port=actual, tcp=True, logger=_QuietLogger(),
                            handler=_TCPHandler, server=_TCPServer)
        except OSError:
            udp.server.server_close()
            raise
        tcp.server.slots = threading.BoundedSemaphore(self.max_tcp)
        tcp.server.tcp_timeout = self.tcp_timeout
        tcp.server.proxy_protocol = self.proxy_protocol
        return [udp, tcp]

    def start(self) -> "CanaryDNSServer":
        """Prepare the store, bind UDP and TCP and serve in background threads."""
        if self._servers:
            return self
        for w in init_store(self.db_path):
            self.warnings.append(w)
        for w in self.warnings:
            log.warning("%s", w)
        attempts = 20 if self.port == 0 else 1
        for k in range(attempts):
            try:
                self._servers = self._bind(self.port)
                break
            except OSError:
                if k == attempts - 1:
                    raise
        self.port = self._servers[0].server.server_address[1]
        self.hits.start()
        for s in self._servers:
            t = threading.Thread(target=s.server.serve_forever, kwargs={"poll_interval": POLL_S}, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def stop(self) -> None:
        """Stop serving, close both sockets and write the hits still queued."""
        for s in self._servers:
            s.server.shutdown()
            s.server.server_close()
        for t in self._threads:
            t.join(timeout=5)
        if self._servers:
            self._tcp_rejected += self._servers[1].server.rejected
        self._servers, self._threads = [], []
        self.hits.stop()

    def __enter__(self) -> "CanaryDNSServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _random_case(name: str, rng: random.Random) -> str:
    """DNS 0x20: flip the case of each letter at random, as hardened resolvers do."""
    return "".join(ch.upper() if ch.isalpha() and rng.random() < 0.5 else ch for ch in name)


def simulate_open(data: bytes, kind: str, resolver: tuple[str, int], timeout: float = 2.0,
                  randomize_case: bool = False, domain: str | None = None) -> list[str]:
    """Do what a fetching viewer does when it opens the file: look up its canary hosts.

    Finds the hosts with :func:`tapak.marker.canary.find_canary_hosts` and sends one A
    query per host over UDP to ``resolver`` (host, port). Stands in for "opening a copy on
    a machine whose resolver points at the listener". Returns the hosts that got a DNS
    reply; a host whose query times out or whose reply is malformed is skipped, as a
    viewer would carry on.

    Meant for the TAPAK listener or a loopback test resolver only. With ``domain`` only
    canary names of that domain are looked up; pass it whenever the file is untrusted, so
    a hostile file cannot make the examiner look up names its author chose.
    """
    hosts = find_canary_hosts(data, kind)
    if domain is not None:
        hosts = [h for h in hosts if token_from_qname(h, domain) is not None]
    rng = random.Random()
    answered = []
    for host in hosts:
        qname = _random_case(host, rng) if randomize_case else host
        query = DNSRecord.question(qname, "A")
        try:
            raw = query.send(resolver[0], resolver[1], timeout=timeout, ipv6=":" in resolver[0])
            reply = DNSRecord.parse(raw)
        except (OSError, DNSError):  # timeouts, refused connections, malformed replies
            continue
        if reply.header.id == query.header.id:
            answered.append(host)
    return answered


__all__ = ["CanaryDNSServer", "CanaryResolver", "HitLogger", "HitStats", "simulate_open"]
