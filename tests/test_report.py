"""Berita acara tests: formatting helpers, the name rule, offline rendering, and full
reports built from a real trace (identified and insufficient evidence)."""

from __future__ import annotations

import html as html_lib
import re
import shutil

import pymupdf
import pytest

from tapak.decoder.accuse import (
    THRESHOLD_RULE,
    VERDICT_IDENTIFIED,
    VERDICT_INSUFFICIENT,
    VISIBLE_MARKS_NOTE,
    Attribution,
    ChannelEvidence,
    CopyCandidate,
    CopyRef,
    ThresholdRecord,
)
from tapak.decoder.report import (
    REDACTED,
    ReportInfo,
    build_report_info,
    channel_observations,
    check_consistent,
    check_local_url,
    evidence_type_for,
    format_datetime,
    format_int,
    format_number,
    format_probability_html,
    format_probability_text,
    html_to_pdf,
    make_redactor,
    render_html,
    render_report,
    rerun_command,
    scientific_parts,
)
from tapak.decoder.trace import collect_from_pdf, run_trace
from tapak.fonts import FONT_DIR, font_path
from tapak.tardos.params import TardosParams

ACCUSED_SEQ = 7
OTHER_SEQ = 5  # a copy that is not accused in the pipeline test
TIMES = "\u00d7"
MINUS = "\u2212"
LE = "\u2264"


