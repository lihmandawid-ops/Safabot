"""Tests for utils/text.py's truncate_text (bugfix stage: 💡 Как
использовать? must stay a short chat message regardless of how verbose
the AI's actual output is)."""
from __future__ import annotations

from utils.text import truncate_text


def test_truncate_text_leaves_short_text_untouched():
    assert truncate_text("short", 200) == "short"


def test_truncate_text_leaves_text_at_exact_limit_untouched():
    text = "a" * 200
    assert truncate_text(text, 200) == text


def test_truncate_text_cuts_long_text_at_a_word_boundary():
    text = "one two three four five six seven eight nine ten"
    result = truncate_text(text, 20)
    assert len(result) <= 20
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")  # trimmed the trailing partial word, not just cut mid-word


def test_truncate_text_never_exceeds_max_length():
    text = "supercalifragilisticexpialidocious " * 20
    result = truncate_text(text, 50)
    assert len(result) <= 50
