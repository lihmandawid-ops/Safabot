"""End-to-end tests for handlers/phrases.py (native-speaker phrasebook
stage) covering the section-30 checklist: opening the menu, saved/
popular phrases, generating a new phrase (preset + custom situation),
saving, dedup, deleting, 📖 Разобрать + ➕ Добавить слова reusing the
existing text-analysis add-word flow, pronunciation, and confirming
DeepSeek is never called just to browse saved/popular lists. Mocks only
the Telegram objects and the AI provider - real handlers, real
session_scope(), real database (same pattern as tests/test_quiz_handlers.py).
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

NATIVE_PHRASE_JSON = (
    '{"language": "en", "phrase": "Could you give me a hand with this?", '
    '"translation": "Не мог бы ты мне с этим помочь?", "pronunciation": "kud yu giv mi a hand with this", '
    '"register": "casual", "naturalness": "native", "situation": "work", '
    '"explanation": "Natural informal phrase for asking for help.", "alternative": null}'
)
NATIVE_PHRASE_JSON_2 = NATIVE_PHRASE_JSON.replace(
    "Could you give me a hand with this?", "Can you give me a hand with this?"
)
ANALYZE_TEXT_JSON = (
    '{"original_text": "Could you give me a hand with this?", "translation": "Не мог бы ты мне с этим помочь?", '
    '"pronunciation": "kud yu giv mi a hand", '
    '"key_words": [{"word": "hand", "translation": "помощь", "part_of_speech": "noun", "pronunciation": "hand"}], '
    '"useful_phrases": []}'
)


def _mock_ai_service(script=None):
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService

    class _MockProvider(AIProvider):
        def __init__(self):
            self.calls = []  # list of system prompts (backward compat)
            self.user_prompts = []
            self._script = list(script) if script else None

        async def complete(self, *, system, user):
            self.calls.append(system)
            self.user_prompts.append(user)
            if self._script is not None:
                return self._script.pop(0)
            if "native speaker" in system.lower():
                return NATIVE_PHRASE_JSON
            return ANALYZE_TEXT_JSON

    provider = _MockProvider()
    live = LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    return live, provider


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
            s, telegram_id=42, username="grace", first_name="Grace",
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


async def test_phrases_menu_shows_the_three_options(handler_db):
    from handlers import phrases as phrases_handler

    context = SimpleNamespace(user_data={})
    update = _message("dummy")
    await phrases_handler.show_phrases_menu(update, context)

    assert context.user_data["mode"] == phrases_handler.MODE
    update.message.reply_text.assert_awaited_once()
    kwargs = update.message.reply_text.call_args[1]
    labels = [btn.text for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert any("Сохранённые" in label for label in labels)
    assert any("Новая фраза" in label for label in labels)
    assert any("Популярные" in label for label in labels)


async def test_saved_phrases_starts_empty(handler_db):
    from handlers import phrases as phrases_handler

    context = SimpleNamespace(user_data={})
    q = _query("phr:saved")
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "нет сохранённых" in text.lower() or "пока нет" in text.lower()


async def test_new_phrase_with_preset_situation_shows_generated_card(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    q = _query("phr:situation:work")
    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Could you give me a hand with this?" in text
    assert "Не мог бы ты мне с этим помочь?" in text
    assert "kud yu giv mi a hand with this" in text  # pronunciation shown (§10, §20)
    assert context.user_data["phrase_gen"]["phrase"] == "Could you give me a hand with this?"
    assert len(provider.calls) == 1  # exactly one AI call for one generation


async def test_new_phrase_never_does_literal_translation_prompting(handler_db, monkeypatch):
    """§31 native-speaker prompt sanity check at the handler level: the
    system prompt actually sent to the AI must instruct native-speaker
    generation, not a literal-translation instruction."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    q = _query("phr:situation:shopping")
    await phrases_handler.handle_phrases_callback(q, SimpleNamespace(user_data={}))

    assert "native speaker" in provider.calls[0].lower()
    assert "literal" in provider.calls[0].lower()