def _pdf_text(pdf: bytes) -> tuple[str, int, set[str]]:
    """Whitespace-normalized text of all pages, page count, font names of all pages."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = " ".join(" ".join(page.get_text() for page in doc).split())
        fonts = {f[3] for i in range(doc.page_count) for f in doc.get_page_fonts(i)}
        return text, doc.page_count, fonts


def _visible(html: str) -> str:
    """Text a reader sees in rendered HTML: tags removed, entities decoded, spaces collapsed."""
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _info(**overrides) -> ReportInfo:
    """A small ReportInfo for tests that do not need a real issuance."""
    fields = dict(
        case_number="BAP/001/X/2026", examiner_name="Pemeriksa Uji", examiner_rank="AKP",
        evidence_name="bukti.pdf", evidence_sha256="ab" * 32, evidence_type="berkas PDF",
        document_name="induk.pdf", doc_hash="cd" * 32, issued_at="2026-10-20T08:00:00+00:00",
        params=TardosParams(c=3, eps=1e-6, n_max=3), copies_issued=3,
        plan_summary={"shift": {"slots": 10, "bits": 10, "positions": 10, "pages": 1}},
        channel_observations=[], software_version="0.1.0",
        examined_at="2026-10-21T09:00:00+07:00",
    )
    fields.update(overrides)
    return ReportInfo(**fields)


# --- formatting helpers ----------------------------------------------------------------


def test_format_number_uses_indonesian_separators():
    assert format_number(1234.5) == "1.234,5"
    assert format_number(-0.25, 2) == "-0,25"
    assert format_number(-0.04) == "0,0"  # no negative zero
    assert format_number(float("inf")) == "\u221e"
    assert format_number(float("nan")) == "-"
    assert format_int(12345) == "12.345"


def test_scientific_parts_and_rounding():
    assert scientific_parts(2.3e-12) == ("2,3", -12)
    assert scientific_parts(2.34e-12) == ("2,3", -12)  # nearest by default
    assert scientific_parts(9.96e-5) == ("1", -4)  # 9,96 rounds up to 10: carry into exponent
    assert scientific_parts(1e-6) == ("1", -6)
    assert scientific_parts(0.0, log10_value=-500.0) == ("1", -500)  # below float range
    with pytest.raises(ValueError):
        scientific_parts(0.0)


def test_upper_bounds_are_rounded_up():
    assert scientific_parts(2.34e-12, round_up=True) == ("2,4", -12)
    assert scientific_parts(2.3e-12, round_up=True) == ("2,3", -12)  # exact values stay
    assert scientific_parts(9.91e-5, round_up=True) == ("1", -4)
    assert format_probability_text(2.34e-12) == "2,4 x 10^-12"
    assert format_probability_text(0.0149) == "0,02"
    assert format_probability_text(0.35) == "0,35"
    assert format_probability_text(2.34e-12, round_up=False) == "2,3 x 10^-12"


def test_probability_formats():
    html = str(format_probability_html(2.3e-12))
    assert html == f"2,3 {TIMES} 10<sup>{MINUS}12</sup>"
    assert format_probability_text(2.3e-12) == "2,3 x 10^-12"
    assert format_probability_text(1.0) == "1"
    assert format_probability_text(0.0) == "0"
    assert format_probability_text(0.0, log10_value=-400.5) == "3,2 x 10^-401"


def test_format_datetime_in_indonesian():
    assert format_datetime("2026-10-21T08:09:10+07:00", with_day=True) == \
        "Rabu, 21 Oktober 2026 pukul 08.09.10 WIB"
    assert format_datetime("2026-10-21T01:02:03.456+00:00") == "21 Oktober 2026 pukul 01.02.03 UTC"
    assert format_datetime("2026-10-21T01:02:03+05:30").endswith("UTC+05.30")
    assert format_datetime("2026-10-21") == "21 Oktober 2026"
    assert format_datetime("2026-10-21T08:09:10+08:00", with_time=False) == "21 Oktober 2026"
    assert format_datetime("kemarin sore") == "kemarin sore"


def test_default_examination_time_is_local_with_offset():
    info = ReportInfo(**{k: v for k, v in _info().__dict__.items() if k != "examined_at"})
    assert re.search(r"[+-]\d\d:\d\d$", info.examined_at)


def test_evidence_type_and_validation():
    assert evidence_type_for("bocoran.PDF") == "berkas PDF"
    assert evidence_type_for("foto.jpg") == "foto"
    assert evidence_type_for("pesan.txt") == "teks"
    with pytest.raises(ValueError, match="jenis barang bukti"):
        _info(evidence_type="video")


def test_rerun_command_quotes_file_names():
    cmd = rerun_command(_info(evidence_name="bukti saya.pdf"))
    assert cmd == "tapak trace 'bukti saya.pdf' --master induk.pdf --manifest manifest.json"


# --- offline rendering -----------------------------------------------------------------


def test_only_bundled_local_files_may_be_fetched():
    assert check_local_url(font_path("DejaVuSans").as_uri()) == font_path("DejaVuSans").resolve()
    traversal = FONT_DIR.as_uri() + "/../../../pyproject.toml"
    for url in ("http://127.0.0.1:9/x.png", "https://example.org/f.ttf", "file:///etc/passwd",
                "data:text/plain,abc", traversal):
        with pytest.raises(ValueError):
            check_local_url(url)


def test_render_fails_instead_of_fetching_network_resources():
    with pytest.raises(RuntimeError, match="gagal membuat berita acara"):
        html_to_pdf('<p>x</p><img src="http://127.0.0.1:9/gambar.png">')


def test_render_refuses_local_files_outside_the_bundle(tmp_path):
    # A valid font outside the asset folders: WeasyPrint would load it if the fetcher
    # allowed every file:// URL, so a refusal proves check_local_url is wired in.
    outside = tmp_path / "fon.ttf"
    shutil.copy(font_path("DejaVuSans"), outside)
    up = "/.." * len(FONT_DIR.resolve().parts)
    for url in (outside.as_uri(), FONT_DIR.resolve().as_uri() + up + outside.as_posix()):
        page = (f'<style>@font-face {{ font-family: "Luar"; src: url("{url}"); }}</style>'
                '<p style="font-family: Luar">x</p>')
        with pytest.raises(RuntimeError, match="gagal membuat berita acara"):
            html_to_pdf(page)


# --- the name rule on a synthetic attribution -------------------------------------------


def _synthetic(verdict: str, channel_accuses: list[int], top_score: float | None = None,
               notes: list[str] | None = None) -> Attribution:
    """Three copies; copy #3 has the top score (150 if identified, 100 if not; Z = 120)."""
    if top_score is None:
        top_score = 150.0 if verdict == VERDICT_IDENTIFIED else 100.0
    accused = top_score >= 120.0
    refs = [CopyRef(i, f"c{i}", f"ID{i:03d}", f"Nama Uji {i}") for i in (1, 2, 3)]
    agreeing = ["geser"] if 3 in channel_accuses else []
    cands = [
        CopyCandidate(refs[2], top_score, -9.0 if accused else -0.5, 2e-9 if accused else 0.63,
                      accused, {"geser": 150.0}, agreeing),
        CopyCandidate(refs[0], 20.0, -0.1, 1.0, False, {"geser": 119.0},
                      ["geser"] if 1 in channel_accuses else []),
        CopyCandidate(refs[1], -5.0, 0.0, 1.0, False),
    ]
    record = ThresholdRecord(THRESHOLD_RULE, 1e-6, 1e-6 / 3, 3, 500, 480.0, 120.0,
                             "2026-10-21T02:00:00.000+00:00")
    channels = [ChannelEvidence("geser", 500, 118.0, 3, 150.0, channel_accuses)]
    return Attribution(verdict, record, cands, channels, {}, list(notes or []))


