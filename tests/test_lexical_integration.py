"""Word-choice channel through issuance, registry, trace, berita acara and CLI.

Also pins the promise that a document without an explicit lexical selection is issued and
recorded exactly as before the channel existed.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import random
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from tapak.config import Settings
from tapak.decoder.ch_zerowidth import extract_pdf_text
from tapak.decoder.trace import collect_from_text, load_context, load_lexical, retyped_text_note, run_trace
from tapak.ketik import retype
from tapak.llm.provider import get_provider
from tapak.marker import lexical as lx
from tapak.marker.issue import (
    LEXICAL_MANIFEST_FIELDS,
    IssueManifest,
    IssueSettings,
    SemanticSelection,
    build_document_plan,
    issue,
    lexical_exclusions,
    read_recipients,
)
from tapak.marker.master import load_master
from tapak.marker.plan import CHANNEL_LEXICAL, CHANNEL_SEMANTIC, RETYPE_BAND
from tapak.marker.semantic import STATUS_APPROVED, IssuanceBlocked, find_candidate_units, generate_variant_set
from tapak.registry.chain import (
    COPY_FIELDS,
    DOCUMENT_FIELDS,
    LEXICAL_DOCUMENT_FIELDS,
    Registry,
    lexical_document_problems,
    manifest_lexical_fields,
    registry_from_manifest,
)
from tapak.registry.verify import verify_registry
from tapak.service import ensure_keys, issue_document, trace_evidence, write_report
from tapak.tardos.params import TardosParams
from tests_support import RECIPIENTS, ROOT, SAMPLE

SECRET = bytes(range(32))
# Plan digests computed with the code before the lexical channel existed (commit e290b63):
# default channels, N = 20, the fixed test secret; "semantic" with every mock variant approved.
BASELINE_PLANS = {
    "nota_dinas/plain": "f2a1726fb23953d9bd28df8c11161629cc3fdf244cf07f85d2f244c3138c3ae5",
    "nota_dinas/semantic": "7c2be0cabe01ee87634d68a0d2270ba863dfc2ec2c24ebeb74430a445057a360",
    "surat_telegram/plain": "26eb384f741d72a14911d7b32623f9407552b37bc73590d3b355defafa863c15",
    "surat_telegram/semantic": "b44659ae5cafda22013351abac5b65413718d64c7c83f7dd789b2c10046d88f5",
}


def _plan_digest(plan) -> str:
    rows = [[s.channel, s.page, list(s.ref), list(s.positions), list(s.whiten)] for s in plan.slots]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _approved_semantic(master) -> SemanticSelection:
    units = find_candidate_units(master)
    sets = [generate_variant_set(master, u, get_provider("mock")) for u in units]
    for vs in sets:
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED)
    return SemanticSelection(units, sets)


def _approved_lexical(master) -> lx.LexicalSelection:
    sel = lx.scan_candidates(master)
    for p in sel.points:
        sel.set_status(p.point_id, STATUS_APPROVED)
    return sel


def _long_master(r: int):
    from tapak.samplegen import load_template, render_template

    nota = load_template(ROOT / "samples" / "templates" / "nota_dinas.json")
    tele = load_template(ROOT / "samples" / "templates" / "surat_telegram.json")
    template = dict(nota)
    template["isi"] = (nota["isi"] + tele["isi"]) * r
    return render_template(template)


# --- documents without the channel stay exactly as before ---------------------------------------


@pytest.mark.parametrize("name", ["nota_dinas", "surat_telegram"])
def test_old_manifests_regenerate_identical_plans(name):
    master = load_master((ROOT / "samples" / f"{name}.pdf").read_bytes())
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    s = IssueSettings()
    plan = build_document_plan(master, params, SECRET, s.channels, set(), s.background)
    assert _plan_digest(plan) == BASELINE_PLANS[f"{name}/plain"]
    sem = _approved_semantic(master)
    plan = build_document_plan(master, params, SECRET, s.channels, sem.carrying_rows(), s.background, sem)
    assert _plan_digest(plan) == BASELINE_PLANS[f"{name}/semantic"]


def test_manifest_and_registry_entry_without_the_channel_are_unchanged(issued, tmp_path):
    _, manifest = issued
    text = manifest.to_json()
    assert not set(json.loads(text)) & set(LEXICAL_MANIFEST_FIELDS)
    assert "lexical" not in manifest.channels and "lexical" not in manifest.plan_summary
    assert IssueManifest.from_json(text).to_json() == text
    assert lexical_exclusions(manifest) == (set(), set())
    assert manifest_lexical_fields(manifest) is None
    with Registry.open(tmp_path / "r.db") as reg:
        entries = registry_from_manifest(manifest, reg)
    assert set(entries[0].payload) == DOCUMENT_FIELDS
    assert all(set(e.payload) == COPY_FIELDS for e in entries[1:])


def test_trace_of_an_old_document_has_no_lexical_channel(ctx, issued):
    out, manifest = issued
    assert ctx.lexical is None and not ctx.plan.channel(CHANNEL_LEXICAL)
    obs = collect_from_text(extract_pdf_text((out / manifest.copies[3].file).read_bytes()), ctx)
    assert {o.channel for o in obs} == {"zw", "homoglyph"}
    result = run_trace(obs, ctx)
    assert not any("ketikan ulang" in n for n in result.notes)


# --- issuance with the channel -------------------------------------------------------------------


@pytest.fixture(scope="module")
def lex_doc(tmp_path_factory):
    """The nota dinas issued with semantic variants and word choice, recorded in a signed registry."""
    tmp = tmp_path_factory.mktemp("leksikal")
    s = Settings(data_dir=tmp / "data", key_dir=tmp / "keys", canary_domain="")
    keys = ensure_keys(s)
    master = load_master(SAMPLE.read_bytes())
    sel = lx.scan_candidates(master)
    recipients = read_recipients(RECIPIENTS)
    with pytest.raises(IssuanceBlocked, match="menunggu keputusan"):
        issue_document(s, SAMPLE, recipients, IssueSettings(workers=4), "uji", keys, lexical=sel)
    assert not list(s.workspaces.glob("*/manifest.json"))
    for p in sel.points:
        sel.set_status(p.point_id, STATUS_APPROVED)
    sel.set_status(sel.points[-1].point_id, "ditolak")  # one point rejected by the reviewer
    sem = _approved_semantic(master)
    out = issue_document(s, SAMPLE, recipients, IssueSettings(workers=4), "uji", keys, semantic=sem, lexical=sel)
    return s, keys, out, sel, sem


def test_issuance_records_digests_but_no_words_or_code_bits(lex_doc):
    s, keys, out, sel, sem = lex_doc
    m = out.manifest
    assert m.retype_positions == RETYPE_BAND and m.lexical_digest == sel.digest
    assert m.lexicon_version == "naskah_dinas_v1" and m.lexicon_digest == lx.load_lexicon().digest
    assert "lexical" in m.channels and m.plan_summary["lexical"]["bits"] == sel.bits
    assert {tuple(r) for r in m.shift_excluded_rows} == sel.shift_excluded_rows()
    assert {tuple(w) for w in m.text_excluded_words} == sel.excluded_words()
    stored = lx.LexicalSelection.from_dict(json.loads((out.folder / "leksikal.json").read_text(encoding="utf-8")))
    assert stored.digest == sel.digest and load_lexical(out.folder).digest == sel.digest
    with Registry.open(s.registry_path) as reg:
        doc = reg.find_document(m.doc_hash)
        copies = reg.copies(m.doc_hash)
    assert set(doc) == DOCUMENT_FIELDS | LEXICAL_DOCUMENT_FIELDS
    assert doc["lexical_digest"] == sel.digest and doc["retype_positions"] == RETYPE_BAND
    assert lexical_document_problems(doc) == []
    for c in copies:  # copy entries hold no form choice (code bits)
        assert set(c) == COPY_FIELDS | {"recipient_mac"} and not any("lex" in k for k in c)
        assert all(v.startswith("u") for v in c["semantic_variant_ids"])
    raw = s.registry_path.read_bytes() + b"".join(p.read_bytes() for p in s.data_dir.rglob("*.log"))
    for p in sel.points:  # no document words in the registry
        assert p.context.encode("utf-8") not in raw
    assert verify_registry(s.registry_path, keys.public_key_hex).ok


def test_band_positions_shared_by_semantic_and_lexical(lex_doc):
    s, keys, out, sel, sem = lex_doc
    m = out.manifest
    ctx = load_context((out.folder / "induk.pdf").read_bytes(), m, keys.code_secret, folder=out.folder)
    assert ctx.warnings == [] and ctx.lexical is not None and ctx.semantic is not None
    sem_pos = [q for sl in ctx.plan.channel(CHANNEL_SEMANTIC) for q in sl.positions]
    lex_pos = [q for sl in ctx.plan.channel(CHANNEL_LEXICAL) for q in sl.positions]
    assert sem_pos and len(lex_pos) == sel.bits
    assert all(0.3 <= ctx.p[q] <= 0.7 for q in sem_pos + lex_pos) and not set(sem_pos) & set(lex_pos)
    shift_rows = {(sl.page, sl.ref[0]) for sl in ctx.plan.channel("shift")}
    assert not shift_rows & sel.shift_excluded_rows()
    assert sel.points[-1].row_id not in sel.shift_excluded_rows() or any(
        p.row_id == sel.points[-1].row_id for p in sel.carrying())  # the rejected point carries nothing


def test_forwarded_copy_still_named_and_lexical_bits_read(lex_doc):
    s, keys, out, sel, sem = lex_doc
    copy7 = out.folder / "salinan" / out.manifest.copies[6].file
    outcome = trace_evidence(s, out.manifest.doc_hash, copy7.name, copy7.read_bytes(), keys)
    att = outcome.attribution
    assert [c.copy.seq for c in att.accused] == [7]
    lex = next(o for o in outcome.observations if o.channel == CHANNEL_LEXICAL)
    x = outcome.ctx.codewords[6]
    assert len(lex) == sel.bits and np.all((lex.llr > 0) == (x[lex.positions] == 1))
    lexical_row = next(ch for ch in att.channels if ch.channel == "leksikal")  # its own independent row
    assert lexical_row.n_observed == sel.bits and lexical_row.accused_seqs == []  # too few bits alone


def test_retyped_nota_gives_insufficient_evidence_with_a_plain_note(lex_doc):
    from tapak.decoder.report import build_report_info, render_html

    s, keys, out, sel, sem = lex_doc
    copy5 = out.folder / "salinan" / out.manifest.copies[4].file
    text = retype(extract_pdf_text(copy5.read_bytes()), random.Random(2026), "sedang")
    outcome = trace_evidence(s, out.manifest.doc_hash, "ketikan.txt", text.encode("utf-8"), keys)
    att = outcome.attribution
    assert att.verdict == "tidak cukup bukti" and att.accused == []
    note = next(n for n in att.notes if "diketik ulang" in n)
    assert f"{lx.LONE_LEAKER_BITS} bit" in note and "tidak cukup bukti" in note
    phys = {ch.channel for ch in att.channels}
    assert "leksikal" in phys and phys <= {"leksikal", "semantik"}
    info = build_report_info(outcome.ctx, "ketikan.txt", text.encode("utf-8"), outcome.observations,
                             case_number="UJI-1", examiner_name="Pemeriksa", examiner_rank="Mayor")
    html = render_html(att, info)
    assert "Leksikal (pilihan kata" in html and "Semantik (variasi kalimat)" in html
    assert "Pilihan kata (leksikal)" in html and "diketik ulang" in html
    assert write_report(outcome)[:4] == b"%PDF"


def test_retyped_text_note_only_for_retype_channels(lex_doc):
    s, keys, out, sel, sem = lex_doc
    ctx = load_context((out.folder / "induk.pdf").read_bytes(), out.manifest, keys.code_secret, folder=out.folder)
    pdf = (out.folder / "salinan" / out.manifest.copies[0].file).read_bytes()
    obs = collect_from_text(extract_pdf_text(pdf), ctx)  # pasted text: zero-width marks survive
    result = run_trace(obs, ctx)
    assert retyped_text_note(obs, result) is None and result.accused
    only = [o for o in obs if o.channel == CHANNEL_LEXICAL]
    result = run_trace(only, ctx)
    assert "bit" in retyped_text_note(only, result)


def test_digest_mismatch_skips_only_the_lexical_channel(lex_doc, tmp_path):
    s, keys, out, sel, sem = lex_doc
    m = out.manifest
    master = (out.folder / "induk.pdf").read_bytes()
    good = load_context(master, m, keys.code_secret, folder=out.folder)
    edited = copy.deepcopy(sel)
    edited.set_status(edited.points[0].point_id, "ditolak")
    for given, why in ((edited, "tidak cocok"), (None, "tidak tersedia")):
        folder = tmp_path / ("ubah" if given is not None else "hilang")
        folder.mkdir()
        if given is not None:
            (folder / "leksikal.json").write_text(given.to_json(), encoding="utf-8")
        ctx = load_context(master, m, keys.code_secret, semantic=sem, folder=folder)
        assert ctx.lexical is None and any(why in w and "pilihan kata" in w for w in ctx.warnings)
        assert not ctx.plan.channel(CHANNEL_LEXICAL)
        for ch in ("shift", "zw", "homoglyph", "background", "semantic"):  # every other channel unchanged
            assert ctx.plan.channel(ch) == good.plan.channel(ch), ch
        pdf = (out.folder / "salinan" / m.copies[2].file).read_bytes()
        result = run_trace(collect_from_text(extract_pdf_text(pdf), ctx), ctx)
        assert [c.copy.seq for c in result.accused] == [3]
        assert any("pilihan kata" in n for n in result.notes)
    (tmp_path / "rusak").mkdir()
    (tmp_path / "rusak" / "leksikal.json").write_text("{}", encoding="utf-8")
    from tapak.decoder.trace import TraceError

    with pytest.raises(TraceError):
        load_lexical(tmp_path / "rusak")
    assert load_lexical(None) is None and load_lexical(tmp_path / "hilang") is None


def test_edited_registry_or_manifest_is_detected(lex_doc, tmp_path):
    from tapak.service import check_registry

    s, keys, out, sel, sem = lex_doc
    m = copy.deepcopy(out.manifest)
    m.retype_positions = None  # a manifest edited back to the uniform rule
    rep = check_registry(s, m, keys.code_secret)
    assert "retype_positions" in rep.document_mismatch
    db = tmp_path / "r.db"
    db.write_bytes(s.registry_path.read_bytes())
    conn = sqlite3.connect(db)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    payload = conn.execute("SELECT payload FROM entries WHERE kind = 'document'").fetchone()[0]
    forged = payload.replace(f'"lexical_digest":"{sel.digest[:4]}', '"lexical_digest":"ffff', 1)
    assert forged != payload
    conn.execute("UPDATE entries SET payload = ? WHERE kind = 'document'", (forged,))
    conn.commit()
    conn.close()
    rep = verify_registry(db, keys.public_key_hex)
    assert not rep.ok and any("hash entri" in text for _, text in rep.problems)


def test_registry_refuses_incomplete_or_wordy_lexical_fields(tmp_path, issued):
    _, manifest = issued
    with Registry.open(tmp_path / "r.db") as reg:
        base = dict(doc_hash="ab" * 32, doc_name="x", params=manifest.params, channels=["lexical"],
                    shift_mm=manifest.shift_mm, excluded_rows=[], plan_summary={}, threshold_rule="r",
                    threshold_full=1.0, issuer="u", issued_at="2026-01-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="tidak lengkap"):
            reg.record_document(**base, lexical={"lexical_digest": "a" * 64})
        bad = {"retype_positions": RETYPE_BAND, "lexical_digest": "a" * 64, "lexicon_version": "naskah_dinas_v1",
               "lexicon_digest": "b" * 64, "shift_excluded_rows": [["dan serta"]], "text_excluded_words": []}
        with pytest.raises(ValueError, match="daftar nomor posisi"):
            reg.record_document(**base, lexical=bad)
        ok = dict(bad, shift_excluded_rows=[[0, 3]], text_excluded_words=[[0, 3, 2]])
        entry = reg.record_document(**base, lexical=ok)
        assert set(entry.payload) == DOCUMENT_FIELDS | LEXICAL_DOCUMENT_FIELDS
    assert lexical_document_problems(dict(ok, retype_positions="lain")) == ["aturan posisi ketik ulang tidak dikenal"]


def test_hand_edited_selection_is_refused_at_issuance(tmp_path):
    master = load_master(SAMPLE.read_bytes())
    sel = _approved_lexical(master)
    sel.points[0].forms = (sel.points[0].forms[0], "bentuk lain sekali")
    with pytest.raises(IssuanceBlocked, match="diubah di luar TAPAK"):
        issue(SAMPLE, read_recipients(RECIPIENTS)[:2], tmp_path, SECRET, IssueSettings(workers=1), lexical=sel)


# --- a document long enough for one retyped leak ---------------------------------------------------


def test_long_document_retyped_names_the_right_copy_text_level():
    """About 6 pages (R = 3): a retyped leak of one copy names it, 10 of 10, never anyone else."""
    from tapak.decoder.accuse import CopyRef, attribute
    from tapak.decoder.ch_lexical import LexReference, decode_lexical
    from tapak.decoder.fuse import fuse, fuse_by_physical_channel
    from tapak.marker.plan import plan_key
    from tapak.tardos.code import derive_bias, derive_codeword

    master = load_master(_long_master(3))
    sel = _approved_lexical(master)
    assert len(master.layout.pages) == 6 and sel.bits >= 48
    ref = LexReference(master, sel.carrying())
    rng = random.Random(20)
    for trial in range(10):
        secret = rng.randbytes(32)
        params = TardosParams(c=3, eps=1e-6, n_max=20)
        p = derive_bias(secret, master.doc_hash, params)
        slots = lx.lexical_slots(sel, params.length, plan_key(secret, master.doc_hash), p, RETYPE_BAND)
        x = np.vstack([derive_codeword(secret, master.doc_hash, f"s{j}", p) for j in range(20)])
        leak = rng.randrange(20)
        text = retype(lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x[leak], sel.points)),
                      rng, "sedang")
        sb = decode_lexical(text, ref, sel.points, slots)
        refs = [CopyRef(j + 1, f"s{j}", f"R{j:03d}", f"Penerima {j}") for j in range(20)]
        att = attribute(fuse([sb], params.length), fuse_by_physical_channel([sb], params.length), p, x, refs, params)
        assert [c.copy.seq for c in att.accused] == [leak + 1], trial


@pytest.mark.slow
def test_long_document_issued_retyped_and_traced(tmp_path):
    """Full pipeline: 20 PDF copies of the 6-page document, one retyped, traced: right copy, nobody else."""
    pdf = tmp_path / "panjang.pdf"
    pdf.write_bytes(_long_master(3))
    master = load_master(pdf.read_bytes())
    sel = _approved_lexical(master)
    sem = _approved_semantic(master)
    recipients = read_recipients(RECIPIENTS)
    m = issue(pdf, recipients, tmp_path / "out", SECRET, IssueSettings(workers=4), semantic=sem, lexical=sel)
    ctx = load_context(pdf.read_bytes(), m, SECRET, semantic=sem, lexical=sel)
    rng = random.Random(6)
    for seq in (4, 11, 17):
        text = retype(extract_pdf_text((tmp_path / "out" / m.copies[seq - 1].file).read_bytes()), rng, "sedang")
        obs = [o for o in collect_from_text(text, ctx) if len(o)]
        assert {o.channel for o in obs} <= {"semantic", "lexical"}  # retyping removed the text marks
        result = run_trace(obs, ctx)
        assert [c.copy.seq for c in result.accused] == [seq]


# --- command line -------------------------------------------------------------------------------


def _run(tmp: Path, *argv: str) -> int:
    from tapak.cli import main

    return main(["--data", str(tmp / "data"), "--keys", str(tmp / "keys"), *argv])


def test_cli_scan_review_issue_and_trace(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    recipients = tmp_path / "penerima.csv"
    with open(RECIPIENTS, newline="", encoding="utf-8") as src, open(recipients, "w", newline="", encoding="utf-8") as dst:
        rows = list(csv.reader(src))
        csv.writer(dst).writerows(rows[:6])  # header and 5 recipients
    assert _run(tmp_path, "keys", "init") == 0
    lexfile = tmp_path / "leksikal.json"
    assert _run(tmp_path, "leksikal", "scan", str(SAMPLE), "-o", str(lexfile)) == 0
    out = capsys.readouterr().out
    assert "DRAF" in out and "menunggu" in out and "judul paragraf" in out
    sel = lx.LexicalSelection.from_dict(json.loads(lexfile.read_text(encoding="utf-8")))
    for p in sel.points:  # refusal categories are printed, never the refused words themselves
        assert p.context not in out

    assert _run(tmp_path, "issue", str(SAMPLE), str(recipients), "--leksikal", str(lexfile)) == 2
    assert "menunggu keputusan" in capsys.readouterr().err

    assert _run(tmp_path, "leksikal", "review", str(lexfile), "--aturan", "dan", "--setujui") == 2
    assert "--ya" in capsys.readouterr().err
    assert _run(tmp_path, "leksikal", "review", str(lexfile), "--aturan", "dan", "--setujui", "--ya") == 0
    assert _run(tmp_path, "leksikal", "review", str(lexfile), "--titik", "l1", "--tolak") == 0
    assert _run(tmp_path, "leksikal", "review", str(lexfile), "--titik", "l99", "--tolak") == 2
    capsys.readouterr()
    answers = iter(["x", "s"] + ["s"] * 50)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert _run(tmp_path, "leksikal", "review", str(lexfile), "--interaktif") == 0
    capsys.readouterr()
    assert _run(tmp_path, "leksikal", "show", str(lexfile)) == 0
    shown = capsys.readouterr().out
    assert "[disetujui]" in shown and "[ditolak]" in shown and "menunggu" in shown and "bentuk:" in shown
    sel = lx.LexicalSelection.from_dict(json.loads(lexfile.read_text(encoding="utf-8")))
    assert sel.pending() == [] and sel.point("l1").status == "ditolak"

    edited = json.loads(lexfile.read_text(encoding="utf-8"))
    edited["points"][0]["forms"][1] = "bentuk karangan"
    hand = tmp_path / "tangan.json"
    hand.write_text(json.dumps(edited), encoding="utf-8")
    assert _run(tmp_path, "issue", str(SAMPLE), str(recipients), "--leksikal", str(hand)) == 2
    assert "diubah di luar TAPAK" in capsys.readouterr().err

    assert _run(tmp_path, "issue", str(SAMPLE), str(recipients), "--leksikal", str(lexfile)) == 0
    out = capsys.readouterr().out
    assert f"{sel.bits} bit pilihan kata" in out and "belum cukup" in out and "Tahan ketik ulang" in out
    folder = next((tmp_path / "data" / "dokumen").glob("*/manifest.json")).parent
    assert (folder / "leksikal.json").exists()
    copy3 = next(folder.glob("salinan/*salinan003_*.pdf"))
    leak = tmp_path / "bocor.txt"
    leak.write_text(retype(extract_pdf_text(copy3.read_bytes()), random.Random(3), "sedang"), encoding="utf-8")
    assert _run(tmp_path, "trace", str(leak)) == 0
    out = capsys.readouterr().out
    assert "TIDAK CUKUP BUKTI" in out and "Pilihan kata (leksikal)" in out and "diketik ulang" in out
    assert _run(tmp_path, "verify") == 0
