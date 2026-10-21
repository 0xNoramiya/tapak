"""DOCX channel 3 (M2): marking Word files, extracting their text, decoding, attribution."""

from __future__ import annotations

import io
import itertools
from pathlib import Path

import numpy as np
import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.text.run import Run

from tapak.decoder.accuse import VERDICT_IDENTIFIED, VERDICT_INSUFFICIENT, CopyRef, attribute
from tapak.decoder.ch_docx import align_docx_tokens, decode_docx, extract_docx_text
from tapak.decoder.ch_zerowidth import tokenize
from tapak.decoder.fuse import fuse, fuse_by_physical_channel
from tapak.decoder.softbits import SoftBits
from tapak.marker.docx_marker import (
    DOCX_HOMOGLYPH_LETTERS,
    DOCX_MAX_ZW_BITS,
    DOCX_ZW_CHARS,
    VERIFIED_FONTS,
    build_docx_plan,
    decode_docx_zw,
    docx_homoglyph_candidates,
    docx_zw_eligible,
    encode_docx_zw,
    font_support,
    issue_docx,
    iter_paragraphs,
    load_docx_master,
    make_sample_docx,
    mark_docx,
    text_runs,
)
from tapak.marker.issue import Recipient
from tapak.marker.layout import sha256_hex
from tapak.marker.master import HOMOGLYPHS, REVERSE_HOMOGLYPHS
from tapak.marker.pdf_zerowidth import ZW_CHARS, encode_zw, normalize_text
from tapak.marker.plan import CHANNEL_HOMOGLYPH, CHANNEL_ZW, plan_key
from tapak.samplegen import FOOTER_TEXT
from tapak.tardos.code import code_digest, derive_bias, derive_codeword
from tapak.tardos.params import TardosParams

SECRET = bytes(range(32))
PARAMS = TardosParams(c=3, eps=1e-6, n_max=20)
CYRILLIC = set(REVERSE_HOMOGLYPHS)
LEAKED = 7
WINDOWS_FONTS = Path("/mnt/c/Windows/Fonts")


# --- fixtures and helpers ------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_path(tmp_path_factory) -> Path:
    return make_sample_docx(tmp_path_factory.mktemp("docx") / "nota_dinas.docx")


@pytest.fixture(scope="module")
def sample(sample_path) -> bytes:
    return sample_path.read_bytes()


@pytest.fixture(scope="module")
def master(sample):
    return load_docx_master(sample)


@pytest.fixture(scope="module")
def plan(master):
    return build_docx_plan(master, PARAMS.length, plan_key(SECRET, master.doc_hash))


def _codeword(doc_hash: str, copy_id: str = "salinan-uji") -> np.ndarray:
    return derive_codeword(SECRET, doc_hash, copy_id, derive_bias(SECRET, doc_hash, PARAMS))


@pytest.fixture(scope="module")
def codeword(master) -> np.ndarray:
    return _codeword(master.doc_hash)


@pytest.fixture(scope="module")
def marked(sample, plan, codeword) -> bytes:
    return mark_docx(sample, plan, codeword)


def _check_bits(sb: SoftBits, x: np.ndarray) -> None:
    assert len(sb) > 0
    assert np.array_equal((sb.llr > 0).astype(np.uint8), x[sb.positions])


def _by_channel(obs: list[SoftBits]) -> dict[str, SoftBits]:
    return {sb.channel: sb for sb in obs}


def _body_runs(data: bytes) -> list:
    doc = Document(io.BytesIO(data))
    return [r for p in iter_paragraphs(doc.element.body) for r in text_runs(p)]


def _styled_chars(data: bytes) -> list[tuple[str, tuple]]:
    """Visible body characters with their direct run formatting (marks and noProof ignored)."""
    out = []
    for r in _body_runs(data):
        f = Run(r, None).font
        fmt = (f.bold, f.italic, f.underline, f.size, f.name, f.small_caps, f.all_caps)
        for ch in r.text:
            if ch not in ZW_CHARS:
                out.append((REVERSE_HOMOGLYPHS.get(ch, ch), fmt))
    return out


