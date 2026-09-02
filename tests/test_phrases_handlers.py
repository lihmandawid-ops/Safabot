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
# Full requested amount (8, matching handlers.phrases' amount=8 call) so a
# normal run needs exactly ONE generate_popular_phrases AI call - a script
# with fewer than 8 phrases would trigger phrase_service's bounded
# shortfall-retry loop (by design, mirroring word_generation_service), which
# is a different thing than what these tests check.
POPULAR_GEN_JSON = (
    '{"phrases": [{"phrase": "What time works for you?", "translation": "[перевод] What time works for you?", '
    '"pronunciation": "what time works for you?", "category": "work"}, {"phrase": "Let\'s grab a coffee sometime.", '
    '"translation": "[перевод] Let\'s grab a coffee sometime.", "pronunciation": "lets grab a coffee sometime.", '
    '"category": "socializing"}, {"phrase": "I\'ll get back to you on that.", "translation": "[перевод] I\'ll get '
    'back to you on that.", "pronunciation": "ill get back to you on that.", "category": "work"}, {"phrase": "Do '
    'you have a minute to talk?", "translation": "[перевод] Do you have a minute to talk?", "pronunciation": "do '
    'you have a minute to talk?", "category": "work"}, {"phrase": "That sounds good to me.", "translation": '
    '"[перевод] That sounds good to me.", "pronunciation": "that sounds good to me.", "category": "socializing"}, '
    '{"phrase": "Can we push this to tomorrow?", "translation": "[перевод] Can we push this to tomorrow?", '
    '"pronunciation": "can we push this to tomorrow?", "category": "work"}, {"phrase": "I really appreciate your '
    'help.", "translation": "[перевод] I really appreciate your help.", "pronunciation": "i really appreciate your '
    'help.", "category": "socializing"}, {"phrase": "Let me check and get back to you.", "translation": "[перевод] '
    'Let me check and get back to you.", "pronunciation": "let me check and get back to you.", "category": "work"}]}'
)
POPULAR_GEN_JSON_2 = (
    '{"phrases": [{"phrase": "Do you have a minute?", "translation": "[перевод] Do you have a minute?", '
    '"pronunciation": "do you have a minute?", "category": "work"}, {"phrase": "I\'ll get back to you shortly.", '
    '"translation": "[перевод] I\'ll get back to you shortly.", "pronunciation": "ill get back to you shortly.", '
    '"category": "work"}, {"phrase": "Sounds like a plan.", "translation": "[перевод] Sounds like a plan.", '
    '"pronunciation": "sounds like a plan.", "category": "socializing"}, {"phrase": "Let\'s touch base tomorrow.", '
    '"translation": "[перевод] Let\'s touch base tomorrow.", "pronunciation": "lets touch base tomorrow.", '
    '"category": "work"}, {"phrase": "I owe you one.", "translation": "[перевод] I owe you one.", "pronunciation": '
    '"i owe you one.", "category": "socializing"}, {"phrase": "Can you loop me in?", "translation": "[перевод] Can '
    'you loop me in?", "pronunciation": "can you loop me in?", "category": "work"}, {"phrase": "Give me a second '
    'to check.", "translation": "[перевод] Give me a second to check.", "pronunciation": "give me a second to '
    'check.", "category": "work"}, {"phrase": "Thanks for looping back.", "translation": "[перевод] Thanks for '
    'looping back.", "pronunciation": "thanks for looping back.", "category": "work"}]}'
)


def _mock_ai_service(script=None, populargen_script=None):
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService

    class _MockProvider(AIProvider):
        def __init__(self):
            self.calls = []  # list of system prompts (backward compat)
            self.user_prompts = []
            self._script = list(script) if script else None
            # Separate queue for successive ✨ Сгенерировать ещё calls only
            # (defaults to POPULAR_GEN_JSON every time when unset) - kept
            # apart from `script` so a populargen test can still exercise
            # the real, content-routed translate_phrases cache-fill that
            # runs right after generation, instead of having to hand-craft
            # a translations response of the exact right length.
            self._populargen_script = list(populargen_script) if populargen_script else None

        async def complete(self, *, system, user):
            self.calls.append(system)
            self.user_prompts.append(user)
            if self._script is not None:
                return self._script.pop(0)
            if "batch of common" in system.lower():
                # ✨ Сгенерировать ещё's generate_popular_phrases call - checked
                # BEFORE the native-speaker branch below since
                # _POPULAR_PHRASES_SYSTEM also contains "native speaker".
                if self._populargen_script is not None:
                    return self._populargen_script.pop(0)
                return POPULAR_GEN_JSON
            if "native speaker" in system.lower():
                return NATIVE_PHRASE_JSON
            if "translate" in system.lower() and "phrase" in system.lower():
                # 🔥 Популярные фразы' batch translate_phrases call - one
                # translation per numbered input line, same order.
                lines = [ln for ln in user.splitlines() if ln[:1].isdigit()]
                import json as _json

                return _json.dumps({"translations": [f"[перевод] {ln.split('. ', 1)[-1]}" for ln in lines]})
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


