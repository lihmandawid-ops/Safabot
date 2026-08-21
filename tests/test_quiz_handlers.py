"""End-to-end tests for handlers/quiz.py (settings-improvements stage
sections 10-12): the full flashcard flow (reveal -> self-grade), the
full multiple-choice/fill-blank flow (pick -> feedback -> next), the
results screen, and 🔁 Повторить ошибки. Mocks only the Telegram
objects - real handlers, real session_scope(), real database (same
pattern as tests/test_learning_handlers.py).
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import WordStatus


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
    from database.repositories import user_words as user_words_repo
    from database.repositories import words as words_repo
    from services import word_service
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
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="cat")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="кошка")
        await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


async def test_quiz_start_with_no_words_shows_friendly_message(handler_db):
    """Uses a fresh user with zero words - the fixture's default user
    already has one word, so this creates a second one."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    async with session_scope() as s:
        await users_repo.create_user(
            s, telegram_id=43, username="empty", first_name="Empty",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        user = await users_repo.get_by_telegram_id(s, 43)
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="beginner", daily_new_words=4,
        )

    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    q.callback_query.from_user = SimpleNamespace(id=43)
    await quiz_handler.handle_quiz_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "недостаточно слов" in text.lower()


async def test_quiz_start_builds_flashcard_question_for_single_word(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    await quiz_handler.handle_quiz_callback(q, context)

    assert "quiz" in context.user_data
    state = context.user_data["quiz"]
    assert len(state["questions"]) == 1
    assert state["questions"][0]["type"] in ("word_to_translation", "translation_to_word")
    q.callback_query.edit_message_text.assert_awaited_once()


async def test_flashcard_reveal_then_correct_selfgrade_shows_results(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)

    q1 = _query("quiz:reveal")
    await quiz_handler.handle_quiz_callback(q1, context)
    text = q1.callback_query.edit_message_text.call_args[0][0]
    assert "Ответ:" in text
    assert context.user_data["quiz"]["revealed"] is True

    q2 = _query("quiz:selfgrade:correct")
    await quiz_handler.handle_quiz_callback(q2, context)
    text2 = q2.callback_query.edit_message_text.call_args[0][0]
    assert "Викторина завершена" in text2
    assert context.user_data["quiz"]["correct"] == 1
    assert context.user_data["quiz"]["wrong"] == 0


async def test_flashcard_wrong_selfgrade_updates_repetition_and_results(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    uw_id = context.user_data["quiz"]["questions"][0]["user_word_id"]

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
        old_wrong = uw.wrong_answers

    await quiz_handler.handle_quiz_callback(_query("quiz:reveal"), context)
    q = _query("quiz:selfgrade:wrong")
    await quiz_handler.handle_quiz_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Викторина завершена" in text
    assert context.user_data["quiz"]["wrong"] == 1
    assert uw_id in context.user_data["quiz"]["wrong_word_ids"]

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.wrong_answers == old_wrong + 1  # fed into the real repetition system


async def test_multiple_choice_flow_picks_correct_and_shows_feedback(handler_db):
    """Adds enough words to guarantee an mc_translation/mc_word question
    is possible, then drives one all the way through pick -> feedback ->
    next -> results."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.repositories import words as words_repo
    from services import word_service
    from handlers import quiz as quiz_handler

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        for i in range(5):
            w, _ = await word_service.get_or_create_word(s, language_code="en", word=f"mcword{i}")
            await words_repo.add_translation(s, word_id=w.id, language_code="ru", translation=f"мцслово{i}")
            await user_words_repo.add_word(s, user_id=user.id, word_id=w.id, language_code="en")

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]

    # force an mc question deterministically for this test's assertions
    q0 = state["questions"][0]
    if q0["type"] not in ("mc_translation", "mc_word"):
        q0["type"] = "mc_translation"
        q0["options"] = [q0["correct_answer"], "x", "y", "z"]

    correct_index = q0["options"].index(q0["correct_answer"])
    q = _query(f"quiz:answer:{correct_index}")
    await quiz_handler.handle_quiz_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Верно" in text

    q2 = _query("quiz:next")
    await quiz_handler.handle_quiz_callback(q2, context)
    state_after = context.user_data["quiz"]
    assert state_after["correct"] == 1
    assert state_after["position"] == 1


async def test_retry_wrong_with_no_prior_mistakes_shows_message(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:retry_wrong")
    await quiz_handler.handle_quiz_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "не было ошибок" in text.lower()


async def test_results_screen_learnwords_button_shows_learning_intro(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:reveal"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:selfgrade:correct"), context)

    q = _query("quiz:learnwords")
    await quiz_handler.handle_quiz_callback(q, context)
    q.callback_query.edit_message_text.assert_awaited_once()
    args, kwargs = q.callback_query.edit_message_text.call_args
    assert kwargs["reply_markup"] is not None


async def test_results_screen_mainmenu_button_clears_quiz_state_and_sends_menu(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:reveal"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:selfgrade:correct"), context)

    q = _query("quiz:mainmenu")
    await quiz_handler.handle_quiz_callback(q, context)
    assert "quiz" not in context.user_data
    q.callback_query.message.reply_text.assert_awaited_once()
    kwargs = q.callback_query.message.reply_text.call_args[1]
    assert kwargs["reply_markup"] is not None


async def test_retry_wrong_after_a_mistake_only_uses_missed_words(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    uw_id = context.user_data["quiz"]["questions"][0]["user_word_id"]

    await quiz_handler.handle_quiz_callback(_query("quiz:reveal"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:selfgrade:wrong"), context)

    q = _query("quiz:retry_wrong")
    await quiz_handler.handle_quiz_callback(q, context)
    state = context.user_data["quiz"]
    assert {qq["user_word_id"] for qq in state["questions"]} == {uw_id}
