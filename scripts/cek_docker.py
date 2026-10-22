"""End-to-end check of the Docker image: ``make docker-cek`` (or ``.venv/bin/python scripts/cek_docker.py``).

Everything runs under its own names and on free ports, so nothing else on the machine is
touched: the image tag ``--image`` (built here unless ``--tanpa-bangun``), the compose project
``--proyek``, the published ports 127.0.0.1:``--port-web`` and ``--port-dns`` (UDP and TCP)
and the scratch folder ``--kerja``. At the end it removes only what it created: its compose
project (containers and networks), the scratch folder and, when it built it, the image.

Checks, on fictional samples only:

1. CLI in containers without any network (``--network none``): keys, the external anchor log
   (its own host folder, TAPAK_ANCHOR_LOG, append-only as with chattr +a), issuance of the text
   sample and of the scanned sample, trace of a copy PDF and of a synthetic photo of each,
   berita acara.
2. docker-compose.yml with docker-compose.jangkar.yml: every web page and static file, a
   scanned master analysed through Terbitkan, the four pieces of evidence traced through Lacak.
3. Canary listener: an issued token is answered and logged; a made-up token is answered but
   never logged; other names in the zone get NXDOMAIN and names outside it REFUSED.
4. Offline: the CLI containers have no network; the sockets of both compose containers are
   sampled throughout and may only be the published services. Registry, anchor log, canary
   log and container logs hold no document word and no recipient name.
5. Tesseract: host and container versions. A scanned master issued on the host is traced in
   the container and the reverse: the shift channel of its scanned pages is either read (same
   word boxes) or skipped with the documented note, and no other copy is named. With other
   language data in the container the boxes always differ, so the channel must be skipped.
6. Research seed: host and container derive the same code secret, copy ids and code
   commitments, and the same copy renders to the same pixels.
7. Tail deletion of the registry inside the container: CLI and web traces are refused.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UID = "10001"  # the image's unprivileged user
DOMAIN = "kanari.tapak.test"
TEXT_SEQ, SCAN_SEQ = 7, 13
ANCHOR_ENV = {"TAPAK_ANCHOR_LOG": "/jangkar/tapak.log"}
DROP_TAIL = """
import sqlite3
from tapak.registry.chain import TRIGGERS
con = sqlite3.connect('/data/registry.db')
for name in TRIGGERS:
    con.execute(f'DROP TRIGGER {name}')
seq, kind = con.execute('SELECT seq, kind FROM entries ORDER BY seq DESC LIMIT 1').fetchone()
con.execute('DELETE FROM entries WHERE seq = ?', (seq,))
for name, body in TRIGGERS.items():
    con.execute(f'CREATE TRIGGER {name} {body}')
con.commit()
print(seq, kind)
"""
APPEND_ONLY = """
import fcntl, struct, sys
GETFLAGS, SETFLAGS, APPEND_FL = 0x80086601, 0x40086602, 0x20
with open(sys.argv[1], 'rb') as f:
    flags = struct.unpack('i', fcntl.ioctl(f, GETFLAGS, struct.pack('i', 0)))[0]
    flags = flags | APPEND_FL if sys.argv[2] == '+' else flags & ~APPEND_FL
    fcntl.ioctl(f, SETFLAGS, struct.pack('i', flags))
