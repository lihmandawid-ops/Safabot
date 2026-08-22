"""LevelProgressService (level-and-difficulty stage): tracks the ONE
estimated level (database.models.UserLanguage.level) a learner's own
accumulated results justify, and separately answers "what difficulty
should word generation actually use right now" given the learner's own
difficulty_mode/learning_difficulty choice.

Two genuinely different questions, kept apart per the spec:

- estimated_level ("level" on the model) - moves forward on its own,
  automatically, based on real learning results. Never touched by a
  manual difficulty pick, never touched by a raw AI opinion, never
  touched by elapsed time or "just a few" correct answers.
- effective_difficulty() - what generation should actually request right
  now: the learner's own manual pick (learning_difficulty) when
  difficulty_mode="manual", otherwise the auto-tracked estimated level.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserLanguage, UserWord, Word, WordStatus
from utils.levels import next_level
from utils.logging import get_logger

logger = get_logger(__name__)


def effective_difficulty(user_language: UserLanguage) -> str:
    """The CEFR level word generation should actually request for this
    learner right now - never mixes the two sources (spec section 9/45:
    "не путать эти значения")."""
    if user_language.difficulty_mode == "manual":
        return user_language.learning_difficulty
    return user_language.level


async def _count_mastered_at_level(
    session: AsyncSession, *, user_id: int, language_code: str, level: str, min_repetitions: int,
) -> tuple[int, float]:
    """(count, aggregate_accuracy) over MASTERED words at exactly this
    CEFR level, each reviewed at least `min_repetitions` times - a single
    lucky guess on one word can never move the count."""
    result = await session.execute(
        select(
            func.count(UserWord.id),
            func.coalesce(func.sum(UserWord.correct_answers), 0),
            func.coalesce(func.sum(UserWord.wrong_answers), 0),
        )
        .join(Word, Word.id == UserWord.word_id)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status == WordStatus.MASTERED,
            UserWord.repetitions >= min_repetitions,
            Word.difficulty == level,
        )
    )
    count, correct, wrong = result.one()
    total_answers = correct + wrong
    accuracy = (correct / total_answers) if total_answers > 0 else 0.0
    return count, accuracy


async def maybe_advance_level(session: AsyncSession, *, user_language: UserLanguage) -> str | None:
    """Checked after a learning/review session completes (services.
    learning_service.finish_session_if_complete). Advances `level` by
    exactly ONE CEFR tier - never more, never based on this call alone
    skipping straight past a tier - only when the accumulated stats at
    the CURRENT level clear every configured threshold. Returns the new
    level if it advanced, else None (the overwhelmingly common case).

    Deliberately never raises: a broken level check must never break the
    learning flow it's attached to, same convention as word generation's
    own AI-failure handling.
    """
    from config import get_settings

    settings = get_settings()
    target = next_level(user_language.level)
    if target is None:
        return None  # already at the top tier (c2)

    try:
        count, accuracy = await _count_mastered_at_level(
            session, user_id=user_language.user_id, language_code=user_language.language_code,
            level=user_language.level, min_repetitions=settings.level_up_min_repetitions_per_word,
        )
    except Exception:
        logger.exception(
            "Level progress check failed user_id=%s language_code=%s",
            user_language.user_id, user_language.language_code,
        )
        return None

    if count < settings.level_up_min_mastered_words or accuracy < settings.level_up_min_accuracy:
        return None

    user_language.level = target
    await session.flush()
    logger.info(
        "Level advanced user_id=%s language_code=%s new_level=%s mastered_words=%d accuracy=%.2f",
        user_language.user_id, user_language.language_code, target, count, accuracy,
    )
    return target
