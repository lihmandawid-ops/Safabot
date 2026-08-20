"""Tests for services/learning_service.py (learning-core stage, sections
5-8, 20-27, 31, 33): daily new-word limits, session build/resume,
priority order, review recording, and streaks.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from database.repositories import sessions as sessions_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.models import WordGenerationLog, WordStatus
from services import learning_service, word_service
from services.repetition_service import ReviewGrade
from sqlalchemy import select

NOW = datetime(2026, 6, 15, 10, 0, 0)


async def _create_user(session, *, telegram_id=2000, daily_new_words=4, timezone="UTC"):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=None, first_name="Test",
        interface_language="ru", timezone=timezone, level="beginner", daily_new_words=daily_new_words,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level="beginner", daily_new_words=daily_new_words,
    )
    return user, ul


async def _make_words(session, n, prefix="word"):
    words = []
    for i in range(n):
        word, _ = await word_service.get_or_create_word(session, language_code="en", word=f"{prefix}{i}")
        words.append(word)
    return words


async def _add_as_new(session, user_id, words):
    for w in words:
        await user_words_repo.add_word(session, user_id=user_id, word_id=w.id, language_code="en")


async def _complete_all_items(session, learning_session, *, now):
    """Rates every remaining item GOOD, in order - a session can contain
    more than the one word a test just added (e.g. a previous day's word
    legitimately becoming due again), so tests must clear the whole
    session, not just the first item, before checking completion/streak."""
    item = sessions_repo.next_incomplete_item(learning_session)
    while item is not None:
        await learning_service.record_review_answer(
            session, learning_session, item.user_word_id, grade=ReviewGrade.GOOD, now=now
        )
        item = sessions_repo.next_incomplete_item(learning_session)


@pytest.mark.parametrize("limit", [2, 4, 8])
async def test_new_word_batch_size_matches_daily_new_words(session, limit):
    """daily_new_words is a per-session batch size (bugfix stage, real-
    Telegram feedback: there is no longer a once-a-day cap on top of it -
    see test_a_fresh_batch_is_available_immediately_after_finishing_one
    below)."""
    user, ul = await _create_user(session, telegram_id=2000 + limit, daily_new_words=limit)
    words = await _make_words(session, limit + 5, prefix=f"lim{limit}_")
    await _add_as_new(session, user.id, words)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert learning_session.total_words == limit
    assert all(item.is_new_word for item in learning_session.items)


async def test_a_fresh_batch_is_available_immediately_after_finishing_one(session):
    """Bugfix stage, explicit product decision: "no daily limit on new
    words - if the person wants more, the bot gives more". Finishing one
    session's batch must not block a second, same-day batch."""
    user, ul = await _create_user(session, telegram_id=2050, daily_new_words=2)
    words = await _make_words(session, 10, prefix="fresh_")
    await _add_as_new(session, user.id, words)
    await session.commit()

    first = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert first.total_words == 2
    await _complete_all_items(session, first, now=NOW)
    await learning_service.finish_session_if_complete(session, user, first, now=NOW)
    await session.commit()

    second = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert second is not None
    assert second.total_words == 2
    assert second.id != first.id


async def test_due_reviews_do_not_count_against_new_word_limit(session):
    user, ul = await _create_user(session, telegram_id=2100, daily_new_words=2)
    new_words = await _make_words(session, 2, prefix="new_")
    due_words = await _make_words(session, 3, prefix="due_")
    await _add_as_new(session, user.id, new_words)

    for w in due_words:
        uw = await user_words_repo.add_word(session, user_id=user.id, word_id=w.id, language_code="en")
        uw.status = WordStatus.REVIEW
        uw.next_review_at = NOW - timedelta(hours=1)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert learning_session.total_words == 5  # 2 new + 3 due, limit of 2 only caps new words
    new_count = sum(1 for i in learning_session.items if i.is_new_word)
    assert new_count == 2


async def test_review_only_session_excludes_new_words(session):
    user, ul = await _create_user(session, telegram_id=2200, daily_new_words=4)
    new_words = await _make_words(session, 3, prefix="new_")
    due_word = (await _make_words(session, 1, prefix="due_"))[0]
    await _add_as_new(session, user.id, new_words)
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=due_word.id, language_code="en")
    uw.status = WordStatus.REVIEW
    uw.next_review_at = NOW - timedelta(hours=1)
    await session.commit()

    learning_session = await learning_service.build_learning_session(
        session, user=user, user_language=ul, include_new_words=False, now=NOW
    )
    assert learning_session.total_words == 1
    assert learning_session.items[0].is_new_word is False


