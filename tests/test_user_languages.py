"""UserLanguage tests: duplicate-pair prevention, active-language switching,
removal (spec sections 4, 13, 17)."""
from __future__ import annotations

from datetime import time

import pytest

from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo


async def _create_test_user(session, telegram_id: int = 700):
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


async def _add(session, user_id, language_code="en", translation_language="ru"):
    return await user_languages_repo.add_language(
        session,
        user_id=user_id,
        language_code=language_code,
        translation_language=translation_language,
        level="beginner",
        daily_new_words=4,
    )


async def test_first_added_language_becomes_current(session):
    user = await _create_test_user(session)
    ul = await _add(session, user.id)
    assert ul.is_current is True


async def test_second_added_language_is_not_current(session):
    user = await _create_test_user(session, telegram_id=701)
    await _add(session, user.id, "en", "ru")
    second = await _add(session, user.id, "de", "ru")
    assert second.is_current is False


async def test_duplicate_pair_is_rejected(session):
    user = await _create_test_user(session, telegram_id=702)
    await _add(session, user.id, "en", "ru")

    with pytest.raises(user_languages_repo.DuplicateUserLanguageError):
        await _add(session, user.id, "en", "ru")


async def test_same_learning_language_different_translation_is_allowed(session):
    """en->ru and en->de for the same user are different pairs."""
    user = await _create_test_user(session, telegram_id=703)
    await _add(session, user.id, "en", "ru")
    await _add(session, user.id, "en", "de")

    languages = await user_languages_repo.get_user_languages(session, user.id)
    assert len(languages) == 2


async def test_set_active_language_switches_current_flag(session):
    user = await _create_test_user(session, telegram_id=704)
    first = await _add(session, user.id, "en", "ru")
    second = await _add(session, user.id, "de", "ru")
    await session.commit()

    await user_languages_repo.set_active_language(session, user_id=user.id, user_language_id=second.id)
    await session.commit()

    current = await user_languages_repo.get_current_language(session, user.id)
    assert current.id == second.id

    languages = await user_languages_repo.get_user_languages(session, user.id)
    current_flags = [ul.is_current for ul in languages]
    assert current_flags.count(True) == 1
    assert first.is_current is False


async def test_set_active_language_rejects_language_from_another_user(session):
    owner = await _create_test_user(session, telegram_id=705)
    other = await _create_test_user(session, telegram_id=706)
    owners_language = await _add(session, owner.id, "en", "ru")
    await session.commit()

    with pytest.raises(ValueError):
        await user_languages_repo.set_active_language(
            session, user_id=other.id, user_language_id=owners_language.id
        )


async def test_remove_language_deletes_the_row(session):
    user = await _create_test_user(session, telegram_id=707)
    ul = await _add(session, user.id, "en", "ru")
    await session.commit()

    await user_languages_repo.remove_language(session, ul)
    await session.commit()

    languages = await user_languages_repo.get_user_languages(session, user.id)
    assert languages == []


async def test_remove_current_language_promotes_another(session):
    user = await _create_test_user(session, telegram_id=708)
    first = await _add(session, user.id, "en", "ru")
    await _add(session, user.id, "de", "ru")
    await session.commit()

    await user_languages_repo.remove_language(session, first)
    await session.commit()

    current = await user_languages_repo.get_current_language(session, user.id)
    assert current is not None
    assert current.language_code == "de"


async def test_set_language_enabled_toggles_active_flag(session):
    user = await _create_test_user(session, telegram_id=709)
    ul = await _add(session, user.id)

    await user_languages_repo.set_language_enabled(session, ul, False)
    assert ul.active is False

    active_only = await user_languages_repo.get_user_languages(session, user.id, active_only=True)
    assert active_only == []
