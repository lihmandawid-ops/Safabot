"""💎 PRO / Telegram Stars subscription (commercial layer).

Real money flow, kept deliberately narrow and defensive:
- ⭐ PRO (main menu) / "get PRO" CTAs everywhere else all render the exact
  same paywall text+keyboard - one screen, not several drifting copies.
- "pay:buy" only ever calls Bot.send_invoice with currency="XTR" (Telegram
  Stars - no provider_token needed, no card data ever touches this bot).
- PRO is granted in exactly ONE place (`_grant_pro`), reached only from
  handle_successful_payment - a button tap or an approved pre-checkout
  query alone NEVER grants anything by itself.
- Idempotent: SuccessfulPayment.telegram_payment_charge_id is checked
  against database.repositories.payments before granting, so a redelivered
  update (Telegram's own retry, at-least-once webhook semantics) can
  never double-grant.
"""
from __future__ import annotations

from telegram import LabeledPrice, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import get_settings
from database.database import session_scope
from database.repositories import payments as payments_repo
from database.repositories import users as users_repo
from keyboards.payments import paywall_keyboard
from services import subscription_service
from utils.i18n import get_current_language, set_current_language, t
from utils.logging import get_logger
from utils.telegram_helpers import safe_edit_message_text

logger = get_logger(__name__)

_PRODUCT_PRO = "pro_subscription"


def _paywall_text(language: str) -> str:
    settings = get_settings()
    lines = [
        t("pro.title", language),
        "",
        t("pro.benefit.new_words", language),
        t("pro.benefit.ai_generation", language),
        t("pro.benefit.review", language),
        t("pro.benefit.stats", language),
        t("pro.benefit.adaptation", language),
        "",
        t("pro.price", language, price=settings.pro_price_stars),
    ]
    return "\n".join(lines)


async def show_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⭐ PRO main-menu button entry point - a plain text reply, same as
    every other main-menu screen that isn't already an interactive flow."""
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
        if user is None:
            return
        set_current_language(user.interface_language)

    await update.message.reply_text(_paywall_text(get_current_language()), reply_markup=paywall_keyboard())


async def handle_payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await safe_edit_message_text(query, text, reply_markup=reply_markup)

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, query.from_user.id)
        if user is None:
            await query.answer()
            return
        set_current_language(user.interface_language)

        if data == "pay:paywall":
            await query.answer()
            await edit(_paywall_text(get_current_language()), reply_markup=paywall_keyboard())
            return

        if data == "pay:buy":
            await query.answer()
            settings = get_settings()
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title=t("pro.invoice.title", get_current_language()),
                description=t("pro.invoice.description", get_current_language()),
                payload=f"{_PRODUCT_PRO}:{user.id}",
                currency="XTR",
                prices=[LabeledPrice(t("pro.invoice.label", get_current_language()), settings.pro_price_stars)],
            )
            return


async def handle_pre_checkout_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram blocks the payment sheet until this answers (must respond
    within ~10s) - approve only a payload this bot itself issued in
    "pay:buy" above, reject anything else outright (never granted, never
    charged - spec section 49's "invalid payment")."""
    query = update.pre_checkout_query
    if not query.invoice_payload.startswith(f"{_PRODUCT_PRO}:"):
        await query.answer(ok=False, error_message="Invalid or expired invoice. Please try again.")
        return
    await query.answer(ok=True)


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The ONLY place PRO is ever granted (spec section 10: never on a
    button tap or an approved pre-checkout alone - only a Telegram-
    confirmed successful_payment). Idempotent on telegram_payment_charge_id
    (spec sections 11, 51) - a redelivered update is a silent no-op, never
    a duplicate subscription or a duplicate Payment row."""
    payment = update.message.successful_payment
    settings = get_settings()

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
        if user is None:
            return
        set_current_language(user.interface_language)

        existing = await payments_repo.get_by_charge_id(
            session, telegram_charge_id=payment.telegram_payment_charge_id
        )
        if existing is not None:
            logger.info(
                "Duplicate successful_payment ignored user_id=%s charge_id=%s",
                user.id, payment.telegram_payment_charge_id,
            )
            return

        await payments_repo.create(
            session,
            user_id=user.id,
            telegram_charge_id=payment.telegram_payment_charge_id,
            amount_stars=payment.total_amount,
            subscription_period_days=settings.pro_duration_days,
        )
        user = await subscription_service.activate_pro(session, user, duration_days=settings.pro_duration_days)
        subscription_end = user.subscription_end
        logger.info(
            "PRO activated user_id=%s charge_id=%s until=%s",
            user.id, payment.telegram_payment_charge_id, subscription_end,
        )

    await update.message.reply_text(
        t(
            "pro.payment.success", get_current_language(),
            date=subscription_end.isoformat() if subscription_end else "",
        )
    )


payments_callback_handler = CallbackQueryHandler(handle_payments_callback, pattern="^pay:")
