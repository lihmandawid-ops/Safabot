"""Tests for services/level_progress_service.py (level-and-difficulty
stage): the estimated CEFR level only advances on real, accumulated
results - never from a handful of correct answers or from time alone.
"""
from __future__ import annotations

from datetime import time

import pytest

from database.models import UserLanguage, WordStatus
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from services import level_progress_service, word_service


async def _create_user_language(session, *, level="a1", difficulty_mode="manual", learning_difficulty=None):
    user = await users_repo.create_user(
        session, telegram_id=3000, username=None, first_name="Test",
        interface_language="ru", timezone="UTC", level=level, daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level=level, daily_new_words=4, difficulty_mode=difficulty_mode, learning_difficulty=learning_difficulty,
    )
    return user, ul


async def _add_mastered_word(session, *, user_id, index, level="a1", repetitions=5, correct=5, wrong=0):
    word, _ = await word_service.get_or_create_word(
        session, language_code="en", word=f"masteredword{index}", difficulty=level,
    )
    uw = await user_words_repo.add_word(session, user_id=user_id, word_id=word.id, language_code="en")
    uw.status = WordStatus.MASTERED
    uw.repetitions = repetitions
    uw.correct_answers = correct
    uw.wrong_answers = wrong
    await session.flush()
    return uw


# --- effective_difficulty() ---

def test_effective_difficulty_uses_learning_difficulty_when_manual():
    ul = UserLanguage(level="b1", difficulty_mode="manual", learning_difficulty="a2")
    assert level_progress_service.effective_difficulty(ul) == "a2"


def test_effective_difficulty_uses_level_when_automatic():
    ul = UserLanguage(level="b1", difficulty_mode="automatic", learning_difficulty="a2")
    assert level_progress_service.effective_difficulty(ul) == "b1"


# --- maybe_advance_level() ---

async def test_does_not_advance_with_too_few_mastered_words(session, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "15")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1")

    for i in range(5):  # well under the threshold
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a1")

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result is None
    assert ul.level == "a1"
    get_settings.cache_clear()


async def test_does_not_advance_with_low_accuracy(session, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_ACCURACY", "0.85")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1")

    for i in range(5):
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a1", correct=3, wrong=3)  # 50% accuracy

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result is None
    assert ul.level == "a1"
    get_settings.cache_clear()


async def test_does_not_advance_when_repetitions_per_word_too_low(session, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_REPETITIONS_PER_WORD", "3")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1")

    # MASTERED but each only reviewed once - a lucky guess must not count.
    for i in range(5):
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a1", repetitions=1, correct=1, wrong=0)

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result is None
    assert ul.level == "a1"
    get_settings.cache_clear()


async def test_advances_exactly_one_tier_when_thresholds_are_met(session, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_REPETITIONS_PER_WORD", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_ACCURACY", "0.85")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1")

    for i in range(5):
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a1", repetitions=5, correct=5, wrong=0)

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result == "a2"  # exactly one CEFR tier up, never skips
    assert ul.level == "a2"
    get_settings.cache_clear()


async def test_never_advances_past_the_top_tier(session, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "1")
    monkeypatch.setenv("LEVEL_UP_MIN_REPETITIONS_PER_WORD", "1")
    monkeypatch.setenv("LEVEL_UP_MIN_ACCURACY", "0.0")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="c2")
    await _add_mastered_word(session, user_id=ul.user_id, index=0, level="c2", repetitions=5, correct=5, wrong=0)

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result is None
    assert ul.level == "c2"
    get_settings.cache_clear()


async def test_words_from_a_different_level_never_count(session, monkeypatch):
    """Mastering 10 A2 words must never advance an A1 learner - only
    mastery AT the current level counts toward its own threshold."""
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "3")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1")

    for i in range(10):
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a2", repetitions=5, correct=5, wrong=0)

    result = await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert result is None
    assert ul.level == "a1"
    get_settings.cache_clear()


async def test_manual_difficulty_mode_is_untouched_by_level_advance(session, monkeypatch):
    """Section 8: an auto-advancing estimated_level must never overwrite
    a learner's own manual difficulty pick."""
    from config import get_settings

    monkeypatch.setenv("LEVEL_UP_MIN_MASTERED_WORDS", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_REPETITIONS_PER_WORD", "3")
    monkeypatch.setenv("LEVEL_UP_MIN_ACCURACY", "0.85")
    get_settings.cache_clear()
    _, ul = await _create_user_language(session, level="a1", difficulty_mode="manual", learning_difficulty="a1")

    for i in range(5):
        await _add_mastered_word(session, user_id=ul.user_id, index=i, level="a1", repetitions=5, correct=5, wrong=0)

    await level_progress_service.maybe_advance_level(session, user_language=ul)
    assert ul.level == "a2"  # estimated level still advances...
    assert ul.learning_difficulty == "a1"  # ...but the manual pick is untouched
    get_settings.cache_clear()
