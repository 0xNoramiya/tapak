"""Word-choice (lexical) channel: lexicon, guards, layout fit, review file, positions, decoder."""

from __future__ import annotations

import copy
import itertools
import json
import random
import re

import numpy as np
import pytest

from tapak.decoder.accuse import CopyRef, attribute
from tapak.decoder.ch_lexical import (
    CLUSTER_MAX_LLR,
    MAX_LLR,
    LexReference,
    decode_lexical,
    phrase_ops,
    position_map,
)
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.ketik import LEVELS, apply_habit, ocr_confusion, retype, typo
from tapak.llm.provider import KEY_WORDS
from tapak.marker import lexical as lx
from tapak.marker import semantic as sem
from tapak.marker.master import load_master
from tapak.marker.plan import (
    CHANNEL_LEXICAL,
    CHANNEL_SEMANTIC,
    RETYPE_BAND,
    RETYPE_STREAM,
    assign_positions,
    plan_key,
    retype_pool,
)
from tapak.marker.semantic import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED, IssuanceBlocked
from tapak.tardos.code import derive_bias, derive_codeword, uniform_stream
from tapak.tardos.params import TardosParams
from tests_support import ROOT

DOCS = [ROOT / "samples" / "nota_dinas.pdf", ROOT / "samples" / "surat_telegram.pdf"]
SECRET = bytes(range(32))
CATEGORIES = {getattr(lx, name) for name in dir(lx) if name.startswith("REFUSE_")}


@pytest.fixture(scope="module")
def lexicon():
    return lx.load_lexicon()


@pytest.fixture(scope="module", params=DOCS, ids=lambda p: p.stem)
def doc(request):
    master = load_master(request.param.read_bytes())
    sel = lx.scan_candidates(master)
    for p in sel.points:
        sel.set_status(p.point_id, STATUS_APPROVED)
    return master, sel


def _plan(master, sel, n=20, secret=SECRET):
    params = TardosParams(c=3, eps=1e-6, n_max=n)
    p = derive_bias(secret, master.doc_hash, params)
    slots = lx.lexical_slots(sel, params.length, plan_key(secret, master.doc_hash), p, RETYPE_BAND)
    return params, p, slots


def _row_combinations(master, points):
    """Every combination of forms, row by row (rows are laid out independently)."""
    by_row: dict = {}
    for p in points:
        by_row.setdefault(p.row_id, []).append(p)
    for rid, pts in by_row.items():
        for combo in itertools.product(*[range(len(p.forms)) for p in pts]):
            yield rid, pts, {p.point_id: k for p, k in zip(pts, combo)}


# --- lexicon --------------------------------------------------------------------------------


def test_lexicon_is_a_versioned_draft(lexicon):
    raw = json.loads((lx.LEXICON_DIR / "naskah_dinas_v1.json").read_text(encoding="utf-8"))
    assert lexicon.name == "naskah_dinas_v1" and lexicon.version == 1
    assert lexicon.status == "draf" and lexicon.is_draft
    assert "Tata Naskah Dinas" in raw["catatan"] and "DRAF" in raw["catatan"]
    assert re.fullmatch(r"[0-9a-f]{64}", lexicon.digest)
    assert lx.load_lexicon().digest == lexicon.digest  # stable
    assert lexicon.rule("dan").forms == ("dan", "serta")
    with pytest.raises(KeyError):
        lexicon.rule("tidak_ada")


def test_lexicon_follows_the_table_rules(lexicon):
    raw = json.loads((lx.LEXICON_DIR / "naskah_dinas_v1.json").read_text(encoding="utf-8"))
    assert lx.lexicon_problems(raw) == []
    seen: dict[str, str] = {}
    for rule in lexicon.rules:
        assert len(set(rule.forms)) == len(rule.forms) >= 2
        for a, b in itertools.combinations(rule.forms, 2):
            from rapidfuzz.distance import Levenshtein

            assert Levenshtein.distance(a, b) >= lx.MIN_FORM_DISTANCE, (a, b)
            assert not lx._minus_one_word(a, b) and not lx._minus_one_word(b, a)
        for form in rule.forms:
            assert form not in seen, form
            seen[form] = rule.rule_id
            assert all(lx._token_problem(w, sentence_start=False) is None for w in form.split()), form
            assert not any(ch.isdigit() for ch in form)


