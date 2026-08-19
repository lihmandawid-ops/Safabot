"""Registration, repeat /start, and repository method tests (spec section 17)."""
from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo


async def _create_test_user(session, telegram_id: int = 100):
    return await users_repo.create_user(
        session,
        telegram_id=telegram_id,
        username="grace",
        first_name="Grace",
        interface_language="ru",
        timezone="Europe/Moscow",
        level="beginner",
        daily_new_words=4,
        morning_time=time(9, 0),
        afternoon_time=time(14, 0),
        evening_time=time(20, 0),
    )


async def test_create_user_persists_expected_fields(session):
    await _create_test_user(session)
    await session.commit()

    fetched = await users_repo.get_by_telegram_id(session, 100)
    assert fetched is not None
    assert fetched.username == "grace"
    assert fetched.interface_language == "ru"
    assert fetched.daily_new_words == 4
    assert fetched.subscription_status == "free"
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_get_by_telegram_id_returns_none_when_missing(session):
    assert await users_repo.get_by_telegram_id(session, 999) is None


async def test_telegram_id_must_be_unique(session):
    await _create_test_user(session, telegram_id=200)
    await session.commit()

    with pytest.raises(IntegrityError):
        await _create_test_user(session, telegram_id=200)
        await session.commit()


async def test_repeat_start_does_not_create_a_duplicate_user(session):
    """Simulates the /start handler's own logic: check-then-create, the way
    handlers/start.py does it (spec section 2: repeat /start must not
    create a second row)."""
    telegram_id = 250

    existing = await users_repo.get_by_telegram_id(session, telegram_id)
    assert existing is None
    await _create_test_user(session, telegram_id=telegram_id)
    await session.commit()

    existing_again = await users_repo.get_by_telegram_id(session, telegram_id)
    assert existing_again is not None
    # Second /start: because a row already exists, the handler must not
    # call create_user() again.
    count_before = existing_again.id
    existing_again_2 = await users_repo.get_by_telegram_id(session, telegram_id)
    assert existing_again_2.id == count_before


async def test_update_user_changes_requested_fields_only(session):
    user = await _create_test_user(session, telegram_id=260)
    await session.commit()

    await users_repo.update_user(session, user, level="advanced", daily_new_words=8)
    await session.commit()

    fetched = await users_repo.get_by_telegram_id(session, 260)
    assert fetched.level == "advanced"
    assert fetched.daily_new_words == 8
    assert fetched.interface_language == "ru"  # untouched


async def test_update_user_rejects_unknown_field(session):
    user = await _create_test_user(session, telegram_id=270)
    with pytest.raises(AttributeError):
        await users_repo.update_user(session, user, not_a_real_field=1)


async def test_add_user_language_creates_learning_language(session):
    user = await _create_test_user(session, telegram_id=300)
    await user_languages_repo.add_language(
        session,
        user_id=user.id,
        language_code="en",
        translation_language="ru",
        level="beginner",
        daily_new_words=4,
    )
    await session.commit()

    languages = await user_languages_repo.get_user_languages(session, user.id)
    assert len(languages) == 1
    assert languages[0].language_code == "en"
    assert languages[0].translation_language == "ru"
    assert languages[0].is_current is True


async def test_a_user_can_study_multiple_languages(session):
    user = await _create_test_user(session, telegram_id=400)
    for code in ("en", "de", "he"):
        await user_languages_repo.add_language(
            session,
            user_id=user.id,
            language_code=code,
            translation_language="ru",
            level="beginner",
            daily_new_words=4,
        )
    await session.commit()

    languages = await user_languages_repo.get_user_languages(session, user.id)
    assert {lang.language_code for lang in languages} == {"en", "de", "he"}
