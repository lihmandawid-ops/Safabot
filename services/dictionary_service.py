"""Word lookup: local dictionary first, external translation as fallback
(spec section 13 of the original brief / section 14 of the words stage).

Thin facade over word_service: handlers/dictionary.py calls this, not
word_service directly, so the "fall back to a translation API when the
local dictionary has nothing" policy lives in one place. The fallback
itself is still a stub - translation_service.py has no real provider
wired up yet (Stage 9+ AI/translation integration).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word
from services import word_service


async def lookup_word(session: AsyncSession, *, language_code: str, raw_word: str, limit: int = 5) -> list[Word]:
    """Return the best local matches for `raw_word` in `language_code`.

    TODO(stage-9+): if this returns [], fall back to translation_service
    once a real provider is configured, instead of leaving the user with
    nothing.
    """
    return await word_service.search_words(session, language_code=language_code, query=raw_word, limit=limit)
