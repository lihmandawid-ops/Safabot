"""Data access for Payment (commercial layer: Telegram Stars).

Kept as thin CRUD only - see services/subscription_service.py for what a
successful payment actually grants (PRO activation), and handlers/
payments.py for the Telegram-facing invoice/checkout flow.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Payment


async def get_by_charge_id(session: AsyncSession, *, telegram_charge_id: str) -> Payment | None:
    """The idempotency check: handlers/payments.py must call this before
    granting PRO, and skip granting again if a row already exists for
    this exact Telegram charge."""
    result = await session.execute(
        select(Payment).where(Payment.telegram_charge_id == telegram_charge_id)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    telegram_charge_id: str,
    amount_stars: int,
    subscription_period_days: int,
    currency: str = "XTR",
    product: str = "pro_subscription",
) -> Payment:
    payment = Payment(
        user_id=user_id,
        telegram_charge_id=telegram_charge_id,
        amount_stars=amount_stars,
        currency=currency,
        product=product,
        subscription_period_days=subscription_period_days,
    )
    session.add(payment)
    await session.flush()
    return payment
