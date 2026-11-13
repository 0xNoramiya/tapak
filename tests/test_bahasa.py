"""Indonesian and English in the web UI and the berita acara (tapak/i18n).

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

from tapak import i18n
from tapak.i18n.en import EN, PATTERNS, RULES

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "tapak" / "web"
REPORT = ROOT / "tapak" / "decoder" / "report.py"
REPORT_TEMPLATE = ROOT / "tapak" / "decoder" / "templates" / "berita_acara.html"
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
EM_DASH = chr(0x2014)
# Indonesian words that never occur in the English copy (whole words, any case).
STOPWORDS = re.compile(r"\b(yang|dan|untuk|dengan|tidak|belum|sudah|dapat|ini|itu|atau|halaman|salinan|"
                       r"penerima|kanal|unduh|terbitkan|pelacakan|bukti|berkas|dokumen)\b", re.IGNORECASE)


def _messages() -> dict[str, str]:
    """Every message of the web UI and the berita acara: _(), ngettext() and {% trans %} in the
    templates, and the _() / N_() calls of tapak/web/*.py and report.py. Value: where it was found."""
    found: dict[str, str] = {}
    for template in [*sorted((WEB / "templates").glob("*.html")), REPORT_TEMPLATE]:
        with open(template, "rb") as f:
            for lineno, _func, msg, _comments in babel_extract(
                    f, ["_", "gettext", "ngettext"], [], {"trimmed": "true", "extensions": "jinja2.ext.i18n,jinja2.ext.do"}):
                first = msg[0] if isinstance(msg, tuple) else msg
                if first:
                    found.setdefault(first, f"{template.name}:{lineno}")
    for module in [*sorted(WEB.glob("*.py")), REPORT]:
        for node in ast.walk(ast.parse(module.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{module.name}:{node.lineno}")
    for key in ("media", "sungguhan"):
        for row in json.loads((WEB / "landing.json").read_text(encoding="utf-8"))[key]:
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
    # a placeholder inside a rule may hold "; " (the OCR engine names its language data)...
    ("Kotak kata: tesseract 5.3.0; ind.traineddata sha256:69786901; hanya hash daftar kotaknya yang dicatat "
     "(c4de30064f23f7ec...)",
     "Word boxes: tesseract 5.3.0; ind.traineddata sha256:69786901; only the hash of the box list is recorded "
     "(c4de30064f23f7ec...)"),
    # ...but one starting or ending it does not swallow the clauses joined before or after it
    ("cocok dengan registri sampai entri #12; 2 entri terakhir (#13..#14) belum tercatat di log dan dilengkapi pada "
     "penulisan berikutnya",
     "matches the registry up to entry #12; the last 2 entries (#13..#14) are not in the log yet and are added on the "
     "next write"),
    # "; " inside parentheses, and a clause that holds "; " itself
    ("cocok dengan registri sampai entri #12; log memuat 1 pengakuan pemulihan, terakhir 2026-10-24 (3 entri dilepas; "
     "lihat tapak verify)",
     "matches the registry up to entry #12; recovery acknowledgements in the log: 1, the last 2026-10-24 (3 entries "
     "released; see tapak verify)"),
    ("cocok dengan registri sampai entri #12; log ini dimulai ulang di entri #5 (2026-10-24) setelah log sebelumnya "
     "hilang atau dipindah; entri yang dihapus dari ujung registri sebelum itu tidak terlihat oleh log ini (periksa "
     "dengan log lama atau jangkar berita acara, tapak verify --jangkar)",
     "matches the registry up to entry #12; this log was started again at entry #5 (2026-10-24) after the earlier log "
     "was lost or moved; entries deleted from the end of the registry before that are invisible to this log (check "
     "with the old log or a forensic report anchor, tapak verify --jangkar)"),
    ("3 entri (#4..#6) belum bertanda tangan; entri itu hanya dilindungi rantai hash, yang dapat dihitung ulang oleh "
     "siapa pun",
     "3 entries (#4..#6) are not signed yet; they are protected only by the hash chain, which anyone can recompute"),
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


# Modules whose messages reach only the terminal (the command line, research scripts, the DNS
# listener), which stays Indonesian.
TERMINAL_ONLY = {"cli.py", "benchmark.py", "collusion.py", "samplegen.py", "tardos/simulate.py", "tardos/attacks.py",
                 "canary_dns/__main__.py", "canary_dns/server.py"}


def _message_texts(node: ast.expr, fill: str, names: dict[str, ast.expr]) -> list[str] | None:
    """Every text an exception message can take, its values filled in with ``fill``: a literal,
    an f-string (a conditional of two literals gives both texts), a sum of those, or a local
    variable holding one. None when the message is built some other way."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and node.id in names:
        return _message_texts(names[node.id], fill, names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _message_texts(node.left, fill, names), _message_texts(node.right, fill, names)
        return None if left is None or right is None else [a + b for a in left for b in right]
    if not isinstance(node, ast.JoinedStr):
        return None
    texts = [""]
    for part in node.values:
        if isinstance(part, ast.Constant):
            options = [part.value]
        elif (isinstance(part.value, ast.IfExp) and all(isinstance(b, ast.Constant) and isinstance(b.value, str)
                                                         for b in (part.value.body, part.value.orelse))):
            options = [part.value.body.value, part.value.orelse.value]
        else:
            options = _message_texts(part.value, fill, names) if isinstance(part.value, ast.Name) else None
            options = options or [fill]
        texts = [t + o for t in texts for o in options]
    return texts


def _raised_messages(path: Path):
    """(line, [texts with "7" filled in, texts with "x"]) for each exception raised with a message
    in a module, SystemExit (the terminal) aside."""
    tree = ast.parse(path.read_text())
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    module = [n for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
              for n in ast.walk(s)]
    for nodes in [module, *(list(ast.walk(f)) for f in functions)]:
        names = {n.targets[0].id: n.value for n in nodes
                 if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
        for node in nodes:
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args):
                continue
            if isinstance(node.exc.func, ast.Name) and node.exc.func.id == "SystemExit":
                continue
            samples = [_message_texts(node.exc.args[0], fill, names) for fill in ("7", "x")]
            if samples[0] is not None:
                yield node.lineno, samples


def test_library_errors_read_in_english():
    """A refused request shows the library's error message, so every message a page can show
    has English (an exact entry or a rule)."""
    def english(text: str) -> bool:
        found = i18n.translate_text(text)
        return found != text and not STOPWORDS.search(found)

    token = i18n.use("en")
    missing, seen = [], 0
    try:
        for path in sorted((ROOT / "tapak").rglob("*.py")):
            rel = path.relative_to(ROOT / "tapak").as_posix()
            if rel in TERMINAL_ONLY or rel.startswith("i18n/"):
                continue
            for line, samples in _raised_messages(path):
                seen += 1
                if not any(all(english(t) for t in texts) for texts in samples):
                    missing.append(f"tapak/{rel}:{line}: {samples[0][0]!r}")
    finally:
        i18n.reset(token)
    assert seen > 200
    assert not missing, "\n".join(sorted(set(missing)))


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
    # the berita acara in English is a rendition; ?asli=1 gives the Indonesian official form
    tid = re.search(r"/lacak/([0-9a-f]{16})/berita-acara.pdf", r.text).group(1)
    english = _pdf_text(client.get(f"/lacak/{tid}/berita-acara.pdf").content)
    assert "DIGITAL EXAMINATION REPORT" in english and "VERDICT: IDENTIFIED" in english
    prose = re.sub(r"tapak trace .*?(?=The command)", "", english)  # the command keeps its flags
    assert not [m.group(0) for m in STOPWORDS.finditer(prose)], prose[:300]
    official = client.get(f"/lacak/{tid}/berita-acara.pdf?asli=1")
    assert "BERITA ACARA PEMERIKSAAN DIGITAL" in _pdf_text(official.content)
    assert official.headers["content-disposition"].endswith(f'berita_acara_{tid}.pdf"')


def _pdf_text(pdf: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return " ".join(" ".join(page.get_text() for page in doc).split())


def test_english_errors_are_english(client):
    client.cookies.set("bahasa", "en")
    r = client.post("/terbitkan/analisis", files={"dokumen": ("x.pdf", b"not a pdf", "application/pdf")},
                    data={"c": "0", "eps": "1e-6"}, headers={"HX-Request": "true"})
    assert "This file is not a PDF" in r.text and "Choose the recipient list" in r.text and "from 1 to 10" in r.text
    r = client.get("/dokumen/0123456789abcdef/salinan.zip")
    assert r.status_code == 404 and "not found" in r.text and not _indonesian_left(r.text)