async def test_priority_order_due_words_come_before_new_words(session):
    user, ul = await _create_user(session, telegram_id=2300, daily_new_words=4)
    new_words = await _make_words(session, 2, prefix="new_")
    due_word = (await _make_words(session, 1, prefix="due_"))[0]
    await _add_as_new(session, user.id, new_words)
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=due_word.id, language_code="en")
    uw.status = WordStatus.REVIEW
    uw.next_review_at = NOW - timedelta(hours=1)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    positions = sorted(learning_session.items, key=lambda i: i.position)
    assert positions[0].is_new_word is False  # the due review is first


async def test_build_learning_session_returns_none_when_nothing_to_do(session):
    user, ul = await _create_user(session, telegram_id=2400, daily_new_words=4)
    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert learning_session is None


async def test_build_learning_session_resumes_in_progress_session(session):
    user, ul = await _create_user(session, telegram_id=2500, daily_new_words=4)
    words = await _make_words(session, 3)
    await _add_as_new(session, user.id, words)
    await session.commit()

    first = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    second = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert first.id == second.id


async def test_record_review_answer_rejects_word_outside_the_session(session):
    user, ul = await _create_user(session, telegram_id=2600, daily_new_words=4)
    words = await _make_words(session, 1)
    await _add_as_new(session, user.id, words)
    await session.commit()

    # Built BEFORE the outsider word exists, so it can never be one of
    # this session's items no matter how many words the user has.
    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)

    outsider_word = (await _make_words(session, 1, prefix="outsider_"))[0]
    outsider_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=outsider_word.id, language_code="en")
    await session.commit()

    result = await learning_service.record_review_answer(
        session, learning_session, outsider_uw.id, grade=ReviewGrade.GOOD, now=NOW
    )
    assert result is None


async def test_record_review_answer_rejects_already_completed_item(session):
    user, ul = await _create_user(session, telegram_id=2700, daily_new_words=4)
    words = await _make_words(session, 1)
    await _add_as_new(session, user.id, words)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    uw_id = learning_session.items[0].user_word_id

    first = await learning_service.record_review_answer(session, learning_session, uw_id, grade=ReviewGrade.GOOD, now=NOW)
    second = await learning_service.record_review_answer(session, learning_session, uw_id, grade=ReviewGrade.GOOD, now=NOW)
    assert first is not None
    assert second is None


async def test_finish_session_updates_user_word_and_marks_complete(session):
    user, ul = await _create_user(session, telegram_id=2800, daily_new_words=4)
    words = await _make_words(session, 1)
    await _add_as_new(session, user.id, words)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    uw_id = learning_session.items[0].user_word_id
    await learning_service.record_review_answer(session, learning_session, uw_id, grade=ReviewGrade.GOOD, now=NOW)

    finished = await learning_service.finish_session_if_complete(session, user, learning_session, now=NOW)
    assert finished is True
    assert learning_session.status == "completed"
    assert learning_session.completed_at is not None


async def test_streak_increments_on_consecutive_local_days(session):
    user, ul = await _create_user(session, telegram_id=2900, daily_new_words=4, timezone="UTC")

    day1 = NOW
    words1 = await _make_words(session, 1, prefix="d1_")
    await _add_as_new(session, user.id, words1)
    await session.commit()
    s1 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=day1)
    await _complete_all_items(session, s1, now=day1)
    await learning_service.finish_session_if_complete(session, user, s1, now=day1)
    assert user.current_streak == 1

    day2 = NOW + timedelta(days=1)
    words2 = await _make_words(session, 1, prefix="d2_")
    await _add_as_new(session, user.id, words2)
    await session.commit()
    s2 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=day2)
    await _complete_all_items(session, s2, now=day2)
    await learning_service.finish_session_if_complete(session, user, s2, now=day2)
    assert user.current_streak == 2
    assert user.longest_streak == 2


