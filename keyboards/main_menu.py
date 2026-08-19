"""The persistent main menu keyboard (spec section 9)."""
from __future__ import annotations

from telegram import ReplyKeyboardMarkup

LEARN_WORDS = "📚 Учить слова"
REVIEW = "🔄 Повторить"
DICTIONARY = "📖 Словарь"
MY_WORDS = "⭐ Мои слова"
PARSE_PHOTO = "📷 Разобрать фото"
PARSE_TEXT = "📝 Разобрать текст"
PARSE_VOICE = "🎤 Разобрать голос"
PROGRESS = "📊 Мой прогресс"
SETTINGS = "⚙️ Настройки"
PRO = "💎 PRO"

MAIN_MENU_LAYOUT: tuple[tuple[str, str], ...] = (
    (LEARN_WORDS, REVIEW),
    (DICTIONARY, MY_WORDS),
    (PARSE_PHOTO, PARSE_TEXT),
    (PARSE_VOICE, PROGRESS),
    (SETTINGS, PRO),
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [list(row) for row in MAIN_MENU_LAYOUT],
        resize_keyboard=True,
    )
