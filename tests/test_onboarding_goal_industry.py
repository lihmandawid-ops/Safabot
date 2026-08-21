"""End-to-end tests for the settings-improvements stage's onboarding
addition (sections 18-21): the 🎯 learning-goal question inserted
between daily-words and timezone, and the conditional work-industry
follow-up only shown when the goal is "work". Drives handlers/start.py's
step functions directly in sequence (same context.user_data object
across calls, like PTB's ConversationHandler would thread it) rather
than going through the real Application dispatcher - same approach as
the rest of this test suite's handler-level tests.
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

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str, telegram_id: int = 900):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=telegram_id)
    effective_user = SimpleNamespace(id=telegram_id, username="tester", first_name="Tester")
    return SimpleNamespace(callback_query=q, effective_user=effective_user)


def _message(text: str, telegram_id: int = 900):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg)


async def _drive_up_to_daily_words(context, telegram_id: int = 900):
    """Runs the unrelated-to-this-stage steps (interface language ->
    ... -> daily words) so each test starts right at the new goal step,
    without re-testing behaviour already covered elsewhere."""
    from handlers import start as start_handler

    await start_handler.choose_interface_language(_query(f"{start_handler.INTERFACE_LANGUAGE_PREFIX}ru", telegram_id), context)
    await start_handler.choose_learning_language(_query(f"{start_handler.LEARNING_LANGUAGE_PREFIX}en", telegram_id), context)
    await start_handler.choose_translation_language(_query(f"{start_handler.TRANSLATION_LANGUAGE_PREFIX}ru", telegram_id), context)
    await start_handler.choose_level(_query(f"{start_handler.LEVEL_PREFIX}beginner", telegram_id), context)
    await start_handler.choose_daily_words(_query(f"{start_handler.DAILY_WORDS_PREFIX}4", telegram_id), context)


async def _fetch_user_language(telegram_id: int):
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, telegram_id)
        return await user_languages_repo.get_current_language(s, user.id)


async def test_goal_step_is_shown_after_daily_words(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    query = _query(f"{start_handler.DAILY_WORDS_PREFIX}4", 901)
    await start_handler.choose_interface_language(_query(f"{start_handler.INTERFACE_LANGUAGE_PREFIX}ru", 901), context)
    await start_handler.choose_learning_language(_query(f"{start_handler.LEARNING_LANGUAGE_PREFIX}en", 901), context)
    await start_handler.choose_translation_language(_query(f"{start_handler.TRANSLATION_LANGUAGE_PREFIX}ru", 901), context)
    await start_handler.choose_level(_query(f"{start_handler.LEVEL_PREFIX}beginner", 901), context)
    state = await start_handler.choose_daily_words(query, context)

    assert state == start_handler.CHOOSING_GOAL
    query.callback_query.message.reply_text.assert_awaited_once()
    kwargs = query.callback_query.message.reply_text.call_args[1]
    callbacks = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert any(cb.startswith(start_handler.GOAL_PREFIX) for cb in callbacks)


async def test_non_work_goal_skips_industry_and_saves_correctly(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 902)

    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}travel", 902), context)
    assert context.user_data["learning_goal"] == "travel"

    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 902), context)

    ul = await _fetch_user_language(902)
    assert ul.learning_goal == "travel"
    assert ul.work_industry is None


async def test_skipped_goal_saves_none(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 903)

    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}skip", 903), context)
    assert context.user_data["learning_goal"] is None

    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 903), context)

    ul = await _fetch_user_language(903)
    assert ul.learning_goal is None
    assert ul.work_industry is None


async def test_work_goal_shows_industry_step_and_saves_preset_choice(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 904)

    result_state = await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}work", 904), context)
    assert result_state == start_handler.CHOOSING_INDUSTRY

    await start_handler.choose_industry(_query(f"{start_handler.INDUSTRY_PREFIX}it", 904), context)
    assert context.user_data["work_industry"] == "it"

    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 904), context)

    ul = await _fetch_user_language(904)
    assert ul.learning_goal == "work"
    assert ul.work_industry == "it"


async def test_work_goal_industry_skip_saves_none(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 905)

    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}work", 905), context)
    await start_handler.choose_industry(_query(f"{start_handler.INDUSTRY_PREFIX}skip", 905), context)
    assert context.user_data["work_industry"] is None

    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 905), context)

    ul = await _fetch_user_language(905)
    assert ul.learning_goal == "work"
    assert ul.work_industry is None


async def test_work_goal_custom_industry_via_free_text(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 906)

    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}work", 906), context)
    await start_handler.choose_industry(_query(f"{start_handler.INDUSTRY_PREFIX}other", 906), context)

    await start_handler.choose_industry_custom(_message("marine biology", 906), context)
    assert context.user_data["work_industry"] == "marine biology"

    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 906), context)

    ul = await _fetch_user_language(906)
    assert ul.learning_goal == "work"
    assert ul.work_industry == "marine biology"


async def test_non_work_goal_never_persists_a_leftover_industry(handler_db):
    """Defensive: even if context.user_data somehow carried a stale
    work_industry (shouldn't happen via the normal flow, but the DB
    write itself must never leak it under a non-work goal)."""
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={})
    await _drive_up_to_daily_words(context, 907)
    context.user_data["work_industry"] = "leftover"

    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}study", 907), context)
    await start_handler.choose_timezone(_query(f"{start_handler.TIMEZONE_PREFIX}UTC", 907), context)

    ul = await _fetch_user_language(907)
    assert ul.learning_goal == "study"
    assert ul.work_industry is None