async def test_streak_resets_after_a_gap(session):
    user, ul = await _create_user(session, telegram_id=3000, daily_new_words=4, timezone="UTC")

    day1 = NOW
    words1 = await _make_words(session, 1, prefix="g1_")
    await _add_as_new(session, user.id, words1)
    await session.commit()
    s1 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=day1)
    await _complete_all_items(session, s1, now=day1)
    await learning_service.finish_session_if_complete(session, user, s1, now=day1)
    assert user.current_streak == 1

    day3 = NOW + timedelta(days=3)  # skipped a day
    words2 = await _make_words(session, 1, prefix="g2_")
    await _add_as_new(session, user.id, words2)
    await session.commit()
    s2 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=day3)
    await _complete_all_items(session, s2, now=day3)
    await learning_service.finish_session_if_complete(session, user, s2, now=day3)
    assert user.current_streak == 1  # reset, not 2
    assert user.longest_streak == 1


async def test_mark_known_and_replace_masters_the_word_and_adds_a_replacement(session):
    """Bugfix spec section 12: "🤔 Я это уже знаю" must not just skip the
    word - it should be marked MASTERED immediately (never touched by the
    normal repetition ladder) and a replacement should be slotted in so
    the day's total doesn't shrink."""
    user, ul = await _create_user(session, telegram_id=3200, daily_new_words=2)
    words = await _make_words(session, 2, prefix="known_")
    await _add_as_new(session, user.id, words)
    await _make_words(session, 3, prefix="pool_")  # local pool for the replacement
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    assert learning_session.total_words == 2
    known_uw_id = learning_session.items[0].user_word_id

    item = await learning_service.mark_known_and_replace(
        session, user=user, user_language=ul, learning_session=learning_session, user_word_id=known_uw_id,
    )
    await session.commit()

    assert item is not None
    assert item.completed is True
    assert item.rating == "known"

    known_uw = await user_words_repo.get_by_id(session, known_uw_id)
    assert known_uw.status == WordStatus.MASTERED

    # A replacement was appended - the session still has something left to do.
    assert learning_session.total_words == 3
    remaining = sessions_repo.next_incomplete_item(learning_session)
    assert remaining is not None
    assert remaining.user_word_id != known_uw_id

    result = await session.execute(
        select(WordGenerationLog).where(WordGenerationLog.user_id == user.id, WordGenerationLog.trigger == "replacement")
    )
    assert len(result.scalars().all()) == 1


async def test_mark_known_and_replace_rejects_a_due_review_item(session):
    """The button only ever appears on a NEW word's card (reveal_keyboard's
    is_new_word gate) - this is the server-side half of that same rule."""
    user, ul = await _create_user(session, telegram_id=3300, daily_new_words=4)
    due_word = (await _make_words(session, 1, prefix="due_"))[0]
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=due_word.id, language_code="en")
    uw.status = WordStatus.REVIEW
    uw.next_review_at = NOW - timedelta(hours=1)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    result = await learning_service.mark_known_and_replace(
        session, user=user, user_language=ul, learning_session=learning_session, user_word_id=uw.id,
    )
    assert result is None


async def test_mark_known_and_replace_handles_no_replacement_available(session):
    """No local pool and no AI configured - generate_new_words legitimately
    returns [] (spec: degrade gracefully, never break the session)."""
    user, ul = await _create_user(session, telegram_id=3400, daily_new_words=4)
    words = await _make_words(session, 1, prefix="only_")
    await _add_as_new(session, user.id, words)
    await session.commit()

    learning_session = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    uw_id = learning_session.items[0].user_word_id

    item = await learning_service.mark_known_and_replace(
        session, user=user, user_language=ul, learning_session=learning_session, user_word_id=uw_id,
    )
    assert item is not None
    assert learning_session.total_words == 1  # no replacement could be added
    assert sessions_repo.next_incomplete_item(learning_session) is None


async def test_streak_does_not_double_count_same_local_day(session):
    user, ul = await _create_user(session, telegram_id=3100, daily_new_words=4, timezone="UTC")

    words1 = await _make_words(session, 1, prefix="s1_")
    await _add_as_new(session, user.id, words1)
    await session.commit()
    s1 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=NOW)
    await _complete_all_items(session, s1, now=NOW)
    await learning_service.finish_session_if_complete(session, user, s1, now=NOW)
    assert user.current_streak == 1

    later_same_day = NOW + timedelta(hours=3)
    words2 = await _make_words(session, 1, prefix="s2_")
    await _add_as_new(session, user.id, words2)
    await session.commit()
    s2 = await learning_service.build_learning_session(session, user=user, user_language=ul, now=later_same_day)
    await _complete_all_items(session, s2, now=later_same_day)
    await learning_service.finish_session_if_complete(session, user, s2, now=later_same_day)
    assert user.current_streak == 1  # still 1, not 2
