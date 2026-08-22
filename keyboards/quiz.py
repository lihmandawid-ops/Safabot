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
    rows = []
    if has_wrong:
        rows.append([InlineKeyboardButton(t("quiz.button.retry_wrong", get_current_language()), callback_data="quiz:retry_wrong")])
    rows.append([InlineKeyboardButton(t("quiz.button.new_quiz", get_current_language()), callback_data="quiz:start")])
    rows.append([InlineKeyboardButton(t("menu.button.learn_words", get_current_language()), callback_data="quiz:learnwords")])
    rows.append([InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="quiz:mainmenu")])
    return InlineKeyboardMarkup(rows)
