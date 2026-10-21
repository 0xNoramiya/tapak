"""Channel 4 (semantic variants): units, safety rules, layout fit, review gate, decoding."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from tapak.decoder.ch_semantic import alignment_ops, decode_semantic, densest_edits, semiglobal_distance
from tapak.llm import get_provider
from tapak.llm.llamacpp import (
    DEFAULT_SERVER_URL,
    MODEL_ENV,
    LlamaCppProvider,
    build_judge_prompt,
    build_paraphrase_prompt,
    parse_judge_answer,
    parse_numbered_lines,
    validate_local_url,
)
from tapak.llm.mock import MockProvider
from tapak.llm.provider import LLMProvider, protected_tokens
from tapak.marker.master import MasterDocument, load_master
from tapak.marker.plan import CHANNEL_SEMANTIC, assign_positions, plan_key
from tapak.marker.render import CopyMarks, render_copy
from tapak.marker.semantic import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    IssuanceBlocked,
    SemanticUnit,
    VariantSet,
    bits_per_unit,
    find_candidate_units,
    fit_variant,
    generate_variant_set,
    make_unit,
    require_approved,
    safety_check,
    scan_candidates,
    semantic_marks,
    semantic_slot_refs,
    usable_indices,
    usable_variants,
    validate_selection,
    variant_sets_digest,
)
from tapak.samplegen import A4, BODY_SIZE, LEADING, MARGIN_BOTTOM, MARGIN_LEFT, _Typesetter
from tapak.tardos.code import random_code
from tapak.tardos.params import TardosParams

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((ROOT / "samples" / "templates").glob("*.json"))
TYPO_RATE = 0.05  # upper bound of the requirement, applied to every trial


@pytest.fixture(autouse=True)
def _no_model_from_environment(monkeypatch):
    """A model path in the developer's shell would make LlamaCppProvider require llama_cpp."""
    monkeypatch.delenv(MODEL_ENV, raising=False)


@pytest.fixture(scope="module")
def master(sample_pdf: bytes) -> MasterDocument:
    return load_master(sample_pdf)


@pytest.fixture(scope="module")
def units(master: MasterDocument) -> list[SemanticUnit]:
    return find_candidate_units(master)


def _approve_all(vs: VariantSet) -> VariantSet:
    for i in vs.pending():
        vs.set_status(i, STATUS_APPROVED)
    return vs


@pytest.fixture(scope="module")
def approved_sets(master, units) -> dict[str, VariantSet]:
    provider = get_provider("mock")
    return {u.unit_id: _approve_all(generate_variant_set(master, u, provider, n_candidates=15)) for u in units}


def _leaked_text(master: MasterDocument, units: list[SemanticUnit], sets: dict[str, VariantSet],
                 variant_ids: list[str]) -> str:
    """Master text row by row, each unit's rows replaced by the chosen variant."""
    chosen = {}
    for vid in variant_ids:
        uid, v = vid.split(":v")
        chosen[uid] = sets[uid].variants[int(v)]
    first_row = {u.row_ids[0]: u.unit_id for u in units if u.unit_id in chosen}
    unit_rows = {rid for u in units if u.unit_id in chosen for rid in u.row_ids}
    lines = []
    for row in master.layout.rows():
        if row.id in first_row:
            lines.append(chosen[first_row[row.id]])
        elif row.id not in unit_rows:
            lines.append(row.text)
    return "\n".join(lines)


def _typos(text: str, rate: float, rng: np.random.Generator) -> str:
    """Apply round(rate * len) random single-character inserts, deletes and substitutions."""
    chars = list(text)
    for _ in range(int(round(rate * len(chars)))):
        i = int(rng.integers(len(chars)))
        op = int(rng.integers(3))
        letter = chr(ord("a") + int(rng.integers(26)))
        if op == 0:
            chars.insert(i, letter)
        elif op == 1:
            del chars[i]
        else:
            chars[i] = letter
    return "".join(chars)


# --- providers ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.stem)
def test_mock_gives_four_equivalent_variants_for_opening_and_closing(path):
    template = json.loads(path.read_text(encoding="utf-8"))
    provider = MockProvider()
    for key in ("pembuka", "penutup"):
        sentence = template[key]
        variants = provider.paraphrase(sentence, 10)
        assert len(set(variants)) >= 4, (key, variants)
        assert sentence not in variants
        for v in variants:
            assert provider.judge_equivalent(sentence, v)[0], v
            assert protected_tokens(v) == protected_tokens(sentence)
    assert provider.paraphrase(template["penutup"], 10) == provider.paraphrase(template["penutup"], 10)


