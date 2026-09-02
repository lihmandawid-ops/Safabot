"""Data access for 📊 Мой прогресс and the learner profile handed to AI
word generation (statistics/progress stage).

Kept as thin aggregate queries only - see services/progress_service.py and
services/learner_profile_service.py for what the numbers mean and how
they're combined. Every query here reuses fields that already exist on
UserWord/ReviewLog/Word - nothing here invents a parallel data source.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ReviewLog, UserWord, Word, WordStatus

# repetition_stage thresholds for the 🟢/🟡/🔴 consolidation buckets (spec:
# "well-consolidated / in progress / difficult"). MASTERED words are always
# 🟢 regardless of stage (they've already left the active ladder). Among
# still-active words: stage 4+ (interval >= 14 days, repetition_service's
# own ladder) counts as genuinely consolidated, stage 0 with at least one
# wrong answer (or a high difficulty_score) is the struggling case, and
# everything else is "in progress" - no new scoring system, just reading
# the two fields the repetition algorithm already maintains.
_CONSOLIDATED_STAGE = 4
_DIFFICULT_SCORE = 2.5


async def status_counts(session: AsyncSession, *, user_id: int, language_code: str) -> dict[str, int]:
    """How many (non-deleted) UserWord rows this user has in each status,
    for this language - the same statuses ⭐ Мои слова already filters by."""
    result = await session.execute(
        select(UserWord.status, func.count(UserWord.id))
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status != WordStatus.DELETED,
        )
        .group_by(UserWord.status)
    )
    return {status: count for status, count in result.all()}


async def consolidation_buckets(session: AsyncSession, *, user_id: int, language_code: str) -> dict[str, int]:
    """🟢 well_consolidated / 🟡 in_progress /🔴 difficult counts, over every
    active (non-deleted, non-paused) word - see the module docstring for
    the thresholds, both already-existing UserWord fields."""
    bucket = case(
        (UserWord.status == WordStatus.MASTERED, "well_consolidated"),
        (UserWord.repetition_stage >= _CONSOLIDATED_STAGE, "well_consolidated"),
        (
            (UserWord.wrong_answers > 0) & (UserWord.difficulty_score >= _DIFFICULT_SCORE),
            "difficult",
        ),
        else_="in_progress",
    )
    result = await session.execute(
        select(bucket, func.count(UserWord.id))
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status.notin_([WordStatus.DELETED, WordStatus.PAUSED]),
        )
        .group_by(bucket)
    )
    counts = {"well_consolidated": 0, "in_progress": 0, "difficult": 0}
    counts.update({key: value for key, value in result.all()})
    return counts


async def lifetime_totals(session: AsyncSession, *, user_id: int, language_code: str) -> tuple[int, int, int]:
    """(total_reviews, correct, wrong) - all-time, summed straight off
    UserWord's own cumulative counters (never re-derived from ReviewLog,
    which only exists from the moment it was introduced onward)."""
    result = await session.execute(
        select(
            func.coalesce(func.sum(UserWord.repetitions), 0),
            func.coalesce(func.sum(UserWord.correct_answers), 0),
            func.coalesce(func.sum(UserWord.wrong_answers), 0),
        ).where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status != WordStatus.DELETED,
        )
    )
    total, correct, wrong = result.one()
    return int(total), int(correct), int(wrong)


async def new_words_since(session: AsyncSession, *, user_id: int, language_code: str, since: datetime) -> int:
    """Exact "new words added" count for a rolling window - UserWord.
    added_at already carries a real timestamp, no new column needed."""
    result = await session.execute(
        select(func.count(UserWord.id)).where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status != WordStatus.DELETED,
            UserWord.added_at >= since,
        )
    )
    return int(result.scalar_one())


async def review_totals_since(
    session: AsyncSession, *, user_id: int, language_code: str, since: datetime
) -> tuple[int, int, int]:
    """(review_count, correct, wrong) over ReviewLog rows in the window -
    the one place period-based review/accuracy stats can come from, since
    UserWord's own counters are all-time cumulative only."""
    result = await session.execute(
        select(
            func.count(ReviewLog.id),
            func.coalesce(func.sum(ReviewLog.correct_delta), 0),
            func.coalesce(func.sum(ReviewLog.wrong_delta), 0),
        ).where(
            ReviewLog.user_id == user_id,
            ReviewLog.language_code == language_code,
            ReviewLog.reviewed_at >= since,
        )
    )
    count, correct, wrong = result.one()
    return int(count), int(correct), int(wrong)


async def recent_review_deltas(
    session: AsyncSession, *, user_id: int, language_code: str, limit: int
) -> list[tuple[int, int]]:
    """The last `limit` (correct_delta, wrong_delta) pairs, most recent
    first - the raw material for a recent-performance trend (adaptive
    difficulty, spec: "требует анализа тренда за последние 10-20
    результатов", never a single result)."""
    result = await session.execute(
        select(ReviewLog.correct_delta, ReviewLog.wrong_delta)
        .where(ReviewLog.user_id == user_id, ReviewLog.language_code == language_code)
        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id.desc())
        .limit(limit)
    )
    return [(int(c), int(w)) for c, w in result.all()]


async def weakest_words(
    session: AsyncSession, *, user_id: int, language_code: str, limit: int
) -> list[str]:
    """Highest difficulty_score among active words - "weak_words" for the
    AI profile (spec section 30)."""
    result = await session.execute(
        select(Word.word)
        .join(UserWord, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status.in_([WordStatus.LEARNING, WordStatus.REVIEW]),
        )
        .order_by(UserWord.difficulty_score.desc(), UserWord.wrong_answers.desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]


async def strongest_words(
    session: AsyncSession, *, user_id: int, language_code: str, limit: int
) -> list[str]:
    """Most solidly mastered words (highest repetition_stage, lowest
    difficulty_score) - "strong_words" for the AI profile."""
    result = await session.execute(
        select(Word.word)
        .join(UserWord, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status == WordStatus.MASTERED,
        )
        .order_by(UserWord.difficulty_score.asc(), UserWord.repetitions.desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]
