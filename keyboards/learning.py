"""Keyboards for the 📚 Учить слова / 🔄 Повторить flow (learning-core
stage, sections 9-12, 35).

Rating buttons deliberately carry only a UserWord id and the grade in
callback_data (`review:<id>:<grade>`) - never the word text (spec section
3/35: keep callback_data compact, never put user-facing content there).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.repetition_service import ReviewGrade
from utils.i18n import t

_LANG = "ru"


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("learning.button.start", _LANG), callback_data="learn:start")]])


def start_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("learning.button.start", _LANG), callback_data="learn:reviewonly")]])


def continue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("learning.button.continue", _LANG), callback_data="learn:continue")]])


def reveal_keyboard(user_word_id: int, *, is_new_word: bool = False) -> InlineKeyboardMarkup:
    """"🤔 Я это уже знаю" (bugfix stage section 12) only makes sense for a
    word the user hasn't started learning yet - a due review is, by
    definition, already something they're partway through."""
    rows = [[InlineKeyboardButton(t("learning.button.reveal", _LANG), callback_data=f"learn:reveal:{user_word_id}")]]
    if is_new_word:
        rows.append([InlineKeyboardButton(t("learning.button.know", _LANG), callback_data=f"learn:know:{user_word_id}")])
    return InlineKeyboardMarkup(rows)


def after_session_keyboard() -> InlineKeyboardMarkup:
    """Shown once nothing more is due today (bugfix stage section 8/9):
    lets the user immediately ask for more new words or jump to ⭐ Мои
    слова, instead of having to go back to the plain-text main menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("learning.button.learn_more", _LANG), callback_data="learn:intro")],
            [InlineKeyboardButton(t("learning.button.extra", _LANG), callback_data="learn:extra")],
            [InlineKeyboardButton(t("learning.button.mywords", _LANG), callback_data="learn:mywords")],
        ]
    )


def extra_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("learning.button.extra_2", _LANG), callback_data="learn:extra:2"),
                InlineKeyboardButton(t("learning.button.extra_4", _LANG), callback_data="learn:extra:4"),
                InlineKeyboardButton(t("learning.button.extra_8", _LANG), callback_data="learn:extra:8"),
            ],
            [InlineKeyboardButton(t("card.button.back", _LANG), callback_data="learn:intro")],
        ]
    )


def rating_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("learning.rating.again", _LANG), callback_data=f"review:{user_word_id}:{ReviewGrade.AGAIN.value}"),
                InlineKeyboardButton(t("learning.rating.hard", _LANG), callback_data=f"review:{user_word_id}:{ReviewGrade.HARD.value}"),
            ],
            [
                InlineKeyboardButton(t("learning.rating.good", _LANG), callback_data=f"review:{user_word_id}:{ReviewGrade.GOOD.value}"),
                InlineKeyboardButton(t("learning.rating.easy", _LANG), callback_data=f"review:{user_word_id}:{ReviewGrade.EASY.value}"),
            ],
        ]
    )
