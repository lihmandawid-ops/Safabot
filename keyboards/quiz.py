"""Inline keyboards for 🧠 Викторина (settings-improvements stage
sections 10-12; quiz-format stage: standardized to ONE format - a
question and exactly 4 word/translation options, never a self-graded
flashcard reveal or difficulty scale)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t

_OPTION_NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")


def quiz_choice_keyboard(options: list[str], *, position: int) -> InlineKeyboardMarkup:
    """`position` (real user report: a slow-to-respond bot invites a
    second tap on the same still-visible answer button before the first
    tap's edit has landed) is embedded in callback_data so a stale second
    tap - one that arrives after handle_quiz_callback has already moved
    the quiz state past this question - can be recognized and ignored
    instead of being re-graded or crashing on state that no longer
    matches."""
    buttons = [
        InlineKeyboardButton(f"{_OPTION_NUMBERS[i]} {option}", callback_data=f"quiz:answer:{position}:{i}")
        for i, option in enumerate(options)
    ]
    rows = [[b] for b in buttons]
    return InlineKeyboardMarkup(rows)


def quiz_continue_keyboard(*, is_last_question: bool, position: int) -> InlineKeyboardMarkup:
    key = "quiz.button.finish" if is_last_question else "quiz.button.next"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(key, get_current_language()), callback_data=f"quiz:next:{position}")]]
    )


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
