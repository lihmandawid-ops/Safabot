"""End-to-end tests for ⚙️ Настройки → 🌍 Часовой пояс (settings-improvements
stage): picking from the curated list, free-text search over the real IANA
database, and rejecting garbage input. Mocks only the Telegram objects -
real handlers, real session_scope(), real database, same pattern as
tests/test_settings_handlers.py.
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
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
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


def _message(text: str):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=42), message=msg)


async def _run(data: str, context=None):
    from handlers import settings as settings_handler

    update = _query(data)
    context = context if context is not None else SimpleNamespace(user_data={})
    await settings_handler.handle_settings_callback(update, context)
    return update.callback_query


async def _get_user():
    from database.database import session_scope
    from database.repositories import users as users_repo

    async with session_scope() as s:
        return await users_repo.get_by_telegram_id(s, 42)


async def test_timezone_list_shows_picker(handler_db):
    q = await _run("set:tz:list")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_pick_curated_timezone_saves_and_updates_screen(handler_db):
    q = await _run("set:tz:pick:Asia/Jerusalem")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()

    user = await _get_user()
    assert user.timezone == "Asia/Jerusalem"


async def test_pick_invalid_timezone_is_rejected(handler_db):
    q = await _run("set:tz:pick:Not/A_Real_Zone")
    args, kwargs = q.answer.call_args
    assert kwargs.get("show_alert") is True

    user = await _get_user()
    assert user.timezone == "UTC"  # unchanged


async def test_search_enters_text_mode_and_finds_matches(handler_db):
    from handlers import settings as settings_handler

    context = SimpleNamespace(user_data={})
    q = await _run("set:tz:search", context=context)
    assert context.user_data["mode"] == settings_handler.MODE

    update = _message("Tel Aviv")
    await settings_handler.handle_text_input(update, context, "Tel Aviv")
    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert kwargs["reply_markup"] is not None


async def test_search_with_no_matches_shows_friendly_message(handler_db):
    from handlers import settings as settings_handler

    context = SimpleNamespace(user_data={})
    update = _message("zzz_not_a_place_zzz")
    await settings_handler.handle_text_input(update, context, "zzz_not_a_place_zzz")
    text = update.message.reply_text.call_args[0][0]
    assert "не найдено" in text.lower() or "не найд" in text.lower()


async def test_search_result_pick_saves_timezone(handler_db):
    q = await _run("set:tz:pick:Asia/Tel_Aviv")
    assert q.answer.call_count == 1

    user = await _get_user()
    assert user.timezone == "Asia/Tel_Aviv"


async def test_timezone_change_does_not_affect_interface_language(handler_db):
    """Bugfix spec section 2: two separate settings must never bleed into
    each other."""
    from database.database import session_scope
    from database.repositories import users as users_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        await users_repo.update_user(s, user, interface_language="en")

    await _run("set:tz:pick:Europe/Berlin")

    user = await _get_user()
    assert user.timezone == "Europe/Berlin"
    assert user.interface_language == "en"  # untouched
