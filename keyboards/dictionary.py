"""Inline keyboards for word cards and dictionary search results (spec
sections 14-15). Shared by handlers/dictionary.py and handlers/words.py
("📖 Открыть карточку") so a word card looks the same everywhere.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t


def search_results_keyboard(words) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{i + 1}. {w.word}", callback_data=f"dict:open:{w.id}")]
        for i, w in enumerate(words)
    ]
    return InlineKeyboardMarkup(rows)


def word_card_keyboard(word_id: int, *, back_callback: str = "dict:back") -> InlineKeyboardMarkup:
    """DeepSeek-integration spec section 6's button list - pronunciation
    used to be its own button (card:pronounce:) but is now inlined
    directly on the card text (utils.word_display.render_word_card_text),
    so that button is gone; the callback handler stays wired for any
    already-sent message that still has the old button."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("card.button.add", get_current_language()), callback_data=f"card:add:{word_id}")],
            [InlineKeyboardButton(t("card.button.usage", get_current_language()), callback_data=f"card:usage:{word_id}")],
            [InlineKeyboardButton(t("card.button.forms", get_current_language()), callback_data=f"card:forms:{word_id}")],
            [InlineKeyboardButton(t("card.button.back", get_current_language()), callback_data=back_callback)],
        ]
    )


def resume_offer_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("dictionary.resume_yes", get_current_language()), callback_data=f"dict:resume:{user_word_id}")],
            [InlineKeyboardButton(t("dictionary.resume_no", get_current_language()), callback_data=f"dict:resume_no:{user_word_id}")],
        ]
    )


def batch_resume_keyboard(paused: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """One 🔄 button per PAUSED word surfaced in a batch-add summary (bugfix
    spec: offer to resume a paused word right from the "already had it"
    section instead of making the user hunt for it in ⭐ Мои слова)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.batch_resume_button", get_current_language(), word=word), callback_data=f"dict:resume:{uw_id}")]
            for uw_id, word in paused
        ]
    )
