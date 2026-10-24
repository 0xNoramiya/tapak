"""Indonesian and English in the web UI (tapak/web/i18n.py, tapak/web/en.py).

Every message of the pages has an English entry with the same placeholders, pages asked for in
English carry no Indonesian outside elements marked lang="id" (document text, lexicon forms),
and the language choice is kept in a cookie."""

from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jinja2.ext import babel_extract

from tapak.web import i18n
from tapak.web.en import EN, PATTERNS, RULES

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "tapak" / "web"
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
EM_DASH = chr(0x2014)
# Indonesian words that never occur in the English copy (whole words, any case).
STOPWORDS = re.compile(r"\b(yang|dan|untuk|dengan|tidak|belum|sudah|dapat|ini|itu|atau|halaman|salinan|"
                       r"penerima|kanal|unduh|terbitkan|pelacakan|bukti|berkas|dokumen)\b", re.IGNORECASE)


def _messages() -> dict[str, str]:
    """Every message of the web UI: _(), ngettext() and {% trans %} in the templates, and the
    _() / N_() calls of tapak/web/*.py. Value: where it was found."""
    found: dict[str, str] = {}
    for template in sorted((WEB / "templates").glob("*.html")):
        with open(template, "rb") as f:
            for lineno, _func, msg, _comments in babel_extract(
                    f, ["_", "gettext", "ngettext"], [], {"trimmed": "true", "extensions": "jinja2.ext.i18n,jinja2.ext.do"}):
                first = msg[0] if isinstance(msg, tuple) else msg
                if first:
                    found.setdefault(first, f"{template.name}:{lineno}")
    for module in sorted(WEB.glob("*.py")):
        if module.name == "en.py":
            continue
        for node in ast.walk(ast.parse(module.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{module.name}:{node.lineno}")
    for row in json.loads((WEB / "landing.json").read_text(encoding="utf-8"))["media"]:
        found.setdefault(row["label"], "landing.json")
    for row in json.loads((WEB / "landing.json").read_text(encoding="utf-8"))["batas"]:
        found.setdefault(row["label"], "landing.json")
    return found


def test_every_message_has_english_with_the_same_placeholders():
    messages = _messages()
    assert len(messages) > 600
    missing = [f"{where}: {msg!r}" for msg, where in messages.items() if msg not in EN]
    assert not missing, "\n".join(missing)
    for msg, where in messages.items():
        values = EN[msg] if isinstance(EN[msg], tuple) else (EN[msg],)
        for value in values:
            assert set(PLACEHOLDER.findall(value)) == set(PLACEHOLDER.findall(msg)), (where, msg, value)
            assert EM_DASH not in value and ("%%" in value) == ("%%" in msg), (where, msg, value)


def test_rules_use_only_their_placeholders_and_compile():
    named = re.compile(r"\{(\w+)(?::\w)?\}")
    assert len(PATTERNS) == len(RULES)
    for indonesian, english in RULES:
        assert set(named.findall(english)) <= set(named.findall(indonesian)), indonesian
        assert EM_DASH not in english


@pytest.mark.parametrize("indonesian, english", [
    ("berkas identik byte demi byte dengan salinan #13 (bukti pendukung)",
     "the file is byte for byte identical to copy #13 (supporting evidence)"),
    ("foto.jpg: dipetakan ke halaman 1 (metode sift, korelasi 0,912, resolusi efektif 143 dpi)",
     "foto.jpg: mapped to page 1 (method sift, correlation 0.912, effective resolution 143 dpi)"),
    ("Kanal geser halaman pindaian dilewati.", "Shift channel of the scanned pages skipped."),
    ("entri pelacakan ini dicatat di registri tanpa tanda tangan; pemegang kunci menandatanganinya dengan tapak "
     "registry sign",
     "this trace\u2019s entry is recorded in the registry without a signature; the key holder signs it with tapak "
     "registry sign"),
    ("z pilot = 1,23 dari 2 halaman gambar dan z tanda = -0,50 dari 1.234 posisi terbaca, ambang 3,09 untuk "
     "masing-masing",
     "z pilot = 1.23 from 2 image pages and z signs = -0.50 from 1,234 positions read, threshold 3.09 for each"),
    ("Kemungkinan penyebab: koalisi pemegang dua salinan atau lebih menghapus tanda di tempat salinannya sama.",
     "Possible causes: a coalition holding two or more copies erased marks where their copies agree."),
    ("Mode halaman: 1 halaman teks, 2 halaman pindaian (halaman 2, 3; 300 dan 600 dpi)",
     "Page modes: 1 text, 2 scanned (pages 2, 3; 300 and 600 dpi)"),
])
def test_library_sentences_read_in_english(indonesian, english):
    token = i18n.use("en")
    try:
        assert i18n.translate_text(indonesian) == english
    finally:
        i18n.reset(token)
    assert i18n.translate_text(indonesian) == indonesian  # Indonesian requests keep the library's words


def test_unknown_sentences_and_indonesian_requests_stay_as_written():
    token = i18n.use("en")
    try:
        assert i18n.translate_text("kalimat yang tidak dikenal katalog") == "kalimat yang tidak dikenal katalog"
        assert i18n.gettext("Salinan #%(n)s", n=4) == "Copy #4"
        assert i18n.translate_plural("%(num)s salinan", "%(num)s salinan", 1) == "%(num)s copy"
        assert i18n.translate_plural("%(num)s salinan", "%(num)s salinan", 20) == "%(num)s copies"
    finally:
        i18n.reset(token)
    assert i18n.current() == "id" and i18n.gettext("Salinan #%(n)s", n=4) == "Salinan #4"


def test_numbers_and_dates_follow_the_language():
    assert i18n.number_text("skor 1.277,2 dari 6.148, pukul 15.09.12, ip 10.0.0.1") == \
        "skor 1,277.2 dari 6,148, pukul 15.09.12, ip 10.0.0.1"
    when = "2026-10-24T15:09:12+07:00"
    assert i18n.format_datetime(when) == "24 Oktober 2026 pukul 15.09.12 WIB"
    assert i18n.format_clock(when) == "15.09.12 WIB"
    token = i18n.use("en")
    try:
        assert i18n.format_datetime(when) == "24 October 2026, 15:09:12 WIB"
        assert i18n.format_datetime(when, with_day=True, with_time=False) == "Saturday, 24 October 2026"
        assert i18n.format_clock(when) == "15:09:12 WIB" and i18n.format_clock("2026-10-24") == ""
        assert i18n.localize("1.234,5") == "1,234.5"
    finally:
        i18n.reset(token)
    assert i18n.choose("en", "id") == "en" and i18n.choose(None, "en") == "en" and i18n.choose("xx", None) == "id"


class _VisibleText(HTMLParser):
    """The prose a reader sees: not what sits in a lang="id" element, in code (commands, file
    names and hashes are set in the monospace face), a script or a style."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    SPOKEN = ("aria-label", "title", "placeholder", "alt", "hx-confirm", "data-loading-text")

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[bool] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            if not (self.stack and self.stack[-1]) and a.get("lang") != "id":
                self.parts += self._spoken(a)
            return
        code = {"mono", "code", "hash"} & set((a.get("class") or "").split())
        hidden = (self.stack and self.stack[-1]) or a.get("lang") == "id" or code or tag in ("script", "style", "title")
        if not hidden:
            self.parts += self._spoken(a)
        self.stack.append(bool(hidden))

    def _spoken(self, attrs: dict) -> list[str]:
        """Text a reader meets in attributes (labels, tooltips, prompts), without the quoted
        words of the document (in curly quotes), which an attribute cannot mark lang="id"."""
        return [re.sub("\u201c[^\u201d]*\u201d", "", attrs[k]) for k in self.SPOKEN if attrs.get(k)]

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not (self.stack and self.stack[-1]):
            self.parts.append(data)


def _indonesian_left(page: str) -> list[str]:
    parser = _VisibleText()
    parser.feed(page)
    text = " ".join(" ".join(parser.parts).split())
    return [text[max(0, m.start() - 60):m.end() + 60] for m in STOPWORDS.finditer(text)]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("TAPAK_CANARY_DOMAIN", "kanari.tapak.test")
    from tapak.cli import main as cli_main
    from tapak.web.app import app

    assert cli_main(["keys", "init"]) == 0
    return TestClient(app, base_url="http://127.0.0.1")


def test_the_language_choice_is_kept_in_a_cookie(client):
    r = client.get("/beranda?lang=en")
    assert r.status_code == 200 and '<html lang="en">' in r.text and "SECRET" in r.text
    assert "bahasa=en" in r.headers["set-cookie"]
    assert '<html lang="en">' in client.get("/lacak").text  # the cookie, no query
    assert 'href="/lacak?lang=id"' in client.get("/lacak").text  # the switch keeps the page
    r = client.get("/lacak?lang=id")
    assert '<html lang="id">' in r.text and "RAHASIA" in r.text
    assert '<html lang="id">' in client.get("/registri").text


@pytest.mark.parametrize("path", ["/", "/demo", "/beranda", "/terbitkan", "/lacak", "/registri", "/halaman-tak-ada"])
def test_english_pages_carry_no_indonesian(client, path):
    r = client.get(path, params={"lang": "en"})
    assert '<html lang="en">' in r.text
    assert not _indonesian_left(r.text), _indonesian_left(r.text)[:5]


def test_an_english_issue_and_trace_carry_no_indonesian(client):
    """The whole Terbitkan flow and a trace of a leaked copy, asked for in English."""
    client.cookies.set("bahasa", "en")
    files = {"dokumen": ("nota_dinas.pdf", SAMPLE.read_bytes(), "application/pdf"),
             "penerima": ("recipients.csv", (ROOT / "samples" / "recipients.csv").read_bytes(), "text/csv")}
    r = client.post("/terbitkan/analisis", files=files, data={"c": "3", "eps": "1e-6", "kanari": "kanari.tapak.test"})
    assert "Marking plan" in r.text and not _indonesian_left(r.text), _indonesian_left(r.text)[:5]
    sid = re.search(r"/terbitkan/([0-9a-f]{16})/varian", r.text).group(1)
    units = re.findall(r'name="unit" value="(u\d+)"', r.text)
    r = client.post(f"/terbitkan/{sid}/varian", data={"unit": units})
    assert not _indonesian_left(r.text), _indonesian_left(r.text)[:5]
    for unit in units:
        r = client.post(f"/terbitkan/{sid}/varian/{unit}/semua")
    r = client.post(f"/terbitkan/{sid}/leksikal")
    assert "Review the points" in r.text and not _indonesian_left(r.text), _indonesian_left(r.text)[:5]
    r = client.post(f"/terbitkan/{sid}/leksikal/batal")
    r = client.post(f"/terbitkan/{sid}/terbitkan")
    assert "20 copies ready to share" in r.text and not _indonesian_left(r.text), _indonesian_left(r.text)[:5]
    doc = re.search(r"/dokumen/([0-9a-f]{16})/salinan.zip", r.text).group(1)
    copy = client.get(f"/dokumen/{doc}/salinan/7").content
    r = client.post("/lacak", data={"dokumen": doc}, files={"bukti": ("bocor.pdf", copy, "application/pdf")})
    assert "Identified" in r.text and "Copy #7" in r.text
    assert not _indonesian_left(r.text), _indonesian_left(r.text)[:5]
    for path in ("/beranda", "/registri", f"/lacak?dokumen={doc}"):
        assert not _indonesian_left(client.get(path).text), path
    # the berita acara stays the Indonesian official form
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    assert client.get(f"/lacak/{tid}/berita-acara.pdf").content.startswith(b"%PDF")


def test_english_errors_are_english(client):
    client.cookies.set("bahasa", "en")
    r = client.post("/terbitkan/analisis", files={"dokumen": ("x.pdf", b"not a pdf", "application/pdf")},
                    data={"c": "0", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert "This file is not a PDF" in r.text and "Choose the recipient list" in r.text and "from 1 to 10" in r.text
    r = client.get("/dokumen/0123456789abcdef/salinan.zip")
    assert r.status_code == 404 and "not found" in r.text and not _indonesian_left(r.text)
