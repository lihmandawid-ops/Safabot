"""Telegram language_code auto-detection at /start (repetition-system-
audit stage sections 1-2; real user request): real bug found - the very
first onboarding message always rendered in a hardcoded "ru", regardless
of the Telegram user's own language_code, so e.g. a Hebrew-speaking
user's first message was in Russian. _detect_interface_language() is now
the DEFINITIVE interface_language (and, by extension,
translation_language, which always equals it) - never a separate
onboarding question the learner confirms via buttons the way it used to
be; they can still change it later via ⚙️ Настройки.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from handlers.start import _detect_interface_language


def _telegram_user(language_code):
    return SimpleNamespace(id=1, language_code=language_code, first_name="T")


def test_detect_exact_supported_code():
    assert _detect_interface_language(_telegram_user("he")) == "he"
    assert _detect_interface_language(_telegram_user("uk")) == "uk"
    assert _detect_interface_language(_telegram_user("ru")) == "ru"


def test_detect_strips_bcp47_region_subtag():
    assert _detect_interface_language(_telegram_user("en-US")) == "en"
    assert _detect_interface_language(_telegram_user("pt-BR")) == "en"  # pt unsupported -> fallback


def test_detect_is_case_insensitive():
    assert _detect_interface_language(_telegram_user("RU")) == "ru"
    assert _detect_interface_language(_telegram_user("He")) == "he"


def test_detect_falls_back_to_english_for_unsupported_or_missing_code():
    assert _detect_interface_language(_telegram_user("pt")) == "en"
    assert _detect_interface_language(_telegram_user(None)) == "en"
    assert _detect_interface_language(_telegram_user("")) == "en"


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

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _start_update(telegram_id: int, language_code: str | None):
    message = AsyncMock()
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=telegram_id, language_code=language_code, first_name="T"),
        message=message,
    )


async def test_brand_new_hebrew_user_gets_a_hebrew_welcome_message(handler_db):
    from handlers.start import start

    update = _start_update(9001, "he")
    await start(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "ברוך הבא" in text
    assert "Добро пожаловать" not in text


async def test_brand_new_user_with_unsupported_language_code_gets_english(handler_db):
    from handlers.start import start

    update = _start_update(9002, "pt-BR")
    await start(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Welcome to Safabot" in text
    assert "Добро пожаловать" not in text


async def test_welcome_keyboard_labels_also_follow_the_detected_language(handler_db):
    """Not just the message text - the learning-language keyboard's own
    button labels (language names) must match too, since they're built
    from utils.i18n.get_current_language() right after start() sets it -
    the very first screen a German-detected user sees is now "which
    language do you want to learn", not a redundant interface-language
    confirmation, but its German-language option must still read
    "Deutsch" either way."""
    from handlers.start import start

    update = _start_update(9003, "de")
    await start(update, SimpleNamespace(user_data={}))

    kwargs = update.message.reply_text.call_args[1]
    labels = [btn.text for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert any("Deutsch" in label for label in labels)
