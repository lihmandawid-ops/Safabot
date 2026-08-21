"""Data access for the review/new-word queues and applying a review's
result (learning-core stage, sections 1, 6-8, 20-21, 28).

Kept as thin queries + one mutation (apply_review_result) - deciding
WHICH grade maps to WHICH new stage is services/repetition_service.py's
job; deciding HOW MANY new words a session gets is
services/learning_service.py's job. This module only fetches and writes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import UserWord, Word, WordStatus
from services.repetition_service import RepetitionResult, clamp_difficulty
from utils.time import utc_now

_WORD = selectinload(UserWord.word)
# Two separate loader options sharing the same prefix - chaining a single
# .selectinload() call only follows one path, so translations/examples
# (siblings on Word) each need their own branch (same pattern as
# database/repositories/user_words.py's _WITH_WORD).
_WITH_WORD = (
    _WORD.selectinload(Word.translations),
    _WORD.selectinload(Word.examples),
)


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


async def get_words_for_old_review(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    limit: int,
    include_mastered: bool = False,
    include_new_fallback: bool = False,
    now: datetime | None = None,
) -> list[UserWord]:
    """🔁 Повторить старые слова / 🔁 Повторить (on-demand review,
    settings-improvements stage section 4 and repetition-system stage
    sections 1-2): the user explicitly asked for `limit` words right now,
    so unlike get_due_for_review this backfills with the soonest-NOT-YET-
    due words when fewer than `limit` are actually overdue, instead of
    just handing back a short list. Still the same due/next_review_at
    priority and the same PAUSED/DELETED exclusion as the normal review
    queue - no second scheduling algorithm, only a different "how many,
    and what if not enough are due yet" policy on top of it. MASTERED is
    excluded unless `include_mastered` is explicitly requested.

    `include_new_fallback` adds a third tier - NEW-status (never-studied)
    words - used only by the on-demand 🔁 Повторить entry point, which
    the spec explicitly wants to fall back to "остальные активные слова"
    rather than come up short; 🔁 Повторить старые слова (the post-
    session menu button) never sets this, since by then 📚 Учить слова
    has already handled the day's new words on purpose."""
    now = now if now is not None else utc_now()
    statuses = [WordStatus.LEARNING, WordStatus.REVIEW]
    if include_mastered:
        statuses.append(WordStatus.MASTERED)

    due = await get_due_for_review(session, user_id=user_id, language_code=language_code, limit=limit, now=now)
    if len(due) >= limit:
        return due

    exclude_ids = {uw.id for uw in due}
    result = await session.execute(
        select(UserWord)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status.in_(statuses),
            UserWord.id.notin_(exclude_ids) if exclude_ids else True,
        )
        .options(*_WITH_WORD)
        .order_by(UserWord.next_review_at.asc().nulls_last(), UserWord.wrong_answers.desc())
        .limit(limit - len(due))
    )
    upcoming = list(result.scalars().unique().all())
    combined = due + upcoming
    if not include_new_fallback or len(combined) >= limit:
        return combined

    exclude_ids = exclude_ids | {uw.id for uw in upcoming}
    result = await session.execute(
        select(UserWord)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status == WordStatus.NEW,
            UserWord.id.notin_(exclude_ids) if exclude_ids else True,
        )
        .options(*_WITH_WORD)
        .order_by(UserWord.added_at.asc())
        .limit(limit - len(combined))
    )
    filler = list(result.scalars().unique().all())
    return combined + filler


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
