"""Inline keyboards for language selection during onboarding (section 9)
and, later, per-language settings.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.languages import SUPPORTED_LANGUAGES

INTERFACE_LANGUAGE_PREFIX = "onb:iface:"
LEARNING_LANGUAGE_PREFIX = "onb:learn:"


def _language_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{lang.flag} {lang.name_ru}", callback_data=f"{callback_prefix}{lang.code}")
        for lang in SUPPORTED_LANGUAGES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def interface_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(INTERFACE_LANGUAGE_PREFIX)


def learning_language_keyboard() -> InlineKeyboardMarkup:
    return _language_keyboard(LEARNING_LANGUAGE_PREFIX)
