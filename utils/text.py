"""Small text helpers shared across handlers."""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_word(raw: str) -> str:
    """Lowercase and collapse whitespace, for matching words against the
    dictionary regardless of case or stray spaces (used by Word.normalized_word,
    Stage 5)."""
    return _WHITESPACE_RE.sub(" ", raw.strip()).casefold()


_NUMBER_SPLIT_RE = re.compile(r"[,\s]+")


def parse_number_list(raw: str) -> list[int]:
    """Parse a user-typed selection like "2,5,7" (spec section 14 of the
    users stage / section 11 of the words stage) into [2, 5, 7]. Accepts
    "2, 5, 7" and "2 5 7" too. Raises ValueError on anything that isn't a
    comma/space-separated list of positive integers.
    """
    parts = [p for p in _NUMBER_SPLIT_RE.split(raw.strip()) if p]
    if not parts:
        raise ValueError("empty selection")
    numbers = [int(p) for p in parts]
    if any(n <= 0 for n in numbers):
        raise ValueError("numbers must be positive")
    return numbers
