"""Shared pytest fixtures.

Each test gets its own throwaway SQLite file and a fresh async engine
scoped to that test's event loop, so tests never share state with each
other or with a developer's local safabot.db, and never fight over a
single global engine across event loops.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base
from database.seed import seed_languages


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
def _isolate_ai_config(monkeypatch):
    """Every test runs with AI forced "unconfigured" by default, regardless
    of what the real .env on this machine actually has (e.g. a live
    DeepSeek or Gemini key for the running bot) - a test suite must never
    make a real network call to an AI provider (spec: "Unit tests НЕ
    должны обращаться к реальному DeepSeek"). Tests that want a
    "configured" AIService inject their own via monkeypatch.setattr on the
    relevant module's `get_ai_service` name (see tests/test_ai_service.py,
    tests/test_manual_add_flow.py, tests/test_text_analysis_flow.py) -
    that bypasses the factory entirely, so this override never interferes.
    """
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OCR_API_KEY", "")
    monkeypatch.setenv("STT_API_KEY", "")
    import config
    config.get_settings.cache_clear()
    from services.ai_service import get_ai_service
    from services.ocr_service import get_ocr_service
    from services.stt_service import get_stt_service
    get_ai_service.cache_clear()
    get_ocr_service.cache_clear()
    get_stt_service.cache_clear()
    yield
    config.get_settings.cache_clear()
    get_ai_service.cache_clear()
    get_ocr_service.cache_clear()
    get_stt_service.cache_clear()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db_session:
            await seed_languages(db_session)
            await db_session.commit()
            yield db_session
    finally:
        await engine.dispose()
        os.remove(path)
