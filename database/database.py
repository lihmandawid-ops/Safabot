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

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from database.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        database_url = settings.database_url
        if database_url.startswith("sqlite"):
            _engine = create_async_engine(database_url, echo=False)
            # SQLite ignores foreign key constraints unless told otherwise per
            # connection - without this, User/UserLanguage rows could point
            # at a language code that doesn't exist in the languages table.
            event.listen(_engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        else:
            # Postgres-migration stage: SQLite has no real connection pool
            # (one file, effectively one writer) so pool sizing only means
            # anything for a network database - pool_pre_ping guards
            # against a connection PostgreSQL silently dropped while idle
            # (a long-lived 24/7 process is exactly the case this matters
            # for), never against a bad DATABASE_URL, which still fails
            # loudly on first use either way.
            _engine = create_async_engine(
                database_url,
                echo=False,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_pre_ping=True,
            )
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