def test_lexicon_problems_catch_bad_tables():
    def table(*rules):
        return {"id": "uji", "version": 1, "rules": [dict(r) for r in rules]}

    good = {"id": "x", "tier": "A", "forms": ["terdiri atas", "terdiri dari"]}
    assert lx.lexicon_problems(table(good)) == []
    close = lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["setiap", "tiap"]}))
    assert any("kurang dari 3 karakter" in p for p in close)
    minus = lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["pada saat", "saat itu juga", "saat"]}))
    assert any("satu kata yang dihilangkan" in p for p in minus)
    protected = lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["dua kali", "tiga kali"]}))
    assert any("kata terlindungi" in p for p in protected)
    negation = lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["tidak boleh", "jangan sampai"]}))
    assert any("kata terlindungi" in p for p in negation)
    twice = lx.lexicon_problems(table(good, {"id": "y", "tier": "A", "forms": ["terdiri atas", "tersusun atas"]}))
    assert any("ada di aturan" in p for p in twice)
    assert lx.lexicon_problems(table({"id": "x", "tier": "C", "forms": ["dan", "serta"]}))
    assert lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["dan", "serta"], "next": "("}))
    assert lx.lexicon_problems(table({"id": "x", "tier": "A", "forms": ["dan", "serta"], "match": ["atau"]}))
    assert lx.lexicon_problems({"rules": []})


def test_load_lexicon_refuses_bad_files(tmp_path):
    bad = tmp_path / "rusak.json"
    bad.write_text(json.dumps({"id": "x", "version": 1, "rules": [{"id": "a", "tier": "A",
                                                                     "forms": ["setiap", "tiap"]}]}))
    with pytest.raises(lx.LexiconError):
        lx.load_lexicon("rusak", path=bad)
    with pytest.raises(lx.LexiconError):
        lx.load_lexicon("../keys")
    with pytest.raises(lx.LexiconError):
        lx.load_lexicon("tidak_ada")


# --- scan, guards, layout --------------------------------------------------------------------


def test_scan_finds_points_and_reports_categories_only(doc):
    master, sel = doc
    assert len(sel.points) >= 4 and sel.body_words > 100
    assert all(len(p.forms) in (2, 4) and p.bits == len(p.forms).bit_length() - 1 for p in sel.points)
    assert set(sel.refused) <= CATEGORIES  # refusals name categories, never document words
    assert sel.scan_digest == sel.compute_scan_digest()
    rep = lx.scan_points(master, layout=False)
    assert isinstance(rep, lx.ScanReport) and rep.matched >= len(sel.points)
    rep.refuse(lx.REFUSE_DIGIT)
    assert rep.refused[lx.REFUSE_DIGIT] >= 1


def _protected(words):
    """Tokens that must never change: digits, names, key words, times, numbers, orders, negations."""
    out = []
    for i, w in enumerate(words):
        start = i == 0 or words[i - 1].endswith((".", ":", "!", "?"))
        bare = w.strip(".,;:!?")
        if (any(ch.isdigit() for ch in bare) or bare.lower() in KEY_WORDS
                or lx._token_problem(w, sentence_start=start) is not None):
            out.append(bare)
    return out


def test_protected_tokens_unchanged_under_every_combination(doc):
    master, sel = doc
    combos = 0
    for rid, pts, choice in _row_combinations(master, sel.points):
        words = [t for t, _ in lx.row_words_for(master.layout.row(rid), pts, choice)]
        original = [w.text for w in master.layout.row(rid).words]
        assert _protected(words) == _protected(original), rid
        combos += 1
    assert combos >= 2 * len({p.row_id for p in sel.points})


