"""Inline keyboards for 🔁 Повторить - ON-DEMAND REVIEW (repetition-
system stage sections 1-7)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t


def review_pool_keyboard() -> InlineKeyboardMarkup:
    """🔄 Повторить (bugfix stage sections 38-42): exactly two options,
    nothing else - no count question, Safabot picks how many words on its
    own (AUTO_REVIEW_COUNT in handlers/review_now.py)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.review_new", get_current_language()), callback_data="revnow:menu")],
            [InlineKeyboardButton(t("revnow.button.review_mastered", get_current_language()), callback_data="revnow:menu:mastered")],
            [InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="revnow:cancel")],
        ]
    )


def mode_picker_keyboard(*, count: int, mastered: bool) -> InlineKeyboardMarkup:
    flag = "1" if mastered else "0"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.flashcard_mode", get_current_language()), callback_data=f"revnow:mode:flashcard:{count}:{flag}")],
            [InlineKeyboardButton(t("revnow.button.quiz_mode", get_current_language()), callback_data=f"revnow:mode:quiz:{count}:{flag}")],
        ]
    )


def flashcard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("revnow.button.know", get_current_language()), callback_data="revnow:know"),
                InlineKeyboardButton(t("revnow.button.dontknow", get_current_language()), callback_data="revnow:dontknow"),
            ]
        ]
    )


def empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="revnow:mainmenu")]]
    )


def notification_keyboard(slot: str) -> InlineKeyboardMarkup:
    """🔔 Быстрое повторение (repetition-system stage sections 10, 16-17):
    both buttons reuse the on-demand review launcher
    (handlers/review_now.py's "revnow:notif:" branch), which re-reads the
    exact word list this notification was logged with
    (NotificationLog.word_ids) rather than re-selecting - so what the user
    taps into is exactly what they were shown."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.start_now", get_current_language()), callback_data=f"revnow:notif:{slot}:flashcard")],
            [InlineKeyboardButton(t("revnow.button.quiz_mode", get_current_language()), callback_data=f"revnow:notif:{slot}:quiz")],
            [InlineKeyboardButton(t("revnow.button.skip", get_current_language()), callback_data="revnow:skip")],
        ]
    )


def completion_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.again", get_current_language()), callback_data="revnow:menu")],
            [InlineKeyboardButton(t("quiz.button.start", get_current_language()), callback_data="quiz:start")],
            [InlineKeyboardButton(t("revnow.button.new_words", get_current_language()), callback_data="learn:intro")],
            [InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="revnow:mainmenu")],
        ]
    )
