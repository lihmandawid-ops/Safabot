"""Inline keyboards for word cards and dictionary search results (spec
sections 14-15). Shared by handlers/dictionary.py and handlers/words.py
("📖 Открыть карточку") so a word card looks the same everywhere.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import t

_LANG = "ru"


def search_results_keyboard(words) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{i + 1}. {w.word}", callback_data=f"dict:open:{w.id}")]
        for i, w in enumerate(words)
    ]
    return InlineKeyboardMarkup(rows)


def word_card_keyboard(word_id: int, *, back_callback: str = "dict:back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("card.button.add", _LANG), callback_data=f"card:add:{word_id}")],
            [
                InlineKeyboardButton(t("card.button.forms", _LANG), callback_data=f"card:forms:{word_id}"),
                InlineKeyboardButton(t("card.button.pronounce", _LANG), callback_data=f"card:pronounce:{word_id}"),
            ],
            [InlineKeyboardButton(t("card.button.usage", _LANG), callback_data=f"card:usage:{word_id}")],
            [InlineKeyboardButton(t("card.button.back", _LANG), callback_data=back_callback)],
        ]
    )


def resume_offer_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("dictionary.resume_yes", _LANG), callback_data=f"dict:resume:{user_word_id}")],
            [InlineKeyboardButton(t("dictionary.resume_no", _LANG), callback_data=f"dict:resume_no:{user_word_id}")],
        ]
    )
