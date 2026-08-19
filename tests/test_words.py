"""Word/UserWord tests (spec section 32): add/delete word, pause/resume,
filtering, numbering, bulk selection.

Skipped until database.models.Word/UserWord and handlers/words.py land in
Stage 5/8 - see DEVELOPMENT RULES (spec section 34). Kept here as a
checklist so the next stage knows exactly what to cover.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Word/UserWord models arrive in Stage 5 (Words); My Words UI in Stage 8."
)


def test_add_word_to_learning():
    ...


def test_delete_word_removes_it_from_learning():
    ...


def test_pause_word_keeps_it_but_excludes_from_review():
    ...


def test_resume_paused_word_returns_it_to_review():
    ...


def test_filter_words_by_status():
    ...


def test_numbered_list_matches_display_order():
    ...


def test_bulk_selection_parses_comma_separated_numbers():
    ...
