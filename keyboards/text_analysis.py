"""Keyboards for 📝 Разбор текста (AI-integration spec sections 15-16)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import t

_LANG = "ru"


def results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("text_analysis.add_all", _LANG), callback_data="textan:add_all")]]
    )


def selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("text_analysis.add_selected", _LANG), callback_data="textan:add_selected")],
            [InlineKeyboardButton(t("words.button.cancel", _LANG), callback_data="textan:cancel")],
        ]
    )
