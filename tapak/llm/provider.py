"""Provider interface for the local language model behind the semantic channel (channel 4).

A provider does two things for a sentence the issuer has marked as safe to rephrase:

* ``paraphrase``: propose meaning-preserving rewordings;
* ``judge_equivalent``: a second pass that says whether a candidate keeps the meaning.

TAPAK never trusts the model alone. Every candidate also passes automatic checks in
``tapak.marker.semantic`` (protected tokens, safety rules, layout fit) and a human approval
step in the review UI. Only local providers exist, so document text never leaves the host.

``protected_tokens`` lists the tokens a paraphrase must keep exactly: anything with a
digit, every capitalized word except the first one (names, units, ranks), and a few key
words whose loss would change the meaning (negations, obligations, the passive verbs of
standard closing formulas).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Characters stripped from both ends of a token (ASCII punctuation and typographic quotes).
_PUNCT = ".,;:!?\"'()[]{}<>\u201c\u201d\u2018\u2019\u00ab\u00bb"

KEY_WORDS = frozenset({
    "tidak", "tak", "bukan", "jangan", "belum", "tanpa", "tiada",  # negation
    "wajib", "harus", "dilarang", "segera", "perlu",               # obligation and urgency
    "dilaksanakan", "dilaporkan", "pelaksanaan", "pelaksanaannya",  # words of closing formulas
})


def split_words(text: str) -> list[str]:
    """Whitespace tokens with surrounding punctuation removed (inner hyphens, dots, slashes kept)."""
    return [w for w in (t.strip(_PUNCT) for t in text.split()) if w]


def is_capitalized(token: str) -> bool:
    """True if the first letter of ``token`` is uppercase."""
    for ch in token:
        if ch.isalpha():
            return ch.isupper()
    return False


def protected_tokens(text: str) -> list[str]:
    """Sorted tokens a paraphrase must keep: digits, capitalized words after the first, key words."""
    out: list[str] = []
    for i, tok in enumerate(split_words(text)):
        if any(ch.isdigit() for ch in tok):
            out.append(tok)
        elif tok.lower() in KEY_WORDS:
            out.append(tok.lower())
        elif i > 0 and is_capitalized(tok):
            out.append(tok)
    return sorted(out)


class LLMProvider(ABC):
    """A local model that proposes paraphrases and judges equivalence."""

    name: str = "abstract"

    @abstractmethod
    def paraphrase(self, sentence: str, n: int) -> list[str]:
        """Return up to ``n`` candidate rewordings of ``sentence`` (the original excluded)."""

    @abstractmethod
    def judge_equivalent(self, original: str, candidate: str) -> tuple[bool, str]:
        """Return (equivalent, reason); the reason is a short Indonesian explanation."""


def get_provider(name: str = "mock", **kwargs: object) -> LLMProvider:
    """Build a provider by name: ``"mock"`` (default, deterministic) or ``"llamacpp"``."""
    key = name.strip().lower().replace(".", "").replace("_", "").replace("-", "")
    if key == "mock":
        from tapak.llm.mock import MockProvider

        return MockProvider(**kwargs)  # type: ignore[arg-type]
    if key == "llamacpp":
        from tapak.llm.llamacpp import LlamaCppProvider

        return LlamaCppProvider(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"penyedia LLM tidak dikenal: {name!r} (pilihan: mock, llamacpp)")