def test_protected_tokens_unchanged_on_a_long_document():
    from tapak.samplegen import load_template, render_template

    nota = load_template(ROOT / "samples" / "templates" / "nota_dinas.json")
    tele = load_template(ROOT / "samples" / "templates" / "surat_telegram.json")
    template = dict(nota)
    template["isi"] = nota["isi"] + tele["isi"]
    master = load_master(render_template(template))
    sel = lx.scan_candidates(master)
    assert len(sel.points) >= 10
    for rid, pts, choice in _row_combinations(master, sel.points):
        words = [t for t, _ in lx.row_words_for(master.layout.row(rid), pts, choice)]
        assert _protected(words) == _protected([w.text for w in master.layout.row(rid).words]), rid


def test_headings_semantic_units_and_other_blocks_untouched(doc):
    master, sel = doc
    unit_rows = {rid for u in sem.find_candidate_units(master) for rid in u.row_ids}
    body = {r.id for r in lx.body_rows(master)}
    for p in sel.points:
        assert p.row_id not in unit_rows and p.row_id in body
        row = master.layout.row(p.row_id)
        phrase = [w.text for w in row.words[p.start:p.end]]
        assert not any(ch.isdigit() for w in phrase for ch in w)
        assert " ".join(phrase) == p.forms[0] and p.context == row.text
        # never a paragraph heading such as "Maksud dan tujuan."
        assert not re.match(r"^\w{1,3}\. \w+ dan \w+\.", row.text) or p.start > 3


def test_every_combination_fits_its_row(doc):
    master, sel = doc
    edges = lx.page_edges(master)
    for rid, pts, choice in _row_combinations(master, sel.points):
        row = master.layout.row(rid)
        placed = lx.fit_row(master, row, lx.row_words_for(row, pts, choice), edges[rid[0]])
        assert placed is not None
        assert placed[0][0] == pytest.approx(row.words[0].x0, abs=1e-3)  # same left edge, label kept
        g0 = row.words[0].glyphs[0]
        font = master.fonts[g0.font].font
        x, text, wid = placed[-1]
        end = x + (master.layout.word(wid).x1 - master.layout.word(wid).x0 if wid else
                   font.text_length(text, g0.size))
        assert end <= edges[rid[0]] + lx.EDGE_TOL
        if edges[rid[0]] - row.words[-1].x1 <= lx.FULL_TOL:
            assert end == pytest.approx(row.words[-1].x1, abs=0.01)  # justified rows keep the right edge


def test_fit_row_refuses_what_does_not_fit(doc):
    master, sel = doc
    p = sel.points[0]
    row = master.layout.row(p.row_id)
    words = lx.row_words_for(row, [p], {})
    huge = [(t, w) for t, w in words] + [("panjangsekali" * 8, None)]
    assert lx.fit_row(master, row, huge, lx.page_edges(master)[p.page]) is None


# --- review file ------------------------------------------------------------------------------


def test_selection_round_trip_digests_and_counts(doc):
    master, sel = doc
    again = lx.LexicalSelection.from_dict(json.loads(sel.to_json()))
    assert again.digest == sel.digest and again.to_dict() == sel.to_dict()
    assert again.bits == sum(p.bits for p in sel.points) and again.candidate_bits == again.bits
    first = again.points[0].point_id
    again.set_status(first, STATUS_REJECTED)
    assert again.digest != sel.digest and again.compute_scan_digest() == sel.scan_digest
    assert again.counts()[STATUS_REJECTED] == 1 and first not in [p.point_id for p in again.carrying()]
    assert again.point(first).status == STATUS_REJECTED
    assert lx.LexPoint.from_dict(again.points[0].to_dict()) == again.points[0]
    assert again.shift_excluded_rows() <= {p.row_id for p in again.points}
    assert all(w[:2] == again.point(first).row_id for w in again.point(first).word_ids())
    assert not set(again.point(first).word_ids()) & again.excluded_words()  # rejected: drawn as master
    with pytest.raises(ValueError):
        again.set_status(first, "mungkin")
    with pytest.raises(ValueError):
        again.set_status("l999", STATUS_APPROVED)
    with pytest.raises(ValueError):
        lx.LexicalSelection.from_dict({"format": "lain"})


