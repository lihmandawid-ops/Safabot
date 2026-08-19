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


def reveal_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("learning.button.reveal", _LANG), callback_data=f"learn:reveal:{user_word_id}")]]
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
