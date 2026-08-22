"""The persistent main menu keyboard (spec section 9).

settings-improvements stage: interface_language must actually change
every visible piece of the UI, including this persistent reply keyboard -
but a ReplyKeyboardMarkup button carries no callback_data, only its
literal label text, so handlers/menu.py can't just compare against a
fixed Russian string once labels start varying by language. The
constants below are locale KEYS (not display text) precisely so they
double as stable, language-independent identifiers: main_menu_keyboard()
renders each key's translation for display, and resolve_menu_action()
reverse-searches every known language's translation of every key to
recover which one a given tapped button's text corresponds to, so a
button stays recognized correctly no matter which language it was
rendered in (e.g. a stale keyboard from before a language switch).
"""
from __future__ import annotations

from telegram import ReplyKeyboardMarkup

from utils.i18n import available_languages, t

LEARN_WORDS = "menu.button.learn_words"
REVIEW = "menu.button.review"
DICTIONARY = "menu.button.dictionary"
MY_WORDS = "menu.button.my_words"
PHRASES = "menu.button.phrases"
GRAMMAR = "menu.button.grammar"
PARSE_TEXT = "menu.button.parse_text"
PROGRESS = "menu.button.progress"
SETTINGS = "menu.button.settings"
PRO = "menu.button.pro"

MAIN_MENU_LAYOUT: tuple[tuple[str, ...], ...] = (
    (LEARN_WORDS, REVIEW),
    (DICTIONARY, MY_WORDS),
    (PHRASES, GRAMMAR),
    (PARSE_TEXT, PROGRESS),
    (SETTINGS, PRO),
)

_ALL_BUTTON_KEYS: tuple[str, ...] = tuple(key for row in MAIN_MENU_LAYOUT for key in row)


def main_menu_keyboard(language: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[t(key, language) for key in row] for row in MAIN_MENU_LAYOUT],
        resize_keyboard=True,
    )


def resolve_menu_action(text: str) -> str | None:
    """Maps a tapped reply-keyboard button's literal text back to one of
    the locale-key constants above, checking every language Safabot has a
    locale file for - not just the user's current one. Returns None for
    plain free text (a dictionary search query, a text-analysis input,
    ...), which callers must treat as "not a menu button"."""
    for key in _ALL_BUTTON_KEYS:
        for language in available_languages():
            if t(key, language) == text:
                return key
    return None