def _save(doc) -> bytes:
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _round_trip(data: bytes) -> tuple[object, bytes, np.ndarray]:
    """Mark ``data`` with a test codeword and check every slot decodes; return (master, copy, x)."""
    master = load_docx_master(data)
    plan = build_docx_plan(master, PARAMS.length, plan_key(SECRET, master.doc_hash))
    x = _codeword(master.doc_hash)
    copy = mark_docx(data, plan, x)
    obs = _by_channel(decode_docx(extract_docx_text(copy), master, plan))
    for name in (CHANNEL_ZW, CHANNEL_HOMOGLYPH):
        if plan.channel(name):
            _check_bits(obs[name], x)
            assert obs[name].meta["slots_read"] == obs[name].meta["slots_total"]
    assert normalize_text(extract_docx_text(copy)) == extract_docx_text(data)
    assert _styled_chars(copy) == _styled_chars(data)
    return master, copy, x


# --- sample document -----------------------------------------------------------------


def test_sample_docx_is_synthetic_and_structured(sample, master):
    doc = Document(io.BytesIO(sample))
    footer = "\n".join(p.text for p in doc.sections[0].footer.paragraphs)
    assert FOOTER_TEXT in footer
    assert len(doc.tables) == 1 and doc.tables[0].cell(0, 0).text == "Kepada"
    assert master.doc_hash == sha256_hex(sample)
    # Master words follow the displayed body text, paragraphs and tables in order.
    assert master.texts == extract_docx_text(sample).split()
    assert master.texts[:2] == ["KOMANDO", "LATIHAN"] and "Kepada" in master.texts
    assert master.unverified_fonts == []  # Arial everywhere


def test_sample_docx_is_reproducible(tmp_path, sample):
    again = make_sample_docx(tmp_path / "lagi.docx").read_bytes()
    assert again == sample  # same doc_hash on every regeneration


def test_eligibility_rules():
    assert DOCX_HOMOGLYPH_LETTERS == set(HOMOGLYPHS)
    assert docx_zw_eligible("dokumen") and docx_zw_eligible("Yth.")
    assert not docx_zw_eligible("9905/Latihan") and not docx_zw_eligible("06.00")
    assert not docx_zw_eligible("kata\u200b")
    assert docx_homoglyph_candidates("dokumen") == [1, 5]
    assert docx_homoglyph_candidates("Dokumen") == []      # capitalized
    assert docx_homoglyph_candidates("dok") == []          # too short
    assert docx_homoglyph_candidates("rapat2") == []       # digit
    assert docx_homoglyph_candidates("tujuan.") == [2, 4]  # j and a; punctuation kept


def test_zero_width_encoding_uses_only_four_symbols():
    assert DOCX_ZW_CHARS == {"\u200b", "\u200c", "\u200d", "\u2060"}
    for n in range(1, DOCX_MAX_ZW_BITS + 1):
        for bits in itertools.product((0, 1), repeat=n):
            prefix, suffix = encode_docx_zw(list(bits))
            assert set(prefix + suffix) <= DOCX_ZW_CHARS
            assert len(prefix) == min(n, 2) and len(suffix) == max(n - 2, 0)
            assert decode_docx_zw(prefix, suffix, n) == list(bits)
    assert decode_docx_zw(*encode_zw([1, 0, 0, 1]), 2) is None  # U+2061 is not a DOCX symbol
    assert decode_docx_zw("\u200c", "", 2) is None              # a symbol is missing
    with pytest.raises(ValueError):
        encode_docx_zw([0] * 5)


def test_plan_skips_digit_words_and_caps_bits_per_word(master, plan):
    assert plan.m == PARAMS.length
    zw_slots = plan.channel(CHANNEL_ZW)
    assert {len(s.positions) for s in zw_slots} == {DOCX_MAX_ZW_BITS}
    assert plan.coverage(CHANNEL_ZW) == min(plan.m, DOCX_MAX_ZW_BITS * len(zw_slots))
    assert len(plan.channel(CHANNEL_HOMOGLYPH)) > 100
    for slot in plan.slots:
        word = master.words[slot.ref[0]].text
        assert not any(ch.isdigit() for ch in word)
    assert plan == build_docx_plan(master, PARAMS.length, plan_key(SECRET, master.doc_hash))


# --- marking and decoding ------------------------------------------------------------


def test_round_trip_decodes_codeword(marked, master, plan, codeword):
    text = extract_docx_text(marked)
    assert not (set(text) & (ZW_CHARS - DOCX_ZW_CHARS))  # never U+2061..U+2064
    obs = _by_channel(decode_docx(text, master, plan))
    for name in (CHANNEL_ZW, CHANNEL_HOMOGLYPH):
        _check_bits(obs[name], codeword)
        assert obs[name].meta["slots_read"] == obs[name].meta["slots_total"] == len(plan.channel(name))
    assert obs[CHANNEL_ZW].meta["slots_broken"] == 0


