"""Indonesian and English for the web UI.

Indonesian is the source language: every message is written in Indonesian in the templates and
in the code, and ``tapak/web/en.py`` maps it to English. A request's language comes from
``?lang=id|en`` (remembered in the ``bahasa`` cookie), else the cookie, else Indonesian. It is
held in a context variable while the request is handled, so code below the route asks
:func:`current` instead of passing the request around.

Text the core library writes (trace notes, registry problems, error messages) is Indonesian
too: :func:`translate_text` turns the sentences that reach the pages into English with the
entries and rules of ``en`` and returns a sentence it does not know unchanged.

Messages are %-formatted, in templates (Jinja's newstyle gettext) and in Python alike, so a
literal percent sign in a message is written ``%%``.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from datetime import datetime

from tapak.web.en import EN, PATTERNS

LANGS = ("id", "en")
DEFAULT = "id"
COOKIE = "bahasa"
_current: ContextVar[str] = ContextVar("bahasa", default=DEFAULT)


def current() -> str:
    """The language of the request being handled: "id" or "en"."""
    return _current.get()


def use(lang: str) -> Token:
    """Make ``lang`` (or Indonesian, for an unknown value) the language of this context."""
    return _current.set(lang if lang in LANGS else DEFAULT)


def reset(token: Token) -> None:
    """Undo :func:`use`."""
    _current.reset(token)


def choose(query: str | None, cookie: str | None) -> str:
    """The language of a request: the ``lang`` query parameter, else the cookie, else Indonesian."""
    for value in (query, cookie):
        if value in LANGS:
            return value  # type: ignore[return-value]
    return DEFAULT


def translate(message: str) -> str:
    """``message`` in the current language, unformatted (Jinja's gettext formats it)."""
    if _current.get() != "en":
        return message
    text = EN.get(message, message)
    return text[0] if isinstance(text, tuple) else text


def translate_plural(singular: str, plural: str, n: int) -> str:
    """Jinja's ngettext: an English entry may be a pair (one, other); Indonesian has one form."""
    if _current.get() != "en":
        return singular
    text = EN.get(singular, plural if n != 1 else singular)
    if isinstance(text, tuple):
        return text[0] if n == 1 else text[1]
    return text


def gettext(message: str, **variables: object) -> str:
    """``message`` in the current language, %-formatted with ``variables``."""
    return translate(message) % variables


def N_(message: str) -> str:
    """Marks an Indonesian message where it is defined (a module constant) for the catalog test;
    it is translated where it is shown."""
    return message


def translate_text(text: str) -> str:
    """A sentence written by the core library, in English when the request is English and the
    catalog knows it (``en.EN`` or ``en.RULES``); otherwise unchanged."""
    if _current.get() != "en" or not text:
        return text
    return _english_sentence(text) or text


def _english_sentence(text: str) -> str | None:
    """English for a library sentence, also as a page shows it (capitalised, with a final full
    stop); None when the catalog does not know it. Exact entries win over rules."""
    core, stop = (text[:-1], ".") if text.endswith(".") and not text.endswith("..") else (text, "")
    candidates = [(text, "", False), (core, stop, False), (core[:1].lower() + core[1:], stop, core[:1].isupper())]

    def finish(found: str, end: str, capital: bool) -> str:
        return (found[:1].upper() + found[1:] if capital else found) + end

    for candidate, end, capital in candidates:
        exact = EN.get(candidate)
        if isinstance(exact, str):
            return finish(exact, end, capital)
    for candidate, end, capital in candidates:
        for pattern, flags, template in PATTERNS:
            m = pattern.fullmatch(candidate)
            if m:
                return finish(template.format(**{k: _value(v, flags[k]) for k, v in m.groupdict().items()}), end,
                              capital)
    if "; " in core:  # clauses joined by the library ("...; kanal semantik dilewati")
        clauses = [_english_sentence(c) for c in core.split("; ")]
        if all(clauses):
            return "; ".join(clauses) + stop  # type: ignore[arg-type]
    return None


def _value(value: str, flag: str) -> str:
    """A placeholder's text in the English sentence: translated (t), a "; " or ", " list of
    translated items (l, c), or as it is with its numbers rewritten."""
    if flag == "t":
        return _english_sentence(value) or number_text(value)
    if flag in ("l", "c"):
        sep = "; " if flag == "l" else ", "
        return sep.join(_english_sentence(item) or number_text(item) for item in value.split(sep))
    return number_text(value)


_ID_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?![\d])(?![.,]\d)")


def number_text(text: str) -> str:
    """The Indonesian numbers of a sentence written the English way: 1.234,5 becomes 1,234.5.
    A time such as 15.09.12 or an address such as 10.0.0.1 is left alone."""
    def swap(m: re.Match) -> str:
        return m.group(1).replace(".", ",") + ("." + m.group(2) if m.group(2) else "")

    return _ID_NUMBER.sub(swap, text)


def localize(text: str) -> str:
    """A number or measure formatted the Indonesian way (``report.format_number``), in the
    current language."""
    return number_text(text) if _current.get() == "en" else text


_EN_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December")


def format_datetime(value: str, with_day: bool = False, with_time: bool = True) -> str:
    """``report.format_datetime`` in the current language: '24 October 2026, 15:09:12 WIB' in
    English. A value that is not ISO 8601 is returned unchanged."""
    from tapak.decoder.report import format_datetime as indonesian

    if _current.get() != "en":
        return indonesian(value, with_day=with_day, with_time=with_time)
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    text = f"{dt.day} {_EN_MONTHS[dt.month - 1]} {dt.year}"
    if with_day:
        text = f"{_EN_DAYS[dt.weekday()]}, {text}"
    clock = format_clock(value)
    return f"{text}, {clock}" if with_time and clock else text


def format_clock(value: str) -> str:
    """The time of day of an ISO time, with its zone: '15.09.12 WIB' ('15:09:12 WIB' in
    English); '' for a date without a time."""
    from tapak.decoder.report import format_datetime as indonesian

    clock = indonesian(value).partition(" pukul ")[2]
    if _current.get() == "en" and clock:
        time_of_day, _, zone = clock.partition(" ")
        clock = f"{time_of_day.replace('.', ':')} {zone}".rstrip()
    return clock
