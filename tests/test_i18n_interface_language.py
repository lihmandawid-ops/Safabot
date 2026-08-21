"""Tests for the settings-improvements stage's interface_language fix
(spec section 2): the ContextVar-based per-update language context, the
persistent main-menu keyboard's language-independent button routing, and
handlers/menu.py actually switching languages end-to-end instead of
always rendering in Russian.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio


def test_set_and_get_current_language_round_trip():
    from utils.i18n import get_current_language, set_current_language

    set_current_language("en")
    assert get_current_language() == "en"
    set_current_language("ru")
    assert get_current_language() == "ru"


def test_get_current_language_defaults_when_none_passed():
    from utils.i18n import FALLBACK_LANGUAGE, get_current_language, set_current_language

    set_current_language(None)
    assert get_current_language() == FALLBACK_LANGUAGE


def test_available_languages_includes_all_8_supported_languages():
    """Repetition-system-audit stage: real bug found - only ru.json and
    en.json actually existed on disk even though SUPPORTED_LANGUAGES (and
    every onboarding/settings picker) offered all 8 languages. Picking
    e.g. Ukrainian silently fell back to Russian for every single string
    (utils.i18n.t()'s own fallback-to-FALLBACK_LANGUAGE behavior), which
    is exactly the "language doesn't propagate" symptom that was
    reported. available_languages() (used by
    keyboards.main_menu.resolve_menu_action) is the simplest signal that
    a language is actually usable, so this guards against the bug class
    recurring for any of the 8, not just Ukrainian."""
    from utils.i18n import available_languages
    from utils.languages import SUPPORTED_LANGUAGES

    langs = available_languages()
    for lang in SUPPORTED_LANGUAGES:
        assert lang.code in langs, f"locales/{lang.code}.json is missing"


def test_every_locale_file_has_the_same_keys_and_placeholders_as_russian():
    """A locale file that exists but is missing keys, or has a
    placeholder typo (e.g. {name} vs {nam}), fails silently at runtime -
    t() just falls back to Russian for that one key. Catch that at test
    time instead of in production for a language nobody on the team
    reads fluently."""
    import json
    import re

    from utils.i18n import LOCALES_DIR
    from utils.languages import SUPPORTED_LANGUAGES

    ru = json.loads((LOCALES_DIR / "ru.json").read_text(encoding="utf-8"))
    placeholder = re.compile(r"\{(\w+)\}")

    for lang in SUPPORTED_LANGUAGES:
        path = LOCALES_DIR / f"{lang.code}.json"
        assert path.exists(), f"{path} does not exist"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert set(catalog) == set(ru), f"{lang.code}.json key set differs from ru.json"
        for key, ru_value in ru.items():
            assert set(placeholder.findall(ru_value)) == set(placeholder.findall(catalog[key])), (
                f"{lang.code}.json[{key!r}] placeholders don't match ru.json"
            )


def test_ukrainian_actually_translates_not_just_falls_back_to_russian():
    from utils.i18n import t

    ru_text = t("menu.button.settings", "ru")
    uk_text = t("menu.button.settings", "uk")
    assert uk_text != ru_text
    assert uk_text == "⚙️ Налаштування"


def test_t_uses_real_english_translation_not_just_fallback():
    from utils.i18n import t

    ru_text = t("menu.button.learn_words", "ru")
    en_text = t("menu.button.learn_words", "en")
    assert ru_text != en_text
    assert en_text == "📚 Learn words"


def test_language_display_name_follows_interface_language_not_always_russian():
    """settings-improvements stage: even language NAMES (e.g. "German",
    "Немецкий") must follow interface_language - previously every screen
    hardcoded Language.name_ru regardless of who was looking at it."""
    from utils.languages import LANGUAGE_BY_CODE, language_display_name

    german = LANGUAGE_BY_CODE["de"]
    assert language_display_name(german, "ru") == "Немецкий"
    assert language_display_name(german, "en") == "German"

    from utils.i18n import set_current_language

    set_current_language("en")
    assert language_display_name(german) == "German"
    set_current_language("ru")
    assert language_display_name(german) == "Немецкий"


def test_main_menu_keyboard_renders_distinct_labels_per_language():
    from keyboards.main_menu import main_menu_keyboard

    ru_kb = main_menu_keyboard("ru")
    en_kb = main_menu_keyboard("en")

    ru_labels = [btn.text for row in ru_kb.keyboard for btn in row]
    en_labels = [btn.text for row in en_kb.keyboard for btn in row]

    assert ru_labels != en_labels
    assert "⚙️ Настройки" in ru_labels
    assert "⚙️ Settings" in en_labels


def test_resolve_menu_action_recognizes_button_in_any_known_language():
    from keyboards.main_menu import SETTINGS, resolve_menu_action

    assert resolve_menu_action("⚙️ Настройки") == SETTINGS
    assert resolve_menu_action("⚙️ Settings") == SETTINGS


def test_resolve_menu_action_returns_none_for_free_text():
    from keyboards.main_menu import resolve_menu_action

    assert resolve_menu_action("hello world") is None
    assert resolve_menu_action("apple") is None


def test_single_word_keyboard_hides_review_button_for_active_word():
    """settings-improvements stage section 3: the action row must reflect
    the word's actual status - an actively-learning word has no use for a
    redundant "add to review" button."""
    from database.models import WordStatus
    from keyboards.words import single_word_keyboard

    markup = single_word_keyboard(1, WordStatus.REVIEW)
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "uw:review:1" not in callbacks
    assert "uw:pause:1" in callbacks


def test_single_word_keyboard_hides_pause_button_for_paused_word():
    from database.models import WordStatus
    from keyboards.words import single_word_keyboard

    markup = single_word_keyboard(1, WordStatus.PAUSED)
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "uw:review:1" in callbacks
    assert "uw:pause:1" not in callbacks


def test_single_word_keyboard_offers_review_button_for_mastered_word():
    """Spec: MASTERED must be manually returnable to review from the same
    per-word action screen, not through a second, separate mechanism."""
    from database.models import WordStatus
    from keyboards.words import single_word_keyboard

    markup = single_word_keyboard(1, WordStatus.MASTERED)
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "uw:review:1" in callbacks
    assert "uw:pause:1" not in callbacks


@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

    import config
    config.get_settings.cache_clear()

    import database.database as db_module
    db_module._engine = None
    db_module._session_factory = None

    from database.database import init_models, session_scope
    from database.seed import seed_languages
    from database.repositories import users as users_repo
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await users_repo.create_user(
            s, telegram_id=77, username="hank", first_name="Hank",
            interface_language="en", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _text_update(text: str, telegram_id: int = 77):
    msg = AsyncMock()
    msg.text = text
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg)


async def test_route_main_menu_shows_settings_in_users_interface_language(handler_db):
    from handlers.menu import route_main_menu

    update = _text_update("⚙️ Settings")
    context = SimpleNamespace(user_data={})
    await route_main_menu(update, context)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Your settings" in text
    assert "Настройки" not in text
    assert "Английский" not in text  # language name must follow interface_language too


async def test_route_main_menu_unknown_command_replies_in_english(handler_db):
    from handlers.menu import route_main_menu

    update = _text_update("some gibberish text that matches nothing")
    context = SimpleNamespace(user_data={})
    await route_main_menu(update, context)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert text == "I don't understand that command. Use the menu below."


async def test_route_main_menu_coming_soon_uses_interface_language(handler_db):
    from handlers.menu import route_main_menu

    update = _text_update("📊 My progress")
    context = SimpleNamespace(user_data={})
    await route_main_menu(update, context)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "My progress" in text
    assert "still in development" in text


async def test_route_main_menu_recognizes_button_regardless_of_stale_keyboard_language(handler_db):
    """A user who just switched interface language may still be looking at
    an old-language keyboard for one tap; resolve_menu_action must still
    route it correctly (spec section 2)."""
    from handlers.menu import route_main_menu

    update = _text_update("📊 Мой прогресс")  # Russian label, but user.interface_language == "en"
    context = SimpleNamespace(user_data={})
    await route_main_menu(update, context)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "My progress" in text
