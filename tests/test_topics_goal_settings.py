"""End-to-end tests for Settings → 🎯 Цель изучения / 🎯 Темы обучения
(settings-improvements stage sections 18-23). Mocks only the Telegram
objects - real handlers, real session_scope(), real database, same
pattern as tests/test_settings_handlers.py.
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


async def _current_language():
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        return await user_languages_repo.get_current_language(s, user.id)


async def test_goal_list_shows_picker(handler_db):
    q = await _run("set:goal:list")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_pick_non_work_goal_saves_and_skips_industry(handler_db):
    q = await _run("set:goal:pick:travel")
    assert q.answer.call_count == 1

    ul = await _current_language()
    assert ul.learning_goal == "travel"
    assert ul.work_industry is None


async def test_pick_work_goal_shows_industry_picker(handler_db):
    q = await _run("set:goal:pick:work")
    assert q.answer.call_count == 1
    args, kwargs = q.edit_message_text.call_args
    callbacks = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert any(cb.startswith("set:goal:industry:") for cb in callbacks)

    ul = await _current_language()
    assert ul.learning_goal == "work"


async def test_pick_preset_industry_saves(handler_db):
    await _run("set:goal:pick:work")
    q = await _run("set:goal:industry:it")
    assert q.answer.call_count == 1

    ul = await _current_language()
    assert ul.learning_goal == "work"
    assert ul.work_industry == "it"


async def test_custom_industry_via_free_text(handler_db):
    context = SimpleNamespace(user_data={})
    await _run("set:goal:pick:work", context)
    await _run("set:goal:industry:other", context)
    assert context.user_data["mode"] == "settings_timezone_search"
    assert context.user_data["settings_submode"] == "industry_custom"

    from handlers import settings as settings_handler

    update = _message("marine biology")
    await settings_handler.handle_text_input(update, context, "marine biology")
    update.message.reply_text.assert_awaited_once()

    ul = await _current_language()
    assert ul.work_industry == "marine biology"
    assert "settings_submode" not in context.user_data


async def test_switching_goal_away_from_work_clears_industry(handler_db):
    await _run("set:goal:pick:work")
    await _run("set:goal:industry:it")
    ul = await _current_language()
    assert ul.work_industry == "it"

    await _run("set:goal:pick:study")
    ul = await _current_language()
    assert ul.learning_goal == "study"
    assert ul.work_industry is None


async def test_topics_list_shows_picker(handler_db):
    q = await _run("set:topics:list")
    assert q.answer.call_count == 1
    q.edit_message_text.assert_awaited_once()


async def test_toggle_preset_topic_on_and_off(handler_db):
    q = await _run("set:topics:toggle:travel")
    assert q.answer.call_count == 1
    ul = await _current_language()
    assert ul.selected_topics == ["travel"]

    q2 = await _run("set:topics:toggle:travel")
    assert q2.answer.call_count == 1
    ul = await _current_language()
    assert ul.selected_topics == []


async def test_topics_limit_is_enforced(handler_db, monkeypatch):
    import utils.topics
    monkeypatch.setattr(utils.topics, "MAX_SELECTED_TOPICS", 2)
    monkeypatch.setattr("handlers.settings.MAX_SELECTED_TOPICS", 2)

    await _run("set:topics:toggle:travel")
    await _run("set:topics:toggle:business")
    q = await _run("set:topics:toggle:food")

    args, kwargs = q.answer.call_args
    assert kwargs.get("show_alert") is True

    ul = await _current_language()
    assert set(ul.selected_topics) == {"travel", "business"}


async def test_custom_topic_via_free_text(handler_db):
    context = SimpleNamespace(user_data={})
    await _run("set:topics:add_custom", context)
    assert context.user_data["mode"] == "settings_timezone_search"
    assert context.user_data["settings_submode"] == "topics_custom"

    from handlers import settings as settings_handler

    update = _message("cooking")
    await settings_handler.handle_text_input(update, context, "cooking")
    update.message.reply_text.assert_awaited_once()

    ul = await _current_language()
    assert "cooking" in ul.selected_topics
    assert "settings_submode" not in context.user_data


async def test_remove_custom_topic(handler_db):
    context = SimpleNamespace(user_data={})
    await _run("set:topics:add_custom", context)
    from handlers import settings as settings_handler

    await settings_handler.handle_text_input(_message("cooking"), context, "cooking")

    q = await _run("set:topics:removecustom:0")
    assert q.answer.call_count == 1

    ul = await _current_language()
    assert "cooking" not in ul.selected_topics


async def test_settings_summary_shows_goal_and_topics(handler_db):
    await _run("set:goal:pick:travel")
    await _run("set:topics:toggle:travel")

    from handlers import settings as settings_handler
    from database.database import session_scope
    from database.repositories import users as users_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        summary = await settings_handler._build_summary(s, user)

    assert "Путешеств" in summary or "travel" in summary.lower()


async def test_timezone_search_still_works_after_visiting_topics_first(handler_db):
    """Regression guard: entering the topics/industry free-text submode
    and then switching to 🌍 Часовой пояс -> 🔎 Другой часовой пояс must
    not leave a stale settings_submode routing the next typed message to
    the wrong handler."""
    context = SimpleNamespace(user_data={})
    await _run("set:topics:add_custom", context)
    assert context.user_data.get("settings_submode") == "topics_custom"

    await _run("set:tz:search", context)
    assert context.user_data.get("settings_submode") is None

    from handlers import settings as settings_handler

    update = _message("Tel Aviv")
    await settings_handler.handle_text_input(update, context, "Tel Aviv")
    update.message.reply_text.assert_awaited_once()
    kwargs = update.message.reply_text.call_args[1]
    assert kwargs["reply_markup"] is not None
