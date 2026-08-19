"""Data access for the review queue (spec sections 7-11 of the words
stage's brief: "prepare data for interval repetition").

This only reads what's already on UserWord (next_review_at, status) - it
does not compute new intervals or grades. The scheduling algorithm itself
(services/repetition_service.py) is Stage 7 (Repetition) and stays a stub
until then.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import UserWord, Word, WordStatus


async def get_due_for_review(
    session: AsyncSession, *, user_id: int, language_code: str, now: datetime | None = None
) -> list[UserWord]:
    now = now or datetime.now(timezone.utc)
    result = await session.execute(
        select(UserWord)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status.in_([WordStatus.LEARNING, WordStatus.REVIEW]),
            UserWord.next_review_at.is_not(None),
            UserWord.next_review_at <= now,
        )
        .options(selectinload(UserWord.word).selectinload(Word.translations))
        .order_by(UserWord.next_review_at)
    )
    return list(result.scalars().unique().all())
