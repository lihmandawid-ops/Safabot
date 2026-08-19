"""Seed data for the languages table (spec section 3).

Called from two places, both safe to run repeatedly:
    - the Alembic migration that creates the table (production/deploy path)
    - bot.py's on_startup, and tests/conftest.py (dev/quick-bootstrap path
      that creates tables directly from the ORM metadata, bypassing Alembic)

seed_languages() only inserts codes that aren't already present, so
re-running it (e.g. every bot startup) is a no-op once seeded.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Language

LANGUAGE_SEED_DATA: tuple[dict[str, str], ...] = (
    {"code": "en", "name": "English", "native_name": "English"},
    {"code": "ru", "name": "Russian", "native_name": "Русский"},
    {"code": "de", "name": "German", "native_name": "Deutsch"},
    {"code": "he", "name": "Hebrew", "native_name": "עברית"},
    {"code": "es", "name": "Spanish", "native_name": "Español"},
    {"code": "fr", "name": "French", "native_name": "Français"},
    {"code": "it", "name": "Italian", "native_name": "Italiano"},
    {"code": "uk", "name": "Ukrainian", "native_name": "Українська"},
)


async def seed_languages(session: AsyncSession) -> None:
    result = await session.execute(select(Language.code))
    existing_codes = set(result.scalars().all())

    missing = [row for row in LANGUAGE_SEED_DATA if row["code"] not in existing_codes]
    for row in missing:
        session.add(Language(code=row["code"], name=row["name"], native_name=row["native_name"]))

    if missing:
        await session.flush()
