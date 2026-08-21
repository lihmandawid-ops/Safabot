"""Centralized pronunciation facade (global pronunciation rule, section 38):
every place in Safabot that needs to show a foreign learning word's
pronunciation goes through this module instead of re-implementing the
"backfill, then format, then fall back to a placeholder" pattern by hand
in each handler.

This is intentionally a thin wrapper, not a new subsystem - it composes
two primitives that already existed and were already correct on their
own, just duplicated inline at several call sites:

- services.word_service.ensure_pronunciation: DB-cached-first, AI-backfill
  -on-demand, never overwrites an existing value (section 39/40's
  save -> AI-fallback priority and never-regenerate-what's-cached rule).
- utils.word_display.format_pronunciation: Latin-readable-first display,
  IPA only as a last-resort fallback (sections 35-36).

No DB fields, tables, or caching behavior are introduced here - this is
purely a call-site consolidation.
"""
from __future__ import annotations

from database.models import Word
from services import word_service
from utils.i18n import get_current_language, t
from utils.word_display import format_pronunciation as _format_pronunciation


async def ensure(session, word: Word, *, translation_language: str, user_id: int) -> Word:
    """Backfills word.pronunciation/phonetic if missing (no-op, no AI call,
    when already set). Thin re-export of word_service.ensure_pronunciation
    so callers only need to import this one module for pronunciation."""
    return await word_service.ensure_pronunciation(
        session, word, translation_language=translation_language, user_id=user_id
    )


def format_pronunciation(word: Word) -> str | None:
    """The Latin-readable pronunciation to display, or None if nothing is
    available yet. Thin re-export of utils.word_display.format_pronunciation."""
    return _format_pronunciation(word)


def display_line(word: Word) -> str:
    """The one unified "🔊 pronunciation" line format used everywhere a
    word's pronunciation is shown inline (section 37) - falls back to the
    existing "not available yet" placeholder message when nothing is
    cached/backfilled, so callers never need to hand-roll this ternary."""
    pronunciation = _format_pronunciation(word)
    if pronunciation:
        return t("card.pronunciation_line", get_current_language(), pronunciation=pronunciation)
    return t("card.pronunciation_placeholder", get_current_language())


async def ensure_and_format(session, word: Word, *, translation_language: str, user_id: int) -> str | None:
    """Backfill-then-format in one call, for the common case where a
    caller wants the display string and doesn't need the Word object
    back separately."""
    word = await ensure(session, word, translation_language=translation_language, user_id=user_id)
    return _format_pronunciation(word)
