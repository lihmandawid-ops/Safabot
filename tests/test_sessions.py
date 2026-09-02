"""Repository-level tests for LearningSession/LearningSessionItem (spec
section 33): creation, item completion, resume, and restart-survival
(re-fetching from a fresh query, not relying on any in-memory state)."""
from __future__ import annotations

from datetime import time

from database.repositories import sessions as sessions_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from services import word_service


async def _create_user(session, telegram_id=4000):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=None, first_name="T",
        interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru", level="beginner", daily_new_words=4
    )
    return user, ul


async def _user_word(session, user_id, word="go"):
    w, _ = await word_service.get_or_create_word(session, language_code="en", word=word)
    return await user_words_repo.add_word(session, user_id=user_id, word_id=w.id, language_code="en")


async def test_create_session_starts_empty_and_in_progress(session):
    user, _ = await _create_user(session)
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    assert ls.status == "in_progress"
    assert ls.total_words == 0
    assert ls.items == []


async def test_add_session_item_updates_total_and_collection(session):
    user, _ = await _create_user(session)
    uw = await _user_word(session, user.id)
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")

    await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw.id, position=1, is_new_word=True)

    assert ls.total_words == 1
    assert len(ls.items) == 1
    assert ls.items[0].position == 1


async def test_next_incomplete_item_returns_lowest_position_uncompleted(session):
    user, _ = await _create_user(session)
    uw1 = await _user_word(session, user.id, "go")
    uw2 = await _user_word(session, user.id, "make")
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw1.id, position=1, is_new_word=True)
    await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw2.id, position=2, is_new_word=True)

    first = sessions_repo.next_incomplete_item(ls)
    assert first.position == 1

    await sessions_repo.complete_item(session, first, rating="good")
    second = sessions_repo.next_incomplete_item(ls)
    assert second.position == 2

    await sessions_repo.complete_item(session, second, rating="good")
    assert sessions_repo.next_incomplete_item(ls) is None


async def test_complete_item_increments_session_completed_words(session):
    user, _ = await _create_user(session)
    uw = await _user_word(session, user.id)
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    item = await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw.id, position=1, is_new_word=False)

    assert ls.completed_words == 0
    await sessions_repo.complete_item(session, item, rating="easy")
    assert ls.completed_words == 1


async def test_complete_session_sets_status_and_timestamp(session):
    user, _ = await _create_user(session)
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    assert ls.completed_at is None

    await sessions_repo.complete_session(session, ls)
    assert ls.status == "completed"
    assert ls.completed_at is not None


async def test_get_active_session_only_returns_in_progress(session):
    user, _ = await _create_user(session)
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    await session.commit()

    active = await sessions_repo.get_active_session(session, user_id=user.id, language_code="en")
    assert active is not None
    assert active.id == ls.id

    await sessions_repo.complete_session(session, ls)
    await session.commit()

    active_after = await sessions_repo.get_active_session(session, user_id=user.id, language_code="en")
    assert active_after is None


async def test_get_active_session_is_scoped_to_language(session):
    """Section 26: English and German sessions must never bleed into each other."""
    user, _ = await _create_user(session)
    await user_languages_repo.add_language(
        session, user_id=user.id, language_code="de", translation_language="ru", level="beginner", daily_new_words=4
    )
    en_session = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    await session.commit()

    de_active = await sessions_repo.get_active_session(session, user_id=user.id, language_code="de")
    en_active = await sessions_repo.get_active_session(session, user_id=user.id, language_code="en")
    assert de_active is None
    assert en_active is not None
    assert en_active.id == en_session.id


async def test_get_item_for_user_word_scoped_to_session(session):
    user, _ = await _create_user(session)
    uw1 = await _user_word(session, user.id, "go")
    uw2 = await _user_word(session, user.id, "make")
    ls1 = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    await sessions_repo.add_session_item(session, learning_session=ls1, user_word_id=uw1.id, position=1, is_new_word=True)
    await session.commit()

    found = await sessions_repo.get_item_for_user_word(session, learning_session_id=ls1.id, user_word_id=uw1.id)
    not_found = await sessions_repo.get_item_for_user_word(session, learning_session_id=ls1.id, user_word_id=uw2.id)
    assert found is not None
    assert not_found is None


async def test_restart_survival_session_state_is_fully_recoverable_from_db(session):
    """No in-memory state required: fetching by id after "the process
    restarted" (a brand-new query, discarding all local Python objects)
    must reproduce the exact same progress (spec section 25)."""
    user, _ = await _create_user(session)
    uw1 = await _user_word(session, user.id, "go")
    uw2 = await _user_word(session, user.id, "make")
    ls = await sessions_repo.create_session(session, user_id=user.id, language_code="en")
    await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw1.id, position=1, is_new_word=True)
    await sessions_repo.add_session_item(session, learning_session=ls, user_word_id=uw2.id, position=2, is_new_word=True)
    item1 = sessions_repo.next_incomplete_item(ls)
    await sessions_repo.complete_item(session, item1, rating="good")
    await session.commit()
    session_id = ls.id

    del ls, item1  # simulate losing all in-memory state

    reloaded = await sessions_repo.get_session_by_id(session, session_id)
    assert reloaded.completed_words == 1
    assert reloaded.total_words == 2
    remaining = sessions_repo.next_incomplete_item(reloaded)
    assert remaining.position == 2
    assert remaining.user_word_id == uw2.id


def test_session_stats_counts_correct_and_wrong_by_rating():
    from database.models import LearningSession, LearningSessionItem

    ls = LearningSession(user_id=1, language_code="en")
    ls.items = [
        LearningSessionItem(position=1, is_new_word=True, completed=True, rating="good"),
        LearningSessionItem(position=2, is_new_word=True, completed=True, rating="again"),
        LearningSessionItem(position=3, is_new_word=False, completed=True, rating="easy"),
        LearningSessionItem(position=4, is_new_word=False, completed=False, rating=None),
    ]
    stats = sessions_repo.session_stats(ls)
    assert stats == {"total_reviewed": 3, "new_words": 2, "correct": 2, "wrong": 1}
