"""🧠 Викторина (settings-improvements stage sections 10-12; quiz-format
stage: standardized to exactly ONE format - question, exactly 4 word/
translation options, one correct - never a self-graded flashcard reveal
or a difficulty scale).

Entry point is a button on keyboards.learning.after_session_keyboard()
(quiz:start) - reached only once the user has actually finished their
daily new words/reviews, per the spec's post-session menu. There is no
separate ConversationHandler: quiz progress lives in
context.user_data["quiz"] (rebuilt fresh each "quiz:start", read/updated
by every other quiz: callback), the same pattern ⭐ Мои слова already
uses for its page cache and bulk selection - it survives a bot restart
via PicklePersistence without needing its own database table.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from handlers.learning import _compute_intro
from keyboards.learning import after_session_keyboard
from keyboards.main_menu import main_menu_keyboard
from keyboards.quiz import quiz_choice_keyboard, quiz_continue_keyboard, quiz_results_keyboard
from services import quiz_service
from utils.i18n import get_current_language, set_current_language, t
from utils.languages import LANGUAGE_BY_CODE
from utils.telegram_helpers import safe_edit_message_text


async def _current_user_and_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _new_quiz_state(language_code: str, translation_language: str, questions: list[dict]) -> dict:
    return {
        "language_code": language_code,
        "translation_language": translation_language,
        "questions": questions,
        "position": 0,
        "correct": 0,
        "wrong": 0,
        "wrong_word_ids": [],
    }


def _flag_for(language_code: str) -> str:
    lang = LANGUAGE_BY_CODE.get(language_code)
    return lang.flag if lang else ""


async def _render_question(edit, state: dict) -> None:
    q = state["questions"][state["position"]]
    total = len(state["questions"])
    title = t("quiz.title", get_current_language())
    progress = t("quiz.progress", get_current_language(), current=state["position"] + 1, total=total)
    flag = _flag_for(state["language_code"])
    text = f"{title}\n{progress}\n\n{flag} {q['word']}"
    await edit(text, reply_markup=quiz_choice_keyboard(q["options"]))


async def _render_results(edit, state: dict) -> None:
    correct = state["correct"]
    wrong = state["wrong"]
    total = correct + wrong
    accuracy = round((correct / total) * 100) if total else 0
    text = t("quiz.results", get_current_language(), correct=correct, wrong=wrong, accuracy=accuracy)
    await edit(text, reply_markup=quiz_results_keyboard(has_wrong=bool(state["wrong_word_ids"])))


async def _advance_or_finish(edit, session, state: dict) -> None:
    state["position"] += 1
    if state["position"] >= len(state["questions"]):
        await _render_results(edit, state)
    else:
        await _render_question(edit, state)


async def _grade_current(session, state: dict, *, correct: bool) -> None:
    q = state["questions"][state["position"]]
    if correct:
        state["correct"] += 1
        return
    state["wrong"] += 1
    if q["user_word_id"] not in state["wrong_word_ids"]:
        state["wrong_word_ids"].append(q["user_word_id"])
    user_word = await user_words_repo.get_by_id(session, q["user_word_id"])
    if user_word is not None:
        await quiz_service.apply_wrong_answer(session, user_word)


async def handle_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await safe_edit_message_text(query, text, reply_markup=reply_markup)

    async with session_scope() as session:
        user, current = await _current_user_and_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        if data in ("quiz:start", "quiz:retry_wrong"):
            await query.answer()
            only_ids = None
            if data == "quiz:retry_wrong":
                prior = context.user_data.get("quiz") or {}
                only_ids = prior.get("wrong_word_ids") or []
                if not only_ids:
                    await edit(t("quiz.no_mistakes", get_current_language()), reply_markup=after_session_keyboard())
                    return
            questions = await quiz_service.build_quiz(
                session,
                user_id=user.id,
                language_code=current.language_code,
                translation_language=current.translation_language,
                only_word_ids=only_ids,
            )
            if not questions:
                context.user_data.pop("quiz", None)
                await edit(t("quiz.no_words", get_current_language()), reply_markup=after_session_keyboard())
                return
            state = _new_quiz_state(current.language_code, current.translation_language, questions)
            context.user_data["quiz"] = state
            await _render_question(edit, state)

        elif data.startswith("quiz:answer:"):
            await query.answer()
            state = context.user_data.get("quiz")
            if state is None:
                await edit(t("quiz.no_words", get_current_language()), reply_markup=after_session_keyboard())
                return
            index = int(data.removeprefix("quiz:answer:"))
            q = state["questions"][state["position"]]
            chosen = q["options"][index] if 0 <= index < len(q["options"]) else None
            is_correct = chosen == q["correct_answer"]
            await _grade_current(session, state, correct=is_correct)
            if is_correct:
                feedback = t("quiz.feedback.correct", get_current_language())
            else:
                feedback = t(
                    "quiz.feedback.wrong", get_current_language(),
                    word_flag=_flag_for(state["language_code"]), word=q["word"],
                    translation_flag=_flag_for(state["translation_language"]), translation=q["correct_answer"],
                )
            if q.get("pronunciation"):
                # Global pronunciation rule section 46: only added now
                # that the answer has been graded/shown.
                feedback += "\n\n" + t("card.pronunciation_line", get_current_language(), pronunciation=q["pronunciation"])
            is_last = state["position"] + 1 >= len(state["questions"])
            await edit(feedback, reply_markup=quiz_continue_keyboard(is_last_question=is_last))

        elif data == "quiz:next":
            await query.answer()
            state = context.user_data.get("quiz")
            if state is None:
                await edit(t("quiz.no_words", get_current_language()), reply_markup=after_session_keyboard())
                return
            await _advance_or_finish(edit, session, state)

        elif data == "quiz:learnwords":
            await query.answer()
            text, keyboard = await _compute_intro(session, user, current, include_new_words=True)
            await edit(text, reply_markup=keyboard)

        elif data == "quiz:mainmenu":
            await query.answer()
            context.user_data.pop("quiz", None)
            context.user_data.pop("mode", None)
            await query.message.reply_text(
                t("onboarding.main_menu_ready", get_current_language()),
                reply_markup=main_menu_keyboard(get_current_language()),
            )


quiz_callback_handler = CallbackQueryHandler(handle_quiz_callback, pattern="^quiz:")
