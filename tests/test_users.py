"""Registration and UserLanguage tests (spec section 32)."""
from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from database.repositories import users as users_repo


async def _create_test_user(session, telegram_id: int = 100):
    return await users_repo.create_user(
        session,
        telegram_id=telegram_id,
        username="grace",
        first_name="Grace",
        interface_language="ru",
        timezone="Europe/Moscow",
        current_level="beginner",
        daily_new_words_limit=4,
        morning_notification_time=time(9, 0),
        afternoon_notification_time=time(14, 0),
        evening_notification_time=time(20, 0),
    )


async def test_create_user_persists_expected_fields(session):
    user = await _create_test_user(session)
    await session.commit()

    fetched = await users_repo.get_user_by_telegram_id(session, 100)
    assert fetched is not None
    assert fetched.username == "grace"
    assert fetched.interface_language == "ru"
    assert fetched.daily_new_words_limit == 4
    assert fetched.subscription_status == "free"


async def test_get_user_by_telegram_id_returns_none_when_missing(session):
    assert await users_repo.get_user_by_telegram_id(session, 999) is None


async def test_telegram_id_must_be_unique(session):
    await _create_test_user(session, telegram_id=200)
    await session.commit()

    with pytest.raises(IntegrityError):
        await _create_test_user(session, telegram_id=200)
        await session.commit()


async def test_add_user_language_creates_learning_language(session):
    user = await _create_test_user(session, telegram_id=300)
    await users_repo.add_user_language(
        session,
        user_id=user.id,
        language_code="en",
        translation_language="ru",
        level="beginner",
        daily_word_limit=4,
    )
    await session.commit()

    languages = await users_repo.get_active_languages(session, user.id)
    assert len(languages) == 1
    assert languages[0].language_code == "en"
    assert languages[0].translation_language == "ru"


async def test_a_user_can_study_multiple_languages(session):
    user = await _create_test_user(session, telegram_id=400)
    for code in ("en", "de", "he"):
        await users_repo.add_user_language(
            session,
            user_id=user.id,
            language_code=code,
            translation_language="ru",
            level="beginner",
            daily_word_limit=4,
        )
    await session.commit()

    languages = await users_repo.get_active_languages(session, user.id)
    assert {lang.language_code for lang in languages} == {"en", "de", "he"}
