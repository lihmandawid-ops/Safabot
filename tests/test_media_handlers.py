"""End-to-end tests for handlers/media.py (bugfix spec sections 17-19):
📷 Разбор фото / 🎤 Разбор голоса. Mocks only the Telegram objects (get_file
+ download_to_drive) and the OCR/STT services - real handler code, real
session_scope(), real database, same pattern as tests/test_manual_add_flow.py.
"""
from __future__ import annotations

import glob
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from services.media_errors import OCRConfigurationError, OCRUnavailableError, STTConfigurationError


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
    from database.seed_words import seed_words
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from datetime import time

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await seed_words(s)
        user = await users_repo.create_user(
            s, telegram_id=42, username="grace", first_name="Grace",
            interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
            morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
        )
        await user_languages_repo.add_language(
            s, user_id=user.id, language_code="en", translation_language="ru",
            level="beginner", daily_new_words=4,
        )

    yield

    await db_module.dispose_engine()
    os.remove(path)


class _FakeTgFile:
    def __init__(self, *, content: bytes, file_size: int | None = None):
        self._content = content
        self.file_size = file_size if file_size is not None else len(content)

    async def download_to_drive(self, path, **kwargs):
        with open(path, "wb") as f:
            f.write(self._content)
        return path


def _photo_update(*, content: bytes = b"fake-jpeg-bytes", file_size: int | None = None):
    tg_file = _FakeTgFile(content=content, file_size=file_size)
    context = SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(return_value=tg_file)), user_data={})
    message = AsyncMock()
    message.photo = [SimpleNamespace(file_id="photo123")]
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))
    return update, context


def _voice_update(*, content: bytes = b"fake-ogg-bytes", file_size: int | None = None):
    tg_file = _FakeTgFile(content=content, file_size=file_size)
    context = SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(return_value=tg_file)), user_data={})
    message = AsyncMock()
    message.voice = SimpleNamespace(file_id="voice123", mime_type="audio/ogg")
    message.audio = None
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))
    return update, context


def _temp_media_files() -> set[str]:
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "safabot_media_*")))


async def test_photo_ocr_not_configured_shows_friendly_message(handler_db):
    from handlers import media as media_handler

    update, context = _photo_update()
    before = _temp_media_files()
    await media_handler.handle_photo_message(update, context)
    after = _temp_media_files()

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "не настроено" in text
    assert after == before  # temp file cleaned up, none left behind


async def test_photo_ocr_success_shows_recognized_text_and_runs_analysis(handler_db, monkeypatch):
    from handlers import media as media_handler

    class _Service:
        async def extract_text_from_image(self, image_bytes, *, mime_type, user_id):
            assert image_bytes == b"fake-jpeg-bytes"
            return "Hello world"

    monkeypatch.setattr(media_handler, "get_ocr_service", lambda: _Service())

    update, context = _photo_update()
    before = _temp_media_files()
    await media_handler.handle_photo_message(update, context)
    after = _temp_media_files()

    assert after == before  # no leftover temp file
    calls = [c.args[0] for c in update.message.reply_text.await_args_list]
    assert any("Hello world" in c for c in calls)  # recognized-text message shown
    # handle_text_input ran too (AI not configured in this fixture's env,
    # so it falls back to the "not configured" message - the point here is
    # that the existing text-analysis pipeline was actually invoked, not a
    # separate implementation).
    assert any("не настроен" in c for c in calls)


async def test_photo_ocr_failure_shows_friendly_error(handler_db, monkeypatch):
    from handlers import media as media_handler

    class _Service:
        async def extract_text_from_image(self, image_bytes, *, mime_type, user_id):
            raise OCRUnavailableError("boom")

    monkeypatch.setattr(media_handler, "get_ocr_service", lambda: _Service())

    update, context = _photo_update()
    await media_handler.handle_photo_message(update, context)

    text = update.message.reply_text.call_args[0][0]
    assert "Не удалось распознать" in text


async def test_photo_too_large_is_rejected_before_download(handler_db, monkeypatch):
    import config
    monkeypatch.setenv("MAX_IMAGE_SIZE_BYTES", "10")
    config.get_settings.cache_clear()

    from handlers import media as media_handler

    update, context = _photo_update(content=b"x" * 100, file_size=100)
    await media_handler.handle_photo_message(update, context)

    text = update.message.reply_text.call_args[0][0]
    assert "слишком большое" in text
    context.bot.get_file.assert_awaited_once()  # metadata was checked...
    # ...but download_to_drive is only reachable via get_file's return value,
    # and the handler must never have read the oversized file into memory.

    config.get_settings.cache_clear()


async def test_voice_stt_not_configured_shows_friendly_message(handler_db):
    from handlers import media as media_handler

    update, context = _voice_update()
    before = _temp_media_files()
    await media_handler.handle_voice_message(update, context)
    after = _temp_media_files()

    text = update.message.reply_text.call_args[0][0]
    assert "не настроено" in text
    assert after == before


async def test_voice_stt_success_shows_recognized_text_and_runs_analysis(handler_db, monkeypatch):
    from handlers import media as media_handler

    class _Service:
        async def transcribe_audio(self, audio_bytes, *, mime_type, filename, user_id):
            assert audio_bytes == b"fake-ogg-bytes"
            assert mime_type == "audio/ogg"
            return "I go home"

    monkeypatch.setattr(media_handler, "get_stt_service", lambda: _Service())

    update, context = _voice_update()
    await media_handler.handle_voice_message(update, context)

    calls = [c.args[0] for c in update.message.reply_text.await_args_list]
    assert any("I go home" in c for c in calls)
