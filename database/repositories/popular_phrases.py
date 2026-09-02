"""Data access for AI-generated 🔥 Популярные фразы rows (✨ Сгенерировать
ещё, native-speaker phrasebook stage). See database.models.PopularPhrase
for why this is a separate table from the static
utils.popular_phrases.POPULAR_PHRASES seed set.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PopularPhrase
from utils.text import normalize_word


async def list_by_language(session: AsyncSession, *, language_code: str) -> list[PopularPhrase]:
    """Ascending id order - the same stable order phrase_service.py
    relies on to keep each row's combined-list index fixed forever."""
    result = await session.execute(
        select(PopularPhrase).where(PopularPhrase.language_code == language_code).order_by(PopularPhrase.id.asc())
    )
    return list(result.scalars().all())


async def add(
    session: AsyncSession, *, language_code: str, phrase: str, pronunciation: str | None, category: str | None,
    level: str | None = None,
) -> PopularPhrase:
    row = PopularPhrase(
        language_code=language_code, phrase=phrase, normalized_phrase=normalize_word(phrase),
        pronunciation=pronunciation, category=category, level=level,
    )
    session.add(row)
    await session.flush()
    return row
