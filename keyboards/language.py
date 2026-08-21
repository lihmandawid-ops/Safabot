"""Inline keyboards for language selection during onboarding (section 5)
and, later, per-language settings.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.languages import SUPPORTED_LANGUAGES, language_display_name

INTERFACE_LANGUAGE_PREFIX = "onb:iface:"
LEARNING_LANGUAGE_PREFIX = "onb:learn:"
TRANSLATION_LANGUAGE_PREFIX = "onb:trans:"


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


def translation_language_keyboard(*, exclude_learning_language: str) -> InlineKeyboardMarkup:
    return _language_keyboard(TRANSLATION_LANGUAGE_PREFIX, exclude=exclude_learning_language)


# ⚙️ Настройки → 🌍 Мой язык → ➕ Добавить язык (bugfix stage, real-Telegram
# feedback: onboarding was the ONLY way to pick a learning language -
# Settings could only switch between languages already added). Distinct
# "set:addlang:" prefixes so these never collide with the onboarding
# ConversationHandler's own "onb:" callback data.
ADD_LANGUAGE_LEARN_PREFIX = "set:addlang:learn:"
ADD_LANGUAGE_TRANS_PREFIX = "set:addlang:trans:"


def settings_add_learning_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(ADD_LANGUAGE_LEARN_PREFIX)


def settings_add_translation_language_keyboard(*, learning_language: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            f"{lang.flag} {language_display_name(lang)}",
            callback_data=f"{ADD_LANGUAGE_TRANS_PREFIX}{learning_language}:{lang.code}",
        )
        for lang in SUPPORTED_LANGUAGES
        if lang.code != learning_language
    ]
    return InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])
