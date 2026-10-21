"""Command line interface.

    tapak keys init                      create the code secret and the registry signing key
    tapak issue DOC.pdf|DOC.docx RECIPIENTS.csv
    tapak semantic suggest DOC.pdf -o varian.json   /   tapak semantic approve varian.json --all
    tapak trace EVIDENCE --doc <doc>     (or --master/--manifest for a loose issuance)
    tapak docs                           list issued documents
    tapak verify                         verify the registry with the public key only
    tapak registry sign | export-merkle
    tapak simulate                       Tardos collusion simulation
    tapak canary-dns | photos | web | demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _settings(args: argparse.Namespace):
    if getattr(args, "data", None):
        os.environ["TAPAK_DATA"] = args.data
    if getattr(args, "keys", None):
        os.environ["TAPAK_KEY_DIR"] = args.keys
    from tapak.config import load_settings

    return load_settings()


# --- simulate ----------------------------------------------------------------------------


def _cmd_simulate(args: argparse.Namespace) -> int:
    from tapak.tardos.params import TardosParams
    from tapak.tardos.simulate import parameter_table, run_simulation

    if args.table:
        print(f"{'N':>4} {'c':>2} {'eps1':>9} {'m (2pi^2)':>10} {'m (100)':>8} {'Z Chernoff':>11} "
              f"{'Z Gauss':>8} {'E[skor koalisi]':>16}")
        for r in parameter_table(eps=args.eps):
            print(f"{r.n:>4} {r.c:>2} {r.eps1:>9.1e} {r.m_skoric:>10} {r.m_tardos:>8} {r.z_chernoff:>11.1f} "
                  f"{r.z_gaussian:>8.1f} {r.expected_top_colluder:>16.1f}")
        return 0
    params = TardosParams(c=args.c, eps=args.eps, n_max=args.n, constant=args.constant)
    strategies = args.strategies.split(",") if args.strategies else None
    t0 = time.perf_counter()
    rep = run_simulation(params, n_users=args.n, coalition=args.coalition, trials=args.trials,
                         strategies=strategies, seed=args.seed, ber=args.ber, erasure=args.erasure)
    dt = time.perf_counter() - t0
    print(f"Simulasi Tardos: N={args.n}, c={params.c}, eps={params.eps:g} (eps1={params.eps1:.1e}), "
          f"m={params.length}, konstanta={params.constant}, koalisi={rep.coalition}, "
          f"percobaan={args.trials}, BER={args.ber}, hapus={args.erasure}")
    print(f"{'strategi':<11} {'tuduhan salah':>14} {'deteksi':>9} {'semua tertangkap':>17} "
          f"{'Z rata2':>8} {'skor koalisi maks':>18} {'maks inosen/Z':>14}")
    for r in rep.results:
        print(f"{r.strategy:<11} {r.false_accusation_trials:>6} ({r.false_accusation_rate:6.4f}) "
              f"{r.detection_rate:>9.4f} {r.all_caught_rate:>17.4f} {r.mean_threshold:>8.1f} "
              f"{r.mean_top_colluder_score:>18.1f} {r.max_innocent_over_threshold:>14.3f}")
    for b in rep.bound_check.values():
        print(f"Uji batas: target {b['target']:g}, empiris {b['empirical']:.2e} "
              f"dari {int(b['innocent_evaluations'])} skor inosen")
    print(f"Waktu: {dt:.1f} s")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2), encoding="utf-8")
    worst_fa = max(r.false_accusation_trials for r in rep.results)
    worst_det = min(r.detection_rate for r in rep.results)
    return 0 if worst_fa == 0 and worst_det > 0.99 else 1


# --- keys ---------------------------------------------------------------------------------


def _cmd_keys_init(args: argparse.Namespace) -> int:
    from tapak.service import ensure_keys

    s = _settings(args)
    keys = ensure_keys(s, create_signing_key=not args.no_signing_key)
    print(f"Rahasia kode   : {s.code_secret_path}")
    if keys.signer is not None:
        print(f"Kunci tanda tangan registri: {s.signing_key_path} (simpan terpisah, idealnya di eselon atas)")
    print(f"Kunci publik   : {s.public_key_path if keys.public_key_hex else '(belum ada)'}")
    if keys.public_key_hex:
        print(f"                 {keys.public_key_hex}")
    return 0


# --- issue ----------------------------------------------------------------------------------


def _issue_settings(args: argparse.Namespace):
    from tapak.marker.issue import IssueSettings
    from tapak.marker.pdf_shift import ShiftSettings

    return IssueSettings(c=args.c, eps=args.eps, n_max=args.n_max, constant=args.constant,
                         shift=ShiftSettings(word_mm=args.shift_mm, row_mm=args.shift_mm),
                         workers=args.workers, canary_domain=args.canary_domain or None)


def _cmd_issue(args: argparse.Namespace) -> int:
    from tapak.marker.issue import IssueSettings, SemanticSelection, read_recipients
    from tapak.service import ensure_keys, issue_document

    s = _settings(args)
    if args.canary_domain is None:
        args.canary_domain = s.canary_domain
    keys = ensure_keys(s, create_signing_key=not args.sign_later)
    if args.sign_later:
        keys.signer = None
    recipients = read_recipients(Path(args.recipients))
    issue_settings: IssueSettings = _issue_settings(args)
    semantic = None
    if args.semantic:
        semantic = SemanticSelection.from_dict(json.loads(Path(args.semantic).read_text(encoding="utf-8")))
    out = issue_document(s, Path(args.doc), recipients, issue_settings, args.issuer, keys,
                         record=not args.no_registry, semantic=semantic)
    m = out.manifest
    p = m.tardos_params
    print(f"Dokumen: {m.doc_name} (SHA-256 {m.doc_hash[:16]}...)")
    print(f"Kode Tardos: N={p.n_max}, c={p.c}, eps={p.eps:g}, m={p.length}; ambang penuh Z={m.threshold_full:.1f}")
    for ch, info in m.plan_summary.items():
        print(f"  kanal {ch:<10} {info['slots']:>5} slot, {info['bits']:>5} bit, {info['positions']:>5} posisi kode")
    if m.canary_domain:
        print(f"  kanal canary     satu subdomain per salinan di bawah {m.canary_domain}")
    print(f"Gerbang visual: {'lulus' if m.gate.get('passed') else 'GAGAL'} (selisih maks {m.gate.get('max_diff')})")
    print(f"{len(m.copies)} salinan ditulis ke {out.folder / 'salinan'} dalam {m.elapsed_s:.2f} s")
    if not args.no_registry:
        state = "ditandatangani" if out.signed else "BELUM ditandatangani (jalankan: tapak registry sign)"
        print(f"Registri: {out.registry_entries} entri baru, {state} ({s.registry_path})")
    if args.out:
        import shutil

        Path(args.out).mkdir(parents=True, exist_ok=True)
        for c in m.copies:
            shutil.copy2(out.folder / "salinan" / c.file, Path(args.out) / c.file)
        print(f"Salinan juga disalin ke {args.out}")
    return 0


# --- semantic --------------------------------------------------------------------------------


def _cmd_semantic_suggest(args: argparse.Namespace) -> int:
    from tapak.llm.provider import get_provider
    from tapak.marker.issue import SemanticSelection
    from tapak.marker.master import load_master
    from tapak.marker.semantic import find_candidate_units, generate_variant_set

    s = _settings(args)
    master = load_master(Path(args.doc).read_bytes())
    kwargs = {}
    if args.llm == "llamacpp":
        kwargs = {"model_path": s.llm_model_path or None, "server_url": s.llm_server_url}
    provider = get_provider(args.llm, **kwargs)
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, provider) for u in units]
    sel = SemanticSelection(units, sets)
    Path(args.out).write_text(json.dumps(sel.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    for u, vs in zip(units, sets):
        print(f"{u.unit_id} (hal. {u.page + 1}): {u.text}")
        for i, v in enumerate(vs.variants[1:], start=1):
            print(f"   v{i} [{vs.status[i]}] {v}")
    print(f"Ditulis ke {args.out}. Tinjau setiap varian, lalu: tapak semantic approve {args.out} --all")
    return 0


def _cmd_semantic_approve(args: argparse.Namespace) -> int:
    from tapak.marker.issue import SemanticSelection
    from tapak.marker.semantic import STATUS_APPROVED, STATUS_REJECTED

    path = Path(args.file)
    sel = SemanticSelection.from_dict(json.loads(path.read_text(encoding="utf-8")))
    changed = 0
    for vs in sel.sets:
        if args.unit and vs.unit_id != args.unit:
            continue
        for i in range(1, len(vs.variants)):
            if args.all or (args.variant is not None and i == args.variant):
                vs.set_status(i, STATUS_REJECTED if args.reject else STATUS_APPROVED)
                changed += 1
    path.write_text(json.dumps(sel.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    pending = sum(len(vs.pending()) for vs in sel.sets)
    print(f"{changed} varian diperbarui; {pending} masih menunggu persetujuan")
    return 0


# --- trace ------------------------------------------------------------------------------------


def _print_attribution(result, obs, notes_extra: list[str] | None = None) -> None:
    for sb in obs:
        meta = {k: v for k, v in sb.meta.items() if k not in ("reads",)}
        print(f"Kanal {sb.channel:<10} {len(sb):>5} observasi  {meta}")
    for line in result.summary_lines():
        print(line)
    for n in notes_extra or []:
        print(f"  {n}")


def _cmd_trace(args: argparse.Namespace) -> int:
    from tapak.service import trace_evidence, write_report

    s = _settings(args)
    evidence = Path(args.evidence)
    if args.master or args.manifest:
        if not (args.master and args.manifest):
            raise ValueError("--master dan --manifest harus diberikan bersama")
        from tapak.decoder.trace import load_context, trace_file
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest

        manifest = IssueManifest.from_json(Path(args.manifest).read_text(encoding="utf-8"))
        ctx = load_context(Path(args.master).read_bytes(), manifest,
                           load_code_secret(Path(args.secret) if args.secret else s.code_secret_path),
                           folder=Path(args.manifest).parent)
        result, obs = trace_file(evidence, ctx)
        _print_attribution(result, obs)
        if args.json:
            Path(args.json).write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str),
                                       encoding="utf-8")
        return 0
    doc = args.doc
    if doc is None:
        from tapak.service import list_workspaces

        docs = list_workspaces(s)
        if len(docs) != 1:
            raise ValueError("pilih dokumen dengan --doc (lihat: tapak docs)")
        doc = docs[0].doc_hash
    outcome = trace_evidence(s, doc, evidence.name, evidence.read_bytes())
    reg = outcome.registry
    extra = [f"Registri: rantai {'terverifikasi' if reg.chain_ok else 'TIDAK terverifikasi' if reg.chain_ok is False else 'belum diverifikasi'}"
             f" ({reg.entries} entri), {reg.copies_confirmed}/{reg.copies_total} salinan cocok"]
    for a in outcome.canary:
        extra.append(f"Kueri kanari: nama salinan #{a['seq']} ({a['recipient_id']}) di-resolve {a['time']} "
                     f"oleh resolver {a['src_ip']}")
    _print_attribution(outcome.attribution, outcome.observations, extra)
    if args.report:
        write_report(outcome, Path(args.report), case_number=args.nomor_perkara or "",
                     examiner_name=args.pemeriksa or "", examiner_rank=args.pangkat or "")
        print(f"Berita acara ditulis ke {args.report}")
    if args.json:
        Path(args.json).write_text(json.dumps(outcome.attribution.to_dict(), indent=2, ensure_ascii=False,
                                              default=str), encoding="utf-8")
    return 0


def _cmd_docs(args: argparse.Namespace) -> int:
    from tapak.service import list_workspaces

    s = _settings(args)
    docs = list_workspaces(s)
    if not docs:
        print(f"Belum ada dokumen yang diterbitkan di {s.workspaces}")
        return 0
    for m in docs:
        print(f"{m.doc_hash[:16]}  {m.issued_at}  {len(m.copies):>3} salinan  {m.doc_name}")
    return 0


# --- registry -----------------------------------------------------------------------------------


def _cmd_verify(args: argparse.Namespace) -> int:
    from tapak.registry.verify import main as verify_main

    s = _settings(args)
    argv = [str(args.registry or s.registry_path), "--public-key", str(args.public_key or s.public_key_path)]
    if args.merkle_dir:
        argv += ["--merkle-dir", args.merkle_dir]
    return verify_main(argv)


def _cmd_registry_sign(args: argparse.Namespace) -> int:
    from tapak.registry.chain import Registry, sign_pending
    from tapak.registry.signing import load_signer

    s = _settings(args)
    signer = load_signer(Path(args.key) if args.key else s.signing_key_path)
    with Registry.open(Path(args.registry) if args.registry else s.registry_path) as reg:
        pending = reg.pending() if hasattr(reg, "pending") else []
        for e in pending:
            print(f"  menunggu: entri #{e.seq} ({e.kind}) {e.created_at}")
        n = sign_pending(reg, signer, up_to=args.up_to)
    print(f"{n} entri ditandatangani")
    return 0


def _cmd_registry_merkle(args: argparse.Namespace) -> int:
    from tapak.registry.merkle import export_daily_roots

    s = _settings(args)
    out = Path(args.out) if args.out else s.data_dir / "merkle"
    files = export_daily_roots(Path(args.registry) if args.registry else s.registry_path, out,
                               include_partial=True)
    for f in files or []:
        print(f"ditulis: {f}")
    return 0


# --- passthroughs -----------------------------------------------------------------------------------


def _passthrough(module: str):
    def run(args: argparse.Namespace) -> int:
        import importlib

        return int(importlib.import_module(module).main(args.rest) or 0)

    return run


def _cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    _settings(args)
    uvicorn.run("tapak.web.app:app", host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from tapak.demo import run_demo

    return run_demo(Path(args.workdir), keep=args.keep)


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for all subcommands."""
    ap = argparse.ArgumentParser(prog="tapak", description="TAPAK: atribusi kebocoran dokumen rahasia")
    ap.add_argument("--data", default=None, help="folder data (bawaan: data/ atau $TAPAK_DATA)")
    ap.add_argument("--keys", default=None, help="folder kunci (bawaan: keys/ atau $TAPAK_KEY_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="simulasi serangan kolusi terhadap kode Tardos")
    s.add_argument("--n", type=int, default=100, help="jumlah penerima")
    s.add_argument("--c", type=int, default=3, help="ukuran koalisi rancangan")
    s.add_argument("--eps", type=float, default=1e-6, help="peluang tuduhan salah total")
    s.add_argument("--trials", type=int, default=1000)
    s.add_argument("--coalition", type=int, default=None, help="ukuran koalisi uji (bawaan: c)")
    s.add_argument("--constant", choices=["skoric", "tardos"], default="skoric")
    s.add_argument("--strategies", default=None, help="daftar dipisah koma")
    s.add_argument("--ber", type=float, default=0.0, help="laju galat bit kanal")
    s.add_argument("--erasure", type=float, default=0.0, help="laju posisi terhapus")
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--table", action="store_true", help="cetak tabel parameter")
    s.add_argument("--json", default=None)
    s.set_defaults(func=_cmd_simulate)

    k = sub.add_parser("keys", help="kelola kunci")
    ksub = k.add_subparsers(dest="keys_cmd", required=True)
    ki = ksub.add_parser("init", help="buat rahasia kode dan kunci tanda tangan registri")
    ki.add_argument("--no-signing-key", action="store_true", help="jangan buat kunci tanda tangan di sini")
    ki.set_defaults(func=_cmd_keys_init)

    i = sub.add_parser("issue", help="terbitkan salinan bertanda")
    i.add_argument("doc", help="dokumen induk (PDF atau DOCX)")
    i.add_argument("recipients", help="CSV penerima (recipient_id, nama, jabatan, satuan)")
    i.add_argument("-o", "--out", default=None, help="salin juga salinan ke folder ini")
    i.add_argument("--c", type=int, default=3)
    i.add_argument("--eps", type=float, default=1e-6)
    i.add_argument("--n-max", type=int, default=None)
    i.add_argument("--constant", choices=["skoric", "tardos"], default="skoric")
    i.add_argument("--shift-mm", type=float, default=0.05)
    i.add_argument("--workers", type=int, default=None)
    i.add_argument("--issuer", default="operator")
    i.add_argument("--canary-domain", default=None, help="domain kanari (kosongkan untuk menonaktifkan)")
    i.add_argument("--semantic", default=None, help="varian.json yang sudah disetujui")
    i.add_argument("--no-registry", action="store_true")
    i.add_argument("--sign-later", action="store_true", help="catat tanpa tanda tangan (ditandatangani eselon atas)")
    i.set_defaults(func=_cmd_issue)

    sm = sub.add_parser("semantic", help="kanal semantik (varian kalimat aman)")
    smsub = sm.add_subparsers(dest="sem_cmd", required=True)
    sg = smsub.add_parser("suggest", help="usulkan kalimat aman dan buat varian dengan LLM lokal")
    sg.add_argument("doc")
    sg.add_argument("-o", "--out", default="varian.json")
    sg.add_argument("--llm", choices=["mock", "llamacpp"], default=os.environ.get("TAPAK_LLM", "mock"))
    sg.set_defaults(func=_cmd_semantic_suggest)
    sa = smsub.add_parser("approve", help="setujui atau tolak varian (keputusan manusia)")
    sa.add_argument("file")
    sa.add_argument("--all", action="store_true")
    sa.add_argument("--unit", default=None)
    sa.add_argument("--variant", type=int, default=None)
    sa.add_argument("--reject", action="store_true")
    sa.set_defaults(func=_cmd_semantic_approve)

    t = sub.add_parser("trace", help="lacak sumber kebocoran")
    t.add_argument("evidence", help="berkas bukti: foto, tangkapan layar, PDF, DOCX, atau teks")
    t.add_argument("--doc", default=None, help="dokumen terbitan (hash atau 16 karakter awal)")
    t.add_argument("--master", default=None, help="PDF induk (mode tanpa folder data)")
    t.add_argument("--manifest", default=None, help="manifest penerbitan (mode tanpa folder data)")
    t.add_argument("--secret", default=None)
    t.add_argument("--report", default=None, help="tulis berita acara PDF ke berkas ini")
    t.add_argument("--nomor-perkara", default=None, help="nomor perkara untuk berita acara")
    t.add_argument("--pemeriksa", default=None, help="nama pemeriksa untuk berita acara")
    t.add_argument("--pangkat", default=None, help="pangkat/NRP pemeriksa untuk berita acara")
    t.add_argument("--json", default=None)
    t.set_defaults(func=_cmd_trace)

    d = sub.add_parser("docs", help="daftar dokumen yang telah diterbitkan")
    d.set_defaults(func=_cmd_docs)

    v = sub.add_parser("verify", help="verifikasi registri hanya dengan kunci publik")
    v.add_argument("--registry", default=None)
    v.add_argument("--public-key", default=None)
    v.add_argument("--merkle-dir", default=None)
    v.set_defaults(func=_cmd_verify)

    r = sub.add_parser("registry", help="operasi registri")
    rsub = r.add_subparsers(dest="reg_cmd", required=True)
    rs = rsub.add_parser("sign", help="tandatangani entri yang belum ditandatangani")
    rs.add_argument("--key", default=None)
    rs.add_argument("--registry", default=None)
    rs.add_argument("--up-to", type=int, default=None, help="tandatangani sampai entri nomor ini (sudah ditinjau)")
    rs.set_defaults(func=_cmd_registry_sign)
    rm = rsub.add_parser("export-merkle", help="ekspor akar Merkle harian")
    rm.add_argument("--out", default=None)
    rm.add_argument("--registry", default=None)
    rm.set_defaults(func=_cmd_registry_merkle)

    for name, module, desc in (("canary-dns", "tapak.canary_dns.__main__", "jalankan pendengar DNS kanari"),
                               ("photos", "tapak.photos", "buat set uji foto sintetis")):
        p = sub.add_parser(name, help=desc, add_help=False)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=_passthrough(module))

    w = sub.add_parser("web", help="jalankan antarmuka web")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    w.set_defaults(func=_cmd_web)

    dm = sub.add_parser("demo", help="skenario demo 90 detik (non-interaktif)")
    dm.add_argument("--workdir", default="out/demo")
    dm.add_argument("--keep", action="store_true", help="jangan hapus folder demo sebelumnya")
    dm.set_defaults(func=_cmd_demo)
    return ap


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"galat: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