def test_visible_text_equals_master(marked, sample):
    text = extract_docx_text(marked)
    assert text != extract_docx_text(sample)
    assert normalize_text(text) == extract_docx_text(sample)
    m_doc, s_doc = Document(io.BytesIO(marked)), Document(io.BytesIO(sample))
    for part in ("header", "footer"):
        a = [p.text for p in getattr(m_doc.sections[0], part).paragraphs]
        b = [p.text for p in getattr(s_doc.sections[0], part).paragraphs]
        assert a == b


def test_words_with_digits_get_nothing(marked):
    digit_tokens = [t for t in tokenize(extract_docx_text(marked)) if any(c.isdigit() for c in t.raw)]
    assert digit_tokens
    for tok in digit_tokens:
        assert tok.prefix == "" and tok.suffix == "" and not tok.broken
        assert not CYRILLIC & set(tok.raw)


def test_formatting_preserved_and_bold_stays_bold(marked, sample):
    assert _styled_chars(marked) == _styled_chars(sample)
    # The check is meaningful: some homoglyphs landed in bold runs, which stayed bold.
    bold_swaps = [r for r in _body_runs(marked) if Run(r, None).bold and CYRILLIC & set(r.text)]
    assert bold_swaps
    # No run was split in the sample (fonts agree), so the run structure is unchanged.
    assert len(_body_runs(marked)) == len(_body_runs(sample))


def test_marked_runs_are_excluded_from_proofing(marked, sample):
    runs = _body_runs(marked)
    with_marks = [r for r in runs if (DOCX_ZW_CHARS | CYRILLIC) & set(r.text)]
    assert with_marks and len(with_marks) < len(runs)
    for r in runs:
        expected = True if r in with_marks else None
        assert Run(r, None).font.no_proof is expected
    assert all(Run(r, None).font.no_proof is None for r in _body_runs(sample))


def test_copy_paste_excerpt_decodes(marked, master, plan, codeword):
    lines = extract_docx_text(marked).split("\n")
    excerpt = "Diteruskan dari grup:\r\n" + "\r\n".join(lines[20:45]) + "\r\nterima kasih"
    excerpt = excerpt.replace("\t", "    ")
    obs = _by_channel(decode_docx(excerpt, master, plan))
    for name in (CHANNEL_ZW, CHANNEL_HOMOGLYPH):
        _check_bits(obs[name], codeword)
    assert 0 < obs[CHANNEL_ZW].meta["slots_read"] < obs[CHANNEL_ZW].meta["slots_total"]
    # Every token aligns except the five added around the excerpt.
    tokens = tokenize(excerpt)
    assert len(align_docx_tokens([t.raw for t in tokens], master)) == len(tokens) - 5


def test_normalized_or_stripped_text_reads_nothing_wrong(marked, master, plan, codeword):
    text = extract_docx_text(marked)
    no_zw = "".join(c for c in text if c not in ZW_CHARS)
    obs = _by_channel(decode_docx(no_zw, master, plan))
    assert len(obs[CHANNEL_ZW]) == 0
    _check_bits(obs[CHANNEL_HOMOGLYPH], codeword)
    obs = _by_channel(decode_docx(normalize_text(text), master, plan))
    assert len(obs[CHANNEL_ZW]) == 0 and len(obs[CHANNEL_HOMOGLYPH]) == 0


def test_mark_rejects_wrong_codeword_or_plan(sample, plan):
    with pytest.raises(ValueError, match="panjang codeword"):
        mark_docx(sample, plan, np.zeros(plan.m - 1, dtype=np.uint8))
    with pytest.raises(ValueError, match="tidak cocok"):
        mark_docx(_tricky_docx(), plan, np.zeros(plan.m, dtype=np.uint8))


def test_invalid_docx_rejected_in_indonesian():
    with pytest.raises(ValueError, match="bukan dokumen Word"):
        extract_docx_text(b"bukan zip")


# --- unusual structures --------------------------------------------------------------


