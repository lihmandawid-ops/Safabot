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


async def test_mastered_button_skips_ladder_and_moves_to_learned(handler_db):
    """AI-new-words stage sections 16-17, 35, 38: works on a due REVIEW
    item too (not just a brand-new word like learn:know:), skips the
    normal repetition ladder entirely, and never deletes the word - only
    its status changes."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers import learning as learning_handler

    learning_session = await _build_main_session()
    uw_id = learning_session.items[0].user_word_id

    context = SimpleNamespace(user_data={})
    q = _query(f"learn:mastered:{uw_id}")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.answer.assert_awaited_once()
    assert "выученные" in q.callback_query.answer.call_args[0][0]
    q.callback_query.edit_message_text.assert_awaited_once()  # shows next word or completion

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.status == WordStatus.MASTERED
    assert uw.status != WordStatus.DELETED  # §17: never deleted, only a status change


async def test_mastered_button_rejects_id_not_in_session(handler_db):
    from handlers import learning as learning_handler

    await _build_main_session()

    context = SimpleNamespace(user_data={})
    q = _query("learn:mastered:999999")
    await learning_handler.handle_learning_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
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
    # AI-new-words stage §16-17: the 4-button grading scale plus a 5th,
    # independent ✅ Слово уже выучено shortcut.
    assert len(buttons) == 5
    assert {b.callback_data for b in buttons} == {
        f"review:{uw_id}:again", f"review:{uw_id}:hard", f"review:{uw_id}:good", f"review:{uw_id}:easy",
        f"learn:mastered:{uw_id}",
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


# --- 📚 Учить слова submenu (level-and-difficulty stage, spec sections
# 10-16, 40-62): 🆕 Новые слова / 🎯 Новые слова по теме, both AI-first. ---

async def test_menu_button_shows_the_two_options(handler_db):
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:menu")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "learn:newwords" in callbacks
    assert "learn:topics" in callbacks


async def test_callback_survives_a_message_not_modified_bad_request(handler_db):
    """Bugfix: a double-tap (or any edit that happens to land on content
    identical to what's already showing) must never crash the handler and
    leave the user's button spinner stuck forever - Telegram's own
    "Message is not modified" BadRequest is swallowed by
    utils.telegram_helpers.safe_edit_message_text."""
    from telegram.error import BadRequest

    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:menu")
    q.callback_query.edit_message_text.side_effect = BadRequest("Message is not modified: specified new message content...")

    await learning_handler.handle_learning_callback(q, context)  # must not raise


async def test_newwords_without_ai_shows_the_exact_failure_message(handler_db):
    """Spec sections 40-62: on AI failure this must be shown verbatim -
    never a silent fallback to random database words."""
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:newwords")
    await learning_handler.handle_learning_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert text == "Сейчас не удалось подобрать новые слова. Попробуйте ещё раз."


async def test_newwords_with_working_ai_shows_a_summary_screen_not_yet_added(handler_db, monkeypatch):
    """study-flow-rework stage sections 2-3, 9: tapping 🆕 Получить новые
    слова must show a compact summary (word/pronunciation/translation) of
    BOTH candidates with a per-word "already know" button and ▶️ Начнём
    изучать - nothing is persisted until study actually starts."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.seed_words import seed_words
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    async with session_scope() as s:
        await seed_words(s)  # plenty of local words available - must be ignored (AI-first, never DB-first)

    class _FakeAI:
        async def generate_words(self, **kwargs):
            return ai_models.GenerateWordsResult(
                words=[ai_models.GeneratedWord(word="aiword", translations=[ai_models.TranslationResult(translation="ии-слово")])]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    q = _query("learn:newwords")
    await learning_handler.handle_learning_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "aiword" in text
    assert "ии-слово" in text
    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    # Fake AI keeps returning the same word, deduped down to exactly one
    # candidate (amount=2 requested, retries exhausted) - one "already
    # know" button for it plus ▶️ Начнём изучать.
    assert callbacks == ["learn:candidate:known:0", "learn:candidate:study"]

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert not any(uw.word.word == "aiword" for uw in words)


async def test_two_distinct_candidates_walk_through_cards_sequentially(handler_db, monkeypatch):
    """study-flow-rework stage sections 7, 9, 11: with two genuinely
    distinct candidates, ▶️ Начнём изучать persists and shows the FIRST
    card with a ➡️ Далее button (not yet the post-study menu, and the
    second word must not be persisted yet); tapping Далее persists and
    shows the SECOND (last) card with the post-study menu."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.models import WordStatus as _WordStatus
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    class _FakeAI:
        async def generate_words(self, **kwargs):
            return ai_models.GenerateWordsResult(
                words=[
                    ai_models.GeneratedWord(word="firstword", translations=[ai_models.TranslationResult(translation="первое-слово")]),
                    ai_models.GeneratedWord(word="secondword", translations=[ai_models.TranslationResult(translation="второе-слово")]),
                ]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:newwords"), context)

    q_study = _query("learn:candidate:study")
    await learning_handler.handle_learning_callback(q_study, context)

    text1 = q_study.callback_query.edit_message_text.call_args[0][0]
    assert "firstword" in text1
    assert "secondword" not in text1
    markup1 = q_study.callback_query.edit_message_text.call_args[1]["reply_markup"]
    assert [b.callback_data for row in markup1.inline_keyboard for b in row] == ["learn:candidate:next"]
    assert "new_words_candidates" in context.user_data  # not finished yet

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert any(uw.word.word == "firstword" and uw.status == _WordStatus.NEW for uw in words)
    assert not any(uw.word.word == "secondword" for uw in words)

    q_next = _query("learn:candidate:next")
    await learning_handler.handle_learning_callback(q_next, context)

    text2 = q_next.callback_query.edit_message_text.call_args[0][0]
    assert "secondword" in text2
    markup2 = q_next.callback_query.edit_message_text.call_args[1]["reply_markup"]
    assert [b.callback_data for row in markup2.inline_keyboard for b in row] == ["revnow:menu", "learn:newwords", "revnow:mainmenu"]
    assert "new_words_candidates" not in context.user_data

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert any(uw.word.word == "secondword" and uw.status == _WordStatus.NEW for uw in words)


async def test_candidate_study_persists_word_and_shows_full_card(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.models import WordStatus as _WordStatus
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    class _FakeAI:
        async def generate_words(self, **kwargs):
            return ai_models.GenerateWordsResult(
                words=[ai_models.GeneratedWord(word="aiword", translations=[ai_models.TranslationResult(translation="ии-слово")])]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:newwords"), context)

    q2 = _query("learn:candidate:study")
    await learning_handler.handle_learning_callback(q2, context)

    q2.callback_query.answer.assert_awaited_once()

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    added = [uw for uw in words if uw.word.word == "aiword"]
    assert len(added) == 1
    assert added[0].status == _WordStatus.NEW

    # Only one candidate survived the dedup, so its card is also the LAST
    # one - the post-study menu is attached directly, and the state is
    # cleared, not a "Далее" button.
    text = q2.callback_query.edit_message_text.call_args[0][0]
    assert "aiword" in text
    markup = q2.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["revnow:menu", "learn:newwords", "revnow:mainmenu"]
    assert "new_words_candidates" not in context.user_data


async def test_marking_one_of_two_known_leaves_the_other_studyable(handler_db, monkeypatch):
    """study-flow-rework stage section 10: marking ONE candidate as known
    must exclude only that one - the other must still show up in the
    summary and still be studyable via ▶️ Начнём изучать."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    class _FakeAI:
        async def generate_words(self, **kwargs):
            return ai_models.GenerateWordsResult(
                words=[
                    ai_models.GeneratedWord(word="firstword", translations=[ai_models.TranslationResult(translation="первое-слово")]),
                    ai_models.GeneratedWord(word="secondword", translations=[ai_models.TranslationResult(translation="второе-слово")]),
                ]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:newwords"), context)

    q_known = _query("learn:candidate:known:0")
    await learning_handler.handle_learning_callback(q_known, context)

    text = q_known.callback_query.edit_message_text.call_args[0][0]
    assert "firstword" not in text
    assert "secondword" in text
    markup = q_known.callback_query.edit_message_text.call_args[1]["reply_markup"]
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == [
        "learn:candidate:known:1", "learn:candidate:study",
    ]

    q_study = _query("learn:candidate:study")
    await learning_handler.handle_learning_callback(q_study, context)
    text2 = q_study.callback_query.edit_message_text.call_args[0][0]
    assert "secondword" in text2

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
    assert not any(uw.word.word == "firstword" for uw in words)
    assert any(uw.word.word == "secondword" for uw in words)


async def test_candidate_known_excludes_from_future_batches_without_adding(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import rejected_words as rejected_words_repo
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    class _FakeAI:
        async def generate_words(self, **kwargs):
            return ai_models.GenerateWordsResult(
                words=[ai_models.GeneratedWord(word="aiword", translations=[ai_models.TranslationResult(translation="ии-слово")])]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:newwords"), context)

    q2 = _query("learn:candidate:known:0")
    await learning_handler.handle_learning_callback(q2, context)

    q2.callback_query.answer.assert_awaited_once()

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        words = await user_words_repo.get_user_words(s, user_id=user.id, language_code="en")
        assert not any(uw.word.word == "aiword" for uw in words)
        rejected = await rejected_words_repo.list_words(s, user_id=user.id, language_code="en")
    assert "aiword" in rejected

    # The only candidate was just marked known - nothing left to study,
    # so this lands straight on the "all known" post-study screen.
    text = q2.callback_query.edit_message_text.call_args[0][0]
    markup = q2.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["revnow:menu", "learn:newwords", "revnow:mainmenu"]
    assert "new_words_candidates" not in context.user_data


async def test_topics_button_shows_topic_picker(handler_db):
    """Instant-generation UX stage sections 14-19: every preset topic
    button must call straight into learn:topicgen:<code> - no toggle
    (✅-prefix) state, no separate "confirm" button anywhere on screen."""
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:topics")
    await learning_handler.handle_learning_callback(q, context)

    q.callback_query.edit_message_text.assert_awaited_once()
    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert any(cb.startswith("learn:topicgen:") for cb in callbacks)
    assert "learn:topics:custom" in callbacks
    assert not any(cb.startswith("set:topics:toggle:") for cb in callbacks)


async def test_tapping_a_preset_topic_immediately_generates_words(handler_db, monkeypatch):
    """Section 15: tapping a topic must go straight to AI generation and
    show the words - no "Получить слова"/"Подтвердить" step in between."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service
    from utils.topics import PRESET_TOPICS

    captured = {}

    class _FakeAI:
        async def generate_words(self, *, category=None, **kwargs):
            captured["category"] = category
            return ai_models.GenerateWordsResult(
                words=[ai_models.GeneratedWord(word="topicword", translations=[ai_models.TranslationResult(translation="тема-слово")])]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    code = PRESET_TOPICS[0]
    context = SimpleNamespace(user_data={})
    q = _query(f"learn:topicgen:{code}")
    await learning_handler.handle_learning_callback(q, context)

    assert captured["category"] == code
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "topicword" in text
    # exactly one edit_message_text call - no intermediate confirmation screen
    assert q.callback_query.edit_message_text.call_count == 1

    # the tap also updates the profile's saved selected_topics, so the OLD
    # automatic daily-quota flow's topic hint benefits from it too.
    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
    assert current.selected_topics == [code]


async def test_tapping_a_preset_topic_with_failing_ai_shows_the_exact_failure_message(handler_db):
    from handlers import learning as learning_handler
    from utils.topics import PRESET_TOPICS

    code = PRESET_TOPICS[0]
    context = SimpleNamespace(user_data={})
    q = _query(f"learn:topicgen:{code}")
    await learning_handler.handle_learning_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert text == "Сейчас не удалось подобрать новые слова. Попробуйте ещё раз."


async def test_custom_topic_prompts_for_free_text(handler_db):
    from handlers import learning as learning_handler

    context = SimpleNamespace(user_data={})
    q = _query("learn:topics:custom")
    await learning_handler.handle_learning_callback(q, context)

    assert context.user_data["mode"] == learning_handler.MODE
    assert context.user_data["learning_submode"] == "custom_topic"
    q.callback_query.edit_message_text.assert_awaited_once()


async def test_custom_topic_free_text_immediately_generates_words(handler_db, monkeypatch):
    """Section 16/19: typing a custom topic must go straight to AI
    generation - no intermediate menu, no second confirmation tap."""
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock

    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import ai_models, word_generation_service

    captured = {}

    class _FakeAI:
        async def generate_words(self, *, category=None, **kwargs):
            captured["category"] = category
            return ai_models.GenerateWordsResult(
                words=[ai_models.GeneratedWord(word="autoword", translations=[ai_models.TranslationResult(translation="авто-слово")])]
            )

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    context = SimpleNamespace(user_data={})
    await learning_handler.handle_learning_callback(_query("learn:topics:custom"), context)

    message = AsyncMock()
    update = NS(effective_user=NS(id=42), message=message)
    await learning_handler.handle_text_input(update, context, "Слова для работы в автомастерской")

    assert captured["category"] == "Слова для работы в автомастерской"
    message.reply_text.assert_awaited_once()
    text = message.reply_text.call_args[0][0]
    assert "autoword" in text
    assert "mode" not in context.user_data
    assert "learning_submode" not in context.user_data

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
    assert current.selected_topics == ["Слова для работы в автомастерской"]


# --- 🆕 Новые слова wording: "выучить" (learn) never "повторить" (repeat)
# (instant-generation UX stage sections 12-13, 22, 24: new_words_message_
# uses_learn_not_repeat). ---

async def test_new_words_message_uses_learn_not_repeat(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import learning_service

    async def _no_due(*args, **kwargs):
        return []

    async def _some_new(*args, **kwargs):
        from services.learning_service import NewWordsResult
        return NewWordsResult(words=["placeholder"], shortfall=False)

    monkeypatch.setattr(learning_service, "get_due_reviews", _no_due)
    monkeypatch.setattr(learning_service, "get_new_words_for_today", _some_new)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        text, _ = await learning_handler._compute_intro(s, user, current, include_new_words=True)

    assert "выучить" in text
    assert "повторить" not in text


async def test_review_only_message_uses_repeat_not_learn(handler_db, monkeypatch):
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import learning_service

    async def _some_due(*args, **kwargs):
        return ["placeholder"]

    async def _no_new(*args, **kwargs):
        from services.learning_service import NewWordsResult
        return NewWordsResult(words=[], shortfall=False)

    monkeypatch.setattr(learning_service, "get_due_reviews", _some_due)
    monkeypatch.setattr(learning_service, "get_new_words_for_today", _no_new)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        text, _ = await learning_handler._compute_intro(s, user, current, include_new_words=True)

    assert "повторить" in text
    assert "выучить" not in text


async def test_mixed_new_and_due_message_says_neither_learn_nor_repeat_exclusively(handler_db, monkeypatch):
    """A batch mixing old and new words must never claim it's purely one
    or the other."""
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from handlers import learning as learning_handler
    from services import learning_service

    async def _some_due(*args, **kwargs):
        return ["placeholder"]

    async def _some_new(*args, **kwargs):
        from services.learning_service import NewWordsResult
        return NewWordsResult(words=["placeholder"], shortfall=False)

    monkeypatch.setattr(learning_service, "get_due_reviews", _some_due)
    monkeypatch.setattr(learning_service, "get_new_words_for_today", _some_new)

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 42)
        current = await user_languages_repo.get_current_language(s, user.id)
        text, _ = await learning_handler._compute_intro(s, user, current, include_new_words=True)

    assert "повторить" not in text
    assert "выучить" not in text
