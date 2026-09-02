"""External translation provider integration point.

Backs dictionary_service.py when a word isn't in the local database yet.
No provider is wired up yet - this file exists so the rest of the
codebase has a stable interface to import against, per the project rule
against faking work for functions that can't be connected yet.

TODO(stage-9): connect a real provider (configured via config.py, API key
in .env) and implement translate_word() / detect_language() against it.
"""
from __future__ import annotations


async def translate_word(word: str, *, source_language: str, target_language: str) -> str:
    raise NotImplementedError("Translation provider integration arrives in Stage 9 (Dictionary)")


async def detect_language(text: str) -> str:
    raise NotImplementedError("Language detection arrives in Stage 9 (Dictionary)")