def _tricky_docx() -> bytes:
    doc = Document()
    caps_style = doc.styles.add_style("HurufKapital", WD_STYLE_TYPE.PARAGRAPH)
    caps_style.font.all_caps = True

    p = doc.add_paragraph()
    p.add_run("ber").bold = True
    p.add_run("kas dokumen rahasia")        # "berkas" spans a bold and a plain run
    p.add_run().add_tab()
    p.add_run("tersimpan aman")

    p = doc.add_paragraph("lihat ")
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), "lampiran")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "lampiran persiapan"
    r.append(t)
    link.append(r)
    p._p.append(link)

    p = doc.add_paragraph()
    run = p.add_run("prosedur anti")
    run._r.append(OxmlElement("w:noBreakHyphen"))
    t = OxmlElement("w:t")
    t.text = "kolusi berlaku"
    run._r.append(t)                          # "anti-kolusi": hyphen is not a w:t

    p = doc.add_paragraph()
    run = p.add_run("persiapan operasi gabungan")
    rfonts = run._r.get_or_add_rPr().get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), "Arial")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")
    run.italic = True

    p = doc.add_paragraph()
    p.add_run("dokumen penting").font.small_caps = True
    spaced = p.add_run(" catatan renggang")
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:val"), "40")
    spaced._r.get_or_add_rPr().append(sp)

    doc.add_paragraph("sampai jumpa kawan", style="HurufKapital")

    table = doc.add_table(rows=2, cols=2)
    outer = table.cell(0, 0)
    outer.paragraphs[0].text = "sel pertama"
    outer.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0].text = "tabel bersarang"
    table.cell(0, 1).text = "sel kedua"
    merged = table.cell(1, 0).merge(table.cell(1, 1))
    merged.text = "sel gabungan"
    doc.add_paragraph("penutup surat")
    return _save(doc)


def test_unusual_structures_round_trip():
    data = _tricky_docx()
    master, marked, _ = _round_trip(data)
    words = {w.text: w for w in master.words}
    assert master.texts == extract_docx_text(data).split()
    # Table cells row by row, nested table inside its cell, merged cell once.
    assert master.texts[-10:] == "sel pertama tabel bersarang sel kedua sel gabungan penutup surat".split()
    assert "lampiran" in words and "anti-kolusi" in words
    assert len(words["berkas"].spans) == 2
    assert not words["anti-kolusi"].zw_ok and not words["anti-kolusi"].hg_ok
    assert words["dokumen"].zw_ok and not words["dokumen"].hg_ok          # small caps
    assert not words["jumpa"].hg_ok                                        # caps via style
    assert not words["renggang"].zw_ok and words["renggang"].hg_ok         # character spacing

    # The swapped letter of the Arial/Times run sits alone in a run drawn with Arial.
    doc = Document(io.BytesIO(marked))
    swapped = [r for p in iter_paragraphs(doc.element.body) for r in p.xpath("./w:r")
               if CYRILLIC & set(r.text) and r.find(f"{qn('w:rPr')}/{qn('w:rFonts')}") is not None]
    assert len(swapped) == 3  # "persiapan", "operasi", "gabungan"
    for r in swapped:
        assert len(r.text) == 1
        rf = r.find(f"{qn('w:rPr')}/{qn('w:rFonts')}")
        assert rf.get(qn("w:hAnsi")) == "Arial" and rf.get(qn("w:hint")) == "default"
        assert Run(r, None).italic and Run(r, None).font.no_proof
    tokens = {normalize_text(t.raw): t for t in tokenize(extract_docx_text(marked))}
    assert tokens["anti-kolusi"].prefix == tokens["anti-kolusi"].suffix == ""
    assert not CYRILLIC & set(tokens["dokumen"].raw) and not CYRILLIC & set(tokens["jumpa"].raw)
    assert tokens["renggang"].prefix == "" and CYRILLIC & set(tokens["renggang"].raw)


def _controls_and_fields_docx() -> bytes:
    doc = Document()
    sect = doc.element.body.find(qn("w:sectPr"))
    w = nsdecls("w")
    blocks = [
        # A paragraph wrapped in a block-level content control.
        f'<w:sdt {w}><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>paragraf dalam kontrol konten</w:t></w:r>'
        "</w:p></w:sdtContent></w:sdt>",
        # Inline content control, then a complex field (REF) whose result Word regenerates.
        f'<w:p {w}><w:r><w:t xml:space="preserve">isian </w:t></w:r>'
        "<w:sdt><w:sdtPr/><w:sdtContent><w:r><w:t>terkendali sempurna</w:t></w:r></w:sdtContent></w:sdt>"
        '<w:r><w:t xml:space="preserve"> lihat bagian </w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> REF penanda </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>rujukan otomatis</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:t xml:space="preserve"> sesudah ruas</w:t></w:r></w:p>',
        # A simple field (DATE).
        f'<w:p {w}><w:r><w:t xml:space="preserve">dibuat </w:t></w:r>'
        '<w:fldSimple w:instr=" DATE "><w:r><w:t>tanggal sekarang</w:t></w:r></w:fldSimple>'
        '<w:r><w:t xml:space="preserve"> selesai</w:t></w:r></w:p>',
    ]
    for xml in blocks:
        sect.addprevious(parse_xml(xml))
    return _save(doc)


