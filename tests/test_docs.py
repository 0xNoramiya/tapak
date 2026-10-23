"""The documentation points only at things that exist: files, headings, make targets, CLI options.

Covers README.md, docs/*.md and research/*/README.md. Anchors follow GitHub's heading slugs, since
the judges read the docs on GitHub; a renamed heading or a removed option fails here instead of
leaving a dead link or a command that errors out.
"""

from __future__ import annotations

import argparse
import re
import shlex
from collections import Counter
from pathlib import Path

import pytest

from tests_support import ROOT

DOCS = sorted([ROOT / "README.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "research").glob("*/README.md")])
FENCE = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_LINK = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
SRCSET = re.compile(r"""srcset=["']([^"']+)["']""")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SEPARATORS = {"&&", "||", ";", "|"}


def _split(path: Path) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(prose lines, code-block lines) of a Markdown file, each with its 1-based line number."""
    prose, code, fenced = [], [], False
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        (code if fenced else prose).append((no, line))
    return prose, code


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: inline markup dropped, lower case, punctuation removed."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").replace("*", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    seen: Counter[str] = Counter()
    out = set()
    for _, line in _split(path)[0]:
        m = HEADING.match(line)
        if not m:
            continue
        slug = _slug(m.group(2))
        out.add(slug if not seen[slug] else f"{slug}-{seen[slug]}")
        seen[slug] += 1
    for _, line in _split(path)[0]:
        out.update(re.findall(r"""<a\s+(?:id|name)=["']([^"']+)["']""", line))
    return out


def _links(path: Path):
    for no, line in _split(path)[0]:
        bare = INLINE_CODE.sub("", line)
        targets = MD_LINK.findall(bare) + HTML_LINK.findall(bare)
        for srcset in SRCSET.findall(bare):
            targets += [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        for target in targets:
            if not re.match(r"^[a-z][a-z0-9+.-]*:", target):
                yield no, target


def test_every_relative_link_and_anchor_resolves():
    broken = []
    for doc in DOCS:
        for no, target in _links(doc):
            file_part, _, anchor = target.partition("#")
            dest = (doc.parent / file_part).resolve() if file_part else doc
            where = f"{doc.relative_to(ROOT)}:{no}: {target}"
            if not dest.exists():
                broken.append(f"{where} (missing file)")
            elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
                broken.append(f"{where} (no such heading)")
    assert not broken, "\n".join(broken)


def _snippets(doc: Path):
    """Every code line and inline code span of a document, as candidate command lines."""
    prose, code = _split(doc)
    yield from code
    for no, line in prose:
        for span in INLINE_CODE.findall(line):
            yield no, span


def _commands(text: str) -> list[list[str]]:
    try:
        tokens = shlex.split(text, comments=True)
    except ValueError:
        tokens = text.split()
    out, cur = [], []
    for tok in tokens:
        if tok in SEPARATORS:
            out.append(cur)
            cur = []
        else:
            cur.append(tok)
    return [c for c in out + [cur] if c]


def _make_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Za-z][\w-]*):", text, flags=re.M))


def test_every_make_target_in_the_docs_exists():
    targets, missing = _make_targets(), []
    for doc in DOCS:
        for no, text in _snippets(doc):
            for cmd in _commands(text):
                if cmd[0] != "make":
                    continue
                for tok in cmd[1:]:
                    if "=" in tok or tok.startswith("-"):
                        continue
                    if not re.fullmatch(r"[a-z][\w-]*", tok):
                        break
                    if tok not in targets:
                        missing.append(f"{doc.relative_to(ROOT)}:{no}: make {tok}")
    assert not missing, "\n".join(missing)


def _grab_parser(main, monkeypatch) -> argparse.ArgumentParser:
    """The parser a console entry point builds, captured when it starts parsing."""

    class Got(Exception):
        pass

    def grab(self, *args, **kwargs):
        raise Got(self)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", grab)
    try:
        main([])
    except Got as got:
        return got.args[0]
    finally:
        monkeypatch.undo()
    raise AssertionError(f"{main} built no parser")


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


@pytest.fixture(scope="module")
def parsers():
    from tapak.canary_dns.__main__ import _parser as canary_parser
    from tapak.cli import build_parser

    return {"tapak": build_parser(), "canary": canary_parser()}


def test_every_cli_option_in_the_docs_exists(parsers, monkeypatch):
    import tapak.photos
    import tapak.registry.verify

    extra = {"tapak-verify-registry": _grab_parser(tapak.registry.verify.main, monkeypatch),
             "photos": _grab_parser(tapak.photos.main, monkeypatch), "canary-dns": parsers["canary"]}
    modules = {"tapak.canary_dns": "canary-dns", "tapak.photos": "photos"}
    root = parsers["tapak"]
    global_opts = {"--data", "--keys", "--log-jangkar"}
    problems, checked = [], 0
    for doc in DOCS:
        for no, text in _snippets(doc):
            for cmd in _commands(text):
                where = f"{doc.relative_to(ROOT)}:{no}: {' '.join(cmd)}"
                rest, parser = None, None
                for i, tok in enumerate(cmd):
                    name = tok.rsplit("/", 1)[-1]
                    if name == "tapak":
                        rest, parser = cmd[i + 1:], root
                        break
                    if name == "tapak-verify-registry":
                        rest, parser = cmd[i + 1:], extra[name]
                        break
                    if tok == "-m" and i + 1 < len(cmd) and cmd[i + 1] in modules:
                        rest, parser = cmd[i + 2:], extra[modules[cmd[i + 1]]]
                        break
                if parser is None:
                    continue
                while parser is root and rest and rest[0] in global_opts:
                    rest = rest[2:]
                while _subparsers(parser) and rest:
                    if rest[0] in extra and parser is root:
                        parser, rest = extra[rest[0]], rest[1:]
                        break
                    choices = _subparsers(parser)
                    if rest[0] not in choices:
                        if not re.fullmatch(r"[a-z][\w-]*", rest[0]):
                            break
                        problems.append(f"{where} (no such command '{rest[0]}')")
                        rest = []
                        break
                    parser, rest = choices[rest[0]], rest[1:]
                known = _options(parser) | (global_opts if parser is root else set())
                for tok in rest:
                    opt = tok.split("=", 1)[0]
                    if re.fullmatch(r"--?[a-z][\w-]*", opt):
                        checked += 1
                        if opt not in known:
                            problems.append(f"{where} (unknown option '{opt}')")
    assert not problems, "\n".join(problems)
    assert checked > 50, f"only {checked} options found: the command extraction broke"
