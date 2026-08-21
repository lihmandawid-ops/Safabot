"""Inline keyboards for 🏆 Викторина (settings-improvements stage
sections 10-12)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t


def quiz_reveal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("quiz.button.reveal", get_current_language()), callback_data="quiz:reveal")]]
    )


def quiz_selfgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("quiz.button.correct", get_current_language()), callback_data="quiz:selfgrade:correct"),
                InlineKeyboardButton(t("quiz.button.wrong", get_current_language()), callback_data="quiz:selfgrade:wrong"),
            ]
        ]
    )


def quiz_choice_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(option, callback_data=f"quiz:answer:{i}") for i, option in enumerate(options)]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
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