def test_mock_judge_rejects_meaning_changes():
    provider = MockProvider()
    original = "Demikian nota dinas ini disampaikan untuk menjadi perhatian dan dilaksanakan dengan penuh tanggung jawab."
    assert provider.judge_equivalent(original, original.replace("Demikian", "Demikianlah"))[0]
    for bad in (
        original.replace("dilaksanakan", "dibatalkan"),               # key verb changed
        original.replace("untuk menjadi", "tidak untuk menjadi"),     # negation added
        original.replace("nota dinas", "nota dinas Brigade"),         # name added
        original + " pada 07.00",                                     # time added
        original.replace("perhatian dan ", ""),                       # information removed
    ):
        ok, reason = provider.judge_equivalent(original, bad)
        assert not ok and reason


def test_mock_paraphrase_stays_fast_on_long_sentences():
    provider = MockProvider()
    sentence = " ".join(["Demikian disampaikan untuk menjadi perhatian dengan penuh tanggung jawab."] * 5)
    assert len(provider._spans(sentence)) == 20
    t0 = time.perf_counter()
    variants = provider.paraphrase(sentence, 6)
    assert time.perf_counter() - t0 < 1.0
    assert len(set(variants)) == 6 and sentence not in variants
    assert all(provider.judge_equivalent(sentence, v)[0] for v in variants)


def test_get_provider_factory():
    assert isinstance(get_provider(), MockProvider)
    assert isinstance(get_provider("llamacpp"), LlamaCppProvider)
    with pytest.raises(ValueError, match="tidak dikenal"):
        get_provider("cloud")
    with pytest.raises(ValueError, match="mesin ini"):
        get_provider("llamacpp", server_url="http://203.0.113.5:8080/completion")


# --- llama.cpp helpers (no model, no network) ---------------------------------------------


@pytest.mark.parametrize("url", [
    DEFAULT_SERVER_URL, "http://localhost:8080/completion", "https://127.0.0.2/x",
    "http://[::1]:8080/completion",
])
def test_validate_local_url_accepts_loopback(url):
    assert validate_local_url(url) == url


@pytest.mark.parametrize("url", [
    "http://10.0.0.5:8080/completion", "http://example.com/completion",
    "http://127.0.0.1.example.com/", "http://localhost.example.com/", "http://0.0.0.0:8080/",
    "ftp://127.0.0.1/", "file:///etc/passwd", "http://127.0.0.1:99999/", "127.0.0.1:8080",
    "http://evil.com\\@127.0.0.1/completion", "http://user@127.0.0.1/", "http://user:pw@localhost:8080/",
])
def test_validate_local_url_refuses_others(url):
    with pytest.raises(ValueError):
        validate_local_url(url)


def test_prompts_are_indonesian_and_contain_the_input():
    s = "Demikian untuk dilaksanakan dan dilaporkan pelaksanaannya."
    p = build_paraphrase_prompt(s, 5)
    assert s in p and "5 parafrase" in p and "angka" in p and "1., 2." in p
    j = build_judge_prompt(s, s.replace("Demikian", "Demikianlah"))
    assert "A: " + s in j and "YA atau TIDAK" in j


def test_parse_numbered_lines():
    answer = (
        "Berikut parafrasenya:\n"
        "1. Demikianlah untuk dilaksanakan.\n"
        "2) \"Demikian agar dilaksanakan.\"\n"
        "   3.   Demikian   untuk  dilaksanakan.  \n"
        "catatan tanpa nomor\n"
        "4. Demikianlah untuk dilaksanakan.\n"
        "5. **Demikian agar dilaksanakan dan dilaporkan.**\n"
    )
    assert parse_numbered_lines(answer) == [
        "Demikianlah untuk dilaksanakan.", "Demikian agar dilaksanakan.", "Demikian untuk dilaksanakan.",
        "Demikian agar dilaksanakan dan dilaporkan.",
    ]
    assert parse_numbered_lines(answer, limit=1) == ["Demikianlah untuk dilaksanakan."]
    assert parse_numbered_lines("") == []


def test_parse_judge_answer():
    assert parse_judge_answer("YA: hanya sinonim") == (True, "hanya sinonim")
    assert parse_judge_answer("\n  tidak - makna berubah\nlainnya") == (False, "makna berubah")
    assert parse_judge_answer("**YA**") == (True, "setara")
    assert parse_judge_answer("mungkin")[0] is False
    assert parse_judge_answer("")[0] is False


def test_llamacpp_judge_checks_protected_tokens_before_the_model(monkeypatch):
    provider = LlamaCppProvider()

    def no_model(*_a, **_k):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(provider, "complete", no_model)
    ok, reason = provider.judge_equivalent("Demikian disampaikan.", "Demikian disampaikan kepada Danyon.")
    assert not ok and "token" in reason


