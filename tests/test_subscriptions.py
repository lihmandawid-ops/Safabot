"""Trial and subscription-status tests (spec sections 24, 32)."""
from __future__ import annotations

from datetime import date, time, timedelta

from database.models import SubscriptionStatus
from database.repositories import subscriptions as subscriptions_repo
from database.repositories import users as users_repo
from services import subscription_service


async def _create_test_user(session, telegram_id: int = 500):
    return await users_repo.create_user(
        session,
        telegram_id=telegram_id,
        username="grace",
        first_name="Grace",
        interface_language="ru",
        timezone="UTC",
        current_level="beginner",
        daily_new_words_limit=4,
        morning_notification_time=time(9, 0),
        afternoon_notification_time=time(14, 0),
        evening_notification_time=time(20, 0),
    )


async def test_start_trial_sets_status_and_dates(session):
    user = await _create_test_user(session)
    today = date(2026, 1, 1)

    await subscription_service.start_trial(session, user, today=today)
    await session.commit()

    assert user.subscription_status == SubscriptionStatus.TRIAL
    assert user.trial_start_date == today
    assert user.trial_end_date == today + timedelta(days=7)


async def test_is_pro_active_true_during_trial(session):
    user = await _create_test_user(session, telegram_id=501)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)

    assert subscription_service.is_pro_active(user, today=today + timedelta(days=6)) is True


async def test_is_pro_active_false_after_trial_expires(session):
    user = await _create_test_user(session, telegram_id=502)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)

    assert subscription_service.is_pro_active(user, today=today + timedelta(days=8)) is False


async def test_is_pro_active_true_for_paid_subscription(session):
    user = await _create_test_user(session, telegram_id=503)
    await subscriptions_repo.set_subscription_status(
        session, user, status=SubscriptionStatus.PRO, end_date=date(2026, 2, 1)
    )

    assert subscription_service.is_pro_active(user, today=date(2026, 1, 15)) is True
    assert subscription_service.is_pro_active(user, today=date(2026, 2, 2)) is False


async def test_is_pro_active_false_for_free_user(session):
    user = await _create_test_user(session, telegram_id=504)
    assert subscription_service.is_pro_active(user) is False


async def test_refresh_expired_trial_downgrades_to_free(session):
    user = await _create_test_user(session, telegram_id=505)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)
    await session.commit()

    refreshed = await subscription_service.refresh_expired_trial(
        session, user, today=today + timedelta(days=10)
    )
    await session.commit()

    assert refreshed.subscription_status == SubscriptionStatus.FREE


async def test_refresh_expired_trial_leaves_active_trial_untouched(session):
    user = await _create_test_user(session, telegram_id=506)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)
    await session.commit()

    refreshed = await subscription_service.refresh_expired_trial(
        session, user, today=today + timedelta(days=1)
    )

    assert refreshed.subscription_status == SubscriptionStatus.TRIAL
