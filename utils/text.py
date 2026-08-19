"""Small text helpers shared across handlers."""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_word(raw: str) -> str:
    """Lowercase and collapse whitespace, for matching words against the
    dictionary regardless of case or stray spaces (used by Word.normalized_word,
    Stage 5)."""
    return _WHITESPACE_RE.sub(" ", raw.strip()).casefold()


def parse_number_list(raw: str) -> list[int]:
    """Parse a user-typed selection like "2,5,7" (spec section 14) into
    [2, 5, 7]. Raises ValueError on anything that isn't a comma-separated
    list of positive integers.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("empty selection")
    numbers = [int(p) for p in parts]
    if any(n <= 0 for n in numbers):
        raise ValueError("numbers must be positive")
    return numbers