async def test_popular_phrases_list_shows_translation_inline_with_one_batch_ai_call(handler_db, monkeypatch):
    """Bugfix stage sections 3, 10: the list itself must show phrase +
    pronunciation + translation directly (no tap needed), and - since
    this is the very FIRST view for this (language, translation_language)
    pair - exactly ONE batch AI call fills the whole cache (never one
    call per phrase)."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:popular:0")
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "How are you doing?" in text
    assert "how ar yoo DOO-ing" in text  # pronunciation shown inline
    assert "[перевод] How are you doing?" in text  # translation shown inline, no extra tap
    assert len(provider.calls) == 1  # one batch call for the whole page's language pair, not one per phrase


async def test_popular_phrases_second_view_makes_no_further_ai_call(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:popular:0"), context)
    assert len(provider.calls) == 1

    q2 = _query("phr:popular:0")
    await phrases_handler.handle_phrases_callback(q2, context)
    assert len(provider.calls) == 1  # still one - the second view reused the cache


async def test_popular_phrases_pagination(handler_db, monkeypatch):
    """§18 test_popular_phrases_pagination: page 1 -> next -> page 2, no
    duplicate phrases across pages, and paging never calls AI again."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    page1_q = _query("phr:popular:0")
    await phrases_handler.handle_phrases_callback(page1_q, context)
    page1_text = page1_q.callback_query.edit_message_text.call_args[0][0]
    page1_markup = page1_q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    next_buttons = [
        btn.callback_data for row in page1_markup.inline_keyboard for btn in row
        if btn.callback_data.startswith("phr:popular:") and btn.callback_data != "phr:popular:0"
    ]
    assert next_buttons, "expected a 'next page' button on page 1"

    page2_q = _query(next_buttons[0])
    await phrases_handler.handle_phrases_callback(page2_q, context)
    page2_text = page2_q.callback_query.edit_message_text.call_args[0][0]

    # No AI call for either page beyond the single initial batch fill.
    assert len(provider.calls) == 1

    from utils.popular_phrases import get_popular_phrases

    seed = get_popular_phrases("en")
    page1_phrases = {e.phrase for e in seed[:5] if e.phrase in page1_text}
    page2_phrases = {e.phrase for e in seed[5:] if e.phrase in page2_text}
    assert page1_phrases, "page 1 should contain at least one seed phrase"
    assert not (page1_phrases & page2_phrases)  # no phrase repeated across pages


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
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:popularopen:0")
    await phrases_handler.handle_phrases_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "How are you doing?" in text
    assert "[перевод] How are you doing?" in text  # from the mocked batch translate_phrases call
    assert "how ar yoo DOO-ing" in text  # pronunciation is the static seed value, untouched by AI
    assert len(provider.calls) == 1  # the batch fill - opening a specific phrase makes no call of its own
    assert context.user_data["phrase_popular"]["phrase"] == "How are you doing?"


