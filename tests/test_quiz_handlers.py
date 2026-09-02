"""End-to-end tests for handlers/quiz.py (quiz-format stage: standardized
to exactly ONE format - question, exactly 4 word/translation options, one
correct - never the old flashcard reveal/self-grade flow or a difficulty
scale). Mocks only the Telegram objects - real handlers, real
session_scope(), real database (same pattern as
tests/test_learning_handlers.py).
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio


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
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        user = await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="a1", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="a1", daily_new_words=4,
        )
        # 5 words: enough for a real 4-option multiple-choice quiz.
        for i in range(5):
            word, _ = await word_service.get_or_create_word(s, language_code="en", word=f"cat{i}")
            await words_repo.add_translation(s, word_id=word.id, language_code="ru", translation=f"кошка{i}")
            await user_words_repo.add_word(s, user_id=user.id, word_id=word.id, language_code="en")

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _query(data: str):
    q = AsyncMock()
    q.data = data
    q.message = AsyncMock()
    q.from_user = SimpleNamespace(id=42)
    return SimpleNamespace(callback_query=q)


async def test_quiz_start_with_no_words_shows_friendly_message(handler_db):
    """Uses a fresh user with zero words - the fixture's default user
    already has 5 words, so this creates a second, empty one."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    async with session_scope() as s:
        await users_repo.create_user(
            s, telegram_id=43, username="empty", first_name="Empty",
            interface_language="ru", timezone="UTC", level="a1", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        user = await users_repo.get_by_telegram_id(s, 43)
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="a1", daily_new_words=4,
        )

    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    q.callback_query.from_user = SimpleNamespace(id=43)
    await quiz_handler.handle_quiz_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "недостаточно слов" in text.lower()


