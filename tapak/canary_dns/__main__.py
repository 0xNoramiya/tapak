"""Command line entry point: ``python -m tapak.canary_dns``.

Three modes:

* default: run the authoritative canary DNS listener in the foreground and print one
  Indonesian log line per canary hit. Stops cleanly on Ctrl+C or SIGTERM (``docker stop``).
* ``--anchor``: write the current head of the event chain into the registry (entry kind
  ``canary_anchor``) and exit. Signed with ``--signing-key`` when that file exists,
  otherwise left pending for the key holder. Run it periodically (cron or a timer) on the
  operator side, not inside the internet-facing listener.
* ``--verify``: check the event chain (against the signed anchors when the public key is
  available) and exit with 0 when it is intact, 1 otherwise.

``main(argv)`` always returns an exit code (2 for a usage error) instead of raising
SystemExit, so ``tapak.cli`` can delegate to it.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import threading
from pathlib import Path

from tapak.canary_dns.server import MAX_TTL, CanaryDNSServer
from tapak.canary_dns.store import CanaryEvent, anchor_head, check_events_chain, verify_events_anchored
from tapak.config import load_settings

# argparse's own messages, translated (applied in order to the whole message).
_TRANSLATIONS = (
    (r"^unrecognized arguments: ", "argumen tidak dikenal: "),
    (r"^argument (\S+): ", r"opsi \1: "),
    (r"expected one argument", "memerlukan satu nilai"),
    (r"ignored explicit argument ", "tidak menerima nilai "),
    (r"not allowed with argument ", "tidak boleh dipakai bersama "),
)


class _Exit(Exception):
    """Raised by the parser instead of SystemExit; carries the exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _Formatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: ANN001, ANN201, D102
        super().add_usage(usage, actions, groups, "penggunaan: " if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    """ArgumentParser with Indonesian messages that never calls sys.exit."""

    def error(self, message: str) -> None:  # noqa: D102
        for pattern, repl in _TRANSLATIONS:
            message = re.sub(pattern, repl, message)
        self.print_usage(sys.stderr)
        print(f"Kesalahan: {message}", file=sys.stderr)
        raise _Exit(2)

    def exit(self, status: int = 0, message: str | None = None) -> None:  # noqa: D102
        if message:
            sys.stderr.write(message)
        raise _Exit(status)


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port harus bilangan bulat 0 sampai 65535, bukan {text!r}")
    return value


def _ttl(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if not 0 <= value <= MAX_TTL:
        raise argparse.ArgumentTypeError(f"TTL harus bilangan bulat 0 sampai {MAX_TTL}, bukan {text!r}")
    return value


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not value >= 0:
        raise argparse.ArgumentTypeError(f"nilai detik harus bilangan 0 atau lebih, bukan {text!r}")
    return value


def format_hit(ev: CanaryEvent) -> str:
    """One log line for a canary hit (shown to the operator)."""
    return (f"[{ev.received_at}] KANARI TERPICU: token {ev.token} ({ev.qtype}) "
            f"dari resolver {ev.src_ip}:{ev.src_port}, nama {ev.qname}, catatan #{ev.seq}")


def _parser() -> _Parser:
    settings = load_settings()
    ap = _Parser(prog="python -m tapak.canary_dns", add_help=False, allow_abbrev=False,
                 formatter_class=_Formatter,
                 description="Pendengar DNS otoritatif untuk token kanari TAPAK (kanal 5).")
    g = ap.add_argument_group("opsi")
    g.add_argument("-h", "--help", action="help", help="tampilkan bantuan ini lalu keluar")
    g.add_argument("--domain", default=settings.canary_domain,
                   help="domain kanari; nama salinan berbentuk <token>.c.<domain> "
                        f"(bawaan: TAPAK_CANARY_DOMAIN atau {settings.canary_domain})")
    g.add_argument("--db", default=str(settings.canary_db),
                   help=f"berkas SQLite catatan kejadian kanari (bawaan: {settings.canary_db})")
    g.add_argument("--registry", default=str(settings.registry_path),
                   help=f"registri tempat jangkar kanari dicatat dan diperiksa (bawaan: {settings.registry_path})")
    g.add_argument("--allowlist", default=str(settings.canary_allowlist),
                   help="berkas digest token yang diterbitkan; kueri token lain dijawab tetapi tidak dicatat "
                        f"(bawaan: {settings.canary_allowlist}; kosongkan untuk mencatat semua)")
    g.add_argument("--per-sumber", type=int, default=0,
                   help="maksimum kejadian tercatat per alamat sumber per menit (bawaan: 0, tanpa batas; "
                        "daftar izin token sudah mencegah log membengkak)")
    g.add_argument("--host", default="0.0.0.0", help="alamat yang didengarkan (bawaan: 0.0.0.0)")
    g.add_argument("--tcp-host", default=None,
                   help="alamat TCP bila berbeda dari --host (bawaan: sama dengan --host); di Fly.io UDP "
                        "hanya tiba di fly-global-services, TCP di alamat mesin")
    g.add_argument("--port", type=_port, default=53, help="port UDP dan TCP (bawaan: 53; 0 = port bebas)")
    g.add_argument("--answer-ip", default="127.0.0.1",
                   help="alamat IPv4 jawaban untuk nama kanari (bawaan: 127.0.0.1)")
    g.add_argument("--ns-ip", default=os.environ.get("TAPAK_CANARY_NS_IP") or None,
                   help="alamat IPv4 publik pendengar ini untuk ns1.<domain>, sama dengan glue di "
                        "registrar (bawaan: --host bila berupa alamat IPv4 tertentu)")
    g.add_argument("--ttl", type=_ttl, default=0, help="TTL jawaban dalam detik (bawaan: 0)")
    g.add_argument("--dedupe", type=_seconds, default=1.0,
                   help="kueri sama (token, sumber, jenis) dalam jendela ini dicatat sekali (bawaan: 1 detik)")
    g.add_argument("--anchor", action="store_true",
                   help="jangkarkan ujung rantai catatan ke registri lalu keluar (tanpa mendengarkan)")
    g.add_argument("--verify", action="store_true", help="periksa rantai catatan lalu keluar (tanpa mendengarkan)")
    g.add_argument("--signing-key", default=str(settings.signing_key_path),
                   help="kunci penanda tangan registri untuk --anchor; bila berkas tidak ada, jangkar "
                        "dicatat belum bertanda tangan")
    g.add_argument("--public-key", default=str(settings.public_key_path),
                   help="kunci publik registri untuk --verify")
    return ap


def _anchor(args: argparse.Namespace) -> int:
    from tapak.registry.chain import RegistryError
    from tapak.registry.signing import load_signer

    key = Path(args.signing_key)
    try:
        signer = load_signer(key) if key.is_file() else None
        seq, h = anchor_head(args.db, signer, registry_path=args.registry)
    except (ValueError, OSError, RegistryError) as exc:
        print(f"Kesalahan: {exc}", file=sys.stderr)
        return 2
    if seq == 0:
        print("Catatan kanari masih kosong; tidak ada yang dijangkarkan.")
    elif signer is None:
        print(f"Ujung rantai kanari #{seq} ({h[:16]}...) dicatat di registri, belum bertanda tangan "
              "(menunggu pemegang kunci).")
    else:
        print(f"Ujung rantai kanari #{seq} ({h[:16]}...) dijangkarkan dan ditandatangani di registri.")
    return 0


def _verify(args: argparse.Namespace) -> int:
    from tapak.registry.signing import load_public_key

    pub_path = Path(args.public_key)
    try:
        if pub_path.is_file():
            report = verify_events_anchored(args.db, load_public_key(pub_path), registry_path=args.registry)
        else:
            report = check_events_chain(args.db)
            report.warnings.append(f"kunci publik tidak ditemukan ({pub_path}); jangkar tidak diperiksa")
    except ValueError as exc:
        print(f"Kesalahan: {exc}", file=sys.stderr)
        return 2
    print("\n".join(report.lines()))
    return 0 if report.ok else 1


def _listen(args: argparse.Namespace) -> int:
    def on_hit(ev: CanaryEvent) -> None:
        print(format_hit(ev), flush=True)

    try:
        server = CanaryDNSServer(args.domain, args.db, host=args.host, port=args.port, answer_ip=args.answer_ip,
                                 ttl=args.ttl, on_hit=on_hit, ns_ip=args.ns_ip, dedupe_s=args.dedupe,
                                 allowlist=args.allowlist or None, per_source_per_min=args.per_sumber,
                                 tcp_host=args.tcp_host)
        if args.allowlist and not Path(args.allowlist).exists():
            print(f"PERINGATAN: daftar izin token {args.allowlist} belum ada; semua token dicatat sampai "
                  "berkas itu dibuat oleh penerbitan pertama", file=sys.stderr, flush=True)
        server.start()
    except ValueError as exc:
        print(f"Kesalahan: {exc}", file=sys.stderr)
        return 2
    except (OSError, OverflowError) as exc:
        detail = getattr(exc, "strerror", None) or exc
        print(f"Gagal membuka port {args.port} di {args.host}: {detail}", file=sys.stderr)
        return 2

    stop = threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
    ns = server.resolver.ns_ip or "tidak diisi"
    where = (f"{args.host}:{server.port} (UDP dan TCP)" if server.tcp_host == args.host
             else f"{args.host}:{server.port} (UDP) dan {server.tcp_host}:{server.port} (TCP)")
    print(f"Pendengar DNS kanari aktif: nama *.c.{server.domain} di {where}, jawaban A {args.answer_ip} "
          f"TTL {args.ttl}, ns1 {ns}, catatan di {args.db}", flush=True)
    for warning in server.warnings:
        print(f"PERINGATAN: {warning}", flush=True)
    try:
        while not stop.wait(0.5):
            pass
    finally:
        server.stop()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        st = server.stats()
        print(f"Pendengar DNS kanari berhenti. Kueri kanari {st['received']}, dicatat {st['written']}, "
              f"digabung sebagai duplikat {st['deduplicated']}, dibuang karena antrean penuh {st['dropped']}, "
              f"gagal dicatat {st['failed']}, koneksi TCP ditolak {st['tcp_rejected']}.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the selected mode and return the process exit code (never raises SystemExit)."""
    try:
        args = _parser().parse_args(argv)
    except _Exit as exc:
        return exc.code
    if not args.domain:
        print("Kesalahan: --domain wajib diisi (atau atur variabel TAPAK_CANARY_DOMAIN)", file=sys.stderr)
        return 2
    if args.anchor and args.verify:
        print("Kesalahan: --anchor dan --verify tidak boleh dipakai bersamaan", file=sys.stderr)
        return 2
    if args.anchor:
        return _anchor(args)
    if args.verify:
        return _verify(args)
    return _listen(args)


if __name__ == "__main__":
    sys.exit(main())
