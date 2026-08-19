"""Trial and PRO subscription logic (spec sections 11/24-26).

Kept separate from handlers so payment/trial rules can change (and Stage
13's Telegram Stars flow can plug in) without touching Telegram-facing
code. Handlers call this service; this service calls the subscriptions
repository. This is the single source of truth for "does this user get
PRO features right now" - never re-implement this check in a handler.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.models import SubscriptionStatus, User
from database.repositories import subscriptions as subscriptions_repo


async def start_trial(session: AsyncSession, user: User, *, today: date | None = None) -> User:
    """Grant the section-24 free trial: TRIAL_DAYS days of PRO from today."""
    start = today or date.today()
    end = start + timedelta(days=get_settings().trial_days)
    return await subscriptions_repo.start_trial(session, user, start=start, end=end)


def is_trial_active(user: User, *, today: date | None = None) -> bool:
    """Whether the user is currently within their free trial window."""
    if user.subscription_status != SubscriptionStatus.TRIAL:
        return False
    today = today or date.today()
    return user.trial_end is not None and user.trial_end >= today


def is_subscription_active(user: User, *, today: date | None = None) -> bool:
    """Whether the user currently has a paid PRO subscription in effect."""
    if user.subscription_status != SubscriptionStatus.PRO:
        return False
    today = today or date.today()
    return user.subscription_end is None or user.subscription_end >= today


def has_pro_access(user: User, *, today: date | None = None) -> bool:
    """Whether the user currently gets PRO-level features, trial or paid."""
    return is_trial_active(user, today=today) or is_subscription_active(user, today=today)


async def refresh_expired_trial(session: AsyncSession, user: User, *, today: date | None = None) -> User:
    """If a TRIAL user's trial has lapsed, downgrade them to FREE.

    Call this whenever a user's subscription state is read (e.g. at the
    start of a session) so status never silently stays "trial" past its
    end date.
    """
    today = today or date.today()
    if (
        user.subscription_status == SubscriptionStatus.TRIAL
        and user.trial_end is not None
        and user.trial_end < today
    ):
        return await subscriptions_repo.set_subscription_status(
            session, user, status=SubscriptionStatus.FREE
        )
    return user
