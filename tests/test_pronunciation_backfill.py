"""Tests for the on-demand pronunciation backfill (settings-improvements
stage section 13): services.word_service.ensure_pronunciation() and
database.repositories.words.set_pronunciation(), plus the end-to-end
handler flow that triggers it when a word card with no pronunciation
yet is actually opened.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from services import word_service


async def test_set_pronunciation_fills_both_fields_when_empty(session):
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    await session.commit()

    from database.repositories import words as words_repo

    await words_repo.set_pronunciation(session, word, pronunciation="KWY-et", phonetic="/ˈkwaɪət/")
    assert word.pronunciation == "KWY-et"
    assert word.phonetic == "/ˈkwaɪət/"


async def test_set_pronunciation_never_overwrites_existing_values(session):
    word, _ = await word_service.get_or_create_word(
        session, language_code="en", word="quiet", pronunciation="original", phonetic="/original/"
    )
    await session.commit()

    from database.repositories import words as words_repo

    await words_repo.set_pronunciation(session, word, pronunciation="new-guess", phonetic="/new/")
    assert word.pronunciation == "original"
    assert word.phonetic == "/original/"


async def test_ensure_pronunciation_is_a_noop_when_already_set(session, monkeypatch):
    """No AI call at all when there's nothing to backfill - the mock
    below would raise if it were ever reached."""
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet", pronunciation="KWY-et")
    await session.commit()

    def _boom():
        raise AssertionError("should never call the dictionary provider when pronunciation is already set")

    monkeypatch.setattr("services.dictionary_service.get_dictionary_provider", _boom)

    result = await word_service.ensure_pronunciation(session, word, translation_language="ru", user_id=1)
    assert result.pronunciation == "KWY-et"


async def test_ensure_pronunciation_gracefully_noop_when_ai_unconfigured(session):
    """Default test environment has AI forced unconfigured (conftest.py's
    autouse fixture) - ensure_pronunciation must degrade to a no-op, not
    raise or crash the card render."""
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    await session.commit()

    result = await word_service.ensure_pronunciation(session, word, translation_language="ru", user_id=1)
    assert result.pronunciation is None


async def test_ensure_pronunciation_backfills_from_a_real_ai_response(session, monkeypatch):
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return (
                '{"word": "quiet", "translations": [{"translation": "тихий", "usage_note": null}], '
                '"part_of_speech": "adjective", "phonetic": "/\\u02c8kwa\\u026a\\u0259t/", '
                '"pronunciation": "KWY-et", "definition": null, "examples": [], '
                '"difficulty": null, "category": null, "verb_forms": null}'
            )

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("services.dictionary_service.get_ai_service", lambda: live)

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    await session.commit()

    result = await word_service.ensure_pronunciation(session, word, translation_language="ru", user_id=1)
    assert result.pronunciation == "KWY-et"
    assert result.phonetic == "/ˈkwaɪət/"

    get_ai_service.cache_clear()


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
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="quiet")
        await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")

    yield word.id

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


def _mock_ai_service():
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return (
                '{"word": "quiet", "translations": [{"translation": "тихий", "usage_note": null}], '
                '"part_of_speech": "adjective", "phonetic": "/kwai-uht/", '
                '"pronunciation": "KWY-et", "definition": null, "examples": [], '
                '"difficulty": null, "category": null, "verb_forms": null}'
            )

    return LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )


async def test_opening_dictionary_card_backfills_missing_pronunciation(handler_db, monkeypatch):
    from handlers import dictionary as dictionary_handler

    monkeypatch.setattr("services.dictionary_service.get_ai_service", _mock_ai_service)

    word_id = handler_db
    q = _query(f"dict:open:{word_id}")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once()
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert "KWY-et" in text
    assert "Произношение пока недоступно" not in text


async def test_opening_my_words_card_backfills_missing_pronunciation(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from handlers import words as words_handler

    monkeypatch.setattr("services.dictionary_service.get_ai_service", _mock_ai_service)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
        uw_id = words[0].id

    q = _query(f"uw:card:{uw_id}")
    await words_handler.handle_words_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once()
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "KWY-et" in text
