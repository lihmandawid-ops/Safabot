"""Data access for the subscription/trial fields on User (spec sections 24-26).

Kept as a thin repository over the User row for now; if Telegram Stars
payments (Stage 13) later need their own transaction table, it will live
here alongside these functions.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import SubscriptionStatus, User


async def start_trial(session: AsyncSession, user: User, *, start: date, end: date) -> User:
    user.trial_start_date = start
    user.trial_end_date = end
    user.subscription_status = SubscriptionStatus.TRIAL
    await session.flush()
    return user


async def set_subscription_status(
    session: AsyncSession, user: User, *, status: SubscriptionStatus, end_date: date | None = None
) -> User:
    user.subscription_status = status
    if end_date is not None:
        user.subscription_end_date = end_date
    await session.flush()
    return user