def test_names_only_for_accused_rows():
    html = render_html(_synthetic(VERDICT_IDENTIFIED, [3]), _info())
    assert html.count("Nama Uji 3") == 1 and "ID003" in html
    assert "Nama Uji 1" not in html and "Nama Uji 2" not in html
    assert "ID001" not in html and "ID002" not in html
    row = re.search(r'<tr class="dituduh">.*?</tr>', html, re.S).group(0)
    assert "#3" in row and "Nama Uji 3" in row
    assert "150,0" in row and "120,0" in row and f"10<sup>{MINUS}9</sup>" in row


def test_runner_up_rows_have_scores_but_no_identity():
    for verdict, rank in ((VERDICT_IDENTIFIED, 2), (VERDICT_INSUFFICIENT, 1)):
        html = render_html(_synthetic(verdict, []), _info())
        rows = re.findall(r'<tr class="anonim">.*?</tr>', html, re.S)
        assert len(rows) == (2 if verdict == VERDICT_IDENTIFIED else 3)
        first = _visible(rows[0])
        assert first.startswith(f"Peringkat {rank}: di bawah ambang, identitas tidak dicantumkan")
        assert "120,0" in first and LE in first
        assert not re.search(r"#\d|ID00|Nama Uji", " ".join(rows))
    insufficient = render_html(_synthetic(VERDICT_INSUFFICIENT, []), _info())
    assert "100,0" in _visible(re.findall(r'<tr class="anonim">.*?</tr>', insufficient, re.S)[0])


def test_insufficient_shows_no_identity_even_if_one_channel_accuses():
    text = _visible(render_html(_synthetic(VERDICT_INSUFFICIENT, [3]), _info()))
    assert "TIDAK CUKUP BUKTI" in text
    assert "Nama Uji" not in text and "ID00" not in text
    assert "#3" not in text
    assert "1 salinan (nomor tidak dicantumkan)" in text


def test_channel_table_names_only_copies_the_combined_score_accused():
    text = _visible(render_html(_synthetic(VERDICT_IDENTIFIED, [3, 1]), _info()))
    assert "#3; 1 salinan lain (nomor tidak dicantumkan)" in text
    assert "#1" not in text


def test_identifiers_in_free_text_are_masked_for_both_verdicts():
    """The evidence name, notes and canary rows can point at an innocent copy: mask it."""
    evidence = "Nama-uji-1__salinan002_ID002.pdf"  # the leaker chose this name
    canary = [{"seq": 2, "time": "2026-10-20T21:14:03+07:00", "source_ip": "203.0.113.45"},
              {"seq": 3, "time": "2026-10-20T22:00:00+07:00", "source_ip": "198.51.100.7"}]
    notes = ["berkas identik byte demi byte dengan salinan #2 (bukti pendukung)"]
    info = _info(evidence_name=evidence, canary_events=canary)
    hidden_pattern = re.compile(r"ID00[12]|nama\W*uji\W*[12]|#[12](?!\d)|salinan\W*0*[12](?!\d)", re.I)

    text = _visible(render_html(_synthetic(VERDICT_IDENTIFIED, [3], notes=notes), info))
    assert not hidden_pattern.search(text), hidden_pattern.search(text)
    assert REDACTED in text and "salinan lain (nomor tidak dicantumkan)" in text
    assert "#3 " in text and "ID003" in text  # the accused copy stays visible

    text = _visible(render_html(_synthetic(VERDICT_INSUFFICIENT, [3], notes=notes), info))
    assert not re.search(r"ID00\d|nama\W*uji|#\d|salinan\W*\d", text, re.I)
    assert f"salinan{REDACTED}_{REDACTED}.pdf" in text
    assert "203.0.113.45" in text  # time and IP stay, the copy number does not


def test_visible_marks_caveat_is_shown_under_the_verdict():
    """A name that rests only on word choice and sentence variants gets its caveat right under
    the verdict, once, and not repeated among the examination notes."""
    caveat = f"salinan #3: {VISIBLE_MARKS_NOTE}"
    html = render_html(_synthetic(VERDICT_IDENTIFIED, [3], notes=["catatan lain", caveat]), _info())
    block = re.search(r'<p class="peringatan">(.*?)</p>', html, re.S)
    assert block and "bukan pengetiknya" in block.group(1) and "#3" in block.group(1)
    assert html.index("PUTUSAN: TERIDENTIFIKASI") < block.start() < html.index('<table class="grid hasil">')
    assert _visible(html).count("bukan pengetiknya") == 1 and "catatan lain" in _visible(html)
    plain = render_html(_synthetic(VERDICT_IDENTIFIED, [3]), _info())
    assert 'class="peringatan"' not in plain


