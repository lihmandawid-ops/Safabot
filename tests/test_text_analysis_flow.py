"""End-to-end tests for handlers/text_analysis.py (AI-integration spec
sections 15-16), mocking only Telegram objects and the AI provider - real
handlers, real session_scope(), real database, real UserWordService reuse.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import WordSource
from services import ai_models
from services.ai_provider import AIProvider


class _MockProvider(AIProvider):
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return self.raw


TEXT_ANALYSIS_JSON = (
    '{"original_text": "I need to schedule an appointment with my doctor tomorrow.", '
    '"translation": "Мне нужно записаться на приём к врачу завтра.", '
    '"pronunciation": "ay need too SKED-yool an uh-POYNT-ment", '
    '"key_words": ['
    '{"word": "schedule", "translation": "планировать", "part_of_speech": "verb", "pronunciation": "SKED-yool"}, '
    '{"word": "appointment", "translation": "встреча", "part_of_speech": "noun", "pronunciation": "uh-POYNT-ment"}, '
    '{"word": "doctor", "translation": "врач", "part_of_speech": "noun"}'
    '], "useful_phrases": [{"phrase": "schedule an appointment", "pronunciation": "SKED-yool an uh-POYNT-ment"}]}'
)


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
    from services import word_service
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await seed_words(s)  # "schedule"/"appointment" already in the EN seed set
        await word_service.get_or_create_word(s, language_code="en", word="doctor")
        user = await users_repo.create_user(
            s, telegram_id=77, username="grace", first_name="Grace",
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


def _message(text: str, uid: int = 77):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=msg)


def _query(data: str, uid: int = 77):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=uid)
    return SimpleNamespace(callback_query=q)


def _configure_live_ai(monkeypatch, raw_json: str):
    from services.ai_service import LiveAIService, get_ai_service

    provider = _MockProvider(raw_json)
    live = LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.text_analysis.get_ai_service", lambda: live)
    return provider


async def test_analyze_text_shows_results_with_numbered_key_words(handler_db, monkeypatch):
    from handlers import text_analysis as text_analysis_handler

    _configure_live_ai(monkeypatch, TEXT_ANALYSIS_JSON)

    context = SimpleNamespace(user_data={})
    await text_analysis_handler.start_text_analysis(_message("dummy"), context)

    update = _message("I need to schedule an appointment with my doctor tomorrow.")
    await text_analysis_handler.handle_text_input(update, context, update.message.text)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "🔊 ay need too SKED-yool an uh-POYNT-ment" in text
    assert "1. schedule (SKED-yool) — планировать" in text
    assert "2. appointment (uh-POYNT-ment) — встреча" in text
    assert "3. doctor — врач" in text  # no pronunciation from AI -> no parens, never crashes
    assert "schedule an appointment (SKED-yool an uh-POYNT-ment)" in text
    assert context.user_data["text_analysis"]["words"] == ["schedule", "appointment", "doctor"]


async def test_add_all_creates_user_words_with_ai_source(handler_db, monkeypatch):
    from handlers import text_analysis as text_analysis_handler
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo

    _configure_live_ai(monkeypatch, TEXT_ANALYSIS_JSON)

    context = SimpleNamespace(user_data={})
    await text_analysis_handler.start_text_analysis(_message("dummy"), context)
    update = _message("I need to schedule an appointment with my doctor tomorrow.")
    await text_analysis_handler.handle_text_input(update, context, update.message.text)

    await text_analysis_handler.handle_text_analysis_callback(_query("textan:add_all"), context)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 77)
        rows = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    words = {r.word.word: r.source for r in rows}
    assert words.get("schedule") == WordSource.AI
    assert words.get("appointment") == WordSource.AI
    assert words.get("doctor") == WordSource.AI
    assert "text_analysis" not in context.user_data


async def test_select_specific_words_then_add_selected(handler_db, monkeypatch):
    from handlers import text_analysis as text_analysis_handler
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo

    _configure_live_ai(monkeypatch, TEXT_ANALYSIS_JSON)

    context = SimpleNamespace(user_data={})
    await text_analysis_handler.start_text_analysis(_message("dummy"), context)
    update = _message("I need to schedule an appointment with my doctor tomorrow.")
    await text_analysis_handler.handle_text_input(update, context, update.message.text)

    selection_update = _message("1,3")
    await text_analysis_handler.handle_text_input(selection_update, context, "1,3")
    selection_update.message.reply_text.assert_awaited_once()
    assert context.user_data["text_analysis"]["selected"] == ["schedule", "doctor"]

    await text_analysis_handler.handle_text_analysis_callback(_query("textan:add_selected"), context)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 77)
        rows = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    words = {r.word.word for r in rows}
    assert words == {"schedule", "doctor"}  # "appointment" was never selected


async def test_analyze_text_uses_translation_language_not_interface_language(handler_db, monkeypatch):
    """Regression: same fix as handlers/dictionary.py's explain_word - the
    prose language must follow this learning pair's own
    translation_language, not the global menu language."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import text_analysis as text_analysis_handler
    from services.ai_service import LiveAIService, get_ai_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 77)
        added = await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="de",
            level="beginner", daily_new_words=4,
        )
        await user_languages_repo.set_active_language(s, user_id=user.id, user_language_id=added.id)

    class _CapturingProvider(AIProvider):
        def __init__(self):
            self.last_user: str | None = None

        async def complete(self, *, system: str, user: str) -> str:
            self.last_user = user
            return TEXT_ANALYSIS_JSON

    provider = _CapturingProvider()
    live = LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.text_analysis.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    update = _message("I need to schedule an appointment with my doctor tomorrow.")
    await text_analysis_handler.handle_text_input(update, context, update.message.text)

    assert "Respond in this language for any prose (ISO 639-1): de" in provider.last_user
    assert "Respond in this language for any prose (ISO 639-1): ru" not in provider.last_user


async def test_analyze_text_without_ai_configured_shows_friendly_message(handler_db):
    from handlers import text_analysis as text_analysis_handler
    from services.ai_service import get_ai_service

    get_ai_service.cache_clear()  # ensure NotConfiguredAIService (no AI_API_KEY in this fixture's env)

    context = SimpleNamespace(user_data={})
    await text_analysis_handler.start_text_analysis(_message("dummy"), context)
    update = _message("Some text.")
    await text_analysis_handler.handle_text_input(update, context, "Some text.")

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "не настроены" in text
    assert "text_analysis" not in context.user_data


async def test_analyze_text_rejects_text_over_the_length_cap(handler_db, monkeypatch):
    """AI-integration spec section 22: never send AI a huge context - a
    too-long text is rejected before any AI call is attempted."""
    import config
    from handlers import text_analysis as text_analysis_handler

    def _fail_if_called():
        raise AssertionError("AI must not be called for text over the length cap")

    monkeypatch.setattr("handlers.text_analysis.get_ai_service", _fail_if_called)

    context = SimpleNamespace(user_data={})
    await text_analysis_handler.start_text_analysis(_message("dummy"), context)

    max_length = config.get_settings().max_text_length
    too_long = "word " * (max_length // 4)
    update = _message(too_long)
    await text_analysis_handler.handle_text_input(update, context, too_long)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert str(max_length) in text