async def test_custom_situation_free_text_generates_a_phrase(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:situation:custom")
    await phrases_handler.handle_phrases_callback(q, context)
    assert context.user_data.get("phrases_submode") == "custom_situation"

    update = _message("Мне нужно попросить коллегу помочь мне с отчётом.")
    await phrases_handler.handle_text_input(update, context, update.message.text)

    text = update.message.reply_text.call_args[0][0]
    assert "Could you give me a hand with this?" in text
    assert "phrases_submode" not in context.user_data


async def test_save_then_appears_in_saved_list(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, _ = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)

    save_q = _query("phr:save")
    await phrases_handler.handle_phrases_callback(save_q, context)
    save_q.callback_query.answer.assert_awaited_once()
    saved_text = save_q.callback_query.edit_message_text.call_args[0][0]
    assert "Could you give me a hand with this?" in saved_text
    assert "phrase_gen" not in context.user_data

    list_q = _query("phr:saved")
    await phrases_handler.handle_phrases_callback(list_q, context)
    list_text = list_q.callback_query.edit_message_text.call_args[0][0]
    assert "Could you give me a hand with this?" in list_text


async def test_saving_the_same_phrase_twice_does_not_duplicate(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import phrases as phrases_repo
    from database.repositories import users as users_repo
    from handlers import phrases as phrases_handler

    live, _ = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    await phrases_handler.handle_phrases_callback(_query("phr:save"), context)

    # Generate + save the exact same phrase again (mock always returns the same JSON).
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    second_save = _query("phr:save")
    await phrases_handler.handle_phrases_callback(second_save, context)
    second_save.callback_query.answer.assert_awaited_with("Эта фраза уже сохранена")

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        all_saved = await phrases_repo.list_phrases(s, user_id=user.id, language_code="en")
    assert len(all_saved) == 1


async def test_delete_requires_confirmation_then_removes_it(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, _ = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    await phrases_handler.handle_phrases_callback(_query("phr:save"), context)

    list_q = _query("phr:saved")
    await phrases_handler.handle_phrases_callback(list_q, context)
    # extract the phrase id from the saved-list keyboard's first button
    markup = list_q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    open_callback = markup.inline_keyboard[0][0].callback_data
    phrase_id = int(open_callback.removeprefix("phr:open:"))

    delete_q = _query(f"phr:delete:{phrase_id}")
    await phrases_handler.handle_phrases_callback(delete_q, context)
    prompt_text = delete_q.callback_query.edit_message_text.call_args[0][0]
    assert "удалить" in prompt_text.lower()

    confirm_q = _query(f"phr:delete_confirm:{phrase_id}")
    await phrases_handler.handle_phrases_callback(confirm_q, context)
    after_text = confirm_q.callback_query.edit_message_text.call_args[0][0]
    assert "Could you give me a hand with this?" not in after_text


async def test_saved_phrase_uses_the_learning_language_not_interface_language(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import phrases as phrases_repo
    from database.repositories import users as users_repo
    from handlers import phrases as phrases_handler

    live, _ = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    await phrases_handler.handle_phrases_callback(_query("phr:save"), context)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        saved = await phrases_repo.list_phrases(s, user_id=user.id, language_code="en")
    assert saved[0].language_code == "en"  # the LEARNING language, never "ru" (interface_language)


async def test_analyze_phrase_reuses_text_analysis_add_words_flow(handler_db, monkeypatch):
    """§18-19: 📖 Разобрать / ➕ Добавить слова must reuse the existing
    UserWordService add path - not a second word-add implementation."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo
    from database.models import WordSource
    from handlers import phrases as phrases_handler
    from handlers import text_analysis as text_analysis_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.text_analysis.get_ai_service", lambda: live)

    # "hand" must resolve locally (services.dictionary_service.lookup_word
    # tries the local dictionary before ever calling AI) so add_word_batch
    # doesn't need a second, differently-shaped AI mock for the lookup.
    from database.database import session_scope
    from database.repositories import words as words_repo
    from services import word_service

    async with session_scope() as s:
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="hand")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="рука")

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)

    analyze_q = _query("phr:analyze:pending")
    await phrases_handler.handle_phrases_callback(analyze_q, context)
    assert context.user_data["mode"] == text_analysis_handler.MODE
    assert context.user_data["text_analysis"]["words"] == ["hand"]

    add_q = _query("textan:add_all")
    await text_analysis_handler.handle_text_analysis_callback(add_q, context)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert any(w.word.word == "hand" and w.source == WordSource.AI for w in words)


async def test_opening_saved_phrase_card_makes_no_ai_call(handler_db, monkeypatch):
    """§15: browsing/opening an already-saved phrase must never call
    DeepSeek - everything needed is already stored."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    await phrases_handler.handle_phrases_callback(_query("phr:save"), context)
    calls_after_save = len(provider.calls)

    list_q = _query("phr:saved")
    await phrases_handler.handle_phrases_callback(list_q, context)
    markup = list_q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    open_callback = markup.inline_keyboard[0][0].callback_data

    open_q = _query(open_callback)
    await phrases_handler.handle_phrases_callback(open_q, context)
    assert len(provider.calls) == calls_after_save  # no new AI call just to open the card


async def test_popular_phrases_list_makes_no_ai_call(handler_db, monkeypatch):
    """§16: showing the popular-phrases LIST must never call DeepSeek per
    item - only opening a specific one does."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:popular")
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "How are you doing?" in text
    assert len(provider.calls) == 0


async def test_regenerate_asks_for_a_different_phrase_excluding_the_current_one(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service(script=[NATIVE_PHRASE_JSON, NATIVE_PHRASE_JSON_2])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    assert context.user_data["phrase_gen"]["phrase"] == "Could you give me a hand with this?"

    regen_q = _query("phr:regenerate")
    await phrases_handler.handle_phrases_callback(regen_q, context)
    text = regen_q.callback_query.edit_message_text.call_args[0][0]
    assert "Can you give me a hand with this?" in text
    assert context.user_data["phrase_gen"]["phrase"] == "Can you give me a hand with this?"
    assert "Could you give me a hand with this?" in provider.user_prompts[1]  # excluded in the regenerate prompt


async def test_analyze_saved_phrase_also_reuses_text_analysis_flow(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import words as words_repo
    from services import word_service
    from handlers import phrases as phrases_handler
    from handlers import text_analysis as text_analysis_handler

    live, _ = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    async with session_scope() as s:
        word, _ = await word_service.get_or_create_word(s, language_code="en", word="hand")
        await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation="рука")

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:situation:work"), context)
    await phrases_handler.handle_phrases_callback(_query("phr:save"), context)

    list_q = _query("phr:saved")
    await phrases_handler.handle_phrases_callback(list_q, context)
    markup = list_q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    open_callback = markup.inline_keyboard[0][0].callback_data
    phrase_id = int(open_callback.removeprefix("phr:open:"))

    analyze_q = _query(f"phr:analyze:saved:{phrase_id}")
    await phrases_handler.handle_phrases_callback(analyze_q, context)
    assert context.user_data["mode"] == text_analysis_handler.MODE
    assert context.user_data["text_analysis"]["words"] == ["hand"]


async def test_opening_a_popular_phrase_fetches_its_translation(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:popularopen:0")
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "How are you doing?" in text
    assert "Не мог бы ты мне с этим помочь?" in text  # from the mocked analyze_text translation
    assert len(provider.calls) == 1
    assert context.user_data["phrase_popular"]["phrase"] == "How are you doing?"
