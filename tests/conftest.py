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

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base
from database.seed import seed_languages


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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
