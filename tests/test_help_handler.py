"""End-to-end test for the /help command (real user request: a second,
independent way to reach 🆘 support besides ⚙️ Настройки).
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio


@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("SUPPORT_CONTACT", "@safabot_support")

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
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="uk", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )

    yield

    await db_module.dispose_engine()
    os.remove(path)
    config.get_settings.cache_clear()


def _update(telegram_id: int):
    message = AsyncMock()
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=message)


async def test_help_command_shows_support_contact_in_the_users_own_language(handler_db):
    from handlers.help import help_command

    update = _update(42)
    await help_command(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "@safabot_support" in text
    assert "Підтримка" in text  # this user's interface_language is "uk"


async def test_help_command_works_for_a_user_with_no_account_yet(handler_db):
    """A stranger typing /help before ever running /start must not crash -
    they just get the message in whatever language is currently active."""
    from handlers.help import help_command

    update = _update(999999)
    await help_command(update, SimpleNamespace(user_data={}))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "@safabot_support" in text
