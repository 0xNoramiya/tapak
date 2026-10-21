"""Command line interface: tapak issue | trace | simulate | verify | demo."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from tapak.keys import load_code_secret


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
    for lvl, b in rep.bound_check.items():
        print(f"Uji batas: target {b['target']:g}, empiris {b['empirical']:.2e} "
              f"dari {int(b['innocent_evaluations'])} skor inosen")
    print(f"Waktu: {dt:.1f} s")
    if args.json:
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2), encoding="utf-8")
    worst_fa = max(r.false_accusation_trials for r in rep.results)
    worst_det = min(r.detection_rate for r in rep.results)
    return 0 if worst_fa == 0 and worst_det > 0.99 else 1


def _cmd_issue(args: argparse.Namespace) -> int:
    from tapak.marker.issue import IssueSettings, issue, read_recipients
    from tapak.marker.pdf_shift import ShiftSettings

    secret = load_code_secret(args.secret, create=True)
    recipients = read_recipients(Path(args.recipients))
    settings = IssueSettings(c=args.c, eps=args.eps, n_max=args.n_max, constant=args.constant,
                             shift=ShiftSettings(word_mm=args.shift_mm, row_mm=args.shift_mm),
                             workers=args.workers)
    m = issue(Path(args.pdf), recipients, Path(args.out), secret, settings, issuer=args.issuer)
    p = m.tardos_params
    print(f"Dokumen: {m.doc_name} (SHA-256 {m.doc_hash[:16]}...)")
    print(f"Kode Tardos: N={p.n_max}, c={p.c}, eps={p.eps:g}, m={p.length}; ambang penuh Z={m.threshold_full:.1f}")
    for ch, s in m.plan_summary.items():
        print(f"  kanal {ch:<10} {s['slots']:>4} slot, {s['bits']:>5} bit, {s['positions']:>5} posisi kode")
    print(f"Gerbang visual: lulus (selisih maks {m.gate['max_diff']})")
    print(f"{len(m.copies)} salinan ditulis ke {args.out} dalam {m.elapsed_s:.2f} s")
    return 0


def _print_attribution(result, as_json: str | None) -> None:
    for line in result.summary_lines():
        print(line)
    if as_json:
        Path(as_json).write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str),
                                 encoding="utf-8")


def _cmd_trace(args: argparse.Namespace) -> int:
    from tapak.decoder.trace import load_context, trace_file
    from tapak.marker.issue import IssueManifest

    secret = load_code_secret(args.secret)
    manifest = IssueManifest.from_json(Path(args.manifest).read_text(encoding="utf-8"))
    ctx = load_context(Path(args.master).read_bytes(), manifest, secret)
    result, obs = trace_file(Path(args.evidence), ctx)
    for sb in obs:
        print(f"Kanal {sb.channel:<10} {len(sb):>5} observasi  {sb.meta}")
    _print_attribution(result, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for all subcommands."""
    ap = argparse.ArgumentParser(prog="tapak", description="TAPAK: atribusi kebocoran dokumen rahasia")
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

    i = sub.add_parser("issue", help="terbitkan salinan bertanda")
    i.add_argument("pdf")
    i.add_argument("recipients")
    i.add_argument("-o", "--out", default="out/salinan")
    i.add_argument("--c", type=int, default=3)
    i.add_argument("--eps", type=float, default=1e-6)
    i.add_argument("--n-max", type=int, default=None)
    i.add_argument("--constant", choices=["skoric", "tardos"], default="skoric")
    i.add_argument("--shift-mm", type=float, default=0.05)
    i.add_argument("--workers", type=int, default=None)
    i.add_argument("--issuer", default="operator")
    i.add_argument("--secret", default=None, help="berkas rahasia kode (bawaan keys/code_secret.key)")
    i.set_defaults(func=_cmd_issue)

    t = sub.add_parser("trace", help="lacak sumber kebocoran")
    t.add_argument("evidence", help="berkas bukti: PDF, teks, atau foto")
    t.add_argument("--master", required=True, help="PDF induk (tanpa tanda)")
    t.add_argument("--manifest", required=True, help="manifest penerbitan")
    t.add_argument("--secret", default=None)
    t.add_argument("--json", default=None)
    t.set_defaults(func=_cmd_trace)
    return ap


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"galat: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