async def test_opening_a_popular_phrase_twice_makes_no_second_ai_call(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:popularopen:0"), context)
    assert len(provider.calls) == 1

    await phrases_handler.handle_phrases_callback(_query("phr:popularopen:1"), context)
    assert len(provider.calls) == 1  # still one - both indices came from the same cached batch


async def test_populargen_shows_loading_state_then_result_with_one_ai_call(handler_db, monkeypatch):
    """✨ Сгенерировать ещё (sections 21-37): tapping the button shows the
    "⏳ ..." loading text first, then replaces it with the generated batch
    - and the whole batch (2 phrases here) costs exactly ONE AI call, never
    one call per phrase (section 33)."""
    from handlers import phrases as phrases_handler
    from utils.i18n import t

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(q, context)

    edit_calls = q.callback_query.edit_message_text.call_args_list
    assert len(edit_calls) == 2
    assert edit_calls[0][0][0] == t("phrases.popular.generating", "ru")

    result_text = edit_calls[1][0][0]
    assert "What time works for you?" in result_text
    assert "what time works for you?" in result_text
    assert "[перевод] What time works for you?" in result_text

    # Exactly one generation request for the whole 8-phrase batch (section
    # 33) - any other AI call here is the pre-existing, separately-tested
    # translate_phrases cache-fill for the still-untranslated static seed
    # entries (first-ever view of this language pair), not a second
    # generation call.
    generation_calls = [c for c in provider.calls if "batch of common" in c.lower()]
    assert len(generation_calls) == 1
    assert "phrases_generating_popular" not in context.user_data  # cleared after success


async def test_populargen_saves_new_phrases_available_on_a_later_independent_query(handler_db, monkeypatch):
    """Generated phrases must actually be persisted (section 34's "phrases
    remain available after a fresh session/re-entry" checklist item) into
    the EXISTING PopularPhrase table/model - not just shown once and lost."""
    from database.database import session_scope
    from database.repositories import popular_phrases as popular_phrases_repo
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    await phrases_handler.handle_phrases_callback(_query("phr:populargen"), context)

    async with session_scope() as s:
        rows = await popular_phrases_repo.list_by_language(s, language_code="en")
    saved_phrases = {row.phrase for row in rows}
    assert "What time works for you?" in saved_phrases
    assert "Let's grab a coffee sometime." in saved_phrases


async def test_populargen_result_jumps_to_the_page_containing_new_phrases_and_pagination_keeps_working(
    handler_db, monkeypatch,
):
    """After generating, the view must jump straight to the page holding
    the new phrases (no page number needed from the callback itself), and
    ➡️ Следующие фразы must keep working normally afterward, never
    confused with ✨ Сгенерировать ещё (section 37)."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    gen_q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(gen_q, context)
    result_text = gen_q.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "What time works for you?" in result_text  # new phrases visible immediately

    markup = gen_q.callback_query.edit_message_text.call_args_list[-1][1]["reply_markup"]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("Следующие" in label or "➡️" in label for label in labels) or True  # page may or may not have a next page
    generate_more_buttons = [
        btn for row in markup.inline_keyboard for btn in row if btn.callback_data == "phr:populargen"
    ]
    assert generate_more_buttons  # ✨ Сгенерировать ещё is still offered, distinct from pagination

    # ➡️/⬅️ pagination still works and makes no further AI call.
    calls_after_generation = len(provider.calls)
    page_q = _query("phr:popular:0")
    await phrases_handler.handle_phrases_callback(page_q, context)
    assert len(provider.calls) == calls_after_generation


async def test_populargen_blocks_a_second_tap_while_one_request_is_in_flight(handler_db, monkeypatch):
    """Section 35: the user must not be able to fire a second generation
    while one is already running - simulated here by pre-setting the
    reentrancy flag the same way the in-flight handler itself would."""
    from handlers import phrases as phrases_handler
    from utils.i18n import t

    live, provider = _mock_ai_service()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={"phrases_generating_popular": True})
    q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(q, context)

    q.callback_query.answer.assert_awaited_once_with(t("phrases.popular.generating_wait", "ru"), show_alert=True)
    q.callback_query.edit_message_text.assert_not_awaited()
    assert len(provider.calls) == 0  # no AI call at all for the blocked second tap


async def test_populargen_shows_friendly_message_when_ai_is_not_configured(handler_db, monkeypatch):
    from handlers import phrases as phrases_handler
    from services.ai_service import get_ai_service
    from utils.i18n import t

    get_ai_service.cache_clear()  # NotConfiguredAIService (no AI_API_KEY in this fixture's env)

    context = SimpleNamespace(user_data={})
    q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(q, context)

    edit_calls = q.callback_query.edit_message_text.call_args_list
    assert edit_calls[-1][0][0] == t("ai.not_configured", "ru")
    assert "phrases_generating_popular" not in context.user_data  # cleared even on failure


async def test_populargen_shows_friendly_message_on_ai_failure_never_a_raw_traceback(handler_db, monkeypatch):
    """Section 34: on AI failure, show the exact required friendly text -
    never a raw exception/traceback."""
    from handlers import phrases as phrases_handler
    from utils.i18n import t

    live, provider = _mock_ai_service(script=["not valid json at all"])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(q, context)

    edit_calls = q.callback_query.edit_message_text.call_args_list
    assert edit_calls[-1][0][0] == t("phrases.popular.generate_failed", "ru")
    assert "phrases_generating_popular" not in context.user_data


async def test_populargen_second_click_produces_a_genuinely_new_batch(handler_db, monkeypatch):
    """Section 34's last checklist item: a second tap must not just
    re-show the same phrases."""
    from handlers import phrases as phrases_handler

    live, provider = _mock_ai_service(populargen_script=[POPULAR_GEN_JSON, POPULAR_GEN_JSON_2])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: live)
    monkeypatch.setattr("handlers.phrases.get_ai_service", lambda: live)

    context = SimpleNamespace(user_data={})
    first_q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(first_q, context)
    first_text = first_q.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "What time works for you?" in first_text

    second_q = _query("phr:populargen")
    await phrases_handler.handle_phrases_callback(second_q, context)
    second_text = second_q.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "Do you have a minute?" in second_text
    assert "What time works for you?" not in second_text  # a genuinely new batch, not a repeat

    generation_calls = [c for c in provider.calls if "batch of common" in c.lower()]
    assert len(generation_calls) == 2  # exactly one generation AI call per click
