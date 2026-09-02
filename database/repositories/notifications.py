"""Data access for NotificationLog (spec section 29: idempotency).

Usage pattern (see services/notification_service.py): check `was_sent`
first, only actually send the Telegram message if it returns False, and
call `log_sent` only AFTER a successful send - a failed send is never
recorded as sent, so it can be retried on the next poll.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationLog


async def was_sent(
    session: AsyncSession, *, user_id: int, notification_type: str, scheduled_date: date
) -> bool:
    result = await session.execute(
        select(NotificationLog.id).where(
            NotificationLog.user_id == user_id,
            NotificationLog.notification_type == notification_type,
            NotificationLog.scheduled_date == scheduled_date,
        )
    )
    return result.scalar_one_or_none() is not None


async def log_sent(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: str,
    scheduled_date: date,
    word_ids: list[int] | None = None,
) -> NotificationLog:
    entry = NotificationLog(
        user_id=user_id, notification_type=notification_type, scheduled_date=scheduled_date, word_ids=word_ids,
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_recent_word_ids(
    session: AsyncSession, *, user_id: int, notification_type: str, limit: int = 1
) -> list[list[int]]:
    """word_ids of the most recently logged `notification_type` sends for
    this user, newest first (repetition-system stage section 15: avoid
    resending the exact same word set) - only rows that actually recorded
    a word list are returned."""
    result = await session.execute(
        select(NotificationLog.word_ids)
        .where(NotificationLog.user_id == user_id, NotificationLog.notification_type == notification_type)
        .order_by(NotificationLog.scheduled_date.desc(), NotificationLog.id.desc())
        .limit(limit)
    )
    return [ids for ids in result.scalars().all() if ids]


async def get_word_ids_for(
    session: AsyncSession, *, user_id: int, notification_type: str, scheduled_date: date
) -> list[int] | None:
    """The exact word_ids logged for today's `notification_type` send, if
    any - lets a "▶️ Начать повторение" tap on a notification review
    exactly the words that were listed in it, without re-running the
    selection query and possibly landing on a different set."""
    result = await session.execute(
        select(NotificationLog.word_ids).where(
            NotificationLog.user_id == user_id,
            NotificationLog.notification_type == notification_type,
            NotificationLog.scheduled_date == scheduled_date,
        )
    )
    return result.scalar_one_or_none()
