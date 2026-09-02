"""Data access for Language (spec section 3)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Language


async def get_all_active(session: AsyncSession) -> list[Language]:
    result = await session.execute(select(Language).where(Language.active.is_(True)))
    return list(result.scalars().all())


async def get_by_code(session: AsyncSession, code: str) -> Language | None:
    result = await session.execute(select(Language).where(Language.code == code))
    return result.scalar_one_or_none()