async def test_quiz_start_builds_a_question_with_four_options(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    await quiz_handler.handle_quiz_callback(q, context)

    assert "quiz" in context.user_data
    state = context.user_data["quiz"]
    assert len(state["questions"]) >= 1
    for question in state["questions"]:
        assert len(question["options"]) == 4
    q.callback_query.edit_message_text.assert_awaited_once()

    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 4
    assert {b.callback_data for b in buttons} == {"quiz:answer:0:0", "quiz:answer:0:1", "quiz:answer:0:2", "quiz:answer:0:3"}


async def test_quiz_question_screen_shows_the_word_never_the_flashcard_reveal_button(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    await quiz_handler.handle_quiz_callback(q, context)

    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "🧠" in text  # quiz.title

    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "quiz:reveal" not in callbacks
    assert not any(cb.startswith("quiz:selfgrade:") for cb in callbacks)


async def test_quiz_question_shows_pronunciation_but_never_the_translation(handler_db):
    """Learning-methodology stage sections 12-13: the question shows the
    word's pronunciation (matches the spec's own worked example) but must
    NEVER reveal any of the 4 options' correct translation text before
    the learner answers - only after grading does the translation appear
    (in the feedback)."""
    from database.database import session_scope
    from database.repositories import words as words_repo
    from handlers import quiz as quiz_handler

    async with session_scope() as s:
        for i in range(5):
            word = await words_repo.find_exact(s, language_code="en", normalized_word=f"cat{i}")
            await words_repo.set_pronunciation(s, word, pronunciation=f"kat-{i}", phonetic=None)

    context = SimpleNamespace(user_data={})
    q = _query("quiz:start")
    await quiz_handler.handle_quiz_callback(q, context)

    state = context.user_data["quiz"]
    question = state["questions"][state["position"]]
    text = q.callback_query.edit_message_text.call_args[0][0]

    assert question["pronunciation"] in text  # pronunciation shown alongside the word
    assert question["correct_answer"] not in text  # the answer is never pre-revealed
    assert "Что означает это слово?" in text


async def test_quiz_correct_answer_shows_correct_feedback(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    q0 = state["questions"][0]
    correct_index = q0["options"].index(q0["correct_answer"])

    q = _query(f"quiz:answer:0:{correct_index}")
    await quiz_handler.handle_quiz_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Правильно" in text
    assert context.user_data["quiz"]["correct"] == 1
    assert context.user_data["quiz"]["wrong"] == 0


async def test_quiz_wrong_answer_shows_wrong_feedback_and_updates_repetition(handler_db):
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    q0 = state["questions"][0]
    wrong_index = next(i for i, opt in enumerate(q0["options"]) if opt != q0["correct_answer"])
    uw_id = q0["user_word_id"]

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
        old_wrong = uw.wrong_answers

    q = _query(f"quiz:answer:0:{wrong_index}")
    await quiz_handler.handle_quiz_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "Неправильно" in text
    assert q0["correct_answer"] in text
    assert context.user_data["quiz"]["wrong"] == 1
    assert uw_id in context.user_data["quiz"]["wrong_word_ids"]

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.wrong_answers == old_wrong + 1  # fed into the real repetition system


async def test_double_tap_on_a_stale_answer_button_is_a_silent_no_op(handler_db):
    """Real user report: a slow response invites an impatient second tap
    on the same still-visible answer button. By the time that stale
    second tap is processed, the quiz has already moved past that
    question (position changed via quiz:next) - it must not be re-graded,
    double-count the score, or raise (which would surface as the bot's
    generic "⚠️ Что-то пошло не так" error message)."""
    from database.database import session_scope
    from database.repositories import user_words as user_words_repo
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    if len(state["questions"]) < 2:
        return  # not enough words in this run to guarantee a second question

    q0 = state["questions"][0]
    correct_index = q0["options"].index(q0["correct_answer"])
    uw_id = q0["user_word_id"]

    await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:0:{correct_index}"), context)
    await quiz_handler.handle_quiz_callback(_query("quiz:next:0"), context)
    assert context.user_data["quiz"]["position"] == 1

    # The stale second tap on question 0's (already-answered) button -
    # its own callback still carries position 0, but the quiz has moved on.
    stale = _query(f"quiz:answer:0:{correct_index}")
    await quiz_handler.handle_quiz_callback(stale, context)

    stale.callback_query.answer.assert_awaited_once()  # spinner stops on the client
    stale.callback_query.edit_message_text.assert_not_awaited()  # no re-render, no crash
    assert context.user_data["quiz"]["correct"] == 1  # not double-counted
    assert context.user_data["quiz"]["position"] == 1  # unchanged

    async with session_scope() as s:
        uw = await user_words_repo.get_by_id(s, uw_id)
    assert uw.correct_answers == 0  # a correct MC answer never writes to UserWord anyway


async def test_double_tap_on_stale_next_button_does_not_skip_a_question(handler_db):
    """Same guard, for quiz:next - a double tap on "Далее" must not
    advance the quiz twice."""
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    if len(state["questions"]) < 2:
        return

    q0 = state["questions"][0]
    correct_index = q0["options"].index(q0["correct_answer"])
    await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:0:{correct_index}"), context)

    await quiz_handler.handle_quiz_callback(_query("quiz:next:0"), context)
    assert context.user_data["quiz"]["position"] == 1

    stale_next = _query("quiz:next:0")
    await quiz_handler.handle_quiz_callback(stale_next, context)
    stale_next.callback_query.edit_message_text.assert_not_awaited()
    assert context.user_data["quiz"]["position"] == 1  # still unchanged, not skipped to 2


async def test_quiz_does_not_show_difficulty_buttons_anywhere(handler_db):
    """С трудом / Не помню / Помню / Очень легко must never appear in the
    quiz flow - that scale belongs only to the normal review flow."""
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    q0 = state["questions"][0]

    q = _query(f"quiz:answer:0:{0}")
    await quiz_handler.handle_quiz_callback(q, context)
    markup = q.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert all(not cb.startswith("review:") for cb in callbacks)
    assert callbacks == ["quiz:next:0"]


async def test_quiz_next_advances_to_the_next_question(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    if len(state["questions"]) < 2:
        return  # not enough words in this run to guarantee a second question

    q0 = state["questions"][0]
    correct_index = q0["options"].index(q0["correct_answer"])
    await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:0:{correct_index}"), context)

    q2 = _query("quiz:next:0")
    await quiz_handler.handle_quiz_callback(q2, context)
    assert context.user_data["quiz"]["position"] == 1


async def test_retry_wrong_with_no_prior_mistakes_shows_message(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    q = _query("quiz:retry_wrong")
    await quiz_handler.handle_quiz_callback(q, context)
    text = q.callback_query.edit_message_text.call_args[0][0]
    assert "не было ошибок" in text.lower()


async def test_results_screen_learnwords_button_shows_learning_intro(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    for _ in range(len(state["questions"])):
        pos = state["position"]
        q0 = state["questions"][pos]
        correct_index = q0["options"].index(q0["correct_answer"])
        await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:{pos}:{correct_index}"), context)
        await quiz_handler.handle_quiz_callback(_query(f"quiz:next:{pos}"), context)

    q = _query("quiz:learnwords")
    await quiz_handler.handle_quiz_callback(q, context)
    q.callback_query.edit_message_text.assert_awaited_once()
    args, kwargs = q.callback_query.edit_message_text.call_args
    assert kwargs["reply_markup"] is not None


async def test_results_screen_offers_next_review_never_learn_words(handler_db):
    """Learning-methodology stage section 14: after finishing a quiz, the
    next step offered is ▶️ Начать следующее повторение (revnow:menu),
    never 📚 Учить слова (quiz:learnwords/menu.button.learn_words) as a
    required next action."""
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]

    q_next = None
    for _ in range(len(state["questions"])):
        pos = state["position"]
        q0 = state["questions"][pos]
        correct_index = q0["options"].index(q0["correct_answer"])
        await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:{pos}:{correct_index}"), context)
        q_next = _query(f"quiz:next:{pos}")
        await quiz_handler.handle_quiz_callback(q_next, context)

    # The final "quiz:next" call above pushed position past the last
    # question, so it rendered the results screen - its own edit call
    # carries the results keyboard.
    markup = q_next.callback_query.edit_message_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "revnow:menu" in callbacks
    assert "quiz:learnwords" not in callbacks
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert any("следующее повторение" in label for label in labels)


async def test_results_screen_mainmenu_button_clears_quiz_state_and_sends_menu(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    for _ in range(len(state["questions"])):
        pos = state["position"]
        q0 = state["questions"][pos]
        correct_index = q0["options"].index(q0["correct_answer"])
        await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:{pos}:{correct_index}"), context)
        await quiz_handler.handle_quiz_callback(_query(f"quiz:next:{pos}"), context)

    q = _query("quiz:mainmenu")
    await quiz_handler.handle_quiz_callback(q, context)
    assert "quiz" not in context.user_data
    q.callback_query.message.reply_text.assert_awaited_once()
    kwargs = q.callback_query.message.reply_text.call_args[1]
    assert kwargs["reply_markup"] is not None


async def test_retry_wrong_after_a_mistake_only_uses_missed_words(handler_db):
    from handlers import quiz as quiz_handler

    context = SimpleNamespace(user_data={})
    await quiz_handler.handle_quiz_callback(_query("quiz:start"), context)
    state = context.user_data["quiz"]
    q0 = state["questions"][0]
    wrong_index = next(i for i, opt in enumerate(q0["options"]) if opt != q0["correct_answer"])
    uw_id = q0["user_word_id"]

    await quiz_handler.handle_quiz_callback(_query(f"quiz:answer:0:{wrong_index}"), context)

    q = _query("quiz:retry_wrong")
    await quiz_handler.handle_quiz_callback(q, context)
    retry_state = context.user_data["quiz"]
    assert {qq["user_word_id"] for qq in retry_state["questions"]} == {uw_id}