def test_review_gate_blocks_pending_and_hand_edits(doc, lexicon):
    master, sel = doc
    fresh = lx.scan_candidates(master)
    assert fresh.pending() == [p.point_id for p in fresh.points]
    with pytest.raises(IssuanceBlocked, match="menunggu keputusan"):
        lx.require_reviewed(fresh)
    with pytest.raises(IssuanceBlocked):
        lx.validate_selection(master, fresh)
    lx.validate_selection(master, sel, lexicon)  # a reviewed, untouched file passes

    edited = copy.deepcopy(sel)  # a form changed by hand: the scan digest no longer matches
    edited.points[0].forms = (edited.points[0].forms[0], "bentuk karangan")
    with pytest.raises(IssuanceBlocked, match="diubah di luar TAPAK"):
        lx.validate_selection(master, edited, lexicon)
    edited.scan_digest = edited.compute_scan_digest()  # even with a recomputed digest: re-scan differs
    with pytest.raises(IssuanceBlocked, match="pemindaian ulang"):
        lx.validate_selection(master, edited, lexicon)

    other = copy.deepcopy(sel)
    other.doc_hash = "0" * 64
    with pytest.raises(IssuanceBlocked, match="dokumen lain"):
        lx.validate_selection(master, other, lexicon)
    changed = copy.deepcopy(sel)
    changed.lexicon_digest = "f" * 64
    changed.scan_digest = changed.compute_scan_digest()
    with pytest.raises(IssuanceBlocked, match="leksikon berubah"):
        lx.validate_selection(master, changed, lexicon)
    odd = copy.deepcopy(sel)
    odd.points[0].status = "barangkali"
    with pytest.raises(IssuanceBlocked):
        lx.validate_selection(master, odd, lexicon)


# --- positions ----------------------------------------------------------------------------------


def test_assign_positions_default_is_the_original_rule():
    key = plan_key(SECRET, "ab" * 32)
    refs = [(0, (i,), 1 + i % 3) for i in range(40)]
    m = 500
    perm = np.argsort(uniform_stream(key, b"perm|semantic", m), kind="stable")
    white = (uniform_stream(key, b"white|semantic", 80) < 0.5).astype(int)
    slots = assign_positions(CHANNEL_SEMANTIC, refs, m, key)
    cursor = 0
    for slot, (_, _, n) in zip(slots, refs):
        assert slot.positions == tuple(int(perm[(cursor + k) % m]) for k in range(n))
        assert slot.whiten == tuple(int(white[cursor + k]) for k in range(n))
        cursor += n


def test_band_positions_shared_sequence_never_collide(doc):
    master, sel = doc
    params, p, lex_slots = _plan(master, sel)
    key = plan_key(SECRET, master.doc_hash)
    pool = retype_pool(p, RETYPE_BAND)
    assert pool.dtype == bool and pool.shape == (params.length,) and 0.15 < pool.mean() < 0.4
    sem_refs = [(0, (i,), 2) for i in range(6)]
    sem_slots = assign_positions(CHANNEL_SEMANTIC, sem_refs, params.length, key, pool=pool, stream=RETYPE_STREAM)
    lex_pos = [q for s in lex_slots for q in s.positions]
    sem_pos = [q for s in sem_slots for q in s.positions]
    assert all(0.3 <= p[q] <= 0.7 for q in lex_pos + sem_pos)
    assert len(set(lex_pos)) == len(lex_pos) and not set(lex_pos) & set(sem_pos)
    # Positions depend on the key and the bias vector only (never on a codeword) and are stable.
    _, _, again = _plan(master, sel)
    assert again == lex_slots
    with pytest.raises(ValueError):
        retype_pool(p, "pita-lain")
    with pytest.raises(ValueError):
        assign_positions(CHANNEL_LEXICAL, [(0, (0,), 1)], params.length, key, pool=np.zeros(3, dtype=bool))
    with pytest.raises(ValueError):
        lx.lexical_slots(sel, params.length, key, None, RETYPE_BAND)
    uniform = lx.lexical_slots(sel, params.length, key, None, None)
    assert [len(s.positions) for s in uniform] == [len(s.positions) for s in lex_slots]


