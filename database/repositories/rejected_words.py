"""Data access for RejectedWord (AI-new-words stage sections 6-7): "❌ Я
уже знаю это слово" on a freshly generated candidate word - excluded from
future AI-generated batches, never turned into a UserWord row.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import RejectedWord
from utils.text import normalize_word


async def add(session: AsyncSession, *, user_id: int, language_code: str, word: str) -> RejectedWord:
    """Idempotent: rejecting the same word twice is a no-op, not a
    duplicate row (unique constraint on user_id/language_code/
    normalized_word)."""
    normalized = normalize_word(word)
    existing = await session.execute(
        select(RejectedWord).where(
            RejectedWord.user_id == user_id,
            RejectedWord.language_code == language_code,
            RejectedWord.normalized_word == normalized,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    row = RejectedWord(user_id=user_id, language_code=language_code, word=word, normalized_word=normalized)
    session.add(row)
    await session.flush()
    return row


async def list_words(session: AsyncSession, *, user_id: int, language_code: str, limit: int = 300) -> list[str]:
    """Bounded hint list for the AI prompt (mirrors word_generation_service.
    _recent_known_words' own cap) - most-recently-rejected first, so a
    long rejection history never crowds out the newest exclusions."""
    result = await session.execute(
        select(RejectedWord.word)
        .where(RejectedWord.user_id == user_id, RejectedWord.language_code == language_code)
        .order_by(RejectedWord.created_at.desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]
