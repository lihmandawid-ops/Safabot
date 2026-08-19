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
    session: AsyncSession, *, user_id: int, notification_type: str, scheduled_date: date
) -> NotificationLog:
    entry = NotificationLog(user_id=user_id, notification_type=notification_type, scheduled_date=scheduled_date)
    session.add(entry)
    await session.flush()
    return entry
