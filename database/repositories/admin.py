"""Data access for the admin panel (commercial layer, operator-facing).

Kept as thin aggregate queries only - see services/admin_service.py for
what the numbers mean and how they're combined into screens. Reuses
existing tables (User, ReviewLog, UserWord, Payment) - no separate
analytics/event table exists yet (a full event-tracking pipeline is a
larger, separate piece of work - see the chat report).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Payment, ReviewLog, SubscriptionStatus, User, UserWord


async def count_users_by_status(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(User.subscription_status, func.count(User.id)).group_by(User.subscription_status)
    )
    counts = {status: 0 for status in SubscriptionStatus}
    counts.update({status: count for status, count in result.all()})
    return counts


async def count_total_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)))
    return int(result.scalar_one())


async def count_new_users_since(session: AsyncSession, *, since: datetime) -> int:
    result = await session.execute(select(func.count(User.id)).where(User.created_at >= since))
    return int(result.scalar_one())


async def count_active_users_since(session: AsyncSession, *, since: datetime) -> int:
    """"Active" = did something that actually reflects learning activity
    in the window - answered a review (ReviewLog) or had a word added
    (UserWord.added_at) - never just "the row was touched" (User.
    updated_at bumps on any column change, including things like a
    timezone edit, so it's not a meaningful activity signal here)."""
    reviewed = select(ReviewLog.user_id).where(ReviewLog.reviewed_at >= since)
    added_words = select(UserWord.user_id).where(UserWord.added_at >= since)
    result = await session.execute(select(func.count(func.distinct(User.id))).where(
        User.id.in_(reviewed) | User.id.in_(added_words)
    ))
    return int(result.scalar_one())


async def list_all_telegram_ids(session: AsyncSession) -> list[int]:
    """📢 Broadcast's recipient list - every registered user regardless of
    notifications_enabled (an explicit broadcast is not a routine
    reminder, spec section 26)."""
    result = await session.execute(select(User.telegram_id))
    return [row[0] for row in result.all()]


async def last_activity_at(session: AsyncSession, *, user_id: int) -> datetime | None:
    """The more recent of "last reviewed something" / "last had a word
    added" - None if the user has never done either (fresh registration)."""
    review_result = await session.execute(
        select(func.max(ReviewLog.reviewed_at)).where(ReviewLog.user_id == user_id)
    )
    word_result = await session.execute(
        select(func.max(UserWord.added_at)).where(UserWord.user_id == user_id)
    )
    candidates = [d for d in (review_result.scalar_one(), word_result.scalar_one()) if d is not None]
    return max(candidates) if candidates else None


async def review_totals_for_user(session: AsyncSession, *, user_id: int) -> tuple[int, int, int]:
    """(review_count, correct, wrong) across ALL of this user's learning
    languages - unlike services.progress_service (scoped to one active
    language), an admin search result is a whole-account summary."""
    result = await session.execute(
        select(
            func.count(ReviewLog.id),
            func.coalesce(func.sum(ReviewLog.correct_delta), 0),
            func.coalesce(func.sum(ReviewLog.wrong_delta), 0),
        ).where(ReviewLog.user_id == user_id)
    )
    count, correct, wrong = result.one()
    return int(count), int(correct), int(wrong)


async def count_payments_since(session: AsyncSession, *, since: datetime) -> tuple[int, int]:
    """(payment_count, total_stars) within the window."""
    result = await session.execute(
        select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount_stars), 0)).where(
            Payment.created_at >= since
        )
    )
    count, stars = result.one()
    return int(count), int(stars)


async def count_all_payments(session: AsyncSession) -> tuple[int, int]:
    result = await session.execute(
        select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount_stars), 0))
    )
    count, stars = result.one()
    return int(count), int(stars)


async def list_recent_payments(session: AsyncSession, *, limit: int = 10) -> list[Payment]:
    result = await session.execute(select(Payment).order_by(Payment.created_at.desc()).limit(limit))
    return list(result.scalars().all())