def test_redactor_masks_ids_names_and_copy_numbers():
    refs = [CopyRef(5, "a1b2c3d4", "R005", "Budi Santoso")]
    redact = make_redactor(refs, shown_seqs={7})
    assert redact("x__salinan005_R005.pdf") == f"x__salinan{REDACTED}_{REDACTED}.pdf"
    assert redact("BUDI_santoso salinan nomor 5, copy-12") == \
        f"{REDACTED} salinan nomor {REDACTED}, copy-{REDACTED}"
    assert redact("salinan #7 dan r005") == f"salinan #7 dan {REDACTED}"


def test_inconsistent_attribution_is_refused():
    bad = _synthetic(VERDICT_INSUFFICIENT, [])
    bad.candidates[0].score = 150.0  # reaches Z = 120 but is not flagged as accused
    with pytest.raises(ValueError, match="tidak konsisten"):
        render_html(bad, _info())
    bad = _synthetic(VERDICT_IDENTIFIED, [3])
    bad.verdict = VERDICT_INSUFFICIENT
    with pytest.raises(ValueError, match="tidak konsisten"):
        check_consistent(bad)


def test_unread_and_not_examined_channels_are_told_apart():
    plan = {name: {"slots": 5, "bits": 5, "positions": 5, "pages": 1}
            for name in ("shift", "background", "zw")}
    observed = [{"channel": "zw", "observations": 0, "slots_read": 0, "slots_total": 5, "noise": None}]
    text = _visible(render_html(_synthetic(VERDICT_IDENTIFIED, [3]),
                                _info(plan_summary=plan, channel_observations=observed)))
    assert "Latar (pola latar halus) - - tidak diperiksa untuk jenis bukti ini" in text
    assert "Teks (karakter tak terlihat dan huruf kembar) 0 dari" in text
    assert "diperiksa tetapi tidak terbaca pada bukti: Teks" in text
    assert "dijalankan untuk jenis bukti ini (berkas PDF): Latar" in text
    vii = text.split("BATASAN", 1)[1]
    assert "Latar" not in vii.split("tidak diperiksa, karena")[0]  # not called destroyed


def test_plan_summary_with_missing_keys_still_renders():
    html = render_html(_synthetic(VERDICT_IDENTIFIED, [3]),
                       _info(plan_summary={"shift": {"slots": 1, "bits": 1}}))
    assert "Pergeseran kata dan baris" in html


def test_standalone_html_inlines_the_stylesheet():
    attr = _synthetic(VERDICT_IDENTIFIED, [3])
    assert "<style>" not in render_html(attr, _info())
    standalone = render_html(attr, _info(), standalone=True)
    assert "<style>" in standalone and "@page" in standalone
    assert str(FONT_DIR) not in standalone  # no server file paths in a web preview


# --- full reports from a real trace ------------------------------------------------------


@pytest.fixture(scope="module")
def traced(issued, ctx):
    out, manifest = issued
    copy = manifest.copies[ACCUSED_SEQ - 1]
    data = (out / copy.file).read_bytes()
    obs = collect_from_pdf(data, ctx)
    return copy, data, obs, run_trace(obs, ctx)


def test_channel_observations_summary(traced):
    _copy, _data, obs, _attr = traced
    rows = {r["channel"]: r for r in channel_observations(obs)}
    assert rows["shift"]["observations"] > 0 and "pt" in rows["shift"]["noise"]
    assert rows["zw"]["slots_read"] == rows["zw"]["slots_total"]
    assert rows["zw"]["noise"].startswith("pembacaan digital")


