"""Trial and subscription-status tests (spec sections 11, 17)."""
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
        level="beginner",
        daily_new_words=4,
        morning_time=time(9, 0),
        afternoon_time=time(14, 0),
        evening_time=time(20, 0),
    )


async def test_start_trial_sets_status_and_dates(session):
    user = await _create_test_user(session)
    today = date(2026, 1, 1)

    await subscription_service.start_trial(session, user, today=today)
    await session.commit()

    assert user.subscription_status == SubscriptionStatus.TRIAL
    assert user.trial_start == today
    assert user.trial_end == today + timedelta(days=7)


async def test_is_trial_active_true_within_window(session):
    user = await _create_test_user(session, telegram_id=501)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)

    assert subscription_service.is_trial_active(user, today=today + timedelta(days=6)) is True
    assert subscription_service.has_pro_access(user, today=today + timedelta(days=6)) is True


async def test_is_trial_active_false_after_trial_expires(session):
    user = await _create_test_user(session, telegram_id=502)
    today = date(2026, 1, 1)
    await subscription_service.start_trial(session, user, today=today)

    assert subscription_service.is_trial_active(user, today=today + timedelta(days=8)) is False
    assert subscription_service.has_pro_access(user, today=today + timedelta(days=8)) is False


async def test_is_subscription_active_true_for_paid_subscription(session):
    user = await _create_test_user(session, telegram_id=503)
    await subscriptions_repo.set_subscription_status(
        session, user, status=SubscriptionStatus.PRO, end_date=date(2026, 2, 1)
    )

    assert subscription_service.is_subscription_active(user, today=date(2026, 1, 15)) is True
    assert subscription_service.has_pro_access(user, today=date(2026, 1, 15)) is True
    assert subscription_service.is_subscription_active(user, today=date(2026, 2, 2)) is False


async def test_has_pro_access_false_for_free_user(session):
    user = await _create_test_user(session, telegram_id=504)
    assert subscription_service.is_trial_active(user) is False
    assert subscription_service.is_subscription_active(user) is False
    assert subscription_service.has_pro_access(user) is False


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


async def test_activate_pro_fresh_starts_from_today(session):
    """A FREE (or never-subscribed) user buying PRO gets exactly
    duration_days from today, not from any stale prior date."""
    user = await _create_test_user(session, telegram_id=507)
    today = date(2026, 1, 1)

    activated = await subscription_service.activate_pro(session, user, duration_days=30, today=today)
    await session.commit()

    assert activated.subscription_status == SubscriptionStatus.PRO
    assert activated.subscription_start == today
    assert activated.subscription_end == today + timedelta(days=30)


async def test_activate_pro_renewal_extends_from_current_end_not_today(session):
    """Buying again while PRO is still active must never shorten what was
    already paid for - the new period stacks onto the existing end date."""
    user = await _create_test_user(session, telegram_id=508)
    today = date(2026, 1, 1)
    await subscription_service.activate_pro(session, user, duration_days=30, today=today)
    await session.commit()
    first_end = user.subscription_end
    assert first_end == today + timedelta(days=30)

    renewed = await subscription_service.activate_pro(
        session, user, duration_days=30, today=today + timedelta(days=5)
    )
    await session.commit()

    assert renewed.subscription_end == first_end + timedelta(days=30)
    assert renewed.subscription_start == today  # unchanged - still the original purchase date


async def test_activate_pro_after_lapse_starts_fresh_again(session):
    """A user whose PRO already expired (or who never had it) gets a
    fresh period starting today, not stacked onto a long-dead end date."""
    user = await _create_test_user(session, telegram_id=509)
    today = date(2026, 1, 1)
    await subscription_service.activate_pro(session, user, duration_days=30, today=today)
    await session.commit()

    # Buy again long after the first period lapsed.
    resubscribed = await subscription_service.activate_pro(
        session, user, duration_days=30, today=today + timedelta(days=100)
    )
    await session.commit()

    assert resubscribed.subscription_start == today + timedelta(days=100)
    assert resubscribed.subscription_end == today + timedelta(days=130)
