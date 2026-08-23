"""Inline keyboards for 🧠 Викторина (settings-improvements stage
sections 10-12; quiz-format stage: standardized to ONE format - a
question and exactly 4 word/translation options, never a self-graded
flashcard reveal or difficulty scale)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t

_OPTION_NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")


def quiz_choice_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{_OPTION_NUMBERS[i]} {option}", callback_data=f"quiz:answer:{i}")
        for i, option in enumerate(options)
    ]
    rows = [[b] for b in buttons]
    return InlineKeyboardMarkup(rows)


def quiz_continue_keyboard(*, is_last_question: bool) -> InlineKeyboardMarkup:
    key = "quiz.button.finish" if is_last_question else "quiz.button.next"
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(key, get_current_language()), callback_data="quiz:next")]])


def quiz_results_keyboard(*, has_wrong: bool) -> InlineKeyboardMarkup:
    """Learning-methodology stage section 14: after a quiz, the next step
    is ▶️ Начать следующее повторение (revnow:menu - the same count-free
    pool-choice screen keyboards.review_now.completion_keyboard() offers
    after a regular review session, for one consistent "what's next"
    action across both) and, if needed, ⬅️ Главное меню - never
    📚 Учить слова as a required next step."""
    rows = []
    if has_wrong:
        rows.append([InlineKeyboardButton(t("quiz.button.retry_wrong", get_current_language()), callback_data="quiz:retry_wrong")])
    rows.append([InlineKeyboardButton(t("revnow.button.again", get_current_language()), callback_data="revnow:menu")])
    rows.append([InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="quiz:mainmenu")])
    return InlineKeyboardMarkup(rows)