@pytest.mark.skipif(importlib.util.find_spec("llama_cpp") is not None, reason="llama_cpp is installed")
def test_llamacpp_configured_model_without_library_is_an_error(monkeypatch):
    with pytest.raises(RuntimeError, match="llama_cpp tidak terpasang"):
        LlamaCppProvider(model_path="model-7b.gguf")
    monkeypatch.setenv(MODEL_ENV, "model-7b.gguf")
    with pytest.raises(RuntimeError, match="llama_cpp tidak terpasang"):
        get_provider("llamacpp")


class _FakeServer(BaseHTTPRequestHandler):
    """Loopback stand-in for llama-server: path /teks answers non-JSON, /alih redirects."""

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/alih":
            self.send_response(302)
            self.send_header("Location", "http://203.0.113.5/completion")
            self.end_headers()
            return
        body = b"bukan json" if self.path == "/teks" else json.dumps({"content": "1. Demikianlah."}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # keep test output clean
        pass


def test_llamacpp_http_errors_are_indonesian():
    with socket.socket() as probe:  # a loopback port with nothing listening
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    with pytest.raises(RuntimeError, match="tidak dapat dihubungi"):
        LlamaCppProvider(server_url=f"http://127.0.0.1:{closed}/completion", timeout=5).complete("uji")
    server = HTTPServer(("127.0.0.1", 0), _FakeServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert LlamaCppProvider(server_url=base + "/completion").paraphrase("Demikian.", 3) == ["Demikianlah."]
        with pytest.raises(RuntimeError, match="tidak dapat dibaca"):
            LlamaCppProvider(server_url=base + "/teks").complete("uji")
        with pytest.raises(RuntimeError, match="menolak permintaan"):
            LlamaCppProvider(server_url=base + "/alih").complete("uji")
    finally:
        server.shutdown()
        server.server_close()


# --- units and safety ---------------------------------------------------------------------


def test_candidate_units_found_for_opening_and_closing(master, units):
    by_text = {u.text.split()[0]: u for u in units}
    pembuka, penutup = by_text["Dengan"], by_text["Demikian"]
    assert (pembuka.page, pembuka.rows, pembuka.justified) == (0, (12, 13), (True, False))
    assert pembuka.text.endswith("sebagai berikut.")
    assert (penutup.page, penutup.rows, penutup.justified) == (1, (18, 19), (True, False))
    assert penutup.text.endswith("tanggung jawab.")
    assert [u.unit_id for u in units] == ["u0", "u1"]
    assert SemanticUnit.from_dict(json.loads(json.dumps(penutup.to_dict()))) == penutup


def test_candidate_units_surat_telegram():
    other = load_master((ROOT / "samples" / "surat_telegram.pdf").read_bytes())
    texts = [u.text for u in find_candidate_units(other)]
    assert any(t.startswith("Bersama ini") for t in texts)
    assert "Demikian untuk dilaksanakan dan dilaporkan pelaksanaannya." in texts


SAFE_LONG = (
    "Demikian nota dinas ini disampaikan untuk menjadi perhatian dan pedoman bersama bagi seluruh jajaran "
    "penerima naskah, sehingga setiap pihak dapat memahami maksud dan tujuan kegiatan dengan baik, menjaga "
    "kerahasiaan isi naskah dengan penuh tanggung jawab, memelihara ketertiban administrasi di lingkungan "
    "masing-masing, serta mendukung kelancaran koordinasi antarbagian sesuai dengan ketentuan yang berlaku "
    "di lingkungan organisasi, demi terwujudnya tertib administrasi yang baik dan teratur bagi semua pihak "
    "yang berkepentingan dalam pengelolaan naskah dinas di lingkungan kerja masing-masing."
)
CONTROL = "Demikian untuk menjadi perhatian dan pedoman bersama."


@pytest.fixture(scope="module")
def fragment_master() -> MasterDocument:
    """A typeset page with every way a trigger row can start a sentence fragment, plus one whole sentence."""
    ts = _Typesetter("RAHASIA")
    ts.gap(10)
    ts.paragraph(SAFE_LONG)                                   # 9 rows: more than MAX_UNIT_ROWS
    ts.gap(8)
    ts.paragraph(CONTROL)                                     # a whole one-row sentence
    ts.gap(8)
    ts.line("kalimat pengantar ini sengaja dibiarkan menggantung dan")
    ts.line("Demikian pula halnya dengan seluruh jajaran penerima naskah.")  # starts mid-sentence
    ts.gap(8)
    ts.paragraph("Demikian nota dinas ini disampaikan untuk menjadi perhatian dan pedoman bersama bagi "
                 "seluruh jajaran penerima naskah tanpa terkecuali.", first_x=MARGIN_LEFT + 30)  # indent
    ts.gap(A4[1] - MARGIN_BOTTOM - ts.pen.y - 1.5 * BODY_SIZE * LEADING)
    ts.paragraph("Demikian nota dinas ini disampaikan untuk menjadi perhatian dan dilaksanakan dengan penuh "
                 "tanggung jawab oleh seluruh jajaran penerima naskah.")  # split by the page break
    return load_master(ts.finish())


def test_sentence_fragments_are_never_offered(fragment_master):
    assert safety_check(SAFE_LONG) == []  # the long paragraph is refused for its shape only
    scanned = scan_candidates(fragment_master)
    offered = find_candidate_units(fragment_master)
    assert [u.text for u in offered] == [CONTROL]
    refused = [(u, why) for u, why in scanned if why]
    assert len(refused) == 4
    for unit, why in refused:
        assert any("kalimat utuh" in r for r in why), (unit.rows, why)
    long_unit = refused[0][0]
    assert len(long_unit.rows) == 6 and SAFE_LONG.startswith(long_unit.text) and long_unit.text != SAFE_LONG
    assert any("sebelumnya" in r for r in refused[1][1])            # starts after an unfinished row
    assert refused[2][0].left_x > MARGIN_LEFT + 20                   # the indented first row alone
    assert refused[3][0].page == 0 and len(fragment_master.layout.pages) == 2  # cut by the page break


def test_custom_fragment_unit_cannot_get_variants(master, units):
    penutup = units[1]
    fragment = make_unit(master, "potongan", penutup.page, penutup.rows[:1])
    with pytest.raises(ValueError, match="tidak boleh diparafrasekan"):
        generate_variant_set(master, fragment, MockProvider())


def test_tembusan_lines_are_scanned_but_never_offered(master, units):
    refused = [(u, r) for u, r in scan_candidates(master) if r]
    assert any(u.text.endswith("Arsip") for u, _ in refused)
    assert all(any("angka" in x or "kapital" in x for x in r) for _, r in refused)
    offered = {u.text for u in units}
    assert not offered & {u.text for u, _ in refused}


@pytest.mark.parametrize("sentence, expected", [
    ("Demikian disampaikan untuk diketahui oleh 3 satuan jajaran.", "angka"),
    ("Demikian disampaikan agar hadir pukul 07.00 di lapangan.", "waktu"),
    ("Demikian disampaikan bahwa pos berada pada koordinat yang ditentukan.", "koordinat"),
    ("Demikian disampaikan kepada Letkol Inf Contoh Nama Fiktif sebagai berikut.", "kapital"),
    ("Demikian agar segera dilaksanakan oleh seluruh satuan.", "perintah"),
    ("Laksanakan pengamanan dokumen dengan penuh tanggung jawab dan wajib dilaporkan.", "perintah"),
    ("Demikian disampaikan bahwa penggandaan dokumen dilarang bagi semua pihak.", "perintah"),
    ("Demikian disampaikan bahwa kegiatan tidak dilanjutkan sampai ada keputusan.", "ingkar"),
    ("Demikian disampaikan bahwa dua regu disiapkan sebagai cadangan.", "bilangan"),
    ("Demikian.", "pendek"),
    # affixed order and deadline words, extra negations, time and quantity words
    ("Demikian disampaikan bahwa semua penerima diwajibkan menyimpan naskah ini.", "perintah"),
    ("Demikian disampaikan bahwa pimpinan melarang penggandaan naskah ini.", "perintah"),
    ("Demikian agar laporan dikirim secepatnya kepada staf operasi.", "perintah"),
    ("Demikian agar laporan dikirim selambat-lambatnya kepada staf operasi.", "perintah"),
    ("Demikian agar laporan dikirim paling lambat kepada staf operasi.", "perintah"),
    ("Demikian disampaikan agar regu menyerang sasaran yang ditentukan.", "perintah"),
    ("Demikian disampaikan bahwa penjaga dapat menembak di tempat.", "perintah"),
    ("Demikian disampaikan bahwa seluruh pos disiagakan sampai ada keputusan.", "perintah"),
    ("Demikian disampaikan bahwa kegiatan tak dapat dilanjutkan.", "ingkar"),
    ("Demikian disampaikan bahwa kegiatan tiada dilanjutkan oleh satuan.", "ingkar"),
    ("Demikian disampaikan agar kegiatan dimulai pagi ini juga.", "waktu"),
    ("Demikian disampaikan bahwa rapat diundur ke minggu depan.", "waktu"),
    ("Demikian disampaikan bahwa setengah kompi ditempatkan di pos.", "bilangan"),
    ("Demikian disampaikan kepada satuan kedua untuk menjadi perhatian.", "bilangan"),
    ("Demikian disampaikan bahwa puluhan personel dilibatkan dalam kegiatan.", "bilangan"),
])
def test_safety_check_rejects_unsafe_sentences(sentence, expected):
    reasons = safety_check(sentence)
    assert any(expected in r for r in reasons), reasons


def test_safety_reasons_name_categories_not_document_words(master):
    reasons = safety_check("Demikian disampaikan kepada Letkol Contoh agar segera hadir pukul 07.00.")
    assert len(reasons) >= 4
    for word in ("Letkol", "Contoh", "segera", "07.00", "pukul"):
        assert all(word not in r for r in reasons)
    for unit, why in scan_candidates(master):
        for word in unit.text.split():
            if len(word) > 3:
                assert all(word not in r for r in why), (word, why)


def test_safety_check_allows_formulas():
    for s in ("Dengan hormat, bersama ini kami sampaikan arahan persiapan latihan sebagai berikut.",
              "Demikian nota dinas ini disampaikan untuk menjadi perhatian dan dilaksanakan dengan penuh tanggung jawab.",
              "Demikian untuk dilaksanakan dan dilaporkan pelaksanaannya.",
              "Bersama ini disampaikan kepada para komandan satuan jajaran hal-hal sebagai berikut."):
        assert safety_check(s) == []


# --- layout fit ---------------------------------------------------------------------------


def test_fit_original_reproduces_master_positions(master, units):
    for unit in units:
        fitted = fit_variant(master, unit, unit.text)
        assert fitted is not None and set(fitted) == set(unit.row_ids)
        for rid, placed in fitted.items():
            row = master.layout.row(rid)
            assert [w for _, w in placed] == [w.text for w in row.words]
            assert max(abs(x - w.x0) for (x, _), w in zip(placed, row.words)) < 0.5


def test_fit_variant_keeps_rows_edges_and_alignment(master, units, approved_sets):
    for unit in units:
        g0 = master.layout.row(unit.row_ids[0]).words[0].glyphs[0]
        font, size = master.fonts[g0.font].font, g0.size
        for text in approved_sets[unit.unit_id].variants:
            fitted = fit_variant(master, unit, text)
            assert fitted is not None, text
            assert " ".join(w for rid in unit.row_ids for _, w in fitted[rid]) == text
            for k, rid in enumerate(unit.row_ids):
                (x0, _), (xl, wl) = fitted[rid][0], fitted[rid][-1]
                assert abs(x0 - unit.left_x) < 1e-6
                right = xl + font.text_length(wl, size)
                if unit.justified[k]:
                    assert abs(right - unit.right_x) < 0.01
                assert right <= unit.right_x + 0.5


def test_fit_variant_refuses_other_row_counts(master, units):
    penutup = units[1]
    assert fit_variant(master, penutup, "Demikian nota dinas ini disampaikan.") is None
    assert fit_variant(master, penutup, penutup.text + " " + penutup.text) is None
    assert fit_variant(master, penutup, "") is None
    assert fit_variant(master, penutup, "Demikian " + "a" * 120 + " nota dinas ini.") is None


# --- variant sets and review gate ---------------------------------------------------------


def test_generate_variant_set_statuses_and_json(master, units):
    vs = generate_variant_set(master, units[1], MockProvider())
    assert vs.variants[0] == units[1].text and vs.status[0] == STATUS_APPROVED
    assert len(vs.variants) == 7 and vs.status[1:] == [STATUS_PENDING] * 6
    assert all(ok for ok, _ in vs.equivalence)
    assert len({v.lower() for v in vs.variants}) == len(vs.variants)
    again = VariantSet.from_dict(json.loads(json.dumps(vs.to_dict())))
    assert again == vs
    with pytest.raises(ValueError):
        vs.set_status(0, STATUS_REJECTED)
    with pytest.raises(ValueError):
        vs.set_status(1, "mungkin")


class _ScriptedProvider(LLMProvider):
    """Returns fixed candidates; accepts every candidate except those containing 'ditolak'."""

    name = "uji"

    def __init__(self, candidates: list[str]) -> None:
        self.candidates = candidates

    def paraphrase(self, sentence: str, n: int) -> list[str]:
        return self.candidates[:n]

    def judge_equivalent(self, original: str, candidate: str) -> tuple[bool, str]:
        return ("ditolak" not in candidate, "uji")


def test_generate_drops_unsafe_candidates(master, units):
    penutup = units[1]
    good = penutup.text.replace("Demikian ", "Demikianlah ")
    bad = [
        penutup.text,                                                    # identical
        penutup.text.replace("nota dinas", "nota dinas Brigade"),       # capitalized word added
        penutup.text.replace("dengan penuh", "segera dengan penuh"),    # order word
        penutup.text.replace("ini disampaikan", "ini disampaikan 2 kali"),  # digit
        penutup.text.replace("tanggung jawab.", "tanggung jawab"),      # duplicate after normalizing
        penutup.text + " Hal ini berlaku untuk seluruh jajaran tanpa terkecuali sampai akhir tahun.",
        penutup.text.replace("Demikian ", "Demikian ditolak "),          # judge says no
        penutup.text.replace("dan dilaksanakan", "dan tak dilaksanakan"),  # negation "tak" added
        penutup.text.replace("disampaikan", "diberitahukan").rstrip("."),  # final period lost
        penutup.text.replace("untuk menjadi", "**agar menjadi**"),       # markdown from a chat model
    ]
    vs = generate_variant_set(master, penutup, _ScriptedProvider([good] + bad), n_candidates=20)
    assert vs.variants == [penutup.text, good]
    assert vs.unit_key == penutup.fingerprint
    assert len(vs.dropped) == len(bad)
    assert all(reason for _, reason in vs.dropped)
    reasons = [r for _, r in vs.dropped]
    assert "token terlindungi" in reasons[-3]
    assert reasons[-2] == "tanda akhir kalimat berubah"
    assert "tanda baca" in reasons[-1]


def test_usable_variants_power_of_two(master, units):
    vs = generate_variant_set(master, units[1], MockProvider(), n_candidates=6)
    assert usable_variants(vs) == [vs.variants[0]] and bits_per_unit(vs) == 0
    vs.set_status(1, STATUS_APPROVED)
    vs.set_status(2, STATUS_REJECTED)
    vs.set_status(3, STATUS_APPROVED)
    vs.set_status(4, STATUS_APPROVED)
    assert usable_variants(vs) == [vs.variants[i] for i in (0, 1, 3, 4)] and bits_per_unit(vs) == 2
    vs.set_status(5, STATUS_APPROVED)
    assert len(usable_variants(vs)) == 4


def test_issuance_blocked_until_variants_reviewed(master, units):
    provider = MockProvider()
    sets = {u.unit_id: generate_variant_set(master, u, provider) for u in units}
    with pytest.raises(IssuanceBlocked, match="menunggu persetujuan"):
        require_approved(sets)
    with pytest.raises(IssuanceBlocked):
        semantic_slot_refs(units, sets)
    with pytest.raises(IssuanceBlocked):
        semantic_marks([], np.zeros(8, dtype=np.uint8), master, units, sets)
    for vs in sets.values():
        for i in vs.pending():
            vs.set_status(i, STATUS_APPROVED if i % 2 else STATUS_REJECTED)
    require_approved(sets)
    assert [b for _, _, b in semantic_slot_refs(units, sets)] == [2, 2]
    assert len(variant_sets_digest(sets)) == 64


def test_set_status_refuses_bad_indices(master, units):
    vs = generate_variant_set(master, units[1], MockProvider(), n_candidates=3)
    for bad in (-1, -3, len(vs.variants), 99):
        with pytest.raises(ValueError, match="indeks varian tidak valid"):
            vs.set_status(bad, STATUS_REJECTED)
    assert vs.status[0] == STATUS_APPROVED
    vs.status[0] = STATUS_REJECTED  # a corrupted state must not crash the helpers
    assert usable_indices(vs) == [] and bits_per_unit(vs) == 0


def _copy_sets(sets: dict[str, VariantSet]) -> dict[str, VariantSet]:
    return {k: VariantSet.from_dict(json.loads(json.dumps(v.to_dict()))) for k, v in sets.items()}


@pytest.fixture(scope="module")
def other_sets() -> dict[str, VariantSet]:
    """Approved sets of surat_telegram: same unit ids (u0, u1) as nota_dinas, other sentences."""
    other = load_master((ROOT / "samples" / "surat_telegram.pdf").read_bytes())
    provider = MockProvider()
    return {u.unit_id: _approve_all(generate_variant_set(other, u, provider, n_candidates=7))
            for u in find_candidate_units(other)}


def test_variant_sets_are_bound_to_their_unit(master, units, approved_sets, other_sets, secret):
    assert set(other_sets) == {u.unit_id for u in units}
    with pytest.raises(ValueError, match="tidak cocok dengan unit"):
        semantic_slot_refs(units, other_sets)
    with pytest.raises(IssuanceBlocked, match="tidak cocok dengan unit"):
        semantic_marks([], np.zeros(64, dtype=np.uint8), master, units, other_sets)
    slots = assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(units, approved_sets), 64,
                             plan_key(secret, master.doc_hash))
    text = "\n".join(r.text for r in master.layout.rows())
    sb = decode_semantic(text, units, other_sets, slots)
    assert len(sb) == 0 and sb.meta["slots_inconsistent"] == len(slots)
    # one unit edited (different right edge): its set no longer matches
    edited = [units[0], dataclasses.replace(units[1], right_x=units[1].right_x - 5.0)]
    with pytest.raises(ValueError, match="tidak cocok dengan unit u1"):
        semantic_slot_refs(edited, approved_sets)
    # order, missing and extra sets
    with pytest.raises(ValueError, match="urutan baca"):
        semantic_slot_refs(units[::-1], approved_sets)
    with pytest.raises(ValueError, match="tidak memiliki himpunan varian"):
        semantic_slot_refs(units, {"u0": approved_sets["u0"]})
    with pytest.raises(ValueError, match="tanpa unit"):
        semantic_slot_refs(units[:1], approved_sets)
    # the digest covers the unit through unit_key
    moved = _copy_sets(approved_sets)
    moved["u1"].unit_key = edited[1].fingerprint
    assert variant_sets_digest(moved) != variant_sets_digest(approved_sets)
    assert variant_sets_digest(_copy_sets(approved_sets)) == variant_sets_digest(approved_sets)


def test_validate_selection_rechecks_approved_variants(master, units, approved_sets):
    validate_selection(master, units, approved_sets)
    for edit, why in ((lambda v: v.replace("nota dinas", "nota dinas 2"), "token terlindungi"),
                      (lambda v: v.replace("dengan penuh", "dengan penuh kecermatan dan ketelitian serta "
                                           "kesungguhan hati dan kehati-hatian dan penuh"), "muat"),
                      (lambda v: v.rstrip(".") + "!", "tanda baca")):
        sets = _copy_sets(approved_sets)
        sets["u1"].variants[3] = edit(sets["u1"].variants[3])  # hand-edited varian.json
        with pytest.raises(IssuanceBlocked, match=f"u1:v3: .*{why}"):
            semantic_marks([], np.zeros(64, dtype=np.uint8), master, units, sets)
    unsafe = dataclasses.replace(units[1], text=units[1].text.replace("ini", "ini segera"))
    sets = _copy_sets(approved_sets)
    sets["u1"].unit_key = unsafe.fingerprint
    sets["u1"].variants[0] = unsafe.text
    with pytest.raises(IssuanceBlocked, match="tidak cocok dengan dokumen induk"):
        validate_selection(master, [units[0], unsafe], sets)


# --- end to end ---------------------------------------------------------------------------


def test_end_to_end_20_recipients_with_typos(master, units, approved_sets, secret):
    params = TardosParams(c=3, eps=1e-6, n_max=20)
    rng = np.random.default_rng(20261103)
    _, codewords = random_code(params, 20, rng)
    refs = semantic_slot_refs(units, approved_sets)
    assert [b for _, _, b in refs] == [4, 4]
    slots = assign_positions(CHANNEL_SEMANTIC, refs, params.length, plan_key(secret, master.doc_hash))
    exact = 0
    seen_variants: set[str] = set()
    for x in codewords:
        row_words, ids = semantic_marks(slots, x, master, units, approved_sets)
        assert set(row_words) == {rid for u in units for rid in u.row_ids}
        seen_variants.update(ids)
        leaked = _typos(_leaked_text(master, units, approved_sets, ids), TYPO_RATE, rng)
        sb = decode_semantic(leaked, units, approved_sets, slots)
        expected = {p: int(x[p]) for s in slots for p in s.positions}
        decoded = {int(p): int(llr > 0) for p, llr in zip(sb.positions, sb.llr)}
        exact += decoded == expected
    assert exact == 20
    assert len(seen_variants) > 10  # copies really differ


def test_rendered_copy_contains_variant(master, units, approved_sets, secret):
    m = 64
    slots = assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(units, approved_sets), m,
                             plan_key(secret, master.doc_hash))
    x = np.zeros(m, dtype=np.uint8)
    for s in slots:  # choose the last usable variant of every unit
        for p, w in zip(s.positions, s.whiten):
            x[p] = 1 ^ w
    row_words, ids = semantic_marks(slots, x, master, units, approved_sets)
    assert ids == ["u0:v15", "u1:v15"]
    pdf = render_copy(master, CopyMarks(row_words=row_words))
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        extracted = "\n".join(page.get_text() for page in doc)
        assert doc.page_count == 2
    flat = " ".join(extracted.split())
    for vid in ids:
        uid, v = vid.split(":v")
        variant = approved_sets[uid].variants[int(v)]
        assert variant != approved_sets[uid].variants[0]
        assert " ".join(variant.split()) in flat
    sb = decode_semantic(extracted, units, approved_sets, slots)
    assert {int(p): int(llr > 0) for p, llr in zip(sb.positions, sb.llr)} == {
        p: int(x[p]) for s in slots for p in s.positions
    }
    assert np.all(np.abs(sb.llr) == 6.0)