"""


class Cek:
    """Prints one line per check and remembers the failures."""

    def __init__(self) -> None:
        self.failed: list[str] = []

    def __call__(self, ok: bool, label: str, detail: str = "") -> bool:
        print(("OK    " if ok else "GAGAL ") + label + (f": {detail}" if detail else ""), flush=True)
        if not ok:
            self.failed.append(label)
        return ok


def sh(cmd: list, check: bool = True, **kw) -> subprocess.CompletedProcess:
    """Run a command, capture text output; on failure with check, show it and raise."""
    res = subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)
    if check and res.returncode != 0:
        print(res.stdout[-3000:], res.stderr[-3000:], sep="\n", file=sys.stderr)
        raise SystemExit(f"perintah gagal ({res.returncode}): {' '.join(str(c) for c in cmd[:8])}")
    return res


class Docker:
    """The image, its throwaway containers (always without network) and the compose project."""

    def __init__(self, args: argparse.Namespace, work: Path) -> None:
        self.args, self.work, self.image = args, work, args.image

    def run(self, cmd: list, mounts: dict, user: str | None = None, env: dict | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
        c = ["docker", "run", "--rm", "--network", "none", "--label", f"tapak-cek={self.args.proyek}"]
        c += ["--user", user] if user else []
        for host, target in mounts.items():
            c += ["-v", f"{host}:{target}"]
        for k, v in (env or {}).items():
            c += ["-e", f"{k}={v}"]
        return sh(c + [self.image] + cmd, check=check)

    def main_mounts(self) -> dict:
        w = self.work
        return {w / "data": "/data", w / "keys": "/keys", w / "jangkar": "/jangkar", w / "sampel": "/sampel:ro",
                w / "bukti": "/bukti"}

    def cli(self, *cmd, check: bool = True) -> subprocess.CompletedProcess:
        """A tapak command on the main deployment, as the image's user, with the anchor log."""
        return self.run(["tapak", *cmd], self.main_mounts(), env=ANCHOR_ENV, check=check)

    def root(self, *cmd, caps: tuple[str, ...] = (), check: bool = True) -> subprocess.CompletedProcess:
        """A command as root on the scratch folder (ownership, permissions and removal of the
        files of uid 10001, which TAPAK writes readable by their owner only)."""
        c = ["docker", "run", "--rm", "--network", "none", "--user", "0", "-v", f"{self.work}:/w"]
        c += [f"--cap-add={cap}" for cap in caps]
        return sh(c + ["--entrypoint", cmd[0], self.image, *cmd[1:]], check=check)

    def append_only(self, on: bool, check: bool = True) -> subprocess.CompletedProcess:
        """chattr +a / -a on the anchor log (the image has no chattr; the same ioctl from Python)."""
        return self.root("python", "-c", APPEND_ONLY, "/w/jangkar/tapak.log", "+" if on else "-",
                         caps=("LINUX_IMMUTABLE",), check=check)

    def manifests(self) -> dict[str, dict]:
        """'teks' and 'pindaian' manifests of the main deployment, read in a container."""
        code = ("import glob, json; print(json.dumps([json.load(open(p)) for p in "
                "sorted(glob.glob('/data/dokumen/*/manifest.json'))]))")
        found = json.loads(self.run(["python", "-c", code], self.main_mounts()).stdout)
        return {("pindaian" if m.get("scan") else "teks"): m for m in found}

    def compose(self, *cmd, check: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ, TAPAK_IMAGE=self.image, TAPAK_PORT=str(self.args.port_web),
                   TAPAK_CANARY_PORT=str(self.args.port_dns), TAPAK_ANCHOR_DIR=str(self.work / "jangkar"))
        env.pop("TAPAK_ANCHOR_LOG", None)
        return sh(["docker", "compose", "-p", self.args.proyek, "--project-directory", self.work,
                   "-f", ROOT / "docker-compose.yml", "-f", ROOT / "docker-compose.jangkar.yml", *cmd],
                  check=check, env=env)


def host_tapak(*cmd, check: bool = True) -> subprocess.CompletedProcess:
    """The repository's tapak on the host (no anchor log)."""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("TAPAK_ANCHOR_LOG", None)
    return sh([sys.executable, "-c", "import sys; from tapak.cli import main; sys.exit(main(sys.argv[1:]))", *cmd],
              check=check, env=env)