def test_content_controls_marked_and_field_results_left_alone():
    data = _controls_and_fields_docx()
    master, marked, _ = _round_trip(data)
    words = {w.text: w for w in master.words}
    assert master.texts == ("paragraf dalam kontrol konten isian terkendali sempurna lihat bagian "
                            "rujukan otomatis sesudah ruas dibuat tanggal sekarang selesai").split()
    for text in ("paragraf", "konten", "terkendali", "sempurna", "sesudah", "selesai"):
        assert words[text].zw_ok, text
    for text in ("rujukan", "otomatis", "tanggal", "sekarang"):
        assert words[text].spans == () and not words[text].zw_ok and not words[text].hg_ok, text
    # The field results are stored exactly as in the master.
    t_texts = [t.text for t in Document(io.BytesIO(marked)).element.body.iter(qn("w:t"))]
    assert "rujukan otomatis" in t_texts and "tanggal sekarang" in t_texts


# --- fonts ---------------------------------------------------------------------------


def _fonts_docx() -> bytes:
    doc = Document()  # default theme: Cambria body text, Calibri headings
    gill = doc.styles.add_style("GayaGill", WD_STYLE_TYPE.PARAGRAPH)
    gill.font.name = "Gill Sans MT"
    doc.add_paragraph("tulisan berbeda sekali", style="GayaGill")  # font from a paragraph style
    doc.add_paragraph().add_run("cocok sekali").font.name = "Verdana"
    doc.add_paragraph().add_run("kode sumber program").font.name = "Courier New"
    run = doc.add_paragraph().add_run("judul bertema")
    rfonts = run._r.get_or_add_rPr().get_or_add_rFonts()
    rfonts.set(qn("w:asciiTheme"), "majorHAnsi")
    rfonts.set(qn("w:hAnsiTheme"), "majorHAnsi")
    trebuchet = doc.styles.add_style("GayaTrebuchet", WD_STYLE_TYPE.CHARACTER)
    trebuchet.font.name = "Trebuchet MS"
    doc.add_paragraph().add_run("karakter bergaya khusus", style="GayaTrebuchet")
    return _save(doc)


def test_marks_follow_the_effective_font():
    data = _fonts_docx()
    master, marked, _ = _round_trip(data)
    words = {w.text: w for w in master.words}
    assert master.unverified_fonts == ["Gill Sans MT", "Trebuchet MS"]
    for text in ("tulisan", "berbeda", "khusus"):        # no Cyrillic in these fonts
        assert not words[text].zw_ok and words[text].hg_candidates == (), text
    assert words["cocok"].hg_candidates == (1, 3)        # Verdana: no c, only the o's
    assert words["cocok"].zw_ok
    assert words["program"].hg_ok and not words["program"].zw_ok  # Courier New
    assert words["bertema"].hg_ok and words["bertema"].zw_ok      # theme font Calibri
    assert font_support("verdana").homoglyphs == VERIFIED_FONTS["Verdana"].homoglyphs
    tokens = {normalize_text(t.raw): t for t in tokenize(extract_docx_text(marked))}
    assert "\u0441" not in tokens["cocok"].raw
    assert tokens["program"].prefix == tokens["program"].suffix == ""


def test_issue_refuses_document_in_unverified_font(tmp_path):
    doc = Document()
    doc.add_paragraph().add_run("seluruh naskah memakai huruf tanpa sirilik").font.name = "Gill Sans MT"
    path = tmp_path / "gill.docx"
    path.write_bytes(_save(doc))
    with pytest.raises(ValueError, match="font belum terverifikasi: Gill Sans MT"):
        issue_docx(path, [Recipient("R001", "Penerima")], tmp_path / "keluar", SECRET, PARAMS)


