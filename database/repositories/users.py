"""Data access for User (repository pattern, spec section 28/12: handlers
and services must go through here, never touch the ORM directly).

UserLanguage access lives in database/repositories/user_languages.py, and
Language access in database/repositories/languages.py - kept as separate
modules so each repository stays focused on one aggregate.
"""
from __future__ import annotations

from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    interface_language: str,
    timezone: str,
    level: str,
    daily_new_words: int,
    morning_time: time,
    afternoon_time: time,
    evening_time: time,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        interface_language=interface_language,
        timezone=timezone,
        level=level,
        daily_new_words=daily_new_words,
        morning_time=morning_time,
        afternoon_time=afternoon_time,
        evening_time=evening_time,
    )
    session.add(user)
    await session.flush()
    return user


async def get_notifiable_users(session: AsyncSession) -> list[User]:
    """Users the scheduler (services/notification_service.py) should even
    consider - notifications_enabled=True filters out the rest at the DB
    level instead of fetching everyone and checking in Python."""
    result = await session.execute(select(User).where(User.notifications_enabled.is_(True)))
    return list(result.scalars().all())


async def update_user(session: AsyncSession, user: User, **fields: Any) -> User:
    """Set arbitrary column values on `user` and flush.

    Used by handlers/settings.py so it never has to reach into the ORM
    object directly - e.g. update_user(session, user, level="advanced").
    """
    for field_name, value in fields.items():
        if not hasattr(user, field_name):
            raise AttributeError(f"User has no field {field_name!r}")
        setattr(user, field_name, value)
    await session.flush()
    return user
