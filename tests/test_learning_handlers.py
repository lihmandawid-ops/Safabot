"""End-to-end tests for the actual handlers/learning.py callbacks added in
the bugfix stage (sections 8-9, 12): ➕ Ещё новые слова (amount picker +
generation), 🤔 Я это уже знаю (mark known + replace), and the post-
completion keyboard's ⭐ Мои слова shortcut. Mocks only the Telegram
objects - real handlers, real session_scope(), real database (same
pattern as tests/test_manual_add_flow.py).
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
    from database.seed_words import seed_words
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await seed_words(s)
        user = await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=2,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="beginner", daily_new_words=2,
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


async def _build_main_session():
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from services import learning_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        return await learning_service.build_learning_session(s, user=user, user_language=current)


async def test_extra_button_shows_amount_picker(handler_db):
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:extra")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    args, kwargs = q.callback_query.edit_message_text.call_args
    assert kwargs["reply_markup"] is not None


async def test_extra_amount_adds_words_and_confirms(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:extra:4")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "4" in text

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert sum(1 for w in words if w.status == WordStatus.NEW) == 4


async def test_extra_amount_reports_limit_reached(handler_db, monkeypatch):
    import config

    monkeypatch.setenv("MAX_EXTRA_WORDS_PER_DAY", "2")
    config.get_settings.cache_clear()

    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:extra:2"), context)  # uses up the cap

    q = _query("learn:extra:2")
    await learning_handler.handle_learning_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "лимит" in text.lower()

    config.get_settings.cache_clear()


async def test_know_button_masters_word_and_advances_session(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers import learning as learning_handler

    learning_session = await _build_main_session()
    assert learning_session.total_words == 2
    known_uw_id = learning_session.items[0].user_word_id

    context = SimpleNamespace(user_data={})
    q = _query(f"learn:know:{known_uw_id}")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()  # shows next word or completion, never crashes

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, known_uw_id)
    assert uw.status == WordStatus.MASTERED


async def test_know_button_rejects_id_not_in_session(handler_db):
    from handlers import learning as learning_handler

    await _build_main_session()

    context = SimpleNamespace(user_data={})
    q = _query("learn:know:999999")
    await learning_handler.handle_learning_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "session_gone" not in text  # sanity: it's the rendered ru text, not a raw key
    assert "больше не активна" in text


async def test_mywords_button_switches_mode_and_shows_filters(handler_db):
    from handlers import learning as learning_handler
    from handlers.words import MODE as WORDS_MODE

    context = SimpleNamespace(user_data={})
    q = _query("learn:mywords")
    await learning_handler.handle_learning_callback(q, context)

    assert context.user_data["mode"] == WORDS_MODE
    q.callback_query.edit_message_text.assert_awaited_once()
    kwargs = q.callback_query.edit_message_text.call_args[1]
    assert kwargs["reply_markup"] is not None


async def test_oldwords_button_shows_amount_picker(handler_db):
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:oldwords")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    args, kwargs = q.callback_query.edit_message_text.call_args
    assert kwargs["reply_markup"] is not None


async def test_oldwords_amount_builds_session_from_due_words(handler_db):
    """settings-improvements stage section 4: 🔁 Повторить старые слова
    must use the existing due/next_review_at priority - never a second
    scheduling system - and hand back exactly the count the user asked
    for when enough old words exist."""
    from datetime import timedelta

    from database.database import session_scope
    from database.models import WordStatus
    from database.repositories import sessions as sessions_repo
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import word_service
    from utils.time import utc_now

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        for i in range(6):
            word, _ = await word_service.get_or_create_word(s, language_code="en", word=f"oldw{i}")
            uw = await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
            uw.status = WordStatus.REVIEW
            uw.next_review_at = utc_now() - timedelta(hours=1)

    context = SimpleNamespace(user_data={})
    q = _query("learn:oldwords:5")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        active = await sessions_repo.get_active_session(s, user_id=user.id, language_code=current.language_code)
    assert active is not None
    assert active.total_words == 5
    assert all(not item.is_new_word for item in active.items)


async def test_oldwords_amount_with_nothing_to_review_shows_friendly_message(handler_db):
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:oldwords:5")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "старых слов" in text.lower()


async def test_dictionary_button_from_after_session_menu_switches_mode(handler_db):
    from handlers import dictionary as dictionary_handler
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:dictionary")
    await learning_handler.handle_learning_callback(q, context)

    assert context.user_data["mode"] == dictionary_handler.MODE
    q.callback_query.edit_message_text.assert_awaited_once()


async def test_new_word_reveal_shows_single_learned_button_not_rating_scale(handler_db):
    """Repetition-system-audit stage sections 7-11: a word never seen
    before must offer only a single acknowledgment - the 4-button
    difficulty scale (С трудом/Не помню/Помню/Очень легко) doesn't make
    sense before the user has ever tried to recall it."""
    from handlers import learning as learning_handler

    learning_session = await _build_main_session()
    item = sorted(learning_session.items, key=lambda i: i.position)[0]
    assert item.is_new_word is True

    context = SimpleNamespace(user_data={})
    q = _query(f"learn:reveal:{item.user_word_id}")
    await learning_handler.handle_learning_callback(q, context)

    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data == f"review:{item.user_word_id}:good"
    assert "Запомнил" in buttons[0].text
    for forbidden in ("С трудом", "Не помню", "🙂 Помню", "Очень легко"):
        assert forbidden not in buttons[0].text


async def test_review_word_reveal_still_shows_the_4_button_rating_scale(handler_db):
    """A word the user has already met before (is_new_word False) keeps
    the existing difficulty-scale behavior exactly as before."""
    from datetime import datetime

    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.models import WordStatus
    from handlers import learning as learning_handler
    from services import learning_service, word_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="duewordxyz")
        uw = await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
        uw.status = WordStatus.REVIEW
        uw.next_review_at = datetime(2020, 1, 1)
        uw_id = uw.id

    from database.repositories import user_languages as user_languages_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        learning_session = await learning_service.build_learning_session(
            s, user=user, user_language=current, include_new_words=False
        )
    item = next(i for i in learning_session.items if i.user_word_id == uw_id)
    assert item.is_new_word is False

    context = SimpleNamespace(user_data={})
    q = _query(f"learn:reveal:{uw_id}")
    await learning_handler.handle_learning_callback(q, context)

    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 4
    assert {b.callback_data for b in buttons} == {
        f"review:{uw_id}:again", f"review:{uw_id}:hard", f"review:{uw_id}:good", f"review:{uw_id}:easy",
    }


async def test_completion_screen_offers_after_session_keyboard(handler_db):
    from services.repetition_service import ReviewGrade
    from handlers import learning as learning_handler

    learning_session = await _build_main_session()
    context = SimpleNamespace(user_data={})

    for item in sorted(learning_session.items, key=lambda i: i.position):
        q = _query(f"review:{item.user_word_id}:{ReviewGrade.GOOD.value}")
        await learning_handler.handle_learning_callback(q, context)

    last_call = q.callback_query.edit_message_text.call_args
    text = last_call[0][0]
    kwargs = last_call[1]
    assert "Отлично" in text
    assert kwargs["reply_markup"] is not None
