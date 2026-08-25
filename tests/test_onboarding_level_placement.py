"""End-to-end tests for the redesigned onboarding level step (real user
request): interface_language/translation_language are auto-detected from
Telegram (never asked), the level step offers only "🟢 Только начинаю"
or "🤖 Узнать мой уровень" (the same AI placement test ⚙️ Настройки → 🎚
Уровень сложности offers), and there is no separate daily-words step at
all - every user gets config.py's DEFAULT_DAILY_NEW_WORDS.

Mocks only services.level_placement_service.get_ai_service - real
handler functions, real session_scope(), real database, same pattern as
tests/test_level_placement_handler.py and tests/test_onboarding_goal_industry.py.
"""
from __future__ import annotations

import os
import tempfile
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
    effective_user = SimpleNamespace(id=telegram_id, username="tester", first_name="Tester")
    return SimpleNamespace(callback_query=q, effective_user=effective_user)


def _message(text: str, telegram_id: int = 900):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg, callback_query=None)


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


async def test_level_keyboard_offers_only_beginner_and_placement(handler_db):
    """Real user request: never the old flat list of 6 CEFR buttons -
    exactly "🟢 Только начинаю" and "🤖 Узнать мой уровень"."""
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={"interface_language": "ru"})
    query = _query(f"{start_handler.LEARNING_LANGUAGE_PREFIX}en", 900)
    await start_handler.choose_learning_language(query, context)

    markup = query.callback_query.message.reply_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == [start_handler.BEGINNER_LEVEL_CALLBACK, start_handler.PLACEMENT_START_CALLBACK]


async def test_beginner_button_skips_straight_to_goal_no_daily_words_step(handler_db):
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={"interface_language": "ru", "learning_language": "en"})
    query = _query(start_handler.BEGINNER_LEVEL_CALLBACK, 900)
    state = await start_handler.choose_level(query, context)

    assert state == start_handler.CHOOSING_GOAL
    assert context.user_data["level"] == "a1"
    markup = query.callback_query.message.reply_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert any(cb.startswith(start_handler.GOAL_PREFIX) for cb in callbacks)


async def test_full_placement_flow_sets_level_and_reaches_goal_step(handler_db, monkeypatch):
    from handlers import start as start_handler

    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="translate", prompt="I go home."),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="b2")

    context = SimpleNamespace(user_data={"interface_language": "ru", "learning_language": "en"})

    start_query = _query(start_handler.PLACEMENT_START_CALLBACK, 900)
    state = await start_handler.choose_level(start_query, context)
    assert state == start_handler.CHOOSING_LEVEL_PLACEMENT
    text1 = start_query.callback_query.message.reply_text.call_args[0][0]
    assert "hello" in text1
    markup1 = start_query.callback_query.message.reply_text.call_args[1]["reply_markup"]
    callbacks1 = [b.callback_data for row in markup1.inline_keyboard for b in row]
    assert f"{start_handler.PLACEMENT_ANSWER_PREFIX}yes" in callbacks1
    assert f"{start_handler.PLACEMENT_ANSWER_PREFIX}no" in callbacks1

    answer_query = _query(f"{start_handler.PLACEMENT_ANSWER_PREFIX}yes", 900)
    state = await start_handler.choose_level_placement_answer(answer_query, context)
    assert state == start_handler.CHOOSING_LEVEL_PLACEMENT
    text2 = answer_query.callback_query.edit_message_text.call_args[0][0]
    assert "I go home." in text2

    translate_update = _message("Я иду домой", 900)
    state = await start_handler.choose_level_placement_translate(translate_update, context)

    assert state == start_handler.CHOOSING_GOAL
    assert context.user_data["level"] == "b2"
    assert "placement_test" not in context.user_data
    # Two sends: the "⏳ Определяем..." placeholder, then the level
    # result - same loading-indicator convention as settings.py's own
    # placement flow.
    assert translate_update.message.reply_text.await_count >= 2
    last_texts = [c[0][0] for c in translate_update.message.reply_text.call_args_list]
    assert any("b2" in text.lower() for text in last_texts)


async def test_word_only_placement_flow_never_enters_text_mode_state(handler_db, monkeypatch):
    """Both questions are "word" kind - answered entirely via buttons -
    the free-text handler must never be needed to finish."""
    from handlers import start as start_handler

    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="word", prompt="goodbye"),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="a2")

    context = SimpleNamespace(user_data={"interface_language": "ru", "learning_language": "en"})
    await start_handler.choose_level(_query(start_handler.PLACEMENT_START_CALLBACK, 900), context)
    state = await start_handler.choose_level_placement_answer(_query(f"{start_handler.PLACEMENT_ANSWER_PREFIX}yes", 900), context)
    assert state == start_handler.CHOOSING_LEVEL_PLACEMENT
    final_query = _query(f"{start_handler.PLACEMENT_ANSWER_PREFIX}no", 900)
    state = await start_handler.choose_level_placement_answer(final_query, context)

    assert state == start_handler.CHOOSING_GOAL
    assert context.user_data["level"] == "a2"


