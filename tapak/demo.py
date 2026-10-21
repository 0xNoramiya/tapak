"""The 90-second demo scenario, fully non-interactive (``make demo`` / ``tapak demo``).

1. issue 20 marked copies of a synthetic nota dinas (all channels, semantic variants
   reviewed by a simulated reviewer), recorded in the signed registry;
2. a recipient photographs copy 13 with a phone (synthetic photo: 25 degrees, shading,
   blur, WhatsApp double JPEG);
3. the photo is traced back to copy 13, with the false-accusation probability;
4. someone opens copy 7 on a machine outside the unit's network: the canary DNS listener
   logs the lookup and the alert names copy 7;
5. a third party verifies the registry with only the public key, and a tampered copy of
   the registry is caught;
6. the berita acara PDF is written.

Everything runs locally; the canary listener binds to 127.0.0.1 on a free port.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def samples_dir() -> Path:
    """The samples folder: in the working directory (Docker, installed package) or the checkout."""
    for base in (Path.cwd(), ROOT):
        if (base / "samples" / "templates").is_dir():
            return base / "samples"
    raise FileNotFoundError("folder samples/templates tidak ditemukan; jalankan dari akar repositori TAPAK")


def _say(step: str, text: str) -> None:
    print(f"\n[{step}] {text}", flush=True)


def _ok(text: str) -> None:
    print(f"      {text}", flush=True)


def run_demo(workdir: Path, keep: bool = False) -> int:
    """Run the scenario in ``workdir``; return 0 if every expected outcome happened."""
    import os

    saved = {k: os.environ.get(k) for k in ("TAPAK_DATA", "TAPAK_KEY_DIR", "TAPAK_CANARY_DOMAIN")}
    try:
        return _run(Path(workdir), keep)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run(workdir: Path, keep: bool) -> int:
    import os

    import numpy as np

    t0 = time.perf_counter()
    if workdir.exists() and not keep:
        shutil.rmtree(workdir)
    (workdir / "data").mkdir(parents=True, exist_ok=True)
    os.environ["TAPAK_DATA"] = str(workdir / "data")
    os.environ["TAPAK_KEY_DIR"] = str(workdir / "keys")
    domain = "kanari.tapak.test"
    os.environ["TAPAK_CANARY_DOMAIN"] = domain

    from tapak.config import load_settings
    from tapak.decoder.accuse import VERDICT_IDENTIFIED
    from tapak.llm.provider import get_provider
    from tapak.marker.issue import IssueSettings, SemanticSelection, read_recipients
    from tapak.marker.master import load_master
    from tapak.marker.render import render_pages
    from tapak.marker.semantic import STATUS_APPROVED, find_candidate_units, generate_variant_set
    from tapak.photos import PhotoParams, photo_jpeg
    from tapak.service import ensure_keys, issue_document, trace_evidence, write_report

    settings = load_settings()
    samples = samples_dir()
    sample = samples / "nota_dinas.pdf"
    recipients_csv = samples / "recipients.csv"
    if not sample.exists() or not recipients_csv.exists():
        from tapak.samplegen import main as gen

        gen(["--templates", str(samples / "templates"), "--out", str(samples)])
    failures: list[str] = []

    # 1 --------------------------------------------------------------------------------
    _say("1/6", "Menerbitkan 20 salinan bertanda dari nota dinas sintetis")
    keys = ensure_keys(settings)  # like `tapak keys init`: code secret and registry signing key
    master = load_master(sample.read_bytes())
    provider = get_provider("mock")
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, provider) for u in units]
    for vs in sets:  # simulated human reviewer: in the web UI each variant is approved by hand
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED)
    _ok(f"kanal semantik: {len(units)} kalimat aman, varian disetujui oleh peninjau (disimulasikan)")
    out = issue_document(settings, sample, read_recipients(recipients_csv),
                         IssueSettings(canary_domain=domain), issuer="Kasi Ops Brigif 9905 (fiktif)",
                         keys=keys, semantic=SemanticSelection(units, sets))
    m = out.manifest
    p = m.tardos_params
    _ok(f"{len(m.copies)} salinan dalam {m.elapsed_s:.1f} s; kode Tardos m={p.length} bit, c={p.c}, eps={p.eps:g}")
    _ok("kanal: " + ", ".join(f"{ch} ({info['positions']} posisi)" for ch, info in m.plan_summary.items())
        + f", canary (subdomain per salinan di {domain})")
    _ok(f"registri: {out.registry_entries} entri ditandatangani Ed25519")

    # 2 --------------------------------------------------------------------------------
    _say("2/6", "Salinan #13 difoto dengan ponsel dan dikirim lewat WhatsApp (sintetis)")
    copy13 = out.folder / "salinan" / m.copies[12].file
    page = render_pages(copy13.read_bytes(), 200, [0])[0]
    photo, meta = photo_jpeg(page, np.random.default_rng(2), PhotoParams(angle_deg=25.0))
    photo_path = workdir / "foto_bocor.jpg"
    photo_path.write_bytes(photo)
    w, h = meta["image_size"]
    _ok(f"{photo_path.name}: {w}x{h} px, sudut pandang 25 derajat, bayangan, blur, JPEG dua kali")

    # 3 --------------------------------------------------------------------------------
    _say("3/6", "Melacak sumber foto")
    t = time.perf_counter()
    outcome = trace_evidence(settings, m.doc_hash, photo_path.name, photo)
    a = outcome.attribution
    for line in a.summary_lines():
        _ok(line)
    _ok(f"waktu analisis: {time.perf_counter() - t:.1f} s")
    if a.verdict != VERDICT_IDENTIFIED or [c.copy.seq for c in a.accused] != [13]:
        failures.append("foto salinan #13 tidak teratribusi ke salinan #13")

    # 4 --------------------------------------------------------------------------------
    _say("4/6", "Salinan #7 dibuka di komputer di luar jaringan satuan")
    from tapak.canary_dns.server import CanaryDNSServer, simulate_open
    from tapak.service import canary_alerts

    copy7 = (out.folder / "salinan" / m.copies[6].file).read_bytes()
    server = CanaryDNSServer(domain, settings.canary_db, host="127.0.0.1", port=0,
                             allowlist=settings.canary_allowlist)
    server.start()
    try:
        t = time.perf_counter()
        simulate_open(copy7, "pdf", ("127.0.0.1", server.port), domain=domain)
        alerts = []
        while time.perf_counter() - t < 5.0:
            alerts = [x for x in canary_alerts(settings, m) if x["seq"] == 7]
            if alerts:
                break
            time.sleep(0.05)
        dt = time.perf_counter() - t
    finally:
        server.stop()
    if alerts:
        x = alerts[0]
        _ok(f"PERINGATAN KANARI: nama kanari salinan #{x['seq']} (penerima {x['recipient_id']}) "
            f"di-resolve {x['time']} oleh resolver {x['src_ip']}; tercatat {dt:.2f} s setelah berkas dibuka")
        _ok("(kueri DNS membuktikan nama itu dicari, bukan siapa pembukanya; alamat adalah resolver, belum tentu komputer pembuka)")
        _ok("(di dalam jaringan satuan, DNS internal menjawab zona kanari secara lokal sehingga tidak ada peringatan)")
    else:
        failures.append("kanari salinan #7 tidak tercatat dalam 5 detik")

    # 5 --------------------------------------------------------------------------------
    _say("5/6", "Pihak ketiga memverifikasi registri hanya dengan kunci publik")
    from tapak.registry.verify import verify_registry

    pub = settings.public_key_path.read_text().strip()
    rep = verify_registry(settings.registry_path, pub)
    _ok(f"{'UTUH' if rep.ok else 'RUSAK'}: {rep.entries} entri, tanda tangan sah: {rep.entries - rep.unsigned}")
    if not rep.ok:
        failures.append("registri asli gagal diverifikasi")
    tampered = workdir / "registri_diubah.db"
    shutil.copy2(settings.registry_path, tampered)
    con = sqlite3.connect(tampered)
    triggers = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
    for name in triggers:
        con.execute(f'DROP TRIGGER "{name}"')
    con.execute("UPDATE entries SET payload = replace(payload, 'R013', 'R014') WHERE kind = 'copy' "
                "AND payload LIKE '%R013%'")
    con.commit()
    con.close()
    rep2 = verify_registry(tampered, pub)
    first = rep2.problems[0] if rep2.problems else None
    _ok(f"salinan registri yang diubah (R013 diganti R014): {'UTUH' if rep2.ok else 'RUSAK'}"
        + (f"; masalah pertama: {first}" if first else ""))
    if rep2.ok:
        failures.append("perubahan registri tidak terdeteksi")

    # 6 --------------------------------------------------------------------------------
    _say("6/6", "Menulis berita acara")
    report = workdir / "berita_acara_salinan13.pdf"
    write_report(outcome, report, case_number="DEMO-TAPAK-001", examiner_name="Mayor Chk Pemeriksa Fiktif",
                 examiner_rank="Mayor / NRP 99990003")
    _ok(f"{report} ({report.stat().st_size // 1024} KB)")

    total = time.perf_counter() - t0
    print(f"\nSelesai dalam {total:.0f} detik. Folder demo: {workdir}", flush=True)
    if failures:
        print("GAGAL: " + "; ".join(failures), flush=True)
        return 1
    print("Semua hasil sesuai harapan.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_demo(ROOT / "out" / "demo"))
