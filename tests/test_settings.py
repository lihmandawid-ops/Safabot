"""Settings-change tests at the repository level (spec section 17): the
same calls handlers/settings.py makes when a user edits a setting."""
from __future__ import annotations

from datetime import time

from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo


async def _create_test_user(session, telegram_id: int = 800):
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


async def test_change_notification_time(session):
    user = await _create_test_user(session)
    await users_repo.update_user(session, user, morning_time=time(7, 30))

    assert user.morning_time == time(7, 30)
    assert user.afternoon_time == time(14, 0)  # untouched


async def test_toggle_notifications(session):
    user = await _create_test_user(session, telegram_id=801)
    assert user.notifications_enabled is True

    await users_repo.update_user(session, user, notifications_enabled=False)
    assert user.notifications_enabled is False


async def test_change_interface_language(session):
    user = await _create_test_user(session, telegram_id=802)
    await users_repo.update_user(session, user, interface_language="en")
    assert user.interface_language == "en"


async def test_change_level(session):
    user = await _create_test_user(session, telegram_id=803)
    await users_repo.update_user(session, user, level="upper_intermediate")
    assert user.level == "upper_intermediate"


async def test_change_daily_new_words_is_per_language(session):
    """Section 8: daily word count is stored per learning language, not
    just on the User row."""
    user = await _create_test_user(session, telegram_id=804)
    en = await user_languages_repo.add_language(
        session,
        user_id=user.id,
        language_code="en",
        translation_language="ru",
        level="beginner",
        daily_new_words=4,
    )
    de = await user_languages_repo.add_language(
        session,
        user_id=user.id,
        language_code="de",
        translation_language="ru",
        level="beginner",
        daily_new_words=4,
    )

    await user_languages_repo.set_daily_new_words(session, en, 8)

    assert en.daily_new_words == 8
    assert de.daily_new_words == 4  # untouched
    assert user.daily_new_words == 4  # the User-level default is untouched
