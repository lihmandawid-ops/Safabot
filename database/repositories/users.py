"""Data access for User and UserLanguage (repository pattern, spec section 28:
handlers and services must go through here, never touch the ORM directly).
"""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserLanguage


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
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
    current_level: str,
    daily_new_words_limit: int,
    morning_notification_time: time,
    afternoon_notification_time: time,
    evening_notification_time: time,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        interface_language=interface_language,
        timezone=timezone,
        current_level=current_level,
        daily_new_words_limit=daily_new_words_limit,
        morning_notification_time=morning_notification_time,
        afternoon_notification_time=afternoon_notification_time,
        evening_notification_time=evening_notification_time,
    )
    session.add(user)
    await session.flush()
    return user


async def add_user_language(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    translation_language: str,
    level: str,
    daily_word_limit: int,
) -> UserLanguage:
    user_language = UserLanguage(
        user_id=user_id,
        language_code=language_code,
        translation_language=translation_language,
        level=level,
        daily_word_limit=daily_word_limit,
    )
    session.add(user_language)
    await session.flush()
    return user_language


async def get_active_languages(session: AsyncSession, user_id: int) -> list[UserLanguage]:
    result = await session.execute(
        select(UserLanguage).where(
            UserLanguage.user_id == user_id, UserLanguage.is_active.is_(True)
        )
    )
    return list(result.scalars().all())