def test_decoder_ignores_text_without_the_units(master, units, approved_sets, secret):
    slots = assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(units, approved_sets), 64,
                             plan_key(secret, master.doc_hash))
    unit_rows = {rid for u in units for rid in u.row_ids}
    body = "\n".join(r.text for r in master.layout.rows() if r.id not in unit_rows)
    for text in (body, "", "Demikian"):
        sb = decode_semantic(text, units, approved_sets, slots)
        assert len(sb) == 0 and sb.meta["slots_absent"] == 2


PRE = "Pelaporan komandan satuan peserta menyampaikan daftar nama."
POST = "Kepala Staf Brigade, Letkol Inf Contoh Nama Fiktif"


def _variant_words(x, slots, master, units, sets) -> list[list[str]]:
    _, ids = semantic_marks(slots, x, master, units, sets)
    return [sets[uid].variants[int(v)].split() for uid, v in (vid.split(":v") for vid in ids)]


def test_decoder_never_reads_wrong_bits_from_cut_off_units(master, units, approved_sets, secret):
    """Excerpts that cut a unit sentence off: skipped as partial, never a wrong bit."""
    slots = assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(units, approved_sets), 64,
                             plan_key(secret, master.doc_hash))
    texts = skipped = 0
    for seed in range(2):
        x = np.random.default_rng(seed).integers(0, 2, 64)
        for words in _variant_words(x, slots, master, units, approved_sets):
            for k in range(len(words) // 2, len(words)):
                head, tail = " ".join(words[:k]), " ".join(words[-k:])
                for text in (head, tail, f"{PRE} {head}", f"{tail} {POST}", f"{PRE} {head} {POST}",
                             f"{PRE} {tail} {POST}"):
                    sb = decode_semantic(text, units, approved_sets, slots)
                    assert all(int(llr > 0) == int(x[p]) for p, llr in zip(sb.positions, sb.llr)), text
                    texts += 1
                    skipped += len(sb) == 0  # too short to search, or found but partial
    assert skipped >= 0.9 * texts


def test_decoder_gives_low_confidence_when_words_are_left_out_or_added(master, units, approved_sets, secret):
    """A word left out or added may make another variant closer; such reads stay weak (|LLR| <= 2)."""
    slots = assign_positions(CHANNEL_SEMANTIC, semantic_slot_refs(units, approved_sets), 64,
                             plan_key(secret, master.doc_hash))
    for seed in range(2):
        x = np.random.default_rng(seed).integers(0, 2, 64)
        for words in _variant_words(x, slots, master, units, approved_sets):
            for a in range(1, len(words) - 1):
                for changed in (words[:a] + words[a + 1:], words[:a] + ["telah"] + words[a:]):
                    sb = decode_semantic(f"{PRE} {' '.join(changed)} {POST}", units, approved_sets, slots)
                    for p, llr in zip(sb.positions, sb.llr):
                        assert int(llr > 0) == int(x[p]) or abs(llr) <= 2.0, (changed, llr)


def test_alignment_ops_and_edit_density():
    assert alignment_ops("demikian", "xx demikian yy") == "MMMMMMMM"
    ops = alignment_ops("demikianlah nota", "xx demikian nota")
    assert ops.count("M") == 13 and len(ops) - ops.count("M") == semiglobal_distance("demikianlah nota",
                                                                                      "xx demikian nota")
    assert densest_edits("MMS" + "M" * 12 + "D" + "M" * 12 + "I") == 1  # scattered typos
    assert densest_edits("MMS" + "M" * 5 + "D" + "M" * 12 + "I") == 2   # two typos within 10 steps
    assert densest_edits("MMMDDDDDDMMMM") == 6                 # a word left out
    assert densest_edits("SMS") == 2


def test_semiglobal_distance():
    assert semiglobal_distance("demikian", "xx demikian yy") == 0
    assert semiglobal_distance("demikianlah", "xx demikian yy") == 3
    assert semiglobal_distance("demikian", "xx demkian yy") == 1
    assert semiglobal_distance("", "abc") == 0
    assert semiglobal_distance("abc", "") == 3
