"""Simulated retyping and OCR of leaked text (for tests and measurements, not for tracing).

``retype(text, rng, level)`` returns what a person retyping the document, or an OCR engine
reading it, might produce. Noise is applied per word:

* typo: one keyboard edit (neighbour substitution or insertion, deletion, transposition,
  doubled letter);
* ocr: one OCR confusion (rn/m, cl/d, l/1, i/l, e/c, a/o, u/n, h/b, ...);
* drop: the word is left out;
* merge: the space after the word is lost;
* split: a space is inserted inside the word;
* punct: trailing punctuation dropped;
* case: case of the first letter flipped.

Invisible symbols are dropped and look-alike letters read as Latin first (a person retypes
what they see). Line breaks are discarded and the text is rewrapped at a random width. ``habit`` is the
share of lexical points where the retyper writes the master form instead of the copy's form
(a systematic error the decoder cannot see; see ``apply_habit``). The levels were fixed
before any result was seen and are the ones of the research report (``sedang`` is the
measured default: 5 % typos).
"""

from __future__ import annotations

import random

LEVELS: dict[str, dict[str, float]] = {
    "ringan": dict(typo=0.02, ocr=0.0, drop=0.005, merge=0.005, split=0.0, punct=0.02, case=0.01),
    "sedang": dict(typo=0.05, ocr=0.01, drop=0.01, merge=0.01, split=0.005, punct=0.05, case=0.02),
    "berat": dict(typo=0.10, ocr=0.03, drop=0.03, merge=0.03, split=0.01, punct=0.10, case=0.05),
    "ocr": dict(typo=0.0, ocr=0.05, drop=0.005, merge=0.02, split=0.02, punct=0.05, case=0.0),
}

_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]


def _neighbours() -> dict[str, str]:
    out: dict[str, str] = {}
    for r, row in enumerate(_ROWS):
        for c, ch in enumerate(row):
            near = []
            for rr in (r - 1, r, r + 1):
                for cc in (c - 1, c, c + 1):
                    if (rr, cc) != (r, c) and 0 <= rr < len(_ROWS) and 0 <= cc < len(_ROWS[rr]):
                        near.append(_ROWS[rr][cc])
            out[ch] = "".join(near)
    return out


_NEIGH = _neighbours()
OCR_CONFUSIONS = (("rn", "m"), ("m", "rn"), ("cl", "d"), ("d", "cl"), ("l", "1"), ("1", "l"), ("i", "l"),
                  ("l", "i"), ("e", "c"), ("c", "e"), ("a", "o"), ("o", "a"), ("u", "n"), ("n", "u"),
                  ("h", "b"), ("b", "h"), ("w", "vv"), ("t", "f"), ("f", "t"), ("O", "0"), ("0", "O"),
                  ("S", "5"), ("g", "q"), ("ri", "n"), ("in", "m"))


def typo(word: str, rng: random.Random) -> str:
    """One keyboard edit in ``word`` (unchanged if it has no letter)."""
    letters = [i for i, ch in enumerate(word) if ch.isalpha()]
    if not letters:
        return word
    i = rng.choice(letters)
    near = _NEIGH.get(word[i].lower(), "aeiou")
    op = rng.randrange(5)
    if op == 0:
        return word[:i] + rng.choice(near) + word[i + 1:]
    if op == 1:
        return word[:i] + rng.choice(near) + word[i:]
    if op == 2 and len(word) > 1:
        return word[:i] + word[i + 1:]
    if op == 3 and i + 1 < len(word):
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    return word[:i] + word[i] + word[i:]


def ocr_confusion(word: str, rng: random.Random) -> str:
    """One OCR confusion in ``word`` (unchanged if none applies)."""
    options = [(a, b) for a, b in OCR_CONFUSIONS if a in word]
    if not options:
        return word
    a, b = rng.choice(options)
    i = rng.choice([k for k in range(len(word)) if word.startswith(a, k)])
    return word[:i] + b + word[i + len(a):]


def retype(text: str, rng: random.Random, level: str | dict[str, float] = "sedang") -> str:
    """A noisy retyped version of ``text`` (see the module docstring for the noise model).

    A person retyping sees only the visible letters, so invisible symbols are dropped and
    look-alike letters become plain Latin before any noise is added.
    """
    from tapak.marker.pdf_zerowidth import normalize_text

    cfg = LEVELS[level] if isinstance(level, str) else level
    words: list[str] = []
    joins: list[str] = []
    for w in normalize_text(text).split():
        if rng.random() < cfg["drop"]:
            continue
        if rng.random() < cfg["typo"]:
            w = typo(w, rng)
        if rng.random() < cfg["ocr"]:
            w = ocr_confusion(w, rng)
        if rng.random() < cfg["punct"]:
            w = w.rstrip(".,;:") or w
        if rng.random() < cfg["case"] and w[:1].isalpha():
            w = (w[0].lower() if w[0].isupper() else w[0].upper()) + w[1:]
        if rng.random() < cfg["split"] and len(w) > 3:
            k = rng.randrange(1, len(w) - 1)
            w = w[:k] + " " + w[k:]
        words.append(w)
        joins.append("" if rng.random() < cfg["merge"] else " ")
    width = rng.randrange(50, 110)
    lines, cur = [], ""
    for w, j in zip(words, joins):
        cur += w
        if len(cur) >= width:
            lines.append(cur)
            cur = ""
        else:
            cur += j
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def apply_habit(choice: dict[str, int], rng: random.Random, rate: float) -> dict[str, int]:
    """Form choices with a share ``rate`` of points reverted to the master form (index 0)."""
    return {k: (0 if rng.random() < rate else v) for k, v in choice.items()}
