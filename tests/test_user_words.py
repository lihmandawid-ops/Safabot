"""UserWord (personal learning state) tests: add/duplicate, pause/resume,
soft delete + restore, mastered, filters, count, personal search (spec
section 22, with extra attention on cross-user/cross-language isolation).
"""
from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from database.repositories import learning as learning_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.models import WordStatus
from services import user_word_service, word_service


async def _create_user(session, telegram_id: int = 900):
    return await users_repo.create_user(
        session,
        telegram_id=telegram_id,
        username="grace",
        first_name="Grace",
        interface_language="ru",
        timezone="UTC",
        level="beginner",
        daily_new_words=4,
        morning_time=time(9, 0),
        afternoon_time=time(14, 0),
        evening_time=time(20, 0),
    )


async def _create_word(session, word="go", language_code="en"):
    created, _ = await word_service.get_or_create_word(session, language_code=language_code, word=word)
    return created


async def test_add_word_to_learning_creates_new(session):
    user = await _create_user(session)
    word = await _create_word(session)

    result = await user_word_service.add_word_to_learning(
        session, user_id=user.id, word_id=word.id, language_code="en"
    )

    assert result.outcome == "created"
    assert result.user_word.status == WordStatus.NEW
    assert result.user_word.next_review_at is not None


async def test_add_word_to_learning_twice_reports_already_active(session):
    user = await _create_user(session, telegram_id=901)
    word = await _create_word(session)

    first = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    second = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")

    assert first.outcome == "created"
    assert second.outcome == "already_active"
    assert second.user_word.id == first.user_word.id


async def test_add_word_to_learning_offers_resume_when_paused(session):
    user = await _create_user(session, telegram_id=902)
    word = await _create_word(session)

    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    await user_word_service.pause_word(session, added.user_word)

    result = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    assert result.outcome == "offer_resume_paused"
    assert result.user_word.status == WordStatus.PAUSED  # not silently resumed


async def test_add_word_to_learning_restores_deleted(session):
    user = await _create_user(session, telegram_id=903)
    word = await _create_word(session)

    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    await user_word_service.delete_word(session, added.user_word)

    result = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    assert result.outcome == "restored_from_deleted"
    assert result.user_word.status == WordStatus.NEW
    assert result.user_word.id == added.user_word.id  # same row, history preserved


async def test_pause_word_sets_status_and_flag(session):
    user = await _create_user(session, telegram_id=904)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")

    await user_word_service.pause_word(session, added.user_word)

    assert added.user_word.status == WordStatus.PAUSED
    assert added.user_word.is_paused is True


async def test_resume_word_from_new_progress_goes_to_new(session):
    user = await _create_user(session, telegram_id=905)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    await user_word_service.pause_word(session, added.user_word)

    await user_word_service.resume_word(session, added.user_word)

    assert added.user_word.status == WordStatus.NEW
    assert added.user_word.is_paused is False


async def test_resume_word_with_progress_goes_to_review(session):
    user = await _create_user(session, telegram_id=906)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    added.user_word.repetition_stage = 2
    await user_word_service.pause_word(session, added.user_word)

    await user_word_service.resume_word(session, added.user_word)

    assert added.user_word.status == WordStatus.REVIEW


async def test_resume_word_naturally_mastered_becomes_due_immediately(session):
    """settings-improvements stage: a naturally-mastered word (reached via
    the real repetition algorithm) has next_review_at=None, since
    repetition_service never schedules a further review for MASTERED.
    Manually returning it to review from ⭐ Мои слова must make it
    actually reappear in the due queue right away, not silently stay
    excluded forever because next_review_at is still None."""
    user = await _create_user(session, telegram_id=920)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    added.user_word.repetition_stage = 7  # MASTERED_STAGE
    added.user_word.status = WordStatus.MASTERED
    added.user_word.next_review_at = None
    await session.commit()

    await user_word_service.resume_word(session, added.user_word)
    await session.commit()

    assert added.user_word.status == WordStatus.REVIEW
    assert added.user_word.next_review_at is not None

    due = await learning_repo.get_due_for_review(session, user_id=user.id, language_code="en", limit=10)
    assert added.user_word.id in {uw.id for uw in due}


async def test_resume_word_with_stale_schedule_becomes_due_immediately(session):
    """A word paused while its next_review_at was still far in the future
    must become due right away once explicitly un-paused, not wait out
    its old schedule from before the pause."""
    from datetime import timedelta

    from utils.time import utc_now

    user = await _create_user(session, telegram_id=921)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    added.user_word.repetition_stage = 2
    added.user_word.status = WordStatus.PAUSED
    added.user_word.next_review_at = utc_now() + timedelta(days=30)
    await session.commit()

    await user_word_service.resume_word(session, added.user_word)
    await session.commit()

    due = await learning_repo.get_due_for_review(session, user_id=user.id, language_code="en", limit=10)
    assert added.user_word.id in {uw.id for uw in due}