def _windows_faces() -> dict[str, list[tuple[Path, int, object]]]:
    from fontTools.ttLib import TTCollection, TTFont

    faces: dict[str, list[tuple[Path, int, object]]] = {}
    for path in sorted(WINDOWS_FONTS.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in (".ttf", ".ttc"):
            continue
        try:
            fonts = TTCollection(str(path), lazy=True).fonts if suffix == ".ttc" else [TTFont(str(path), lazy=True)]
            for index, tt in enumerate(fonts):
                family = tt["name"].getDebugName(1)  # the family name Word stores in w:rFonts
                if family:
                    faces.setdefault(family.casefold(), []).append((path, index, tt))
        except Exception:  # noqa: BLE001 - unreadable or bitmap-only font files are skipped
            continue
    return faces


def _render(path: Path, ch: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=600)
    writer = pymupdf.TextWriter(page.rect)
    writer.append((50, 450), ch, font=pymupdf.Font(fontfile=str(path)), fontsize=400)
    writer.write_text(page)
    return page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY).samples


def _twins_identical(tt, path: Path, index: int, latin: str) -> bool:
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    cmap, hmtx = tt.getBestCmap() or {}, tt["hmtx"]
    gl, gc = cmap.get(ord(latin)), cmap.get(ord(HOMOGLYPHS[latin]))
    if gl is None or gc is None or hmtx[gl][0] != hmtx[gc][0]:
        return False
    glyphs = tt.getGlyphSet()
    pens = [DecomposingRecordingPen(glyphs), DecomposingRecordingPen(glyphs)]
    glyphs[gl].draw(pens[0])
    glyphs[gc].draw(pens[1])
    if pens[0].value == pens[1].value:
        return True
    # Same shape drawn from another start point (Times New Roman Italic): compare pixels.
    return index == 0 and _render(path, latin) == _render(path, HOMOGLYPHS[latin])


def _zero_width_ok(tt) -> bool:
    cmap, hmtx = tt.getBestCmap() or {}, tt["hmtx"]
    return all(hmtx[cmap[ord(c)]][0] == 0 for c in DOCX_ZW_CHARS if ord(c) in cmap)


@pytest.mark.skipif(not WINDOWS_FONTS.is_dir(), reason="Windows font files are not mounted here")
def test_verified_fonts_match_windows_font_files():
    """Re-derive VERIFIED_FONTS from the font files: every listed letter passes, every other fails."""
    faces = _windows_faces()
    for family, support in VERIFIED_FONTS.items():
        styles = faces.get(family.casefold())
        assert styles, family
        letters = {c for c in DOCX_HOMOGLYPH_LETTERS
                   if all(_twins_identical(tt, path, index, c) for path, index, tt in styles)}
        assert letters == support.homoglyphs, family
        assert all(_zero_width_ok(tt) for _, _, tt in styles) == support.zero_width, family


# --- issuance and attribution --------------------------------------------------------


def test_issue_and_attribute_among_20(tmp_path, sample_path, master, plan):
    recipients = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji") for i in range(1, 21)]
    seen: list[int] = []
    per_copy: list[str] = []

    def hook(data: bytes) -> bytes:
        seen.append(len(data))
        return data

    def hook_copy(data: bytes, copy_id: str) -> bytes:
        per_copy.append(copy_id)
        return data

    issued = issue_docx(sample_path, recipients, tmp_path / "keluar", SECRET, PARAMS,
                        post_process=hook, post_process_copy=hook_copy)
    assert [row[0] for row in issued] == list(range(1, 21))
    assert len(seen) == 20 and per_copy == [row[1] for row in issued]
    assert len({row[1] for row in issued}) == 20
    p = derive_bias(SECRET, master.doc_hash, PARAMS)
    codewords = np.vstack([derive_codeword(SECRET, master.doc_hash, cid, p) for _, cid, _, _ in issued])
    for (seq, cid, path, digest), x in zip(issued, codewords):
        assert path.exists() and path.name.endswith(f"_R{seq:03d}.docx")
        assert code_digest(master.doc_hash, cid, x) == digest

    leaked = issued[LEAKED - 1][2].read_bytes()
    obs = decode_docx(extract_docx_text(leaked), master, plan)
    for sb in obs:
        _check_bits(sb, codewords[LEAKED - 1])
    refs = [CopyRef(seq, cid, r.recipient_id, r.nama) for (seq, cid, _, _), r in zip(issued, recipients)]
    result = attribute(fuse(obs, PARAMS.length), fuse_by_physical_channel(obs, PARAMS.length),
                       p, codewords, refs, PARAMS)
    assert result.verdict == VERDICT_IDENTIFIED
    assert [c.copy.seq for c in result.accused] == [LEAKED]
    assert result.accused[0].false_accusation_probability < PARAMS.eps


