"""Deterministic stand-in for the LLM: paraphrases from a table of equivalent phrases.

Each group in ``SUBSTITUTION_GROUPS`` lists Indonesian phrases with the same meaning in
the opening, closing and cc formulas of official letters. A paraphrase replaces one or
more matched phrases with another member of its group. Matches never overlap (longest
phrase wins at a position), so every combination of choices gives a distinct sentence.

``judge_equivalent`` maps every group member to the group's first member and compares the
results: it accepts exactly the sentences this table can produce (and rejects any other
change), after checking that the protected tokens are identical.

Same input, same output, no model file: suitable for tests, demos and CI.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence

from tapak.llm.provider import LLMProvider, protected_tokens

SUBSTITUTION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("demikian", "demikianlah"),
    ("disampaikan", "diberitahukan"),
    ("untuk menjadi perhatian", "agar menjadi perhatian", "untuk diperhatikan"),
    ("dengan penuh tanggung jawab", "secara bertanggung jawab", "dengan rasa tanggung jawab"),
    ("bersama ini", "dengan ini", "melalui surat ini"),
    ("hal-hal sebagai berikut", "beberapa hal berikut", "hal-hal berikut"),
    ("kami sampaikan", "kami beritahukan"),
    ("sebagai berikut", "seperti berikut", "berikut ini"),
    ("untuk dilaksanakan", "agar dilaksanakan"),
    ("dilaporkan pelaksanaannya", "pelaksanaannya dilaporkan"),
)


def _phrase_pattern(phrase: str) -> str:
    return r"\s+".join(re.escape(w) for w in phrase.split())


def _match_case(source: str, replacement: str) -> str:
    """Capitalize ``replacement`` if ``source`` starts with an uppercase letter."""
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class MockProvider(LLMProvider):
    """Table-driven paraphraser and judge (no model, fully deterministic)."""

    name = "mock"

    def __init__(self, groups: Sequence[Sequence[str]] | None = None) -> None:
        self.groups: tuple[tuple[str, ...], ...] = tuple(
            tuple(" ".join(p.lower().split()) for p in g) for g in (groups or SUBSTITUTION_GROUPS)
        )
        self._group_of: dict[str, int] = {}
        for gi, group in enumerate(self.groups):
            for phrase in group:
                self._group_of[phrase] = gi
        phrases = sorted(self._group_of, key=len, reverse=True)  # longest first
        self._regex = re.compile(
            r"(?<!\w)(?:" + "|".join(_phrase_pattern(p) for p in phrases) + r")(?!\w)", re.IGNORECASE
        )

    def _spans(self, sentence: str) -> list[tuple[int, int, int, int]]:
        """(start, end, group index, member index) of every matched phrase, left to right."""
        spans = []
        for m in self._regex.finditer(sentence):
            phrase = " ".join(m.group(0).lower().split())
            gi = self._group_of[phrase]
            spans.append((m.start(), m.end(), gi, self.groups[gi].index(phrase)))
        return spans

    def paraphrase(self, sentence: str, n: int) -> list[str]:
        """Up to ``n`` variants, fewest substitutions first, in a fixed order.

        Variants are enumerated lazily: first every single substitution (span by span, left
        to right), then every pair of spans, and so on, stopping as soon as ``n`` variants
        exist. A long sentence with many matched phrases therefore stays fast.
        """
        spans = self._spans(sentence)
        out: list[str] = []
        if n <= 0:
            return out
        for k in range(1, len(spans) + 1):
            for chosen in itertools.combinations(range(len(spans)), k):
                alternatives = [
                    [m for m in range(len(self.groups[spans[s][2]])) if m != spans[s][3]] for s in chosen
                ]
                for picks in itertools.product(*alternatives):
                    out.append(self._apply(sentence, spans, dict(zip(chosen, picks))))
                    if len(out) >= n:
                        return out
        return out

    def _apply(self, sentence: str, spans: list[tuple[int, int, int, int]], picks: dict[int, int]) -> str:
        """``sentence`` with span ``s`` replaced by member ``picks[s]`` of its group."""
        parts, cursor = [], 0
        for s, (start, end, gi, _) in enumerate(spans):
            if s in picks:
                parts.append(sentence[cursor:start])
                parts.append(_match_case(sentence[start:end], self.groups[gi][picks[s]]))
                cursor = end
        parts.append(sentence[cursor:])
        return "".join(parts)

    def canonical(self, sentence: str) -> str:
        """Lowercase sentence with every table phrase replaced by its group's first member."""
        def repl(m: re.Match[str]) -> str:
            return self.groups[self._group_of[" ".join(m.group(0).lower().split())]][0]

        return self._regex.sub(repl, " ".join(sentence.lower().split()))

    def judge_equivalent(self, original: str, candidate: str) -> tuple[bool, str]:
        """Equivalent iff protected tokens match and only table phrases were exchanged."""
        if protected_tokens(original) != protected_tokens(candidate):
            return False, "token terlindungi (angka, nama, atau kata kunci) berubah"
        if self.canonical(original) != self.canonical(candidate):
            return False, "ada perubahan di luar tabel frasa baku yang setara"
        return True, "setara: hanya frasa baku yang diganti dengan padanannya"