def test_report_for_identified_copy(traced, ctx, tmp_path):
    copy, data, obs, attr = traced
    assert attr.verdict == VERDICT_IDENTIFIED
    best = attr.accused[0]
    assert best.copy.seq == ACCUSED_SEQ and best.false_accusation_probability > 0
    canary = [{"seq": ACCUSED_SEQ, "time": "2026-10-20T21:14:03+07:00", "source_ip": "203.0.113.45"},
              {"seq": OTHER_SEQ, "time": "2026-10-20T22:00:00+07:00", "source_ip": "198.51.100.7"}]
    info = build_report_info(ctx, copy.file, data, obs, case_number="BAP/017/X/2026",
                             examiner_name="Pemeriksa Uji", examiner_rank="AKP",
                             registry_ok=True, registry_entries=21, canary_events=canary)
    out_path = tmp_path / "bap" / "bap.pdf"
    pdf = render_report(attr, info, out_path)
    assert out_path.read_bytes() == pdf and pdf.startswith(b"%PDF")

    text, pages, fonts = _pdf_text(pdf)
    assert "BERITA ACARA PEMERIKSAAN DIGITAL" in text
    z = format_number(attr.threshold.threshold)
    mantissa, exponent = scientific_parts(best.false_accusation_probability, round_up=True)
    probability = f"{mantissa} {TIMES} 10{MINUS}{abs(exponent)}"
    # The Section V row: copy number, id, name, score, Z and bound together.
    row = re.compile(
        rf"#{ACCUSED_SEQ} {copy.recipient.recipient_id} {copy.recipient.nama} .*?"
        rf"{re.escape(format_number(best.score))} {re.escape(z)} {LE} {re.escape(probability)}")
    assert row.search(text), text.split("HASIL ATRIBUSI")[1][:600]
    assert ctx.manifest.doc_hash[:16] in text
    assert info.evidence_sha256[:16] in text
    assert copy.code_digest[:16] in text
    command = f"tapak trace {copy.file} --master {ctx.manifest.doc_name} --manifest manifest.json"
    assert command.replace(" ", "") in text.replace(" ", "")  # hashes and commands may wrap
    assert "203.0.113.45" in text and "198.51.100.7" in text
    assert f"#{OTHER_SEQ}" not in text and "salinan lain (nomor tidak dicantumkan)" in text

    # Page furniture: RAHASIA header and footer on every page, page x of y, bundled fonts only.
    assert text.count("RAHASIA") >= 2 * pages
    assert f"Halaman 1 dari {pages}" in text and f"Halaman {pages} dari {pages}" in text
    assert any("TAPAK-Sans" in f for f in fonts)
    assert all("TAPAK" in f for f in fonts), fonts

    # Only the accused recipient is named.
    assert set(re.findall(r"Penerima Fiktif (\d+)", text)) == {str(ACCUSED_SEQ)}
    assert set(re.findall(r"R0\d\d", text)) == {copy.recipient.recipient_id}


def test_planned_channel_without_decoder_is_not_examined(traced, ctx):
    """Evidence whose decoders skip the background (as for a PDF before background decoding
    existed): Latar is reported as not examined, never as unreadable or destroyed."""
    copy, data, obs, _attr = traced
    partial = [sb for sb in obs if sb.channel != "background"]
    info = build_report_info(ctx, copy.file, data, partial, case_number="BAP/019/X/2026",
                             examiner_name="Pemeriksa Uji", examiner_rank="AKP")
    text = _visible(render_html(run_trace(partial, ctx), info))
    assert "Latar (pola latar halus) - - tidak diperiksa untuk jenis bukti ini" in text
    assert "tidak diperiksa, karena dekodernya tidak dijalankan untuk jenis bukti ini " \
           "(berkas PDF): Latar (pola latar halus)" in text
    assert "diperiksa tetapi tidak terbaca" not in text


def test_report_for_insufficient_evidence(ctx):
    attr = run_trace([], ctx, notes=["berkas identik byte demi byte dengan salinan #3 (bukti pendukung)"])
    assert attr.verdict == VERDICT_INSUFFICIENT
    renamed = ctx.manifest.copies[2].file  # the default issued name embeds the recipient id
    info = build_report_info(ctx, renamed, b"bukan bukti", [],
                             case_number="BAP/018/X/2026", examiner_name="Pemeriksa Uji",
                             examiner_rank="AKP", evidence_type="tangkapan layar",
                             canary_events=[{"seq": 3, "time": "2026-10-20T21:14:03+07:00",
                                             "source_ip": "203.0.113.45"}])
    text, _pages, _fonts = _pdf_text(render_report(attr, info))
    assert "TIDAK CUKUP BUKTI" in text
    assert "Fiktif" not in text
    for ref in ctx.refs:
        assert ref.nama not in text
        assert ref.recipient_id not in text
    for c in ctx.manifest.copies:
        assert c.code_digest[:16] not in text
    assert not re.search(r"#\d|salinan\W*\d", text)
