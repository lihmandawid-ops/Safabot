"""End-to-end tests for handlers/settings.py (bugfix stage, real-Telegram
feedback): every branch of handle_settings_callback must answer the
callback query EXACTLY once. A prior version answered unconditionally at
the top of the function AND again with a toast message in several
branches - Telegram rejects a second answerCallbackQuery for the same
query, so _render_home never ran and the settings screen silently never
updated for language/level/daily-words/notification changes. These tests
assert call_count == 1 specifically to catch a regression of that bug,
plus cover the new ➕ Добавить язык flow (real gap: onboarding used to be
the only way to pick a learning language at all).

Mocks only the Telegram objects - real handlers, real session_scope(),
real database, same pattern as tests/test_manual_add_flow.py.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio


@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

    import config
    config.get_settings.cache_clear()

    import database.database as db_module
    db_module._engine = None
    db_module._session_factory = None

    from database.database import init_models, session_scope
    from database.seed import seed_languages
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        user = await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="beginner", daily_new_words=4,
        )

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


async def _run(data: str):
    from handlers import settings as settings_handler

    update = _query(data)
    context = SimpleNamespace(user_data={})
    await settings_handler.handle_settings_callback(update, context)
    return update.callback_query


async def test_notifications_toggle_answers_once_and_updates_screen(handler_db):
    q = await _run("set:notif:toggle")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()  # _render_home actually ran


async def test_language_pick_answers_once_and_updates_screen(handler_db):
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        de = await user_languages_repo.add_language(
            s, user_id=user.id, language_code="de", translation_language="ru",
            level="beginner", daily_new_words=4,
        )
        de_id = de.id

    q = await _run(f"set:lang:pick:{de_id}")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_interface_language_pick_answers_once_and_updates_screen(handler_db):
    q = await _run("set:iface:pick:en")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_daily_words_pick_answers_once_and_updates_screen(handler_db):
    q = await _run("set:words:pick:8")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_level_pick_answers_once_and_updates_screen(handler_db):
    q = await _run("set:level:pick:advanced")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_notification_time_pick_answers_once_and_updates_screen(handler_db):
    q = await _run("set:notif:time:morning:0800")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_add_language_full_flow(handler_db):
    from database.database import session_scope
    from database.models import SubscriptionStatus
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo

    # The fixture user already has 1 language (en) and free_max_languages
    # defaults to 1 - grant PRO so this test exercises the picker flow
    # itself, not the plan-limit gate (covered separately below).
    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        await users_repo.update_user(s, user, subscription_status=SubscriptionStatus.PRO)

    start = await _run("set:addlang:start")
    assert start.answer.call_count == 1
    start.edit_message_text.assert_awaited_once()

    pick_learn = await _run("set:addlang:learn:de")
    assert pick_learn.answer.call_count == 1

    pick_trans = await _run("set:addlang:trans:de:ru")
    assert pick_trans.answer.call_count == 1

    pick_level = await _run("set:addlang:level:de:ru:advanced")
    assert pick_level.answer.call_count == 1

    final = await _run("set:addlang:words:de:ru:advanced:8")
    assert final.answer.call_count == 1
    final.edit_message_text.assert_awaited_once()

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        languages = await user_languages_repo.get_user_languages(s, user.id)
        de = next(ul for ul in languages if ul.language_code == "de")
        assert de.translation_language == "ru"
        assert de.level == "advanced"
        assert de.daily_new_words == 8
        assert de.is_current is True  # newly added language becomes active


async def test_add_language_duplicate_shows_alert_without_crashing(handler_db):
    q = await _run("set:addlang:words:en:ru:beginner:4")  # en/ru already exists from the fixture
    assert q.answer.call_count == 1
    args, kwargs = q.answer.call_args
    assert kwargs.get("show_alert") is True


async def test_add_language_respects_free_plan_limit(handler_db):
    """The fixture user already has 1 language (en) and no PRO access -
    free_max_languages defaults to 1, so ➕ Добавить язык must refuse."""
    q = await _run("set:addlang:start")
    assert q.answer.call_count == 1
    args, kwargs = q.answer.call_args
    assert kwargs.get("show_alert") is True
    q.edit_message_text.assert_not_awaited()  # never entered the picker