async def test_delete_word_is_soft_delete_and_excluded_from_lists(session):
    user = await _create_user(session, telegram_id=907)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")

    await user_word_service.delete_word(session, added.user_word)
    await session.commit()

    still_in_db = await user_words_repo.get_by_id(session, added.user_word.id)
    assert still_in_db is not None
    assert still_in_db.status == WordStatus.DELETED

    active_list = await user_word_service.list_user_words(session, user_id=user.id, language_code="en")
    assert active_list == []


async def test_delete_does_not_touch_the_shared_word_or_other_users(session):
    owner = await _create_user(session, telegram_id=908)
    other = await _create_user(session, telegram_id=909)
    word = await _create_word(session, word="have")

    owner_added = await user_word_service.add_word_to_learning(session, user_id=owner.id, word_id=word.id, language_code="en")
    other_added = await user_word_service.add_word_to_learning(session, user_id=other.id, word_id=word.id, language_code="en")

    await user_word_service.delete_word(session, owner_added.user_word)
    await session.commit()

    assert await word_service.get_word_card(session, word_id=word.id) is not None  # shared Word survives
    assert other_added.user_word.status != WordStatus.DELETED  # other user's row untouched


async def test_db_rejects_duplicate_user_word_row(session):
    """Belt-and-braces: even bypassing the service layer, the unique
    constraint on (user_id, word_id) holds."""
    user = await _create_user(session, telegram_id=910)
    word = await _create_word(session)

    await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    with pytest.raises(IntegrityError):
        await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
        await session.commit()


async def test_list_user_words_filters_by_status(session):
    user = await _create_user(session, telegram_id=911)
    words = {name: await _create_word(session, word=name) for name in ("go", "make", "take", "have")}

    new_word = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["go"].id, language_code="en")
    paused = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["make"].id, language_code="en")
    await user_word_service.pause_word(session, paused.user_word)
    mastered = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["take"].id, language_code="en")
    mastered.user_word.status = WordStatus.MASTERED
    await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["have"].id, language_code="en")
    await session.commit()

    assert len(await user_word_service.list_user_words(session, user_id=user.id, language_code="en", status_filter="all")) == 4
    assert [uw.word.word for uw in await user_word_service.list_user_words(session, user_id=user.id, language_code="en", status_filter="new")] == ["go", "have"]
    assert [uw.word.word for uw in await user_word_service.list_user_words(session, user_id=user.id, language_code="en", status_filter="paused")] == ["make"]
    assert [uw.word.word for uw in await user_word_service.list_user_words(session, user_id=user.id, language_code="en", status_filter="mastered")] == ["take"]


async def test_review_filter_covers_every_status_except_mastered_and_deleted(session):
    """Real user report: words sat in "Все" but were missing from both
    "Повторение" and "Выученные" - root cause was "review" only covering
    [LEARNING, REVIEW], leaving a freshly-added NEW word (and a PAUSED
    one) with nowhere to show up except "Все". "Повторение" must now mean
    "not mastered yet", i.e. everything except MASTERED/DELETED."""
    user = await _create_user(session, telegram_id=915)
    words = {name: await _create_word(session, word=name) for name in ("go", "make", "take", "have")}

    await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["go"].id, language_code="en")
    paused = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["make"].id, language_code="en")
    await user_word_service.pause_word(session, paused.user_word)
    mastered = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["take"].id, language_code="en")
    mastered.user_word.status = WordStatus.MASTERED
    have = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=words["have"].id, language_code="en")
    have.user_word.status = WordStatus.REVIEW
    await session.commit()

    review_words = {uw.word.word for uw in await user_word_service.list_user_words(session, user_id=user.id, language_code="en", status_filter="review")}
    assert review_words == {"go", "make", "have"}


async def test_count_user_words_matches_filtered_list(session):
    user = await _create_user(session, telegram_id=912)
    word = await _create_word(session)
    await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    assert await user_word_service.count_user_words(session, user_id=user.id, language_code="en", status_filter="all") == 1
    assert await user_word_service.count_user_words(session, user_id=user.id, language_code="en", status_filter="mastered") == 0


async def test_search_user_words_finds_partial_matches(session):
    user = await _create_user(session, telegram_id=913)
    improve = await _create_word(session, word="improve")
    improvement = await _create_word(session, word="improvement")
    other = await _create_word(session, word="go")
    for w in (improve, improvement, other):
        await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=w.id, language_code="en")
    await session.commit()

    results = await user_word_service.search_user_words(session, user_id=user.id, language_code="en", query="improv")
    assert {uw.word.word for uw in results} == {"improve", "improvement"}


async def test_search_user_words_excludes_deleted(session):
    user = await _create_user(session, telegram_id=914)
    word = await _create_word(session)
    added = await user_word_service.add_word_to_learning(session, user_id=user.id, word_id=word.id, language_code="en")
    await user_word_service.delete_word(session, added.user_word)
    await session.commit()

    results = await user_word_service.search_user_words(session, user_id=user.id, language_code="en", query=word.word)
    assert results == []
