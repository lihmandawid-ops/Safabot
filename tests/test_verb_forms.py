"""🔤 Все формы (repetition-system stage sections 18-25): services/
verb_forms_service.py's cache-or-generate logic, and the end-to-end
handlers/dictionary.py flow - a real, standalone message with a ✖️
Закрыть button that deletes it, never a show_alert popup again.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from services import word_service
from services.ai_errors import AIConfigurationError, AIUnavailableError


class _FakeConjugationService:
    """Stands in for AIService, counting calls so tests can assert the
    cache actually prevents a second DeepSeek request (section 24)."""

    def __init__(self, forms: dict[str, list] | None = None, *, raises: Exception | None = None) -> None:
        self.forms = forms or {
            "present": [{"form": "I go", "pronunciation": "gohh"}, {"form": "You go", "pronunciation": "gohh"}],
            "past": [{"form": "I went", "pronunciation": "wehnt"}, {"form": "You went", "pronunciation": "wehnt"}],
        }
        self.raises = raises
        self.calls = 0

    async def generate_verb_conjugation(self, word, *, language_code, translation_language, user_id):
        self.calls += 1
        self.last_translation_language = translation_language
        if self.raises is not None:
            raise self.raises
        from services import ai_models

        return ai_models.VerbConjugationResult(word=word, language=language_code, forms=self.forms)


async def test_get_or_generate_returns_cached_conjugation_without_calling_ai(session, monkeypatch):
    """A legacy flat {tense: [...]} cache (predates person_label/
    translation, so it's language-independent) is served as-is regardless
    of translation_language."""
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(
        session, language_code="en", word="go", is_verb=True, part_of_speech="verb",
        verb_conjugation={"present": ["I go"]},
    )
    await session.commit()

    def _boom():
        raise AssertionError("must not call AI when a cached conjugation already exists")

    monkeypatch.setattr("services.verb_forms_service.get_ai_service", _boom)

    result = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result == {"present": ["I go"]}


def _with_defaults(forms: dict[str, list]) -> dict[str, list]:
    return {
        tense: [{"person_label": None, "translation": None, **item} for item in items]
        for tense, items in forms.items()
    }


async def test_get_or_generate_calls_ai_and_caches_for_a_verb(session, monkeypatch):
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="go", is_verb=True, part_of_speech="verb")
    await session.commit()

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    result = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result == _with_defaults(fake.forms)
    assert word.verb_conjugation == {"ru": _with_defaults(fake.forms)}
    assert fake.calls == 1
    assert fake.last_translation_language == "ru"

    # Second call (same translation_language) must hit the now-populated
    # cache, not the AI again.
    result2 = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result2 == _with_defaults(fake.forms)
    assert fake.calls == 1


async def test_get_or_generate_regenerates_for_a_second_translation_language(session, monkeypatch):
    """Two learners with different native languages must each get their
    own person_label/translation text - the cache is scoped per
    translation_language, so a second language triggers exactly one more
    AI call, not zero (spec: never show a Russian label to a Hebrew
    native speaker) and not a lost first-language entry either."""
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="go", is_verb=True, part_of_speech="verb")
    await session.commit()

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert fake.calls == 1

    await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="he", user_id=1)
    assert fake.calls == 2
    assert set(word.verb_conjugation) == {"ru", "he"}

    # The first language's entry is still cached, untouched.
    await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert fake.calls == 2


async def test_get_or_generate_caches_per_form_pronunciation(session, monkeypatch):
    """Global pronunciation rule section 49: each cached form keeps its
    OWN pronunciation, not one shared pronunciation for the whole verb."""
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="go", is_verb=True, part_of_speech="verb")
    await session.commit()

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    result = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result["present"][0]["form"] == "I go"
    assert result["present"][0]["pronunciation"] == "gohh"
    assert result["past"][0]["form"] == "I went"
    assert result["past"][0]["pronunciation"] == "wehnt"
    assert word.verb_conjugation["ru"]["present"][0]["pronunciation"] == "gohh"


async def test_get_or_generate_returns_none_for_a_non_verb_without_calling_ai(session, monkeypatch):
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="cat", is_verb=False, part_of_speech="noun")
    await session.commit()

    def _boom():
        raise AssertionError("must not call AI for a non-verb word")

    monkeypatch.setattr("services.verb_forms_service.get_ai_service", _boom)

    result = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result is None


async def test_get_or_generate_returns_none_gracefully_on_ai_failure(session, monkeypatch):
    from services import verb_forms_service

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="go", is_verb=True, part_of_speech="verb")
    await session.commit()

    fake = _FakeConjugationService(raises=AIUnavailableError("down"))
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    result = await verb_forms_service.get_or_generate_conjugation(session, word, translation_language="ru", user_id=1)
    assert result is None
    assert word.verb_conjugation is None


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
    from database.repositories import words as words_repo
    from database.seed import seed_languages
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        user = await users_repo.get_by_telegram_id(s, 42)
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="beginner", daily_new_words=4,
        )
        verb, _ = await word_service.get_or_create_word(s, language_code="en", word="go", is_verb=True, part_of_speech="verb")
        noun, _ = await word_service.get_or_create_word(s, language_code="en", word="cat", is_verb=False, part_of_speech="noun")
        await words_repo.add_form(s, word_id=noun.id, form_type="plural", form="cats")

    yield SimpleNamespace(verb_id=verb.id, noun_id=noun.id)

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


async def test_forms_button_never_shows_a_popup_and_sends_a_real_message(handler_db, monkeypatch):
    from handlers import dictionary as dictionary_handler

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    q = _query(f"card:forms:{handler_db.verb_id}")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once_with()  # no text/show_alert - never a popup
    assert q.callback_query.message.reply_text.await_count >= 1
    args, kwargs = q.callback_query.message.reply_text.call_args_list[0]
    assert kwargs["reply_markup"] is not None
    assert "I go" in args[0]


async def test_forms_message_shows_per_form_pronunciation(handler_db, monkeypatch):
    from handlers import dictionary as dictionary_handler

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    q = _query(f"card:forms:{handler_db.verb_id}")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    text = q.callback_query.message.reply_text.call_args_list[0][0][0]
    assert "I go (gohh)" in text


async def test_forms_second_tap_uses_cache_not_a_new_ai_call(handler_db, monkeypatch):
    from handlers import dictionary as dictionary_handler

    fake = _FakeConjugationService()
    monkeypatch.setattr("services.verb_forms_service.get_ai_service", lambda: fake)

    q1 = _query(f"card:forms:{handler_db.verb_id}")
    await dictionary_handler.handle_dictionary_callback(q1, SimpleNamespace(user_data={}))
    q2 = _query(f"card:forms:{handler_db.verb_id}")
    await dictionary_handler.handle_dictionary_callback(q2, SimpleNamespace(user_data={}))

    assert fake.calls == 1


async def test_forms_close_button_deletes_the_message(handler_db):
    from handlers import dictionary as dictionary_handler

    q = _query("card:formsclose")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once()
    q.callback_query.message.delete.assert_awaited_once()


async def test_non_verb_falls_back_to_legacy_forms_as_a_real_message(handler_db):
    """AI is unconfigured in the default test environment - a non-verb
    word with existing WordForm rows must still render as a real message,
    not a popup, using the older flat forms list."""
    from handlers import dictionary as dictionary_handler

    q = _query(f"card:forms:{handler_db.noun_id}")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once_with()
    text = q.callback_query.message.reply_text.call_args[0][0]
    assert "cats" in text


async def test_verb_with_no_ai_configured_falls_back_gracefully(handler_db):
    """AI is unconfigured (default test env) and the verb has no cached
    conjugation and no legacy WordForm rows either - must still show a
    friendly real message, never crash or fall through to a popup."""
    from handlers import dictionary as dictionary_handler

    q = _query(f"card:forms:{handler_db.verb_id}")
    await dictionary_handler.handle_dictionary_callback(q, SimpleNamespace(user_data={}))

    q.callback_query.answer.assert_awaited_once_with()
    q.callback_query.message.reply_text.assert_awaited_once()
