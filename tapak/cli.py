"""Command line interface.

    tapak keys init                      create the code secret and the registry signing key
    tapak issue DOC.pdf|DOC.docx RECIPIENTS.csv
    tapak semantic suggest DOC.pdf -o varian.json   /   tapak semantic approve varian.json --all
    tapak leksikal scan DOC.pdf -o leksikal.json   /   review | show   (word choice, opt-in)
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
    from tapak.tardos.attacks import STRATEGY_LABELS

    print(f"{'strategi':<12} {'tuduhan salah':>14} {'deteksi':>9} {'semua tertangkap':>17} "
          f"{'Z rata2':>8} {'skor koalisi maks':>18} {'maks inosen/Z':>14}")
    for r in rep.results:
        print(f"{STRATEGY_LABELS.get(r.strategy, r.strategy):<12} {r.false_accusation_trials:>6} ({r.false_accusation_rate:6.4f}) "
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
    elif keys.public_key_hex:
        print("Kunci tanda tangan registri: dipegang di tempat lain (hanya kunci publik ada di sini); "
              "entri dicatat tanpa tanda tangan sampai pemegang kunci menjalankan tapak registry sign")
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
    # The signing key is never created here (only by `tapak keys init`): without it, rows are
    # recorded unsigned and the key holder signs them later.
    keys = ensure_keys(s, create_signing_key=False)
    if args.sign_later:
        keys.signer = None
    recipients = read_recipients(Path(args.recipients))
    issue_settings: IssueSettings = _issue_settings(args)
    semantic = None
    if args.semantic:
        semantic = SemanticSelection.from_dict(json.loads(Path(args.semantic).read_text(encoding="utf-8")))
    lexical = _read_lexical(Path(args.leksikal)) if args.leksikal else None
    out = issue_document(s, Path(args.doc), recipients, issue_settings, args.issuer, keys,
                         record=not args.no_registry, semantic=semantic, lexical=lexical)
    m = out.manifest
    p = m.tardos_params
    is_docx = m.gate.get("note") == "DOCX"
    print(f"Dokumen: {m.doc_name} (SHA-256 {m.doc_hash[:16]}...)")
    print(f"Kode Tardos: N={p.n_max}, c={p.c}, eps={p.eps:g}, m={p.length}; ambang penuh Z={m.threshold_full:.1f}")
    for ch, info in m.plan_summary.items():
        print(f"  kanal {ch:<10} {info['slots']:>5} slot, {info['bits']:>5} bit, {info['positions']:>5} posisi kode")
    if m.canary_domain:
        print(f"  kanal canary     satu subdomain per salinan di bawah {m.canary_domain}")
    if m.lexical_digest:  # only documents that opted into word choice
        from tapak.marker.lexical import capacity_verdict

        # Distinct band positions (issuance refuses a band too small for both channels).
        lex_bits = m.plan_summary.get("lexical", {}).get("positions", 0)
        sem_bits = m.plan_summary.get("semantic", {}).get("positions", 0)
        print(f"Tahan ketik ulang: {lex_bits} bit pilihan kata + {sem_bits} bit semantik, posisi pita bias "
              f"0,3 sampai 0,7. {capacity_verdict(lex_bits + sem_bits, lexical.body_words, lex_bits)}")
    if is_docx:
        print("Gerbang visual: tidak berlaku untuk DOCX (Word yang menata ulang dokumen)")
    else:
        print(f"Gerbang visual: {'lulus' if m.gate.get('passed') else 'GAGAL'} (selisih maks {m.gate.get('max_diff')})")
    print(f"{len(m.copies)} salinan ditulis ke {out.folder / 'salinan'} dalam {m.elapsed_s:.2f} s")
    if not args.no_registry:
        state = ("ditandatangani" if out.signed else
                 "BELUM ditandatangani (kunci tanda tangan tidak ada di sini; pemegang kunci menjalankan: "
                 "tapak registry sign)")
        print(f"Registri: {out.registry_entries} entri baru, {state} ({s.registry_path})")
    for w in out.warnings:
        print(f"PERINGATAN: {w}")
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
        if vs.dropped:
            from collections import Counter

            why = Counter(reason.split(":")[0] for _, reason in vs.dropped)
            print(f"   {len(vs.dropped)} kandidat dibuang: " + "; ".join(f"{r} ({k})" for r, k in why.most_common()))
        elif len(vs.variants) == 1:
            print("   model tidak mengusulkan kandidat yang berbeda dari kalimat asli")
    print(f"Ditulis ke {args.out}. Baca setiap varian, lalu putuskan satu per satu: "
          f"tapak semantic approve {args.out} --unit u0 --variant 1 (tambahkan --reject untuk menolak)")
    return 0


def _cmd_semantic_approve(args: argparse.Namespace) -> int:
    from tapak.marker.issue import SemanticSelection
    from tapak.marker.semantic import STATUS_APPROVED, STATUS_REJECTED, bulk_approval_allowed

    path = Path(args.file)
    sel = SemanticSelection.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if args.all and not args.reject:
        # Model judges let meaning changes through, so model variants are approved one by one.
        model_sets = [vs.unit_id for vs in sel.sets
                      if (not args.unit or vs.unit_id == args.unit) and not bulk_approval_allowed(vs)]
        if model_sets:
            print("Galat: varian dari model bahasa harus disetujui satu per satu (--unit ... --variant N), "
                  "bukan dengan --all. Kalimat: " + ", ".join(model_sets), file=sys.stderr)
            return 2
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


# --- leksikal (word choice) -------------------------------------------------------------------


def _read_lexical(path: Path):
    """A lexical selection file; ValueError (Indonesian) if it is not one."""
    from tapak.marker.lexical import LexicalSelection

    try:
        return LexicalSelection.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path}: bukan berkas pilihan kata TAPAK yang sah") from exc


def _lexical_summary(sel) -> list[str]:
    """Counts and capacity of a selection; refusals by category only (no document words)."""
    from tapak.marker.lexical import LONE_LEAKER_BITS, capacity_verdict

    c = sel.counts()
    lines = [f"{len(sel.points)} titik dari {sel.body_words} kata isi: {c['disetujui']} disetujui, "
             f"{c['ditolak']} ditolak, {c['menunggu']} menunggu",
             f"Bit pilihan kata: {sel.bits} disetujui, {sel.candidate_bits} bila semua yang belum ditolak disetujui. "
             f"TAPAK menyatakan cukup untuk satu pembocor dari teks ketikan ulang mulai {LONE_LEAKER_BITS} bit, "
             "termasuk bit semantik bila ada.",
             f"Perkiraan: {capacity_verdict(sel.candidate_bits, sel.body_words, sel.candidate_bits)}"]
    repeated = sum(1 for p in sel.points if p.repeated)
    if repeated:
        lines.append(f"{repeated} titik berkonteks berulang (frasa dan kata di sekitarnya juga ada di bagian lain "
                     "dokumen). Bila pembocor menukar urutan kalimat, titik ini dapat terbaca di tempat lain: skor "
                     "pembocor turun, tetapi salinan lain tidak pernah tertuduh karenanya. Tolak titik ini bila perlu.")
    if sel.refused:
        lines.append("Kandidat yang ditolak pemeriksaan otomatis (per kategori): "
                     + ", ".join(f"{k} {v}" for k, v in sorted(sel.refused.items())))
    return lines


def _cmd_lexical_scan(args: argparse.Namespace) -> int:
    from tapak.marker.lexical import load_lexicon, scan_candidates
    from tapak.marker.master import load_master

    data = Path(args.doc).read_bytes()
    if b"%PDF-" not in data[:1024]:
        raise ValueError("kanal pilihan kata hanya tersedia untuk dokumen induk PDF")
    lexicon = load_lexicon(args.leksikon)
    sel = scan_candidates(load_master(data), lexicon, tiers=args.tingkat)
    Path(args.out).write_text(sel.to_json(), encoding="utf-8")
    print(f"Leksikon {lexicon.name} versi {lexicon.version}"
          + (" (DRAF: belum disahkan peninjau bahasa Tata Naskah Dinas)" if lexicon.is_draft else ""))
    for line in _lexical_summary(sel):
        print(line)
    print(f"Ditulis ke {args.out}. Berkas ini memuat teks dokumen: simpan bersama dokumen induk. "
          f"Tinjau setiap titik: tapak leksikal show {args.out}, lalu tapak leksikal review {args.out}")
    return 0


def _print_point(sel, point, lexicon) -> None:
    """One point for the reviewer: its whole sentence (across rows) with the phrase in brackets."""
    try:
        note = lexicon.rule(point.rule_id).note
    except KeyError:
        note = ""
    repeated = ", konteks berulang" if point.repeated else ""
    print(f"{point.point_id:>4} [{point.status}] aturan {point.rule_id}, hal. {point.page + 1}, {point.bits} bit"
          f"{repeated}")
    print(f"      {point.context}")
    print("      bentuk: " + " | ".join(point.forms) + (f"  ({note})" if note else ""))


def _cmd_lexical_show(args: argparse.Namespace) -> int:
    from tapak.marker.lexical import load_lexicon

    sel = _read_lexical(Path(args.file))
    lexicon = load_lexicon(sel.lexicon)
    for point in sel.points:
        if args.status and point.status != args.status:
            continue
        _print_point(sel, point, lexicon)
    for line in _lexical_summary(sel):
        print(line)
    return 0


def _cmd_lexical_review(args: argparse.Namespace) -> int:
    from tapak.marker.lexical import load_lexicon
    from tapak.marker.semantic import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED

    path = Path(args.file)
    sel = _read_lexical(path)
    decision = STATUS_APPROVED if args.setujui else STATUS_REJECTED if args.tolak else \
        STATUS_PENDING if args.tunda else None
    targets: list[str] = []
    if args.titik:
        wanted = [t.strip() for t in args.titik.split(",") if t.strip()]
        known = {p.point_id for p in sel.points}
        unknown = [t for t in wanted if t not in known]
        if unknown:
            raise ValueError("titik tidak dikenal: " + ", ".join(unknown))
        targets += wanted
    bulk = bool(args.aturan or args.semua)
    if args.aturan:
        rules = {r.strip() for r in args.aturan.split(",") if r.strip()}
        known_rules = {p.rule_id for p in sel.points}
        if not rules <= known_rules:
            raise ValueError("aturan tanpa titik di berkas ini: " + ", ".join(sorted(rules - known_rules)))
        targets += [p.point_id for p in sel.points if p.rule_id in rules]
    if args.semua:
        targets += [p.point_id for p in sel.points]
    if args.interaktif:
        if targets or decision:
            raise ValueError("--interaktif tidak digabung dengan --titik, --aturan, --semua, atau keputusan")
        return _review_interactive(sel, path, load_lexicon(sel.lexicon))
    if not targets:
        raise ValueError("pilih titik dengan --titik, --aturan, --semua, atau --interaktif")
    if decision is None:
        raise ValueError("pilih keputusan: --setujui, --tolak, atau --tunda")
    if bulk and decision == STATUS_APPROVED and not args.ya:
        raise ValueError(f"persetujuan sekaligus untuk {len(set(targets))} titik memerlukan --ya; tinjau dulu "
                         f"setiap titik dengan tapak leksikal show {path}")
    for point_id in dict.fromkeys(targets):
        sel.set_status(point_id, decision)
    path.write_text(sel.to_json(), encoding="utf-8")
    print(f"{len(set(targets))} titik diperbarui menjadi {decision}")
    for line in _lexical_summary(sel)[:2]:
        print(line)
    return 0


def _review_interactive(sel, path: Path, lexicon) -> int:
    """Ask for a decision on every point still awaiting review; saves after each answer."""
    from tapak.marker.semantic import STATUS_APPROVED, STATUS_REJECTED

    todo = sel.pending()
    print(f"{len(todo)} titik menunggu. Jawab s (setujui), t (tolak), l (lewati) atau q (selesai).")
    for point_id in todo:
        _print_point(sel, sel.point(point_id), lexicon)
        while True:
            try:
                answer = input("      keputusan [s/t/l/q]: ").strip().lower()
            except EOFError:
                answer = "q"
            if answer in ("s", "t", "l", "q"):
                break
        if answer == "q":
            break
        if answer in ("s", "t"):
            sel.set_status(point_id, STATUS_APPROVED if answer == "s" else STATUS_REJECTED)
            path.write_text(sel.to_json(), encoding="utf-8")
    for line in _lexical_summary(sel)[:2]:
        print(line)
    return 0


# --- trace ------------------------------------------------------------------------------------


def _print_attribution(result, obs, notes_extra: list[str] | None = None) -> None:
    from tapak.decoder.report import SUBCHANNEL_LABELS, channel_observations

    for row in channel_observations(obs):
        label = SUBCHANNEL_LABELS.get(row["channel"], row["channel"])
        noise = f"; {row['noise']}" if row["noise"] not in (None, "-") else ""
        print(f"Kanal {label}: {row['observations']} observasi{noise}")
    for line in result.summary_lines():
        print(line)
    for n in notes_extra or []:
        print(f"  {n}")


def _cmd_trace(args: argparse.Namespace) -> int:
    from tapak.service import trace_evidence, write_report

    s = _settings(args)
    paths = [Path(e) for e in args.evidence]
    evidence = paths[0]
    items = [(p.name, p.read_bytes()) for p in paths]
    if args.trace_no is not None and not (args.master or args.manifest):
        raise ValueError("--pelacakan-ke hanya untuk mode lepas (--master dan --manifest); dengan --doc nomor "
                         "pelacakan diambil dari registri")
    if args.master or args.manifest:
        if not (args.master and args.manifest):
            raise ValueError("--master dan --manifest harus diberikan bersama")
        if args.report:
            raise ValueError("--report memerlukan --doc: berita acara hanya dibuat setelah registri diperiksa")
        from tapak.decoder.trace import load_context, trace_files
        from tapak.keys import load_code_secret
        from tapak.marker.issue import IssueManifest
        from tapak.service import UNLOGGED_TRACE_NOTE
        from tapak.tardos.spending import TraceSpending

        try:
            manifest = IssueManifest.from_json(Path(args.manifest).read_text(encoding="utf-8"))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{args.manifest}: bukan catatan penerbitan (manifest) TAPAK yang sah") from exc
        master = Path(args.master).read_bytes()
        secret = load_code_secret(Path(args.secret) if args.secret else s.code_secret_path)
        if not (master.startswith(b"PK") or b"%PDF-" in master[:1024]):
            raise ValueError(f"{args.master}: dokumen induk harus berkas PDF atau DOCX")
        eps = manifest.tardos_params.eps
        # Repeating a recorded trace with its own share only raises the threshold; without
        # --pelacakan-ke the trace spends all of eps and is not counted anywhere.
        spending = (TraceSpending.unlogged(eps) if args.trace_no is None
                    else TraceSpending.logged(eps, args.trace_no))
        if master.startswith(b"PK"):  # a DOCX master: text-layer channel only
            from tapak.service import _trace_docx

            result, obs, _ = _trace_docx(master, manifest, secret, items, spending)
        else:
            ctx = load_context(master, manifest, secret, folder=Path(args.manifest).parent)
            result, obs = trace_files(items, ctx, spending)
        if args.trace_no is None:
            result.notes.append(UNLOGGED_TRACE_NOTE)
        else:
            result.notes.append(f"mengulang pelacakan ke-{args.trace_no} dengan jatah eps-nya; pengulangan ini tidak "
                                "dicatat di registri dan, dengan bukti yang sama, memberi hasil yang sama")
        _print_attribution(result, obs, ["Mode lepas: registri tidak diperiksa; identitas penerima hanya berasal "
                                         "dari catatan penerbitan yang diberikan"])
        if args.json:
            _write_json(Path(args.json), result)
        return 0
    doc = args.doc
    if doc is None:
        from tapak.service import list_workspaces

        docs = list_workspaces(s)
        if len(docs) != 1:
            raise ValueError("pilih dokumen dengan --doc (lihat: tapak docs)")
        doc = docs[0].doc_hash
    outcome = trace_evidence(s, doc, items[0][0], items[0][1], more=items[1:])
    reg = outcome.registry
    if reg.chain_ok and reg.unsigned:
        state = (f"rantai hash utuh, tetapi {reg.unsigned} dari {reg.entries} entri belum bertanda tangan "
                 "sehingga belum terlindungi dari pemalsuan")
    elif reg.chain_ok:
        state = f"rantai terverifikasi dengan tanda tangan ({reg.entries} entri)"
    else:
        state = f"rantai belum diverifikasi ({reg.entries} entri)"
    extra = [f"Registri: {state}; {reg.copies_confirmed}/{reg.copies_total} salinan cocok"]
    if outcome.trace_entry is not None:
        signed = "bertanda tangan" if outcome.trace_signed else "belum bertanda tangan"
        extra.append(f"Pelacakan ke-{outcome.attribution.threshold.trace_no} dicatat sebelum dekode sebagai entri "
                     f"registri #{outcome.trace_entry} ({signed}); jatah eps semua pelacakan dokumen ini "
                     "berjumlah paling banyak eps")
        extra.append(f"Jangkar entri pelacakan (catat di luar sistem): tapak verify --jangkar "
                     f"{outcome.trace_entry}:{outcome.trace_entry_hash}")
    accused = {c.copy.seq for c in outcome.attribution.accused}
    for a in outcome.canary:
        # As in the berita acara: a copy that is not accused is not identified, not even by number.
        which = f"salinan #{a['seq']} ({a['recipient_id']})" if a["seq"] in accused else \
            "salinan lain (nomor tidak dicantumkan)"
        extra.append(f"Kueri kanari: nama {which} di-resolve {a['time']} oleh resolver {a['src_ip']}")
    _print_attribution(outcome.attribution, outcome.observations, extra)
    if args.report:
        write_report(outcome, Path(args.report), case_number=args.nomor_perkara or "",
                     examiner_name=args.pemeriksa or "", examiner_rank=args.pangkat or "")
        print(f"Berita acara ditulis ke {args.report}")
    if args.json:
        _write_json(Path(args.json), outcome.attribution)
    return 0


def _write_json(path: Path, attribution) -> None:
    """Attribution as JSON; copies that are not accused keep their score but lose their identity."""
    data = attribution.to_dict()
    for c in data["candidates"]:
        # log10_false_accusation is the authoritative bound; the float underflows below 1e-308.
        if c["false_accusation_probability"] < 1e-300:
            c["false_accusation_probability"] = None
        if not c["accused"]:
            c["copy"] = {"seq": None, "copy_id": "", "recipient_id": "", "nama": "", "jabatan": "", "satuan": ""}
    for ch in data["channels"]:
        shown = [s for s in ch["accused_seqs"] if any(c.copy.seq == s for c in attribution.accused)]
        ch["accused_seqs"], ch["accused_hidden"] = shown, len(ch["accused_seqs"]) - len(shown)
        if ch["top_seq"] not in shown:
            ch["top_seq"] = None
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _cmd_canary_allowlist(args: argparse.Namespace) -> int:
    from tapak.service import publish_canary_allowlist

    s = _settings(args)
    n = publish_canary_allowlist(s)
    print(f"Daftar izin kanari ditulis ulang: {n} digest token ke {s.canary_allowlist}")
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
    for anchor in args.jangkar:
        argv += ["--jangkar", anchor]
    return verify_main(argv)


def _cmd_registry_sign(args: argparse.Namespace) -> int:
    from tapak.registry.chain import KIND_LABELS, Registry, sign_pending
    from tapak.registry.signing import load_signer

    s = _settings(args)
    signer = load_signer(Path(args.key) if args.key else s.signing_key_path)
    with Registry.open(Path(args.registry) if args.registry else s.registry_path) as reg:
        pending = reg.pending() if hasattr(reg, "pending") else []
        for e in pending:
            print(f"  menunggu: entri #{e.seq} ({KIND_LABELS.get(e.kind, e.kind)}) {e.created_at}")
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


def _cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    _settings(args)
    uvicorn.run("tapak.web.app:app", host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from tapak.demo import run_demo

    return run_demo(Path(args.workdir), keep=args.keep)


PASSTHROUGH = {"canary-dns": "tapak.canary_dns.__main__", "photos": "tapak.photos"}


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for all subcommands (Indonesian help and errors)."""
    from tapak.registry.signing import IndonesianArgumentParser

    ap = IndonesianArgumentParser(prog="tapak", description="TAPAK: atribusi kebocoran dokumen rahasia")
    ap.add_argument("--data", default=None, help="folder data (bawaan: data/ atau $TAPAK_DATA)")
    ap.add_argument("--keys", default=None, help="folder kunci (bawaan: keys/ atau $TAPAK_KEY_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True, title="perintah", metavar="PERINTAH",
                            parser_class=IndonesianArgumentParser)

    s = sub.add_parser("simulate", help="simulasi serangan kolusi terhadap kode Tardos")
    s.add_argument("--n", type=int, default=100, help="jumlah penerima")
    s.add_argument("--c", type=int, default=3, help="ukuran koalisi rancangan")
    s.add_argument("--eps", type=float, default=1e-6, help="peluang tuduhan salah total")
    s.add_argument("--trials", type=int, default=1000, help="jumlah percobaan per strategi")
    s.add_argument("--coalition", type=int, default=None, help="ukuran koalisi uji (bawaan: c)")
    s.add_argument("--constant", choices=["skoric", "tardos"], default="skoric",
                   help="konstanta panjang kode: skoric (2 pi^2) atau tardos (100)")
    s.add_argument("--strategies", default=None,
                   help="daftar dipisah koma dari: majority (mayoritas), minority (minoritas), random-mix "
                        "(campur acak), coin (lempar koin), all-1, all-0, erase (hapus); bawaan semua")
    s.add_argument("--ber", type=float, default=0.0, help="laju galat bit kanal")
    s.add_argument("--erasure", type=float, default=0.0, help="laju posisi terhapus")
    s.add_argument("--seed", type=int, default=2026, help="benih bilangan acak (hasil dapat diulang)")
    s.add_argument("--table", action="store_true", help="cetak tabel parameter")
    s.add_argument("--json", default=None, help="tulis hasil lengkap ke berkas JSON ini")
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
    i.add_argument("--leksikal", default=None, metavar="BERKAS",
                   help="leksikal.json yang setiap titiknya sudah disetujui atau ditolak (kanal pilihan kata, "
                        "opsional); ditolak bila masih ada titik menunggu atau titik dan bentuknya diubah di luar "
                        "TAPAK (keputusan setuju atau tolak tidak diautentikasi)")
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

    lk = sub.add_parser("leksikal", help="kanal pilihan kata (opsional, setiap titik ditinjau manusia)")
    lksub = lk.add_subparsers(dest="lex_cmd", required=True, title="perintah", metavar="PERINTAH",
                              parser_class=type(ap))
    lscan = lksub.add_parser("scan", help="cari titik pilihan kata yang aman pada PDF induk")
    lscan.add_argument("doc", help="dokumen induk PDF")
    lscan.add_argument("-o", "--out", default="leksikal.json", help="berkas hasil (memuat teks dokumen)")
    lscan.add_argument("--tingkat", choices=["A", "AB"], default="A",
                       help="aturan yang dipakai: A (kata tugas dan frasa baku, bawaan) atau AB (juga kata isi)")
    lscan.add_argument("--leksikon", default="naskah_dinas_v1", help="nama berkas leksikon di tapak/assets/leksikon")
    lscan.set_defaults(func=_cmd_lexical_scan)
    lshow = lksub.add_parser("show", help="tampilkan setiap titik dengan konteks, bentuk, dan statusnya")
    lshow.add_argument("file", help="leksikal.json")
    lshow.add_argument("--status", choices=["menunggu", "disetujui", "ditolak"], default=None,
                       help="hanya titik dengan status ini")
    lshow.set_defaults(func=_cmd_lexical_show)
    lrev = lksub.add_parser("review", help="setujui atau tolak titik (keputusan manusia)")
    lrev.add_argument("file", help="leksikal.json")
    lrev.add_argument("--titik", default=None, metavar="ID", help="id titik, dipisah koma (misalnya l0,l3)")
    lrev.add_argument("--aturan", default=None, metavar="ID",
                      help="semua titik dari aturan ini, dipisah koma (misalnya dan,setiap)")
    lrev.add_argument("--semua", action="store_true", help="semua titik")
    decision = lrev.add_mutually_exclusive_group()
    decision.add_argument("--setujui", action="store_true", help="setujui titik yang dipilih")
    decision.add_argument("--tolak", action="store_true", help="tolak titik yang dipilih")
    decision.add_argument("--tunda", action="store_true", help="kembalikan ke status menunggu")
    lrev.add_argument("--ya", action="store_true",
                      help="konfirmasi persetujuan sekaligus per aturan atau semua titik")
    lrev.add_argument("--interaktif", action="store_true",
                      help="tanya keputusan untuk setiap titik yang masih menunggu")
    lrev.set_defaults(func=_cmd_lexical_review)

    t = sub.add_parser("trace", help="lacak sumber kebocoran")
    t.add_argument("evidence", nargs="+",
                   help="berkas bukti: foto, tangkapan layar, PDF, DOCX, atau teks; beberapa berkas dari "
                        "kebocoran yang sama (misalnya foto tiap halaman) digabung dalam satu atribusi")
    t.add_argument("--doc", default=None, help="dokumen terbitan (hash atau 16 karakter awal)")
    t.add_argument("--master", default=None, help="PDF induk (mode tanpa folder data)")
    t.add_argument("--manifest", default=None, help="manifest penerbitan (mode tanpa folder data)")
    t.add_argument("--secret", default=None)
    t.add_argument("--pelacakan-ke", dest="trace_no", type=int, default=None, metavar="K",
                   help="mode lepas: ulangi pelacakan ke-K yang tercatat dengan jatah eps-nya, 6/(pi^2 K^2) dari "
                        "eps (lihat berita acara); tanpa ini mode lepas memakai seluruh eps")
    t.add_argument("--report", default=None, help="tulis berita acara PDF ke berkas ini")
    t.add_argument("--nomor-perkara", default=None, help="nomor perkara untuk berita acara")
    t.add_argument("--pemeriksa", default=None, help="nama pemeriksa untuk berita acara")
    t.add_argument("--pangkat", default=None, help="pangkat/NRP pemeriksa untuk berita acara")
    t.add_argument("--json", default=None)
    t.set_defaults(func=_cmd_trace)

    d = sub.add_parser("docs", help="daftar dokumen yang telah diterbitkan")
    d.set_defaults(func=_cmd_docs)

    ka = sub.add_parser("kanari-izin", help="tulis ulang daftar izin pendengar kanari dari semua penerbitan")
    ka.set_defaults(func=_cmd_canary_allowlist)

    v = sub.add_parser("verify", help="verifikasi registri hanya dengan kunci publik")
    v.add_argument("--registry", default=None)
    v.add_argument("--public-key", default=None)
    v.add_argument("--merkle-dir", default=None)
    v.add_argument("--jangkar", action="append", default=[], metavar="NOMOR:HASH",
                   help="ujung rantai yang dicatat sebelumnya; entri yang hilang sesudahnya terdeteksi")
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

    for name, desc in (("canary-dns", "jalankan pendengar DNS kanari (opsi: tapak canary-dns --help)"),
                       ("photos", "buat set uji foto sintetis (opsi: tapak photos --help)")):
        sub.add_parser(name, help=desc)  # dispatched in main() before parsing

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
    os.umask(0o077)  # masters, copies, manifests and keys are readable by the operator only
    argv = list(sys.argv[1:] if argv is None else argv)
    # canary-dns and photos keep their own option parsers: hand everything after the name over.
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] in ("--data", "--keys") else 1
    if i < len(argv) and argv[i] in PASSTHROUGH:
        _settings(build_parser().parse_args(argv[:i] + ["docs"]))  # validates and applies --data/--keys
        import importlib

        return int(importlib.import_module(PASSTHROUGH[argv[i]]).main(argv[i + 1:]) or 0)
    args = build_parser().parse_args(argv)
    import sqlite3

    from tapak.registry.signing import describe_error

    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"galat: {describe_error(exc)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("dibatalkan", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
