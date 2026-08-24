"""End-to-end tests for the actual ➕ Добавить слово / 📖 Словарь handlers
(bugfix spec root cause #1), mocking only the Telegram objects - real
handlers, real session_scope(), real database.

Uses its own temp-file DB (like tests/test_notifications.py) because
handlers/dictionary.py opens its own session_scope() per call instead of
taking a session fixture, so it always goes through
database.database's module-level engine.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import WordSource, WordStatus


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


def _message(text: str):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=42), message=msg)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


async def _fetch_user_word(word_text: str):
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
        for uw in words:
            if uw.word.word == word_text:
                return uw
    return None


async def test_manual_add_single_word_shows_confirmation_card_with_add_button(handler_db):
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)
    assert context.user_data["mode"] == dictionary_handler.MODE
    assert context.user_data["dictionary_entry_source"] == "manual"

    update = _message("go")
    await dictionary_handler.handle_search_query(update, context, "go")

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "go" in args[0]
    assert kwargs["reply_markup"] is not None  # the ✅ Добавить card keyboard


async def test_manual_add_confirm_button_creates_user_word_with_manual_source(handler_db):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")

    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    await dictionary_handler.handle_dictionary_callback(_query(f"card:add:{word.id}"), context)

    user_word = await _fetch_user_word("go")
    assert user_word is not None
    assert user_word.status == WordStatus.NEW
    assert user_word.source == WordSource.MANUAL


async def test_dictionary_search_add_uses_dictionary_source(handler_db):
    """The 📖 Словарь entry point (no ➕ Добавить слово involved) must tag
    the same add flow with source=DICTIONARY, not MANUAL."""
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    assert context.user_data["dictionary_entry_source"] == "search"

    await dictionary_handler.handle_search_query(_message("make"), context, "make")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="make")
    await dictionary_handler.handle_dictionary_callback(_query(f"card:add:{word.id}"), context)

    user_word = await _fetch_user_word("make")
    assert user_word.source == WordSource.DICTIONARY


async def test_adding_the_same_word_twice_shows_real_status_not_generic_message(handler_db):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    await dictionary_handler.handle_dictionary_callback(_query(f"card:add:{word.id}"), context)  # first add
    second = _query(f"card:add:{word.id}")
    await dictionary_handler.handle_dictionary_callback(second, context)  # duplicate attempt

    second.callback_query.answer.assert_awaited_once()
    call_args = second.callback_query.answer.call_args
    assert "🆕" in call_args[0][0] or "Новое" in call_args[0][0]  # real status shown, not a generic message

    # still exactly one UserWord row - no duplicate created
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        rows = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert sum(1 for r in rows if r.word.word == "go") == 1


async def test_batch_add_creates_multiple_words_with_summary(handler_db):
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)

    update = _message("go, make, zzznotarealword")
    await dictionary_handler.handle_search_query(update, context, "go, make, zzznotarealword")

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "✅" in text and "❌" in text
    assert "go" in text and "make" in text and "zzznotarealword" in text

    go_uw = await _fetch_user_word("go")
    make_uw = await _fetch_user_word("make")
    assert go_uw is not None and go_uw.source == WordSource.MANUAL
    assert make_uw is not None and make_uw.source == WordSource.MANUAL


async def test_batch_add_reports_already_had_without_duplicating(handler_db):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")  # shows the card
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")
    await dictionary_handler.handle_dictionary_callback(_query(f"card:add:{word.id}"), context)  # confirm add

    update = _message("go, make")
    await dictionary_handler.handle_search_query(update, context, "go, make")
    text = update.message.reply_text.call_args[0][0]
    assert "⚠️" in text  # "already had" section present

    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        rows = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert sum(1 for r in rows if r.word.word == "go") == 1  # still just one


async def test_manual_add_of_paused_word_offers_resume(handler_db):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from handlers import words as words_handler
    from services import user_word_service

    context = SimpleNamespace(user_data={})
    await words_handler.handle_words_callback(_query("words:add"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")
    await dictionary_handler.handle_dictionary_callback(_query(f"card:add:{word.id}"), context)

    async with session_scope() as s:
        uw = await _fetch_user_word("go")
        from database.repositories import user_words as user_words_repo
        row = await user_words_repo.get_by_id(s, uw.id)
        await user_word_service.pause_word(s, row)

    q = _query(f"card:add:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)
    q.callback_query.message.reply_text.assert_awaited_once()
    _, kwargs = q.callback_query.message.reply_text.call_args
    assert kwargs["reply_markup"] is not None  # 🔄 Вернуть в повторение button


async def test_explain_word_button_without_ai_falls_back_to_local_usage_note(handler_db):
    """AI-integration spec section 28: 💡 Как использовать? must never
    break just because AI isn't configured (no AI_API_KEY in this
    fixture's environment) - it falls back to the word's own usage_note
    when one exists locally."""
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from services.ai_service import get_ai_service

    get_ai_service.cache_clear()

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    q = _query(f"card:usage:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)
    q.callback_query.message.reply_text.assert_awaited_once()
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert "go to, go on, go out" in text  # "go"'s seeded usage_note


async def test_explain_word_button_without_ai_or_usage_note_shows_not_configured(handler_db):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from services.ai_service import get_ai_service

    get_ai_service.cache_clear()

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    await dictionary_handler.handle_search_query(_message("make"), context, "make")  # no usage_note in seed data
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="make")

    q = _query(f"card:usage:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)
    q.callback_query.message.reply_text.assert_awaited_once()
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert "не настроены" in text


async def test_explain_word_button_with_ai_configured_shows_real_explanation(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return '{"explanation": "Means to move from one place to another.", "examples": ["I go home."]}'

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.dictionary.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    q = _query(f"card:usage:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)
    q.callback_query.message.reply_text.assert_awaited_once()
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert "Means to move from one place to another." in text
    assert "I go home." in text


async def test_explain_word_button_uses_translation_language_not_interface_language(handler_db, monkeypatch):
    """Regression: the explanation's response language must follow this
    learning language's own translation_language, not the global menu
    chrome language (user.interface_language) - they can differ (menus in
    Russian, translating this pair into Hebrew), and the two were
    conflated before this fix."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    captured = {}

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            captured["user_prompt"] = user
            return '{"explanation": "...", "examples": []}'

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        added = await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="he",
            level="beginner", daily_new_words=4,
        )
        await user_languages_repo.set_active_language(s, user_id=user.id, user_language_id=added.id)
        current = await user_languages_repo.get_current_language(s, user.id)
        assert current.translation_language == "he"  # interface_language stays "ru" (fixture default)

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.dictionary.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    q = _query(f"card:usage:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)

    assert "Respond in this language (ISO 639-1): he" in captured["user_prompt"]
    assert "Respond in this language (ISO 639-1): ru" not in captured["user_prompt"]


async def test_explain_word_button_truncates_a_long_ai_explanation(handler_db, monkeypatch):
    """Bugfix stage, real-Telegram feedback: 💡 Как использовать? must stay
    a short chat message, not a wall of text - the AI is asked to be
    brief, but this is the guaranteed outcome regardless of compliance."""
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import dictionary as dictionary_handler
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    long_explanation = "This word can mean many different things. " * 20  # far over 200 chars

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            import json
            return json.dumps({"explanation": long_explanation, "examples": []})

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.dictionary.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await dictionary_handler.start_search(_message("dummy"), context)
    await dictionary_handler.handle_search_query(_message("go"), context, "go")
    async with session_scope() as s:
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")

    q = _query(f"card:usage:{word.id}")
    await dictionary_handler.handle_dictionary_callback(q, context)
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert len(text) <= 200


# --- 📚 Мои слова restructure (bugfix stage sections 31-37): exactly 5
# sections, numbered, "Новые"/"Приостановлено" no longer top-level. ---

async def test_my_words_menu_shows_exactly_five_sections(handler_db):
    from handlers import words as words_handler

    update = _message("dummy")
    await words_handler.show_words_menu(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    markup = kwargs["reply_markup"]
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 5
    assert [b.callback_data for b in buttons] == [
        "words:filter:all", "words:filter:review", "words:filter:mastered", "words:search", "words:add",
    ]


async def test_my_words_menu_no_longer_offers_new_or_paused_as_top_level_filters(handler_db):
    from handlers import words as words_handler

    update = _message("dummy")
    await words_handler.show_words_menu(update, SimpleNamespace(user_data={}))
    kwargs = update.message.reply_text.call_args[1]
    callbacks = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert "words:filter:new" not in callbacks
    assert "words:filter:paused" not in callbacks


async def test_my_words_menu_buttons_have_no_numbering_prefix(handler_db):
    """AI-new-words stage section 18: plain button labels ("Все",
    "Повторение", ...) - no 1️⃣-5️⃣ emoji-digit prefix. In-list word
    numbering elsewhere is untouched by this."""
    from handlers import words as words_handler

    update = _message("dummy")
    await words_handler.show_words_menu(update, SimpleNamespace(user_data={}))
    kwargs = update.message.reply_text.call_args[1]
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert labels == ["📚 Все", "🔄 Повторение", "✅ Выученные слова", "🔎 Найти моё слово", "➕ Добавить слово для изучения"]
    assert not any(label[0].isdigit() or "️⃣" in label for label in labels)


async def test_my_words_list_backfills_translation_after_interface_language_change(handler_db, monkeypatch):
    """Real user report: "при смене языка интерфейса не меняется перевод
    ... в сохранённых словах" - a word saved while translation_language
    was "ru" must show a fresh "de" translation in the ⭐ Мои слова list
    once the user switches to translation_language "de", not silently
    fall back to the stale Russian one."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.repositories import words as words_repo
    from handlers import words as words_handler
    from services import ai_models, word_service
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="quiet")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="тихий")
        await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
        current = await user_languages_repo.get_current_language(s, user.id)
        # Simulate the user switching their interface language, which per
        # database.repositories.user_languages.set_translation_language_for_all
        # propagates translation_language onto every UserLanguage row.
        current.translation_language = "de"

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return (
                '{"word": "quiet", "translations": [{"translation": "ruhig", "usage_note": null}], '
                '"part_of_speech": "adjective", "phonetic": null, "pronunciation": null, '
                '"definition": null, "examples": [], "difficulty": null, "category": null, '
                '"verb_forms": null}'
            )

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("services.dictionary_service.get_ai_service", lambda: live)

    q = _query("words:filter:all")
    await words_handler.handle_words_callback(q, SimpleNamespace(user_data={}))

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "ruhig" in text
    assert "тихий" not in text

    get_ai_service.cache_clear()


async def test_manage_screen_from_review_section_moves_word_to_mastered(handler_db):
    """Real user feedback: in the 🔄 Повторение section, "⏸ Убрать из
    повторения" isn't a pause anymore - tapping it must move the word
    straight to выученные."""
    from database.database import session_scope
    from database.models import WordStatus
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo
    from database.repositories import words as words_repo
    from handlers import words as words_handler
    from services import word_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="testword")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="тестовое слово")
        uw = await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
        uw.status = WordStatus.REVIEW
        uw_id = uw.id

    context = SimpleNamespace(user_data={})

    filter_update = _query("words:filter:review")
    await words_handler.handle_words_callback(filter_update, context)
    assert context.user_data["words_list"]["filter"] == "review"

    manage_update = _message("1")
    await words_handler.handle_text_input(manage_update, context, "1")
    manage_markup = manage_update.message.reply_text.call_args[1]["reply_markup"]
    manage_callbacks = [b.callback_data for row in manage_markup.inline_keyboard for b in row]
    assert f"uw:mastered:{uw_id}" in manage_callbacks
    assert f"uw:pause:{uw_id}" not in manage_callbacks

    mastered_update = _query(f"uw:mastered:{uw_id}")
    await words_handler.handle_words_callback(mastered_update, context)
    assert mastered_update.callback_query.answer.call_count == 1

    async with session_scope() as s:
        uw2 = await user_words_repo.get_by_id(s, uw_id)
        assert uw2.status == WordStatus.MASTERED


async def test_manage_screen_from_all_section_hides_the_pause_button(handler_db):
    """Real user feedback: the 📚 Все section must not offer "⏸ Убрать из
    повторения" from the per-word screen at all."""
    from database.database import session_scope
    from database.models import WordStatus
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo
    from database.repositories import words as words_repo
    from handlers import words as words_handler
    from services import word_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="anotherword")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="другое слово")
        uw = await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")
        uw.status = WordStatus.REVIEW
        uw_id = uw.id

    context = SimpleNamespace(user_data={})

    filter_update = _query("words:filter:all")
    await words_handler.handle_words_callback(filter_update, context)
    assert context.user_data["words_list"]["filter"] == "all"

    number = context.user_data["words_list"]["ids"].index(uw_id) + 1
    manage_update = _message(str(number))
    await words_handler.handle_text_input(manage_update, context, str(number))
    manage_markup = manage_update.message.reply_text.call_args[1]["reply_markup"]
    manage_callbacks = [b.callback_data for row in manage_markup.inline_keyboard for b in row]
    assert f"uw:pause:{uw_id}" not in manage_callbacks
    assert f"uw:mastered:{uw_id}" not in manage_callbacks
