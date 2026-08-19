"""Async SQLAlchemy engine/session setup.

Uses SQLite via aiosqlite in development; switching DATABASE_URL to a
PostgreSQL async DSN (postgresql+asyncpg://...) in production requires no
code changes here (section 28).

`init_models()` is a dev convenience that creates tables directly from the
ORM metadata. It is what bot.py calls on startup for a quick local setup.
Real deployments should run the Alembic migrations in migrations/ instead
(see README) so schema changes are tracked and reversible.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from database.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session: commits on success, rolls back on error."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Create all tables that don't exist yet. Dev convenience only - see
    module docstring; production schema changes go through Alembic."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