# --- decoder ----------------------------------------------------------------------------------


def test_clean_round_trip_reads_every_bit(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    for k in range(10):
        x = derive_codeword(SECRET, master.doc_hash, f"salinan{k}", p)
        text = lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x, sel.points))
        sb = decode_lexical(text, ref, sel.points, slots)
        assert len(sb) == sel.bits and sb.meta["points_read"] == len(sel.points)
        assert np.array_equal((sb.llr > 0).astype(int), x[sb.positions])
        assert np.all(np.abs(sb.llr) == MAX_LLR)
        assert all(set(r) == {"point", "form", "edits", "densest_edits", "bits"} for r in sb.meta["reads"])


def test_five_percent_typos_give_at_most_three_percent_wrong_bits(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    rng = random.Random(1)
    wrong = read = 0
    for k in range(40):
        x = derive_codeword(SECRET, master.doc_hash, f"ketik{k}", p)
        words = lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x, sel.points)).split()
        words = [typo(w, rng) if rng.random() < 0.05 else w for w in words]
        sb = decode_lexical(" ".join(words), ref, sel.points, slots)
        read += len(sb)
        wrong += int(np.sum((sb.llr > 0).astype(int) != x[sb.positions]))
    assert read >= 0.95 * 40 * sel.bits
    assert wrong <= 0.03 * read


def test_excerpt_reads_nothing_outside_the_excerpt(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    order = {row.id: i for i, row in enumerate(master.layout.rows())}
    point_rows = sorted(order[q.row_id] for q in sel.carrying())
    cut = point_rows[len(point_rows) // 2]  # the excerpt ends before the row of the middle point
    row_of = {q: order[sel.points[s.ref[0]].row_id] for s in slots for q in s.positions}
    rng = random.Random(7)
    inside = outside = wrong = 0
    for k in range(20):
        x = derive_codeword(SECRET, master.doc_hash, f"kutip{k}", p)
        lines = lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x, sel.points)).split("\n")
        sb = decode_lexical(retype("\n".join(lines[:cut]), rng, "sedang"), ref, sel.points, slots)
        outside += sum(row_of[int(q)] >= cut for q in sb.positions)
        inside += sum(row_of[int(q)] < cut for q in sb.positions)
        wrong += int(np.sum((sb.llr > 0).astype(int) != x[sb.positions]))
    assert outside == 0 and inside > 0
    assert wrong <= max(1, 0.05 * inside)


def test_threshold_identical_for_different_codeword_matrices(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    x = np.vstack([derive_codeword(SECRET, master.doc_hash, f"c{j}", p) for j in range(20)])
    rng = np.random.default_rng(3)
    other = (rng.random(x.shape) < p).astype(np.uint8)
    text = retype(lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x[0], sel.points)),
                  random.Random(5), "sedang")
    sb = decode_lexical(text, ref, sel.points, slots)
    fused, per = fuse([sb], params.length), fuse_by_physical_channel([sb], params.length)
    refs = [CopyRef(j + 1, f"c{j}", f"R{j}", f"P{j}") for j in range(20)]
    results = [attribute(fused, per, p, cw, refs, params) for cw in (x, 1 - x, other)]
    assert len({r.threshold.threshold for r in results}) == 1
    assert len({r.channels[0].threshold for r in results}) == 1
    assert results[0].accused == []  # one sample document never names anyone from retyped text


def _text_with_row_edit(master, sel, choice, pt, edit):
    """Copy text with ``edit`` applied to the word list of the point's row (at the point itself)."""
    rows = lx.copy_rows(master, sel.carrying(), choice)
    lines = []
    for row in master.layout.rows():
        words = [t for t, _ in rows[row.id]] if row.id in rows else [w.text for w in row.words]
        lines.append(" ".join(edit(words) if row.id == pt.row_id else words))
    return "\n".join(lines)


