"""Admin panel business logic (commercial layer, operator-facing).

is_admin() is the single access-control check - handlers/admin.py calls
it on EVERY admin action (not just to decide whether to show a menu
button), per the explicit requirement that a regular user must never be
able to reach admin screens even by guessing callback_data.

Reuses services/progress_service.py for a searched user's own learning
stats (total/mastered words, reviews, accuracy) rather than re-deriving
them - the exact same numbers 📊 Мой прогресс shows that user, just read
by an operator instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.models import SubscriptionStatus, User
from database.repositories import admin as admin_repo
from database.repositories import user_languages as user_languages_repo
from services import progress_service
from utils.time import utc_now


def is_admin(telegram_id: int) -> bool:
    return telegram_id in get_settings().admin_user_ids


@dataclass(frozen=True)
class UserOverview:
    total: int
    by_status: dict[str, int]
    new_today: int
    new_7d: int
    new_30d: int
    active_today: int
    active_7d: int
    active_30d: int


@dataclass(frozen=True)
class PaymentsOverview:
    total_count: int
    total_stars: int
    today_count: int
    today_stars: int
    week_count: int
    week_stars: int
    month_count: int
    month_stars: int


@dataclass(frozen=True)
class UserDetail:
    telegram_id: int
    username: str | None
    first_name: str | None
    subscription_status: str
    interface_language: str
    created_at: datetime
    trial_end: object | None
    subscription_end: object | None
    last_activity_at: datetime | None
    current_language_code: str | None
    total_words: int
    mastered_words: int
    total_reviews_all_languages: int
    overall_accuracy: float


def _period_bounds(now: datetime) -> tuple[datetime, datetime, datetime]:
    """UTC calendar-day/rolling-week/rolling-month bounds - an admin
    overview is a whole-product aggregate with no single "user" timezone
    to anchor "today" to, unlike 📊 Мой прогресс's per-user local day."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    return today_start, week_start, month_start


async def build_user_overview(session: AsyncSession, *, now: datetime | None = None) -> UserOverview:
    now = now if now is not None else utc_now()
    today_start, week_start, month_start = _period_bounds(now)

    total = await admin_repo.count_total_users(session)
    by_status = await admin_repo.count_users_by_status(session)
    new_today = await admin_repo.count_new_users_since(session, since=today_start)
    new_7d = await admin_repo.count_new_users_since(session, since=week_start)
    new_30d = await admin_repo.count_new_users_since(session, since=month_start)
    active_today = await admin_repo.count_active_users_since(session, since=today_start)
    active_7d = await admin_repo.count_active_users_since(session, since=week_start)
    active_30d = await admin_repo.count_active_users_since(session, since=month_start)

    return UserOverview(
        total=total, by_status=by_status,
        new_today=new_today, new_7d=new_7d, new_30d=new_30d,
        active_today=active_today, active_7d=active_7d, active_30d=active_30d,
    )


async def build_payments_overview(session: AsyncSession, *, now: datetime | None = None) -> PaymentsOverview:
    now = now if now is not None else utc_now()
    today_start, week_start, month_start = _period_bounds(now)

    total_count, total_stars = await admin_repo.count_all_payments(session)
    today_count, today_stars = await admin_repo.count_payments_since(session, since=today_start)
    week_count, week_stars = await admin_repo.count_payments_since(session, since=week_start)
    month_count, month_stars = await admin_repo.count_payments_since(session, since=month_start)

    return PaymentsOverview(
        total_count=total_count, total_stars=total_stars,
        today_count=today_count, today_stars=today_stars,
        week_count=week_count, week_stars=week_stars,
        month_count=month_count, month_stars=month_stars,
    )


async def find_user_detail(session: AsyncSession, *, telegram_id: int) -> UserDetail | None:
    from database.repositories import users as users_repo

    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None

    current = await user_languages_repo.get_current_language(session, user.id)
    total_words = 0
    mastered_words = 0
    if current is not None:
        try:
            snapshot = await progress_service.build_snapshot(
                session, user_id=user.id, user_language=current, timezone=user.timezone
            )
            total_words = snapshot.total_words
            mastered_words = snapshot.mastered_count
        except Exception:
            pass

    last_activity = await admin_repo.last_activity_at(session, user_id=user.id)
    total_reviews, correct, wrong = await admin_repo.review_totals_for_user(session, user_id=user.id)
    total_answers = correct + wrong
    overall_accuracy = (correct / total_answers) if total_answers > 0 else 0.0

    return UserDetail(
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        subscription_status=user.subscription_status,
        interface_language=user.interface_language,
        created_at=user.created_at,
        trial_end=user.trial_end,
        subscription_end=user.subscription_end,
        last_activity_at=last_activity,
        current_language_code=current.language_code if current is not None else None,
        total_words=total_words,
        mastered_words=mastered_words,
        total_reviews_all_languages=total_reviews,
        overall_accuracy=overall_accuracy,
    )