async def test_stray_text_during_a_word_question_is_ignored(handler_db, monkeypatch):
    """Real bug class this guards against: a free-text message sent while
    the CURRENT placement question is "word" kind (button-answered) must
    never be silently recorded as that question's answer."""
    from handlers import start as start_handler

    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="word", prompt="goodbye"),
    ]
    _install_fake_ai(monkeypatch, questions=questions, level="a1")

    context = SimpleNamespace(user_data={"interface_language": "ru", "learning_language": "en"})
    await start_handler.choose_level(_query(start_handler.PLACEMENT_START_CALLBACK, 900), context)

    state = await start_handler.choose_level_placement_translate(_message("some stray text", 900), context)

    assert state == start_handler.CHOOSING_LEVEL_PLACEMENT
    assert context.user_data["placement_test"]["answers"] == []
    assert context.user_data["placement_test"]["index"] == 0


async def test_placement_unavailable_falls_back_to_level_keyboard(handler_db):
    """Default test environment has AI forced unconfigured (conftest.py's
    autouse fixture) - no monkeypatch needed here."""
    from handlers import start as start_handler

    context = SimpleNamespace(user_data={"interface_language": "ru", "learning_language": "en"})
    query = _query(start_handler.PLACEMENT_START_CALLBACK, 900)
    state = await start_handler.choose_level(query, context)

    assert state == start_handler.CHOOSING_LEVEL
    query.callback_query.message.reply_text.assert_awaited_once()
    markup = query.callback_query.message.reply_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == [start_handler.BEGINNER_LEVEL_CALLBACK, start_handler.PLACEMENT_START_CALLBACK]


async def test_full_registration_never_asks_interface_language_or_daily_words(handler_db, monkeypatch):
    """Full onboarding, driven start() -> ... -> choose_timezone(), never
    touching an interface-language or daily-words step (both real user
    requests: interface_language is auto-detected, daily_new_words is a
    fixed config default). Registers a Hebrew-detected user learning
    English via the AI placement test."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import start as start_handler

    questions = [ai_models.PlacementQuestion(level="a1", kind="word", prompt="hi")]
    _install_fake_ai(monkeypatch, questions=questions, level="b1")

    context = SimpleNamespace(user_data={})
    start_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=910, language_code="he", first_name="T", username="t"),
        message=AsyncMock(),
    )
    state = await start_handler.start(start_update, context)
    assert state == start_handler.CHOOSING_LEARNING_LANGUAGE
    assert context.user_data["interface_language"] == "he"
    # No confirmation step in between - the welcome message itself already
    # asks which language to learn.
    welcome_markup = start_update.message.reply_text.call_args[1]["reply_markup"]
    welcome_callbacks = [b.callback_data for row in welcome_markup.inline_keyboard for b in row]
    assert all(cb.startswith(start_handler.LEARNING_LANGUAGE_PREFIX) for cb in welcome_callbacks)

    await start_handler.choose_learning_language(_query(f"{start_handler.LEARNING_LANGUAGE_PREFIX}en", 910), context)
    await start_handler.choose_level(_query(start_handler.PLACEMENT_START_CALLBACK, 910), context)
    await start_handler.choose_level_placement_answer(_query(f"{start_handler.PLACEMENT_ANSWER_PREFIX}yes", 910), context)
    await start_handler.choose_goal(_query(f"{start_handler.GOAL_PREFIX}skip", 910), context)
    tz_query = _query(f"{start_handler.TIMEZONE_PREFIX}UTC", 910)
    final_state = await start_handler.choose_timezone(tz_query, context)

    from telegram.ext import ConversationHandler
    assert final_state == ConversationHandler.END

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 910)
        assert user.interface_language == "he"
        current = await user_languages_repo.get_current_language(s, user.id)
        assert current.language_code == "en"
        assert current.translation_language == "he"
        assert current.level == "b1"
        assert current.difficulty_mode == "manual"
        assert current.learning_difficulty == "b1"

        from config import get_settings
        assert user.daily_new_words == get_settings().default_daily_new_words

    complete_text = tz_query.callback_query.edit_message_text.call_args[0][0]
    assert "2" in complete_text  # mentions the 2-words-a-morning routine, not a picked daily count