def test_dense_edits_lower_confidence_or_drop_the_point(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    x = derive_codeword(SECRET, master.doc_hash, "padat", p)
    choice = lx.choices_for_codeword(slots, x, sel.points)
    pt = next(q for q in sel.carrying() if not any(o.row_id == q.row_id and o is not q for o in sel.carrying()))
    pos = set(next(s for s in slots if sel.points[s.ref[0]].point_id == pt.point_id).positions)
    left, right, _, _ = ref.context(pt.point_id)
    assert left or right

    def stutter(words):  # three edits glued to the phrase
        return words[:pt.start] + ["xyz" + words[pt.start]] + words[pt.start + 1:]

    sb = decode_lexical(_text_with_row_edit(master, sel, choice, pt, stutter), ref, sel.points, slots)
    near = [abs(v) for q, v in zip(sb.positions, sb.llr) if int(q) in pos]
    assert not near or max(near) <= CLUSTER_MAX_LLR  # kept at most with a low weight

    def reword(words):  # the phrase and its neighbours rewritten
        lo, hi = max(0, pt.start - 2), pt.start + 3
        return words[:lo] + ["qwrtpsdfghjk", "zxcvbnmqwrtp", "plkmjnhbgv"] + words[hi:]

    sb = decode_lexical(_text_with_row_edit(master, sel, choice, pt, reword), ref, sel.points, slots)
    assert all(int(q) not in pos for q in sb.positions) and sb.meta["points_absent"] >= 1
    empty = decode_lexical("", ref, sel.points, slots)
    assert len(empty) == 0 and empty.meta["points_absent"] == empty.meta["points_total"]


def test_inconsistent_slots_are_never_read(doc):
    master, sel = doc
    params, p, slots = _plan(master, sel)
    ref = LexReference(master, sel.carrying())
    x = derive_codeword(SECRET, master.doc_hash, "x", p)
    text = lx.copy_text(master, sel.carrying(), lx.choices_for_codeword(slots, x, sel.points))
    wrong_points = [lx.LexPoint(q.point_id, q.page, q.row, q.start, q.end, q.rule_id, q.forms[:1], q.context,
                                STATUS_APPROVED) for q in sel.points]
    sb = decode_lexical(text, ref, wrong_points, slots)
    assert len(sb) == 0 and sb.meta["points_inconsistent"] == len(slots)
    with pytest.raises(ValueError):
        lx.choices_for_codeword(slots, x, wrong_points)


def test_position_map_and_phrase_ops():
    f = position_map("abcdef", "abXdef")
    assert list(f) == [0, 1, 2, 3, 4, 5, 6]
    f = position_map("abcdef", "abdef")
    assert f[0] == 0 and f[3] == 2 and f[-1] == 5
    assert list(position_map("", "abc")) == [3]
    from tapak.decoder.ch_semantic import alignment_ops

    # pattern "kiri dan kanan": edits far from the form are left out, edits at the form kept
    ops = alignment_ops("kiri dan kanan", "kxyzri dan kanan")
    assert ops.count("M") < len(ops) and phrase_ops(ops, 5, 8, margin=1) == "MMMMM"
    ops = alignment_ops("kiri dan kanan", "kiri dqqan kanan")
    assert phrase_ops(ops, 5, 8, margin=0).count("I") == 2
    ops = alignment_ops("kiri dan kanan", "kiri xyzdan kanan")  # insertions glued to the form count
    assert phrase_ops(ops, 5, 8, margin=0) == "IIIMMM"


def test_lexical_marks_keep_zero_width_marks_on_unchanged_words():
    """Rows re-justified for a point keep the zero-width marks and homoglyphs of their other
    words, every word stays inside the row's edges, and the lexical bits read back."""
    from tapak.decoder.ch_zerowidth import decode_text, extract_pdf_text
    from tapak.marker.issue import IssueSettings, build_document_plan, marks_for_codeword
    from tapak.marker.layout import extract_layout
    from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW
    from tapak.marker.render import render_copy

    master = load_master(DOCS[0].read_bytes())
    sel = lx.scan_candidates(master)
    for pt in sel.points:
        sel.set_status(pt.point_id, STATUS_APPROVED)
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    settings = IssueSettings(channels=("shift", "zw", "homoglyph", "lexical"))
    plan = build_document_plan(master, params, SECRET, settings.channels, set(), None, None, sel, RETYPE_BAND,
                               sel.shift_excluded_rows(), sel.excluded_words())
    point_rows = sel.shift_excluded_rows()
    shift_rows = {(s.page, s.ref[0]) for s in plan.channel("shift")}
    assert not point_rows & shift_rows  # point rows leave the shift channel only
    zw_in_point_rows = [s for s in plan.channel(CHANNEL_ZW) if (s.page, s.ref[0]) in point_rows]
    assert zw_in_point_rows  # ... their other words still carry text marks
    excluded = sel.excluded_words()
    assert not any((s.page, s.ref[0], s.ref[1]) in excluded for s in plan.channel(CHANNEL_ZW))
    p = derive_bias(SECRET, master.doc_hash, params)
    x = derive_codeword(SECRET, master.doc_hash, "salinan-uji", p)
    marks, _ = marks_for_codeword(master, plan, x, settings, None, None, sel)
    assert set(marks.row_words) == point_rows
    pdf = render_copy(master, marks)
    text = extract_pdf_text(pdf)
    zw, hg = decode_text(text, master, plan)
    assert zw.meta["slots_read"] == zw.meta["slots_total"] and np.all((zw.llr > 0) == (x[zw.positions] == 1))
    assert hg.meta["slots_read"] == hg.meta["slots_total"]
    sb = decode_lexical(text, LexReference(master, sel.carrying()), sel.points, plan.channel(CHANNEL_LEXICAL))
    assert len(sb) == sel.bits and np.all((sb.llr > 0) == (x[sb.positions] == 1))
    copy_layout = extract_layout(pdf)
    edges = lx.page_edges(master)
    for rid in point_rows:
        row = master.layout.row(rid)
        drawn = next(r for r in copy_layout.pages[rid[0]].rows if abs(r.baseline - row.baseline) < 0.5)
        assert drawn.words[0].x0 >= row.words[0].x0 - 0.05
        assert drawn.words[-1].x1 <= edges[rid[0]] + lx.EDGE_TOL
    assert CHANNEL_HOMOGLYPH in {s.channel for s in plan.slots}


def test_capacity_verdict_says_enough_only_from_64_bits():
    assert "cukup untuk satu pembocor" in lx.capacity_verdict(lx.LONE_LEAKER_BITS)
    assert "tidak tahan kolusi" in lx.capacity_verdict(100)
    low = lx.capacity_verdict(lx.LONE_LEAKER_BITS - 1)
    assert "belum cukup" in low and "cukup untuk satu pembocor" not in low


def test_retype_noise_model_is_reproducible():
    text = "Sehubungan dengan hal tersebut, latihan posko terpadu dilaksanakan untuk menguji prosedur."
    a = retype(text, random.Random(4), "berat")
    assert a == retype(text, random.Random(4), "berat") and set(LEVELS) == {"ringan", "sedang", "berat", "ocr"}
    rng = random.Random(9)
    assert sum(ch != " " for ch in typo("prosedur", rng)) in (7, 8, 9)
    assert ocr_confusion("modern", random.Random(1)) != "modern" and ocr_confusion("xyz", rng) == "xyz"
    assert apply_habit({"l0": 1, "l1": 1}, random.Random(2), 1.0) == {"l0": 0, "l1": 0}
    assert apply_habit({"l0": 1}, random.Random(2), 0.0) == {"l0": 1}
    assert retype("", random.Random(1)) == ""
    assert STATUS_PENDING == "menunggu"
