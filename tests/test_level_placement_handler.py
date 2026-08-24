"""End-to-end tests for 🤖 Узнать мой уровень (real user request): the
AI-graded placement test that replaces ⚙️ Настройки → 🎚 Уровень сложности
изучения языка's old "Автоматически" button.

Mocks only services.level_placement_service.get_ai_service - real
handlers, real session_scope(), real database, same pattern as
tests/test_settings_handlers.py and tests/test_manual_add_flow.py.
"""
from __future__ import annotations

import os
import tempfile
from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from services import ai_models


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


def _install_fake_ai(monkeypatch, *, questions, level: str):
    async def _fake_generate(**kwargs):
        return ai_models.PlacementTestResult(questions=questions)

    async def _fake_grade(**kwargs):
        return ai_models.PlacementLevelResult(level=level)

    fake_ai = type(
        "FakeAI", (),
        {"generate_placement_test": staticmethod(_fake_generate), "grade_placement_test": staticmethod(_fake_grade)},
    )()
    monkeypatch.setattr("services.level_placement_service.get_ai_service", lambda: fake_ai)
    return fake_ai


async def test_full_placement_flow_sets_manual_difficulty_to_the_ai_result(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import settings as settings_handler

    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="translate", prompt="I go home."),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="b2")

    context = SimpleNamespace(user_data={})

    start = await _run_callback(settings_handler, "set:difficulty:placement:start", context)
    start.callback_query.answer.assert_awaited_once()
    text1 = start.callback_query.edit_message_text.call_args[0][0]
    assert "hello" in text1
    markup1 = start.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks1 = [b.callback_data for row in markup1.inline_keyboard for b in row]
    assert "set:placement:answer:yes" in callbacks1
    assert "set:placement:answer:no" in callbacks1

    answer1 = await _run_callback(settings_handler, "set:placement:answer:yes", context)
    answer1.callback_query.answer.assert_awaited_once()
    text2 = answer1.callback_query.edit_message_text.call_args[0][0]
    assert "I go home." in text2
    assert context.user_data["mode"] == settings_handler.MODE
    assert context.user_data["settings_submode"] == "placement_answer"

    update2 = _message("Я иду домой")
    await settings_handler.handle_text_input(update2, context, "Я иду домой")
    # Two sends: the "⏳ Определяем ваш уровень..." placeholder, then the
    # actual result - same loading-indicator convention as every other
    # AI-backed flow in this codebase.
    assert update2.message.reply_text.await_count == 2
    result_text = update2.message.reply_text.call_args_list[-1][0][0]
    assert "b2" in result_text.lower() or "B2" in result_text

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        assert current.difficulty_mode == "manual"
        assert current.learning_difficulty == "b2"

    assert "placement_test" not in context.user_data
    assert "mode" not in context.user_data
    assert "settings_submode" not in context.user_data


async def test_word_question_answer_via_button_never_enters_text_mode(handler_db, monkeypatch):
    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="word", prompt="goodbye"),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="a1")
    from handlers import settings as settings_handler

    context = SimpleNamespace(user_data={})
    await _run_callback(settings_handler, "set:difficulty:placement:start", context)
    await _run_callback(settings_handler, "set:placement:answer:no", context)

    # Both questions are "word" kind - answered entirely via buttons, so
    # free-text mode must never be switched on for this flow.
    assert "mode" not in context.user_data
    assert "settings_submode" not in context.user_data


async def test_placement_can_be_cancelled_mid_flow(handler_db, monkeypatch):
    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="translate", prompt="I go home."),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="b2")
    from handlers import settings as settings_handler

    context = SimpleNamespace(user_data={})
    await _run_callback(settings_handler, "set:difficulty:placement:start", context)

    cancel = await _run_callback(settings_handler, "set:placement:cancel", context)
    cancel.callback_query.answer.assert_awaited_once()
    assert "placement_test" not in context.user_data
    assert "mode" not in context.user_data
    markup = cancel.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "set:difficulty:placement:start" in callbacks  # back on the difficulty screen


async def test_placement_start_shows_not_configured_when_ai_is_unavailable(handler_db):
    """Default test environment has AI forced unconfigured (conftest.py's
    autouse fixture) - no monkeypatch needed here."""
    from handlers import settings as settings_handler

    context = SimpleNamespace(user_data={})
    start = await _run_callback(settings_handler, "set:difficulty:placement:start", context)
    text = start.callback_query.edit_message_text.call_args[0][0]
    assert text  # some not-configured message was shown
    assert "placement_test" not in context.user_data


async def _run_callback(settings_handler, data: str, context: SimpleNamespace):
    update = _query(data)
    await settings_handler.handle_settings_callback(update, context)
    return update