def manifests(data: Path) -> dict[str, dict]:
    """'teks' and 'pindaian' manifests of a host-readable data folder (the latter has a scan record)."""
    out = {}
    for p in sorted(data.glob("dokumen/*/manifest.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        out["pindaian" if m.get("scan") else "teks"] = m
    return out


def copy_of(data: Path, m: dict, seq: int) -> Path:
    c = next(c for c in m["copies"] if c["seq"] == seq)
    return data / "dokumen" / m["doc_hash"][:16] / "salinan" / c["file"]


def accused(json_path: Path) -> tuple[list[int], list[str]]:
    """Copies named at any stage of a ``tapak trace --json`` result, and its notes."""
    a = json.loads(json_path.read_text(encoding="utf-8"))
    stages = [a["candidates"]] + [st["candidates"] for st in a["stages"]]
    return [c["copy"]["seq"] for cs in stages for c in cs if c["accused"]], [str(n) for n in a["notes"]]


# --- web ------------------------------------------------------------------------------------


def http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 900) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def post_form(url: str, fields: dict, files: list[tuple[str, str, bytes]]) -> tuple[int, str]:
    boundary = "tapakcek" + secrets.token_hex(8)
    body = b""
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for field, name, data in files:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    status, out, _ = http(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return status, out.decode("utf-8", errors="replace")


class SocketWatch(threading.Thread):
    """Samples /proc/net of running containers; any connected socket whose local port is not
    one of the published services is an outbound connection."""

    def __init__(self, containers: dict[str, set[int]]) -> None:
        super().__init__(daemon=True)
        self.containers, self.samples, self.outbound = containers, 0, set()
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            for cid, ports in self.containers.items():
                res = sh(["docker", "exec", cid, "cat", "/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp",
                          "/proc/net/udp6"], check=False)
                for line in res.stdout.splitlines():
                    f = line.split()
                    if len(f) < 4 or ":" not in f[1] or f[0] == "sl":
                        continue
                    local_port, remote_port = int(f[1].rsplit(":", 1)[1], 16), int(f[2].rsplit(":", 1)[1], 16)
                    if remote_port and local_port not in ports:
                        self.outbound.add(f"{cid[:12]} {f[1]} -> {f[2]}")
                self.samples += 1
            self.stop.wait(0.25)


# --- the check --------------------------------------------------------------------------------


def run_check(args: argparse.Namespace, d: Docker, cek: Cek) -> None:
    w = d.work
    from tapak.decoder.trace import SCAN_SHIFT_SKIPPED
    from tapak.samplegen import scanned_sample

    # Versions.
    engine_ctr = d.run(["python", "-c", "from tapak.marker.raster import ocr_engine; print(ocr_engine())"],
                       {}).stdout.strip()
    try:
        from tapak.marker.raster import ocr_engine

        engine_host = ocr_engine()
    except RuntimeError as exc:
        engine_host = None
        print(f"Tesseract host tidak tersedia ({exc}); uji silang dilewati")
    print(f"Tesseract kontainer: {engine_ctr}\nTesseract host     : {engine_host}")

    # Scratch folder: samples (host-owned, read-only in the containers), state owned by uid 10001.
    for sub in ("data/kanari", "data/kanari-izin", "keys", "jangkar", "bukti", "sampel", "host", "kontainer",
                "riset/h", "riset/k"):
        (w / sub).mkdir(parents=True, exist_ok=True)
    nota = ROOT / "samples" / "nota_dinas.pdf"
    shutil.copy(nota, w / "sampel")
    shutil.copy(ROOT / "samples" / "recipients.csv", w / "sampel")
    (w / "sampel" / "nota_dinas_pindaian.pdf").write_bytes(scanned_sample(nota.read_bytes()))
    (w / "sampel" / "nota_dinas_pindaian_ocr.pdf").write_bytes(scanned_sample(nota.read_bytes(), ocr_layer=True))
    d.root("chown", "-R", f"{UID}:{UID}", "/w/data", "/w/keys", "/w/jangkar", "/w/bukti")

    # 1. CLI without network.
    print("\n== CLI di kontainer tanpa jaringan ==")
    cek(d.cli("keys", "init").returncode == 0, "tapak keys init")
    r = d.cli("jangkar", "mulai")
    cek(r.returncode == 0 and (w / "jangkar" / "tapak.log").is_file(), "tapak jangkar mulai (log di folder host terpisah)")
    # chattr +a, as docs/operasi.md suggests: TAPAK still appends, nobody can truncate.
    attr = d.append_only(True, check=False)
    if attr.returncode == 0:
        r = d.run(["python", "-c", "import os; os.open('/jangkar/tapak.log', os.O_WRONLY)"], d.main_mounts(),
                  check=False)  # opening for writing without O_APPEND: refused, and harmless if it were not
        cek(r.returncode != 0 and "PermissionError" in r.stderr, "log jangkar tambah-saja (chattr +a): tidak dapat dibuka untuk ditimpa")
    else:
        print(f"Atribut tambah-saja tidak dapat dipasang di sistem berkas ini; dilewati ({attr.stderr.strip()[-120:]})")
    for name in ("nota_dinas.pdf", "nota_dinas_pindaian.pdf"):
        t0 = time.perf_counter()
        r = d.cli("issue", f"/sampel/{name}", "/sampel/recipients.csv", "--canary-domain", DOMAIN, "--workers", "3")
        cek("Gerbang visual: lulus" in r.stdout, f"tapak issue {name}", f"{time.perf_counter() - t0:.0f} s")
    docs = d.manifests()
    evidence = {}  # label -> (doc key, path inside the container, host path, expected seq)
    for kind, seq in (("teks", TEXT_SEQ), ("pindaian", SCAN_SEQ)):
        m, key = docs[kind], docs[kind]["doc_hash"][:16]
        copy = next(c for c in m["copies"] if c["seq"] == seq)
        d.run(["cp", f"/data/dokumen/{key}/salinan/{copy['file']}", f"/bukti/{kind}-salinan.pdf"], d.main_mounts())
        evidence[f"{kind}-pdf"] = (key, f"/bukti/{kind}-salinan.pdf", w / "bukti" / f"{kind}-salinan.pdf", seq)
        d.run(["python", "-m", "tapak.photos", "--issued", f"/data/dokumen/{key}/salinan", "--out", f"/bukti/foto-{kind}",
               "--seqs", str(seq), "--per-copy", "1", "--angles", "10", "--no-screenshots"], d.main_mounts())
        photo = next((w / "bukti" / f"foto-{kind}").glob("photo_*.jpg"))
        evidence[f"{kind}-foto"] = (key, f"/bukti/foto-{kind}/{photo.name}", photo, seq)
    results = {}
    for label, (key, inside, _, seq) in evidence.items():
        t0 = time.perf_counter()
        r = d.cli("trace", inside, "--doc", key, "--json", f"/bukti/{label}.json", "--report", f"/bukti/{label}.pdf",
                  check=False)
        results[label] = (r, time.perf_counter() - t0)
    d.root("chmod", "-R", "a+rX", "/w/bukti")  # the CLI writes its results readable by uid 10001 only
    for label, (key, inside, _, seq) in evidence.items():
        r, seconds = results[label]
        named, notes = accused(w / "bukti" / f"{label}.json") if r.returncode == 0 else ([], [r.stderr[-200:]])
        skipped = [n for n in notes if n.startswith(SCAN_SHIFT_SKIPPED)]
        report_ok = (w / "bukti" / f"{label}.pdf").read_bytes()[:5] == b"%PDF-" if r.returncode == 0 else False
        cek(named == [seq] and not skipped and report_ok and "Log jangkar: cocok" in r.stdout,
            f"CLI lacak {label}", f"salinan {named}, {seconds:.0f} s, berita acara {report_ok}")

    # 2. compose: web on the published port, canary listener on its own network.
    print("\n== docker compose (app + canary-dns, log jangkar) ==")
    d.compose("up", "-d", "--no-build")
    base = f"http://127.0.0.1:{args.port_web}"
    for _ in range(120):
        try:
            if http(base + "/healthz", timeout=2)[0] == 200:
                break
        except OSError:
            pass
        time.sleep(0.5)
    app_id = d.compose("ps", "-q", "app").stdout.strip()
    dns_id = d.compose("ps", "-q", "canary-dns").stdout.strip()
    watch = SocketWatch({app_id: {8000}, dns_id: {5353}})
    watch.start()
    statics: set[str] = set()
    pages = ["/", "/terbitkan", "/lacak", "/registri", "/registri/status", "/healthz"]
    bad = []
    for page in pages:
        status, body, headers = http(base + page)
        text = body.decode("utf-8", errors="replace")
        statics |= set(re.findall(r'(?:href|src)="(/static/[^"?#]+)', text))
        statics |= set(re.findall(r'data-pratinjau="(/dokumen/[^"]+)"', text))
        if status != 200 or ("frame-ancestors" not in headers.get("content-security-policy", "")):
            bad.append(f"{page} {status}")
    for s in sorted(statics):
        status = http(base + s)[0]
        bad += [f"{s} {status}"] if status != 200 else []
    cek(not bad, f"{len(pages)} halaman web dan {len(statics)} berkas statis/pratinjau", ", ".join(bad))

    # Terbitkan with a scanned master (OCR layer dropped), read with the container's Tesseract.
    # Not issued here: the web issues with up to 8 worker processes (os.cpu_count), and issuance
    # itself is the code path the CLI already ran in the container.
    t0 = time.perf_counter()
    status, html = post_form(base + "/terbitkan/analisis", {"c": "3", "eps": "1e-6"},
                             [("dokumen", "nota_pindaian_ocr.pdf", (w / "sampel" / "nota_dinas_pindaian_ocr.pdf").read_bytes()),
                              ("penerima", "recipients.csv", (w / "sampel" / "recipients.csv").read_bytes())])
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/terbitkan", html)
    cek(status == 200 and sid is not None and "kotak kata (Tesseract)" in html, "web Terbitkan: analisis induk hasil pindai",
        f"{time.perf_counter() - t0:.0f} s")

    for label, (key, _, host_path, seq) in evidence.items():
        t0 = time.perf_counter()
        status, html = post_form(base + "/lacak", {"dokumen": key}, [("bukti", host_path.name, host_path.read_bytes())])
        named = [int(s) for s in re.findall(r'<h2[^>]*><span class="who-seq">Salinan #(\d+)</span>', html)]
        tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara\.pdf", html)
        pdf = http(base + f"/lacak/{tid.group(1)}/berita-acara.pdf")[1][:5] if tid else b""
        scan_ok = "pindaian" not in label or "Kanal geser mencakup halaman pindaian" in html
        cek(status == 200 and named == [seq] and pdf == b"%PDF-" and scan_ok, f"web lacak {label}",
            f"salinan {named}, {time.perf_counter() - t0:.0f} s, berita acara {pdf == b'%PDF-'}")

    # 3. Canary listener.
    print("\n== pendengar kanari ==")
    from dnslib import QTYPE, RCODE, DNSRecord

    def ask(name: str, tcp: bool = False) -> DNSRecord:
        return DNSRecord.parse(DNSRecord.question(name, "A").send("127.0.0.1", args.port_dns, tcp=tcp, timeout=5))

    issued = {c["canary_token"] for m in docs.values() for c in m["copies"]}
    token = next(c["canary_token"] for c in docs["teks"]["copies"] if c["seq"] == TEXT_SEQ)
    fake = token
    while fake in issued:
        fake = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz234567") for _ in range(16))
    for name, tcp in ((f"{token}.c.{DOMAIN}", False), (f"{token.upper()}.c.{DOMAIN}", True)):
        a = ask(name, tcp)
        cek(a.header.rcode == RCODE.NOERROR and [str(r.rdata) for r in a.rr if r.rtype == QTYPE.A] == ["127.0.0.1"],
            f"token terbit dijawab ({'TCP' if tcp else 'UDP'})")
    a = ask(f"{fake}.c.{DOMAIN}")
    cek(a.header.rcode == RCODE.NOERROR, "token karangan dijawab (tetapi tidak boleh dicatat)")
    cek(ask(f"tidak-ada.{DOMAIN}").header.rcode == RCODE.NXDOMAIN, "nama lain di zona: NXDOMAIN")
    cek(ask("example.com").header.rcode == RCODE.REFUSED, "nama di luar zona: REFUSED (bukan resolver terbuka)")
    time.sleep(2.5)  # the writer thread batches hits
    logged = sh(["docker", "exec", dns_id, "python", "-c", "import json; from tapak.canary_dns.store import events; "
                 "print(json.dumps([e.token for e in events('/data/kanari/kanari.db')]))"]).stdout
    tokens = json.loads(logged)
    cek(set(tokens) == {token}, "log kanari hanya memuat token terbit", f"{len(tokens)} kejadian")
    page = http(base + "/registri")[1].decode()
    cek(f'<span class="dok-nama">Salinan #{TEXT_SEQ}</span>' in page, f"halaman Registri menampilkan kueri salinan #{TEXT_SEQ}")

    # 7. Tail deletion inside the container, then CLI and web traces.
    print("\n== penghapusan ujung registri ==")
    dropped = d.run(["python", "-c", DROP_TAIL], d.main_mounts(), user=UID).stdout.strip()
    key, inside, host_path, _ = evidence["teks-pdf"]
    r = d.cli("trace", inside, "--doc", key, check=False)
    cek(r.returncode == 2 and "pelacakan ditolak: log jangkar" in r.stderr and "dihapus dari ujung rantai" in r.stderr,
        f"CLI lacak ditolak setelah entri {dropped} dihapus")
    r = d.cli("verify", check=False)
    cek(r.returncode == 1 and "TIDAK COCOK" in r.stdout, "tapak verify: log jangkar TIDAK COCOK")
    status, html = post_form(base + "/lacak", {"dokumen": key}, [("bukti", host_path.name, host_path.read_bytes())])
    cek("pelacakan ditolak: log jangkar" in html and "who-seq" not in html, "web lacak ditolak, tanpa nama")

    # 4. Offline and data minimization.
    print("\n== luring dan minimisasi data ==")
    watch.stop.set()
    watch.join()
    cek(not watch.outbound and watch.samples > 20, "tidak ada koneksi keluar dari kontainer compose",
        f"{watch.samples} sampel soket" + (f"; {sorted(watch.outbound)[:3]}" if watch.outbound else ""))
    from tapak.marker.layout import extract_layout

    words = {x.text.strip(".,;:()") for x in extract_layout(nota.read_bytes()).words()}
    words = {x for x in words if len(x) >= 9 and x.isalpha()}
    with open(w / "sampel" / "recipients.csv", encoding="utf-8-sig", newline="") as f:
        names = {row["nama"] for row in csv.DictReader(f)}
    logs = d.compose("logs", "--no-color").stdout.encode()
    d.root("chmod", "-R", "a+rX", "/w/data")  # the anchor log is append-only now: read it as root
    anchor_log = d.root("cat", "/w/jangkar/tapak.log").stdout.encode()
    stores = [*(w / "data").glob("registry.db*"), *(w / "data" / "kanari").glob("kanari.db*")]
    blob = b"".join(p.read_bytes() for p in stores) + anchor_log + logs
    leaks = sorted(x for x in words | names if x.encode() in blob)
    cek(not leaks and len(words) > 20, f"registri, log jangkar, log kanari, log kontainer tanpa {len(words)} kata "
        f"dokumen dan {len(names)} nama penerima", ", ".join(leaks[:5]))

    # 5. Tesseract across host and container. Whether two Tesseract builds find the same word
    # boxes is not known in advance: the digest of the boxes decides. Either the shift channel of
    # the scanned pages is read (same boxes) or it is skipped with the note; no other copy may
    # be named. Other language data (eng.traineddata as ind.traineddata, TESSDATA_PREFIX) always
    # changes the boxes, so that trace in the container must skip the channel.
    if engine_host is not None:
        print("\n== Tesseract host dan kontainer ==")
        me = f"{os.getuid()}:{os.getgid()}"
        host_tapak("--data", w / "host/data", "--keys", w / "host/keys", "keys", "init")
        host_tapak("--data", w / "host/data", "--keys", w / "host/keys", "issue", w / "sampel/nota_dinas_pindaian.pdf",
                   w / "sampel/recipients.csv", "--canary-domain", "", "--workers", "3")
        d.run(["tapak", "--data", "/k/data", "--keys", "/k/keys", "keys", "init"], {w / "kontainer": "/k"}, user=me)
        d.run(["tapak", "--data", "/k/data", "--keys", "/k/keys", "issue", "/sampel/nota_dinas_pindaian.pdf",
               "/sampel/recipients.csv", "--canary-domain", "", "--workers", "3"],
              {w / "kontainer": "/k", w / "sampel": "/sampel:ro"}, user=me)
        hm, km = manifests(w / "host/data")["pindaian"], manifests(w / "kontainer/data")["pindaian"]
        host_pdf, ctr_pdf = copy_of(w / "host/data", hm, SCAN_SEQ), copy_of(w / "kontainer/data", km, SCAN_SEQ)
        sh([sys.executable, "-m", "tapak.photos", "--issued", host_pdf.parent, "--out", w / "host/foto", "--seqs",
            SCAN_SEQ, "--per-copy", "1", "--angles", "10", "--no-screenshots"], env=dict(os.environ, PYTHONPATH=str(ROOT)))
        host_photo = next((w / "host/foto").glob("photo_*.jpg"))
        (w / "tessdata-lain").mkdir()
        d.run(["python", "-c", "import glob, shutil; shutil.copy(glob.glob('/usr/share/tesseract-ocr/*/tessdata/"
               "eng.traineddata')[0], '/t/ind.traineddata')"], {w / "tessdata-lain": "/t"}, user=me)

        def in_container(evidence: Path, out: str, other_data: bool = False) -> subprocess.CompletedProcess:
            mounts = {w / "host": "/x", w / "tessdata-lain": "/tessdata-lain:ro"}
            env = {"TESSDATA_PREFIX": "/tessdata-lain"} if other_data else {}
            return d.run(["tapak", "--data", "/x/data", "--keys", "/x/keys", "trace", f"/x/{evidence.relative_to(w / 'host')}",
                          "--doc", hm["doc_hash"][:16], "--json", f"/x/{out}"], mounts, user=me, env=env, check=False)

        cases = [
            ("terbit di host, lacak PDF di kontainer", lambda: in_container(host_pdf, "a.json"), w / "host/a.json", False),
            ("terbit di kontainer, lacak PDF di host",
             lambda: host_tapak("--data", w / "kontainer/data", "--keys", w / "kontainer/keys", "trace", ctr_pdf, "--doc",
                                km["doc_hash"][:16], "--json", w / "kontainer/b.json", check=False),
             w / "kontainer/b.json", False),
            ("terbit di host, lacak PDF di kontainer dengan data bahasa lain",
             lambda: in_container(host_pdf, "c.json", True), w / "host/c.json", True),
            ("terbit di host, lacak foto di kontainer dengan data bahasa lain",
             lambda: in_container(host_photo, "d.json", True), w / "host/d.json", True),
        ]
        for label, trace, out, must_skip in cases:
            r = trace()
            if r.returncode != 0:
                cek(False, label, r.stderr.strip()[-200:])
                continue
            named, notes = accused(out)
            channels = [c["channel"] for c in json.loads(out.read_text(encoding="utf-8"))["channels"]]
            skipped = [n for n in notes if n.startswith(SCAN_SHIFT_SKIPPED)]
            read = not skipped and "geser" in channels and named == [SCAN_SEQ]
            ok = set(named) <= {SCAN_SEQ} and (bool(skipped) if must_skip else (read or bool(skipped)))
            how = skipped[0] if skipped else "kotak kata sama, kanal geser halaman pindaian dibaca"
            cek(ok, label, f"salinan {named}, kanal {'+'.join(channels) or '-'}; {how}")

    # 6. Research seed: the same code secret, copy ids and code commitments on the host and in
    # the container, and copies that render to the same pixels (the PDF /ID differs per write).
    print("\n== benih riset ==")
    seed = ["--no-registry", "--canary-domain", "", "--benih-riset", "2026", "--workers", "3"]
    host_tapak("--data", w / "riset/h/data", "--keys", w / "riset/h/keys", "issue", w / "sampel/nota_dinas.pdf",
               w / "sampel/recipients.csv", *seed)
    d.run(["tapak", "--data", "/r/data", "--keys", "/r/keys", "issue", "/sampel/nota_dinas.pdf",
           "/sampel/recipients.csv", *seed], {w / "riset/k": "/r", w / "sampel": "/sampel:ro"},
          user=f"{os.getuid()}:{os.getgid()}")
    mh, mk = (manifests(w / f"riset/{x}/data")["teks"] for x in ("h", "k"))
    same = all(a["copy_id"] == b["copy_id"] and a["code_digest"] == b["code_digest"]
               for a, b in zip(mh["copies"], mk["copies"])) and len(mh["copies"]) == len(mk["copies"])
    secret_same = (w / "riset/h/keys/code_secret.key").read_bytes() == (w / "riset/k/keys/code_secret.key").read_bytes()
    from tapak.marker.render import render_pages

    seq = TEXT_SEQ
    pages = [render_pages(copy_of(w / f"riset/{x}/data", m, seq).read_bytes(), 150) for x, m in (("h", mh), ("k", mk))]
    pixels = len(pages[0]) == len(pages[1]) and all((a == b).all() for a, b in zip(*pages))
    cek(same and secret_same and pixels, "--benih-riset 2026: host dan kontainer sama",
        f"rahasia kode, id salinan, dan komitmen kode {len(mh['copies'])} salinan; piksel salinan #{seq} identik {pixels}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Uji ujung ke ujung image Docker TAPAK (nama, port, dan folder sendiri)")
    ap.add_argument("--image", default="tapak-cek:lokal", help="tag image yang dibangun atau dipakai")
    ap.add_argument("--tanpa-bangun", action="store_true", help="pakai image yang sudah ada, jangan bangun")
    ap.add_argument("--simpan-image", action="store_true", help="jangan hapus image yang dibangun skrip ini")
    ap.add_argument("--proyek", default="tapakcek", help="nama proyek compose")
    ap.add_argument("--port-web", type=int, default=8797, help="port web di 127.0.0.1 host")
    ap.add_argument("--port-dns", type=int, default=15353, help="port pendengar kanari di host (UDP dan TCP)")
    ap.add_argument("--kerja", default=str(ROOT / "out" / "docker-cek"), help="folder kerja sementara")
    ap.add_argument("--simpan-kerja", action="store_true", help="jangan hapus folder kerja")
    args = ap.parse_args(argv)
    work = Path(args.kerja).resolve()
    if work.exists():
        raise SystemExit(f"{work} sudah ada; hapus dulu atau pilih --kerja lain")
    work.mkdir(parents=True)
    d, cek = Docker(args, work), Cek()
    built = False
    try:
        if not args.tanpa_bangun:
            t0 = time.perf_counter()
            sh(["docker", "build", "-t", args.image, ROOT])
            built = True
            print(f"Image {args.image} dibangun dalam {time.perf_counter() - t0:.0f} s")
        size = int(sh(["docker", "image", "inspect", "-f", "{{.Size}}", args.image]).stdout)
        print(f"Ukuran image {args.image}: {size / 1e6:.0f} MB (docker image inspect; terkompresi bila Docker memakai penyimpanan image containerd)")
        run_check(args, d, cek)
    finally:
        d.compose("down", "--remove-orphans", check=False)
        if (work / "jangkar" / "tapak.log").exists():
            d.append_only(False, check=False)
        if not args.simpan_kerja:
            d.root("find", "/w", "-mindepth", "1", "-delete", check=False)  # files of uid 10001
            shutil.rmtree(work, ignore_errors=True)
        if built and not args.simpan_image:
            sh(["docker", "image", "rm", args.image], check=False)
    print("\n" + ("Semua pemeriksaan lulus." if not cek.failed else f"{len(cek.failed)} pemeriksaan GAGAL: "
                                                                      + "; ".join(cek.failed)))
    return 1 if cek.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
