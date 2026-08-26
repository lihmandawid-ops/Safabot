"""🔐 Admin Panel (commercial layer, operator-facing).

Access control (spec sections 24-25): services.admin_service.is_admin()
is checked at the START of every single handler in this module - the
/admin command, every "admin:" callback, and the free-text search/
broadcast input - never assumed from a prior check or from the mere fact
that a callback_data string looks like an admin one. A regular user who
somehow sends "admin:users" gets exactly the same silent no-op a stranger
guessing any other bot's internal callback would.

Plain hardcoded Russian text throughout (see keyboards/admin.py's
docstring for why this is intentionally NOT part of the localized
user-facing surface).
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from database.database import session_scope
from database.models import SubscriptionStatus
from database.repositories import admin as admin_repo
from database.repositories import subscriptions as subscriptions_repo
from database.repositories import users as users_repo
from keyboards.admin import (
    admin_menu_keyboard,
    back_to_admin_menu_keyboard,
    broadcast_confirm_keyboard,
    user_actions_keyboard,
)
from keyboards.main_menu import main_menu_keyboard
from services import admin_service, subscription_service
from utils.i18n import get_current_language, set_current_language, t
from utils.logging import get_logger
from utils.telegram_helpers import safe_edit_message_text

logger = get_logger(__name__)

MODE = "admin"
_BROADCAST_SEND_DELAY_SECONDS = 0.05  # stays well under Telegram's flood limits


def _status_lines(by_status: dict[str, int]) -> str:
    labels = {"trial": "🎁 Trial", "free": "🆓 Free", "pro": "⭐ PRO", "expired": "⌛ Expired"}
    return "\n".join(f"{labels.get(status, status)}: {count}" for status, count in by_status.items())


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_service.is_admin(update.effective_user.id):
        return  # silent no-op - a non-admin gets nothing, not even a denial
    context.user_data.pop("mode", None)
    context.user_data.pop("admin_submode", None)
    await update.message.reply_text("🔐 Admin Panel", reply_markup=admin_menu_keyboard())


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not admin_service.is_admin(query.from_user.id):
        await query.answer()
        return
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await safe_edit_message_text(query, text, reply_markup=reply_markup or back_to_admin_menu_keyboard())

    if data == "admin:exit":
        await query.answer()
        context.user_data.pop("mode", None)
        context.user_data.pop("admin_submode", None)
        async with session_scope() as session:
            user = await users_repo.get_by_telegram_id(session, query.from_user.id)
            set_current_language(user.interface_language if user else None)
        language = get_current_language()
        await query.message.reply_text(
            t("onboarding.main_menu_ready", language), reply_markup=main_menu_keyboard(language)
        )
        return

    if data == "admin:home":
        await query.answer()
        context.user_data.pop("admin_submode", None)
        await edit("🔐 Admin Panel", reply_markup=admin_menu_keyboard())
        return

    if data == "admin:users":
        await query.answer()
        async with session_scope() as session:
            overview = await admin_service.build_user_overview(session)
        text = (
            "👥 Users\n\n"
            f"Total: {overview.total}\n\n"
            f"{_status_lines(overview.by_status)}\n\n"
            f"New: today {overview.new_today} · 7d {overview.new_7d} · 30d {overview.new_30d}\n"
            f"Active: today {overview.active_today} · 7d {overview.active_7d} · 30d {overview.active_30d}"
        )
        await edit(text)
        return

    if data == "admin:subscriptions":
        await query.answer()
        async with session_scope() as session:
            overview = await admin_service.build_user_overview(session)
        text = "⭐ Subscriptions\n\n" + _status_lines(overview.by_status)
        await edit(text)
        return

    if data == "admin:payments":
        await query.answer()
        async with session_scope() as session:
            payments = await admin_service.build_payments_overview(session)
            recent = await admin_repo.list_recent_payments(session, limit=10)
        lines = [
            "💳 Payments",
            "",
            f"All-time: {payments.total_count} payments, {payments.total_stars} ⭐",
            f"Today: {payments.today_count} payments, {payments.today_stars} ⭐",
            f"7d: {payments.week_count} payments, {payments.week_stars} ⭐",
            f"30d: {payments.month_count} payments, {payments.month_stars} ⭐",
        ]
        if recent:
            lines.append("")
            lines.append("Recent:")
            for payment in recent:
                lines.append(f"· user_id={payment.user_id} {payment.amount_stars}⭐ {payment.created_at:%Y-%m-%d}")
        await edit("\n".join(lines))
        return

    if data == "admin:analytics":
        await query.answer()
        async with session_scope() as session:
            users = await admin_service.build_user_overview(session)
            payments = await admin_service.build_payments_overview(session)
        pro_count = users.by_status.get("pro", 0)
        trial_count = users.by_status.get("trial", 0)
        conversion = f"{(pro_count / users.total * 100):.1f}%" if users.total else "—"
        text = (
            "📊 Analytics\n\n"
            f"👥 Users: {users.total}\n"
            f"⭐ PRO: {pro_count}\n"
            f"🎁 Trial: {trial_count}\n"
            f"🆓 Free: {users.by_status.get('free', 0)}\n"
            f"💰 Revenue (all-time): {payments.total_stars} ⭐\n"
            f"📈 Trial→PRO conversion (all-time): {conversion}\n"
            f"🔥 Active today: {users.active_today} · 7d: {users.active_7d} · 30d: {users.active_30d}\n\n"
            "Full event-based funnel/retention tracking is a separate, "
            "not-yet-built piece (would need a dedicated event log)."
        )
        await edit(text)
        return

    if data == "admin:limits":
        await query.answer()
        from config import get_settings

        settings = get_settings()
        text = (
            "⚙️ Limits (current config, requires a .env change + restart to edit)\n\n"
            f"FREE daily AI word generation: {settings.plan_limits.free_daily_ai_generation_limit}\n"
            f"FREE max languages: {settings.plan_limits.free_max_languages}\n"
            f"PRO max languages: {settings.plan_limits.pro_max_languages}\n"
            f"Extra words/day (all tiers): {settings.max_extra_words_per_day}\n"
            f"Trial length: {settings.trial_days} days\n"
            f"PRO price: {settings.pro_price_stars} ⭐ / {settings.pro_duration_days} days"
        )
        await edit(text)
        return

    if data == "admin:search":
        await query.answer()
        context.user_data["mode"] = MODE
        context.user_data["admin_submode"] = "search"
        await edit("🔎 Send the user's numeric Telegram ID.")
        return

    if data == "admin:broadcast":
        await query.answer()
        context.user_data["mode"] = MODE
        context.user_data["admin_submode"] = "broadcast"
        await edit("📢 Send the message text to broadcast to every registered user.")
        return

    if data == "admin:broadcast:cancel":
        await query.answer()
        context.user_data.pop("admin_submode", None)
        context.user_data.pop("admin_broadcast_text", None)
        await edit("Cancelled.", reply_markup=admin_menu_keyboard())
        return

    if data.startswith("admin:grant:"):
        await query.answer()
        parts = data.removeprefix("admin:grant:").split(":")
        target_id, days = int(parts[0]), int(parts[1])
        async with session_scope() as session:
            user = await users_repo.get_by_telegram_id(session, target_id)
            if user is None:
                await edit("User not found.", reply_markup=admin_menu_keyboard())
                return
            user = await subscription_service.activate_pro(session, user, duration_days=days)
            subscription_end = user.subscription_end
        await edit(
            f"🎁 PRO granted to {target_id} until {subscription_end}.",
            reply_markup=user_actions_keyboard(target_id),
        )
        return

    if data.startswith("admin:revoke:"):
        await query.answer()
        target_id = int(data.removeprefix("admin:revoke:"))
        async with session_scope() as session:
            user = await users_repo.get_by_telegram_id(session, target_id)
            if user is None:
                await edit("User not found.", reply_markup=admin_menu_keyboard())
                return
            await subscriptions_repo.set_subscription_status(session, user, status=SubscriptionStatus.FREE)
        await edit(f"❌ PRO revoked for {target_id} → Free.", reply_markup=user_actions_keyboard(target_id))
        return

    if data == "admin:broadcast:confirm":
        await query.answer()
        text = context.user_data.pop("admin_broadcast_text", None)
        context.user_data.pop("admin_submode", None)
        if not text:
            await edit("Nothing to send.", reply_markup=admin_menu_keyboard())
            return
        async with session_scope() as session:
            telegram_ids = await admin_repo.list_all_telegram_ids(session)
        sent, failed = 0, 0
        for telegram_id in telegram_ids:
            try:
                await context.bot.send_message(chat_id=telegram_id, text=text)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(_BROADCAST_SEND_DELAY_SECONDS)
        logger.info("Admin broadcast complete sent=%d failed=%d admin_id=%s", sent, failed, query.from_user.id)
        await edit(f"📢 Broadcast complete: sent {sent}, failed {failed}.", reply_markup=admin_menu_keyboard())
        return


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not admin_service.is_admin(update.effective_user.id):
        context.user_data.pop("mode", None)
        context.user_data.pop("admin_submode", None)
        return

    submode = context.user_data.get("admin_submode")

    if submode == "search":
        context.user_data.pop("admin_submode", None)
        raw = text.strip()
        if not raw.isdigit():
            await update.message.reply_text(
                "That doesn't look like a numeric Telegram ID.", reply_markup=admin_menu_keyboard()
            )
            return
        async with session_scope() as session:
            detail = await admin_service.find_user_detail(session, telegram_id=int(raw))
        if detail is None:
            await update.message.reply_text("No user found with that Telegram ID.", reply_markup=admin_menu_keyboard())
            return
        lines = [
            f"🔎 User {detail.telegram_id}",
            f"@{detail.username}" if detail.username else (detail.first_name or "—"),
            "",
            f"Status: {detail.subscription_status}",
            f"Interface language: {detail.interface_language}",
            f"Registered: {detail.created_at:%Y-%m-%d}",
        ]
        if detail.trial_end:
            lines.append(f"Trial until: {detail.trial_end}")
        if detail.subscription_end:
            lines.append(f"PRO until: {detail.subscription_end}")
        lines.append("")
        lines.append(f"Learning language: {detail.current_language_code or '—'}")
        lines.append(f"Words in learning: {detail.total_words} (mastered: {detail.mastered_words})")
        lines.append(f"Total reviews: {detail.total_reviews_all_languages} ({detail.overall_accuracy:.0%} accuracy)")
        lines.append(f"Last activity: {detail.last_activity_at:%Y-%m-%d %H:%M} UTC" if detail.last_activity_at else "Last activity: never")
        await update.message.reply_text("\n".join(lines), reply_markup=user_actions_keyboard(detail.telegram_id))
        return

    if submode == "broadcast":
        context.user_data["admin_broadcast_text"] = text
        async with session_scope() as session:
            recipient_count = len(await admin_repo.list_all_telegram_ids(session))
        preview = f"📢 Preview ({recipient_count} recipients):\n\n{text}"
        await update.message.reply_text(preview, reply_markup=broadcast_confirm_keyboard())
        return


admin_callback_handler = CallbackQueryHandler(handle_admin_callback, pattern="^admin:")
admin_command_handler = CommandHandler("admin", admin_command)
