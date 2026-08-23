"""Inline keyboards for language selection during onboarding (section 5)
and, later, per-language settings.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.languages import SUPPORTED_LANGUAGES, language_display_name

INTERFACE_LANGUAGE_PREFIX = "onb:iface:"
LEARNING_LANGUAGE_PREFIX = "onb:learn:"


def _language_keyboard(callback_prefix: str, *, exclude: str | None = None) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{lang.flag} {language_display_name(lang)}", callback_data=f"{callback_prefix}{lang.code}")
        for lang in SUPPORTED_LANGUAGES
        if lang.code != exclude
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def interface_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(INTERFACE_LANGUAGE_PREFIX)


def learning_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(LEARNING_LANGUAGE_PREFIX)


# ⚙️ Настройки → 🌍 Мой язык → ➕ Добавить язык (bugfix stage, real-Telegram
# feedback: onboarding was the ONLY way to pick a learning language -
# Settings could only switch between languages already added). Distinct
# "set:addlang:" prefix so this never collides with the onboarding
# ConversationHandler's own "onb:" callback data. study-flow-rework stage
# sections 4-6: there is no separate translation-language step anymore -
# translation_language always equals the user's interface_language.
ADD_LANGUAGE_LEARN_PREFIX = "set:addlang:learn:"


def settings_add_learning_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(ADD_LANGUAGE_LEARN_PREFIX)
