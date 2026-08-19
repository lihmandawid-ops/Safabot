"""Data access for the review/new-word queues and applying a review's
result (learning-core stage, sections 1, 6-8, 20-21, 28).

Kept as thin queries + one mutation (apply_review_result) - deciding
WHICH grade maps to WHICH new stage is services/repetition_service.py's
job; deciding HOW MANY new words a session gets is
services/learning_service.py's job. This module only fetches and writes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import LearningSession, LearningSessionItem, UserWord, Word, WordStatus
from services.repetition_service import RepetitionResult, clamp_difficulty
from utils.time import utc_now

_WITH_WORD = (selectinload(UserWord.word).selectinload(Word.translations),)


async def get_due_for_review(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    limit: int,
    now: datetime | None = None,
) -> list[UserWord]:
    """Section 21's priority order: most overdue first, then most-wrong-
    answers first, capped at `limit` (spec section 8's MAX_DAILY_REVIEWS -
    never dump hundreds of overdue words on the user at once)."""
    now = now if now is not None else utc_now()
    result = await session.execute(
        select(UserWord)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status.in_([WordStatus.LEARNING, WordStatus.REVIEW]),
            UserWord.next_review_at.is_not(None),
            UserWord.next_review_at <= now,
        )
        .options(*_WITH_WORD)
        .order_by(UserWord.next_review_at.asc(), UserWord.wrong_answers.desc())
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def get_new_word_candidates(
    session: AsyncSession, *, user_id: int, language_code: str, level: str, limit: int
) -> list[UserWord]:
    """NEW-status words not yet shown, preferring ones matching the user's
    level (spec section 21) without hard-excluding the rest - a dictionary
    with sparse difficulty tagging should never leave a user with nothing
    to learn."""
    level_match = case((Word.difficulty == level, 0), else_=1)
    result = await session.execute(
        select(UserWord)
        .join(Word, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status == WordStatus.NEW,
        )
        .options(*_WITH_WORD)
        .order_by(level_match, UserWord.added_at)
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def count_new_words_started_today(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    day_start: datetime,
    day_end: datetime,
) -> int:
    """How many distinct words were already handed out as "new" today
    (spec section 6) - counted from LearningSessionItem.is_new_word so an
    abandoned-and-rebuilt session still can't push a user over their
    daily limit."""
    result = await session.execute(
        select(func.count(func.distinct(LearningSessionItem.user_word_id)))
        .select_from(LearningSessionItem)
        .join(LearningSession, LearningSessionItem.session_id == LearningSession.id)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.language_code == language_code,
            LearningSessionItem.is_new_word.is_(True),
            LearningSession.started_at >= day_start,
            LearningSession.started_at < day_end,
        )
    )
    return int(result.scalar_one())


async def apply_review_result(
    session: AsyncSession, user_word: UserWord, result: RepetitionResult, *, now: datetime | None = None
) -> UserWord:
    """Write a RepetitionResult onto a UserWord row (spec section 9:
    "учёт результатов пользователя"). The algorithm itself
    (services/repetition_service.py) never touches the database - this is
    the one place its output becomes a mutation."""
    now = now if now is not None else utc_now()
    user_word.repetition_stage = result.new_stage
    user_word.interval_days = result.new_interval_days
    user_word.next_review_at = result.next_review_at
    user_word.status = result.new_status
    user_word.last_review_at = now
    user_word.repetitions += 1
    user_word.correct_answers += result.correct_delta
    user_word.wrong_answers += result.wrong_delta
    user_word.difficulty_score = clamp_difficulty(user_word.difficulty_score + result.difficulty_delta)
    user_word.is_paused = False
    await session.flush()
    return user_word