def test_issue_rejects_too_many_recipients(tmp_path, sample_path):
    recipients = [Recipient(f"R{i}", f"Penerima {i}") for i in range(3)]
    with pytest.raises(ValueError, match="n_max"):
        issue_docx(sample_path, recipients, tmp_path, SECRET, TardosParams(n_max=2))


def test_issue_rejects_recipient_id_unfit_for_file_name(tmp_path, sample_path):
    recipients = [Recipient("R001", "Penerima Satu"), Recipient("a/b", "Penerima Dua")]
    with pytest.raises(ValueError, match="recipient_id tidak valid"):
        issue_docx(sample_path, recipients, tmp_path / "keluar", SECRET, PARAMS)
    assert not (tmp_path / "keluar").exists()  # checked before anything is written


def test_failed_issuance_leaves_no_copies(tmp_path, sample_path):
    recipients = [Recipient(f"R{i:03d}", f"Penerima {i}") for i in range(1, 6)]
    calls: list[str] = []

    def failing_canary(data: bytes, copy_id: str) -> bytes:
        calls.append(copy_id)
        if len(calls) == 3:
            raise RuntimeError("kanari gagal")
        return data

    with pytest.raises(RuntimeError, match="kanari gagal"):
        issue_docx(sample_path, recipients, tmp_path / "keluar", SECRET, PARAMS, post_process_copy=failing_canary)
    assert list((tmp_path / "keluar").iterdir()) == []


@pytest.fixture(scope="module")
def fixed_copies(master):
    """20 codewords with fixed copy ids, so the excerpt verdicts below are deterministic."""
    p = derive_bias(SECRET, master.doc_hash, PARAMS)
    ids = [f"salinan-tetap-{i:02d}" for i in range(1, 21)]
    codewords = np.vstack([derive_codeword(SECRET, master.doc_hash, cid, p) for cid in ids])
    refs = [CopyRef(i, cid, f"R{i:03d}", f"Penerima Fiktif {i}") for i, cid in enumerate(ids, start=1)]
    return p, codewords, refs


@pytest.fixture(scope="module")
def leaked_text(sample, plan, fixed_copies) -> str:
    _, codewords, _ = fixed_copies
    return extract_docx_text(mark_docx(sample, plan, codewords[LEAKED - 1]))


def _attribute(text: str, master, plan, fixed_copies):
    p, codewords, refs = fixed_copies
    obs = decode_docx(text, master, plan)
    return attribute(fuse(obs, PARAMS.length), fuse_by_physical_channel(obs, PARAMS.length),
                     p, codewords, refs, PARAMS)


def _longest_paragraph(text: str) -> str:
    return max(text.split("\n"), key=lambda line: len(line.split()))


def test_one_long_paragraph_identifies_the_copy(leaked_text, master, plan, fixed_copies):
    excerpt = _longest_paragraph(leaked_text)
    assert len(excerpt.split()) >= 40
    result = _attribute(excerpt, master, plan, fixed_copies)
    assert result.verdict == VERDICT_IDENTIFIED
    assert [c.copy.seq for c in result.accused] == [LEAKED]


def test_homoglyphs_alone_identify_the_full_text(leaked_text, master, plan, fixed_copies):
    stripped = "".join(c for c in leaked_text if c not in ZW_CHARS)
    result = _attribute(stripped, master, plan, fixed_copies)
    assert result.verdict == VERDICT_IDENTIFIED
    assert [c.copy.seq for c in result.accused] == [LEAKED]


def test_three_words_accuse_nobody(leaked_text, master, plan, fixed_copies):
    excerpt = " ".join(_longest_paragraph(leaked_text).split()[5:8])
    obs = _by_channel(decode_docx(excerpt, master, plan))
    assert len(obs[CHANNEL_ZW]) > 0  # the words were read, there is just too little evidence
    result = _attribute(excerpt, master, plan, fixed_copies)
    assert result.verdict == VERDICT_INSUFFICIENT
    assert result.accused == []
