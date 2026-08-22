"""Tests for utils/popular_phrases.py (native-speaker phrasebook stage,
section 17): every supported language has a non-empty curated set, no
Cyrillic/Hebrew leaking into pronunciation (global pronunciation rule,
Latin-only), and an unsupported code degrades to an empty tuple rather
than raising.
"""
from __future__ import annotations

import re

from utils.languages import LANGUAGE_BY_CODE
from utils.popular_phrases import get_popular_phrases
from utils.phrase_situations import PRESET_SITUATIONS

_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")


def test_every_supported_language_has_popular_phrases():
    for code in LANGUAGE_BY_CODE:
        phrases = get_popular_phrases(code)
        assert len(phrases) >= 1, f"no popular phrases for {code}"


def test_pronunciation_is_always_latin_only():
    for code in LANGUAGE_BY_CODE:
        for entry in get_popular_phrases(code):
            assert not _NON_LATIN_RE.search(entry.pronunciation), (code, entry.pronunciation)


def test_every_entry_has_a_known_situation_code():
    for code in LANGUAGE_BY_CODE:
        for entry in get_popular_phrases(code):
            assert entry.situation in PRESET_SITUATIONS


def test_unsupported_language_code_returns_empty_tuple():
    assert get_popular_phrases("xx") == ()
