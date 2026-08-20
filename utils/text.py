"""Small text helpers shared across handlers."""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_word(raw: str) -> str:
    """Lowercase and collapse whitespace, for matching words against the
    dictionary regardless of case or stray spaces (used by Word.normalized_word,
    Stage 5)."""
    return _WHITESPACE_RE.sub(" ", raw.strip()).casefold()


_WORD_BATCH_SPLIT_RE = re.compile(r"[,\n]+")


def split_word_batch(raw: str) -> list[str]:
    """Split a user-typed word list on commas and/or newlines (bugfix
    spec's ➕ Добавить слово: "несколько слов через запятую или с новой
    строки"). Deliberately NOT split on plain spaces, unlike
    parse_number_list, since a single entry may itself be a multi-word
    phrase (e.g. "give up"). A single entry with no separators simply
    yields a one-item list.
    """
    return [p.strip() for p in _WORD_BATCH_SPLIT_RE.split(raw) if p.strip()]


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


def truncate_text(text: str, max_length: int) -> str:
    """Cuts `text` down to `max_length` characters (ellipsis included) at
    a word boundary where possible - a defensive safety net for AI output
    a prompt asked to be short but that isn't guaranteed to comply (bugfix
    stage: 💡 Как использовать? must stay a short chat message, not a
    wall of text, regardless of what the model actually returns)."""
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1].rsplit(" ", 1)[0]
    return f"{cut}…"
