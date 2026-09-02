"""Tests for the commercial layer's FREE-tier usage limit
(services/limits_service.py) and the Telegram Stars payment flow
(database/repositories/payments.py, handlers/payments.py).

Payment idempotency is the single most safety-critical property here:
a duplicate/redelivered successful_payment update must never grant PRO
twice or create a second Payment row for the same Telegram charge.
"""
from __future__ import annotations

import os
import tempfile
from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import SubscriptionStatus
from database.repositories import payments as payments_repo
from database.repositories import subscriptions as subscriptions_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from database.repositories import word_generation_logs as generation_logs_repo
from services import limits_service
from utils.time import local_day_bounds, utc_now


async def _create_user(session, *, telegram_id=6000, status=SubscriptionStatus.FREE):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=None, first_name="Test",
        interface_language="en", timezone="UTC", level="a1", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    if status != SubscriptionStatus.FREE:
        await subscriptions_repo.set_subscription_status(session, user, status=status)
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="en",
        level="a1", daily_new_words=4,
    )
    return user, ul


# --------------------------------------------------------------------- #
# services/limits_service.py
# --------------------------------------------------------------------- #

async def test_free_user_under_limit_is_allowed(session, monkeypatch):
    import config
    monkeypatch.setenv("FREE_DAILY_AI_GENERATION_LIMIT", "4")
    config.get_settings.cache_clear()

    user, _ = await _create_user(session)
    result = await limits_service.check_ai_generation_limit(session, user=user, language_code="en")
    assert result.allowed is True
    assert result.limit == 4
    config.get_settings.cache_clear()


async def test_free_user_at_limit_is_blocked(session, monkeypatch):
    import config
    monkeypatch.setenv("FREE_DAILY_AI_GENERATION_LIMIT", "4")
    config.get_settings.cache_clear()

    user, _ = await _create_user(session, telegram_id=6001)
    now = utc_now()
    day_start, _ = local_day_bounds(now, user.timezone)
    await generation_logs_repo.log(
        session, user_id=user.id, language_code="en", requested_amount=2, generated_amount=2,
        provider="deepseek", trigger="explicit_new_words",
    )
    await generation_logs_repo.log(
        session, user_id=user.id, language_code="en", requested_amount=2, generated_amount=2,
        provider="deepseek", trigger="explicit_new_words_topic",
    )
    await session.commit()

    result = await limits_service.check_ai_generation_limit(session, user=user, language_code="en")
    assert result.allowed is False
    assert result.used_today == 4
    config.get_settings.cache_clear()


async def test_trial_user_is_never_limited(session, monkeypatch):
    import config
    monkeypatch.setenv("FREE_DAILY_AI_GENERATION_LIMIT", "1")
    config.get_settings.cache_clear()

    user, _ = await _create_user(session, telegram_id=6002, status=SubscriptionStatus.TRIAL)
    from datetime import date, timedelta
    user.trial_end = date.today() + timedelta(days=5)
    await session.commit()

    result = await limits_service.check_ai_generation_limit(session, user=user, language_code="en")
    assert result.allowed is True
    assert result.limit is None
    config.get_settings.cache_clear()


async def test_pro_user_is_never_limited(session, monkeypatch):
    import config
    monkeypatch.setenv("FREE_DAILY_AI_GENERATION_LIMIT", "1")
    config.get_settings.cache_clear()

    from datetime import date, timedelta
    user, _ = await _create_user(session, telegram_id=6003, status=SubscriptionStatus.PRO)
    await subscriptions_repo.set_subscription_status(
        session, user, status=SubscriptionStatus.PRO, end_date=date.today() + timedelta(days=10)
    )
    await session.commit()

    result = await limits_service.check_ai_generation_limit(session, user=user, language_code="en")
    assert result.allowed is True
    assert result.limit is None
    config.get_settings.cache_clear()


async def test_no_configured_limit_means_unlimited(session, monkeypatch):
    """PlanLimits.free_daily_ai_generation_limit accepts None (unlimited)
    as a Python-level value even though the env-var wiring always
    resolves to a concrete int - covers that code path directly."""
    import config
    import dataclasses

    settings = config.get_settings()
    unlimited_settings = dataclasses.replace(
        settings, plan_limits=dataclasses.replace(settings.plan_limits, free_daily_ai_generation_limit=None)
    )
    monkeypatch.setattr(limits_service, "get_settings", lambda: unlimited_settings)

    user, _ = await _create_user(session, telegram_id=6004)
    result = await limits_service.check_ai_generation_limit(session, user=user, language_code="en")
    assert result.allowed is True
    assert result.limit is None


# --------------------------------------------------------------------- #
# database/repositories/payments.py
# --------------------------------------------------------------------- #

