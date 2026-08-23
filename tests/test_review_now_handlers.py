"""End-to-end tests for handlers/review_now.py (repetition-system stage
sections 1-7, 16-17): the count picker, the mode picker, the compact
flashcard flow, the quiz mode hand-off, and PAUSED/MASTERED exclusion.
Mocks only the Telegram objects - real handlers, real session_scope(),
real database (same pattern as tests/test_quiz_handlers.py).
"""
from __future__ import annotations

import os
import tempfile
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import WordStatus
from utils.time import utc_now


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
        # Not due yet - next_review_at is far in the future - so the tests
        # below prove on-demand review is independent of next_review_at
        # (spec section 1/7).
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="appointment")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="встреча")
        uw = await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
        uw.status = WordStatus.LEARNING
        uw.next_review_at = utc_now() + timedelta(days=5)

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


def _message():
    m = AsyncMock()
    return SimpleNamespace(message=m, effective_user=SimpleNamespace(id=42))


async def test_tapping_review_shows_pool_choice_never_a_count_question(handler_db):
    """bugfix stage sections 38-42: 🔄 Повторить must show exactly the two
    pool choices and NEVER ask "how many words?" - the word above isn't
    due for 5 more days, and on-demand review must still offer something
    regardless (spec section 1/7)."""
    from handlers.review_now import show_review_now_menu

    update = _message()
    await show_review_now_menu(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Сколько слов" not in args[0]
    markup = kwargs["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callbacks == ["revnow:menu", "revnow:menu:mastered", "revnow:cancel"]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert not any(label.isdigit() for label in labels)  # no bare count buttons (4/8/12/...)


async def test_review_new_words_pool_with_no_saved_mode_shows_mode_picker(handler_db):
    from handlers.review_now import handle_review_now_callback

    q = _query("revnow:menu")
    await handle_review_now_callback(q, SimpleNamespace(user_data={}))

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Как повторять" in text


async def test_flashcard_mode_renders_compact_card_with_only_mastered_and_next_buttons(handler_db):
    """study-flow-rework stage (real user feedback): the flashcard only
    offers 🏆 Уже выучено / ➡️ Далее now - no separate ✅/❌ Знаю/Не знаю
    grading step."""
    from handlers.review_now import handle_review_now_callback

    context = SimpleNamespace(user_data={})
    q = _query("revnow:mode:flashcard:4:0")
    await handle_review_now_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "1/1" in text
    assert "appointment" in text
    assert "встреча" in text
    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["revnow:mastered", "revnow:next"]


async def test_next_button_advances_without_touching_the_repetition_schedule(handler_db):
    """study-flow-rework stage (real user feedback, explicit product
    decision): ➡️ Далее is not an answer - it must never call
    learning_service.record_on_demand_answer, so repetitions/wrong_answers/
    next_review_at are all left exactly as they were."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers.review_now import handle_review_now_callback

    context = SimpleNamespace(user_data={})
    q = _query("revnow:mode:flashcard:4:0")
    await handle_review_now_callback(q, context)

    state = context.user_data["revnow"]
    uw_id = state["items"][0]["user_word_id"]
    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
        old_repetitions = uw.repetitions
        old_wrong_answers = uw.wrong_answers
        old_next_review_at = uw.next_review_at

    q2 = _query("revnow:next")
    await handle_review_now_callback(q2, context)

    final_text = q2.callback_query.edit_message_text.call_args[0][0]
    assert "Ещё один маленький шаг" in final_text  # AI-new-words stage §26: celebratory close, not "завершено"
    assert "revnow" not in context.user_data

    # §14: no path back into 📚 Учить слова from the completion screen -
    # only "start next review", quiz, and main menu.
    markup = q2.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["revnow:menu", "quiz:start", "revnow:mainmenu"]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert any("следующее повторение" in label for label in labels)

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.repetitions == old_repetitions
    assert uw.wrong_answers == old_wrong_answers
    assert uw.next_review_at == old_next_review_at


async def test_finishing_flashcard_review_updates_the_streak(handler_db):
    """study-flow-rework stage: with "📚 Учить слова" no longer routing
    through the old LearningSession-based flow (the only place that used
    to call learning_service.update_streak), completing a 🔄 Повторить
    batch must now be one of the daily-practice checkpoints that keeps the
    streak alive - otherwise the whole streak feature would silently stop
    working for every user."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from handlers.review_now import handle_review_now_callback

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        assert user.current_streak == 0
        assert user.last_learning_date is None

    context = SimpleNamespace(user_data={})
    await handle_review_now_callback(_query("revnow:mode:flashcard:4:0"), context)
    await handle_review_now_callback(_query("revnow:next"), context)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        assert user.current_streak == 1
        assert user.last_learning_date is not None


async def test_mastered_button_during_flashcard_review_skips_ladder(handler_db):
    """AI-new-words stage sections 16-17, 35, 38: ✅ Слово уже выучено
    during 🔄 Повторить jumps straight to MASTERED - never the normal
    repetition ladder record_on_demand_answer uses - and the word is never
    deleted, only its status changes."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers.review_now import handle_review_now_callback

    context = SimpleNamespace(user_data={})
    q = _query("revnow:mode:flashcard:4:0")
    await handle_review_now_callback(q, context)

    state = context.user_data["revnow"]
    uw_id = state["items"][0]["user_word_id"]

    q2 = _query("revnow:mastered")
    await handle_review_now_callback(q2, context)

    q2.callback_query.answer.assert_awaited_once()
    assert "выученные" in q2.callback_query.answer.call_args[0][0]

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.status == WordStatus.MASTERED

    final_text = q2.callback_query.edit_message_text.call_args[0][0]
    assert "Ещё один маленький шаг" in final_text
    assert "revnow" not in context.user_data


async def test_quiz_mode_hands_off_to_existing_quiz_state_machine(handler_db):
    """quiz-format stage: every quiz question now needs 4 distinct
    translation options, so this test adds 3 more translated words on top
    of the shared fixture's single "appointment" - real distractor
    material a genuine multi-word vocabulary would already have."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.repositories import words as words_repo
    from handlers.review_now import handle_review_now_callback
    from services import word_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        for i in range(3):
            w, _ = await word_service.get_or_create_word(s, language_code="en", word=f"distractor{i}")
            await words_repo.add_translation(s, word_id=w.id, language_code="ru", translation=f"дистрактор{i}")
            await user_words_repo.add_word(s, user_id=user.id, word_id=w.id, language_code="en")

    context = SimpleNamespace(user_data={})
    q = _query("revnow:mode:quiz:4:0")
    await handle_review_now_callback(q, context)

    assert "quiz" in context.user_data
    assert "revnow" not in context.user_data
    state = context.user_data["quiz"]
    assert len(state["questions"]) >= 1
    for question in state["questions"]:
        assert len(question["options"]) == 4
    q.callback_query.edit_message_text.assert_awaited_once()


async def test_paused_word_is_excluded_from_on_demand_review(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers.review_now import handle_review_now_callback

    async with session_scope() as s:
        user_words = await user_words_repo.get_user_words(s, user_id=1, language_code="en")
        for uw in user_words:
            uw.status = WordStatus.PAUSED

    q = _query("revnow:menu")
    await handle_review_now_callback(q, SimpleNamespace(user_data={}))

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "У вас пока нет слов для повторения" in text


async def test_mastered_word_excluded_by_default_but_included_via_mastered_menu(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers.review_now import handle_review_now_callback

    async with session_scope() as s:
        user_words = await user_words_repo.get_user_words(s, user_id=1, language_code="en")
        for uw in user_words:
            uw.status = WordStatus.MASTERED

    q = _query("revnow:menu")
    await handle_review_now_callback(q, SimpleNamespace(user_data={}))
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "У вас пока нет слов для повторения" in text

    q2 = _query("revnow:menu:mastered")
    await handle_review_now_callback(q2, SimpleNamespace(user_data={}))
    text2 = q2.callback_query.edit_message_text.call_args[0][0]
    assert "Как повторять" in text2


async def test_cancel_clears_state_and_returns_to_main_menu(handler_db):
    from handlers.review_now import handle_review_now_callback

    context = SimpleNamespace(user_data={"revnow": {"items": [], "position": 0}})
    q = _query("revnow:cancel")
    await handle_review_now_callback(q, context)

    assert "revnow" not in context.user_data
    q.callback_query.message.reply_text.assert_awaited_once()
