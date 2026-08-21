"""🔁 Повторить - ON-DEMAND REVIEW (repetition-system stage sections 1-7,
16-17): replaces the old due-gated "🔄 Повторить" entry point
(handlers/review.py used to call handlers.learning.show_review_intro,
which only showed anything when words were actually due). Tapping the
button now always shows the count picker immediately - selection,
scoring and the mode hand-off all reuse existing machinery:

- word selection: services.learning_service.get_words_for_on_demand_review
  (itself a thin wrapper over the same due/upcoming/new-fallback query
  every other review path uses).
- 🔤 Обычное повторение: an ephemeral context.user_data["revnow"] state,
  the same lightweight pattern 🏆 Викторина already uses (no
  LearningSession row for something this transient) - answers are scored
  through services.learning_service.record_on_demand_answer, which is
  just repetition_service.calculate_next_review + apply_review_result,
  the exact same path the normal review flow uses.
- 🏆 Викторина: handed off entirely to handlers/quiz.py's existing state
  machine via quiz_service.build_quiz(only_word_ids=...) so there is only
  ever one quiz renderer in the codebase.

Word selection is re-run (not cached in user_data) between the count-pick
and mode-pick callbacks: get_words_for_old_review is a deterministic
ORDER BY query, so re-issuing it with the same (count, mastered) a few
seconds later returns the same set - simpler than trying to pickle a list
of ORM objects across callback taps.
"""
from __future__ import annotations

import random

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from handlers import quiz as quiz_handler
from keyboards.main_menu import main_menu_keyboard
from keyboards.review_now import (
    completion_keyboard,
    count_picker_keyboard,
    empty_keyboard,
    flashcard_keyboard,
    mode_picker_keyboard,
)
from services import learning_service, quiz_service, review_now_service
from utils.i18n import get_current_language, set_current_language, t


async def _current_user_and_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


async def show_review_now_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("revnow", None)
    async with session_scope() as session:
        user, current = await _current_user_and_language(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return
        await update.message.reply_text(
            t("revnow.count_prompt", get_current_language()),
            reply_markup=count_picker_keyboard(mastered=False),
        )


def _flashcard_text(item: dict, position: int, total: int) -> str:
    lines = [t("revnow.progress", get_current_language(), current=position + 1, total=total), ""]
    lines.append(f"{item['flag']} {item['word']}".strip())
    lines.append("")
    lines.append(item["translation"])
    if item["pronunciation"]:
        lines.append("")
        lines.append(f"🔊 {item['pronunciation']}")
    if item["example"]:
        lines.append("")
        lines.append(f"💬 {item['example']}")
    return "\n".join(lines)


async def _render_flashcard(edit, state: dict) -> None:
    text = _flashcard_text(state["items"][state["position"]], state["position"], len(state["items"]))
    await edit(text, reply_markup=flashcard_keyboard())


async def _finish_flashcards(edit, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    total = len(state["items"])
    context.user_data.pop("revnow", None)
    await edit(t("revnow.completed", get_current_language(), count=total, total=total), reply_markup=completion_keyboard())


async def _launch_flashcards(edit, context: ContextTypes.DEFAULT_TYPE, words, translation_language: str) -> None:
    items = review_now_service.build_flashcard_items(words, translation_language)
    if not items:
        await edit(t("revnow.empty", get_current_language()), reply_markup=empty_keyboard())
        return
    state = {"items": items, "position": 0}
    context.user_data["revnow"] = state
    await _render_flashcard(edit, state)


async def _launch_quiz(session, edit, context: ContextTypes.DEFAULT_TYPE, user, current, words) -> None:
    questions = await quiz_service.build_quiz(
        session,
        user_id=user.id,
        language_code=current.language_code,
        translation_language=current.translation_language,
        only_word_ids=[uw.id for uw in words],
    )
    if not questions:
        await edit(t("revnow.empty", get_current_language()), reply_markup=empty_keyboard())
        return
    state = quiz_handler._new_quiz_state(current.language_code, current.translation_language, questions)
    context.user_data["quiz"] = state
    await quiz_handler._render_question(edit, state)


async def _launch(session, edit, context: ContextTypes.DEFAULT_TYPE, user, current, words, *, mode: str) -> None:
    resolved = mode if mode != "mixed" else random.choice(("flashcard", "quiz"))
    if resolved == "quiz":
        await _launch_quiz(session, edit, context, user, current, words)
    else:
        await _launch_flashcards(edit, context, words, current.translation_language)


def _parse_count_flag(text: str) -> tuple[int, bool]:
    count_str, flag_str = text.split(":")
    return int(count_str), flag_str == "1"


async def handle_review_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await query.edit_message_text(text, reply_markup=reply_markup)

    async with session_scope() as session:
        user, current = await _current_user_and_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        if data in ("revnow:menu", "revnow:menu:mastered"):
            await query.answer()
            context.user_data.pop("revnow", None)
            context.user_data.pop("quiz", None)
            mastered = data == "revnow:menu:mastered"
            key = "revnow.count_prompt_mastered" if mastered else "revnow.count_prompt"
            await edit(t(key, get_current_language()), reply_markup=count_picker_keyboard(mastered=mastered))

        elif data.startswith("revnow:count:"):
            await query.answer()
            count, mastered = _parse_count_flag(data.removeprefix("revnow:count:"))
            words = await learning_service.get_words_for_on_demand_review(
                session, user=user, user_language=current, limit=count, include_mastered=mastered,
            )
            if not words:
                await edit(t("revnow.empty", get_current_language()), reply_markup=empty_keyboard())
                return
            if user.review_mode is None:
                await edit(t("revnow.mode_prompt", get_current_language()), reply_markup=mode_picker_keyboard(count=count, mastered=mastered))
                return
            await _launch(session, edit, context, user, current, words, mode=user.review_mode)

        elif data.startswith("revnow:mode:"):
            await query.answer()
            mode_str, rest = data.removeprefix("revnow:mode:").split(":", 1)
            count, mastered = _parse_count_flag(rest)
            words = await learning_service.get_words_for_on_demand_review(
                session, user=user, user_language=current, limit=count, include_mastered=mastered,
            )
            if not words:
                await edit(t("revnow.empty", get_current_language()), reply_markup=empty_keyboard())
                return
            await _launch(session, edit, context, user, current, words, mode=mode_str)

        elif data in ("revnow:know", "revnow:dontknow"):
            await query.answer()
            state = context.user_data.get("revnow")
            if state is None:
                await edit(t("revnow.empty", get_current_language()), reply_markup=empty_keyboard())
                return
            item = state["items"][state["position"]]
            user_word = await user_words_repo.get_by_id(session, item["user_word_id"])
            if user_word is not None:
                await learning_service.record_on_demand_answer(session, user_word, correct=(data == "revnow:know"))
            state["position"] += 1
            if state["position"] >= len(state["items"]):
                await _finish_flashcards(edit, context, state)
            else:
                await _render_flashcard(edit, state)

        elif data in ("revnow:cancel", "revnow:mainmenu"):
            await query.answer()
            context.user_data.pop("revnow", None)
            context.user_data.pop("quiz", None)
            await query.message.reply_text(
                t("onboarding.main_menu_ready", get_current_language()),
                reply_markup=main_menu_keyboard(get_current_language()),
            )


review_now_callback_handler = CallbackQueryHandler(handle_review_now_callback, pattern="^revnow:")