async def test_payment_create_and_lookup_by_charge_id(session):
    user, _ = await _create_user(session, telegram_id=6010)
    await payments_repo.create(
        session, user_id=user.id, telegram_charge_id="charge_abc123",
        amount_stars=100, subscription_period_days=30,
    )
    await session.commit()

    found = await payments_repo.get_by_charge_id(session, telegram_charge_id="charge_abc123")
    assert found is not None
    assert found.amount_stars == 100

    missing = await payments_repo.get_by_charge_id(session, telegram_charge_id="does_not_exist")
    assert missing is None


# --------------------------------------------------------------------- #
# handlers/payments.py - real session_scope()/real database, same
# handler_db pattern as other handler test files.
# --------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

    import config
    config.get_settings.cache_clear()

    import database.database as db_module
    db_module._engine = None
    db_module._session_factory = None

    from database.database import init_models, session_scope
    from database.seed import seed_languages

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)
        await _create_user(s, telegram_id=7000)

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _update_with_message(telegram_id: int = 7000):
    msg = AsyncMock()
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg), msg


async def test_show_paywall_renders_price_and_buy_button(handler_db):
    from handlers import payments as payments_handler

    update, msg = _update_with_message()
    await payments_handler.show_paywall(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert "100" in text  # default PRO_PRICE_STARS
    markup = msg.reply_text.call_args[1]["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "pay:buy" in callbacks


async def test_pay_buy_sends_a_stars_invoice(handler_db):
    from handlers import payments as payments_handler

    q = AsyncMock()
    q.data = "pay:buy"
    q.from_user = SimpleNamespace(id=7000)
    q.message = SimpleNamespace(chat_id=7000)
    update = SimpleNamespace(callback_query=q)
    context = SimpleNamespace(user_data={}, bot=AsyncMock())

    await payments_handler.handle_payments_callback(update, context)

    context.bot.send_invoice.assert_awaited_once()
    kwargs = context.bot.send_invoice.call_args.kwargs
    assert kwargs["currency"] == "XTR"
    assert kwargs["prices"][0].amount == 100
    assert kwargs["payload"].startswith("pro_subscription:")


async def test_pre_checkout_approves_own_payload(handler_db):
    from handlers import payments as payments_handler

    query = AsyncMock()
    query.invoice_payload = "pro_subscription:1"
    update = SimpleNamespace(pre_checkout_query=query)

    await payments_handler.handle_pre_checkout_query(update, SimpleNamespace())

    query.answer.assert_awaited_once_with(ok=True)


async def test_pre_checkout_rejects_unknown_payload(handler_db):
    from handlers import payments as payments_handler

    query = AsyncMock()
    query.invoice_payload = "something_else:1"
    update = SimpleNamespace(pre_checkout_query=query)

    await payments_handler.handle_pre_checkout_query(update, SimpleNamespace())

    query.answer.assert_awaited_once()
    assert query.answer.call_args.kwargs["ok"] is False


async def test_successful_payment_grants_pro_exactly_once(handler_db):
    from database.database import session_scope
    from database.repositories import users as users_repo
    from handlers import payments as payments_handler

    update, msg = _update_with_message()
    update.message.successful_payment = SimpleNamespace(
        telegram_payment_charge_id="charge_xyz", total_amount=100, currency="XTR",
    )

    await payments_handler.handle_successful_payment(update, SimpleNamespace())

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 7000)
        assert user.subscription_status == SubscriptionStatus.PRO
        assert user.subscription_end is not None

    payment = await _get_payment_by_charge(session_scope, "charge_xyz")
    assert payment is not None
    assert payment.amount_stars == 100

    msg.reply_text.assert_awaited_once()


async def test_duplicate_successful_payment_does_not_double_grant(handler_db):
    """The critical idempotency guarantee: a redelivered
    successful_payment for the SAME charge_id must never create a second
    Payment row or push subscription_end out further a second time."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from handlers import payments as payments_handler

    update1, msg1 = _update_with_message()
    update1.message.successful_payment = SimpleNamespace(
        telegram_payment_charge_id="charge_dup", total_amount=100, currency="XTR",
    )
    await payments_handler.handle_successful_payment(update1, SimpleNamespace())

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 7000)
        end_after_first = user.subscription_end

    # The exact same charge_id arrives again (Telegram redelivery).
    update2, msg2 = _update_with_message()
    update2.message.successful_payment = SimpleNamespace(
        telegram_payment_charge_id="charge_dup", total_amount=100, currency="XTR",
    )
    await payments_handler.handle_successful_payment(update2, SimpleNamespace())

    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 7000)
        assert user.subscription_end == end_after_first  # not extended a second time

    # Only one Payment row for this charge_id.
    async with session_scope() as s:
        from sqlalchemy import select
        from database.models import Payment
        result = await s.execute(select(Payment).where(Payment.telegram_charge_id == "charge_dup"))
        rows = result.scalars().all()
        assert len(rows) == 1

    msg1.reply_text.assert_awaited_once()
    msg2.reply_text.assert_not_awaited()  # duplicate is a silent no-op


async def _get_payment_by_charge(session_scope, charge_id: str):
    async with session_scope() as s:
        return await payments_repo.get_by_charge_id(s, telegram_charge_id=charge_id)
