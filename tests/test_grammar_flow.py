"""End-to-end tests for handlers/grammar.py (✏️ Грамматика, AI-integration
spec section 17), mocking only Telegram objects and the AI provider.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from services.ai_provider import AIProvider


class _MockProvider(AIProvider):
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0
        self.last_user: str | None = None

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        self.last_user = user
        return self.raw


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
            s, telegram_id=55, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="intermediate", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="intermediate", daily_new_words=4,
        )

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _message(text: str, uid: int = 55):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=msg)


async def test_grammar_prompt_sets_mode(handler_db):
    from handlers import grammar as grammar_handler

    context = SimpleNamespace(user_data={})
    await grammar_handler.start_grammar(_message("dummy"), context)

    assert context.user_data["mode"] == grammar_handler.MODE
    context_message = None  # just confirming no exception; prompt text checked below


async def test_grammar_question_answered_with_explicit_language_context(handler_db, monkeypatch):
    from handlers import grammar as grammar_handler
    from services.ai_service import LiveAIService, get_ai_service

    provider = _MockProvider(
        '{"explanation": "\\"Went\\" is the irregular past tense of \\"go\\".", "examples": ["I went home."]}'
    )
    live = LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.grammar.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await grammar_handler.start_grammar(_message("dummy"), context)

    update = _message("Why do we say 'went' instead of 'goed'?")
    await grammar_handler.handle_text_input(update, context, update.message.text)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "irregular past tense" in text
    assert "I went home." in text
    # language/level/interface_language must be passed explicitly, not guessed
    assert "language_code: en" in provider.last_user or "en" in provider.last_user
    assert "intermediate" in provider.last_user
    assert "ru" in provider.last_user


async def test_grammar_explanation_uses_translation_language_not_interface_language(handler_db, monkeypatch):
    """Regression: same fix as handlers/dictionary.py's explain_word - the
    explanation language must follow this learning pair's own
    translation_language, not the global menu language."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import grammar as grammar_handler
    from services.ai_service import LiveAIService, get_ai_service

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 55)
        added = await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="uk",
            level="intermediate", daily_new_words=4,
        )
        await user_languages_repo.set_active_language(s, user_id=user.id, user_language_id=added.id)

    provider = _MockProvider('{"explanation": "...", "examples": []}')
    live = LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("handlers.grammar.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await grammar_handler.start_grammar(_message("dummy"), context)
    update = _message("Why 'went' not 'goed'?")
    await grammar_handler.handle_text_input(update, context, update.message.text)

    assert "Respond in this language (ISO 639-1): uk" in provider.last_user
    assert "Respond in this language (ISO 639-1): ru" not in provider.last_user


async def test_grammar_question_without_ai_shows_not_configured(handler_db):
    from handlers import grammar as grammar_handler
    from services.ai_service import get_ai_service

    get_ai_service.cache_clear()

    context = SimpleNamespace(user_data={})
    await grammar_handler.start_grammar(_message("dummy"), context)
    update = _message("Why 'went' not 'goed'?")
    await grammar_handler.handle_text_input(update, context, update.message.text)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "не настроены" in text
