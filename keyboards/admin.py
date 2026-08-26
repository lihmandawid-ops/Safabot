"""Keyboards for 🔐 Admin Panel (commercial layer, operator-facing).

Plain, hardcoded Russian labels by design - this is an internal operator
tool, not part of the product's user-facing i18n surface (spec section 39
covers user-facing messages; an admin's own interface_language has no
bearing on how they operate the bot). Every callback here uses the
"admin:" prefix, routed by handlers/admin.py's single CallbackQueryHandler,
which re-checks services.admin_service.is_admin() on every single one -
never trust that only an admin could have reached this keyboard.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👥 Users", callback_data="admin:users")],
            [InlineKeyboardButton("⭐ Subscriptions", callback_data="admin:subscriptions")],
            [InlineKeyboardButton("💳 Payments", callback_data="admin:payments")],
            [InlineKeyboardButton("📊 Analytics", callback_data="admin:analytics")],
            [InlineKeyboardButton("⚙️ Limits", callback_data="admin:limits")],
            [InlineKeyboardButton("🔎 Search user", callback_data="admin:search")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast")],
            [InlineKeyboardButton("🚪 Exit", callback_data="admin:exit")],
        ]
    )


def back_to_admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin:home")]])


def user_actions_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """Shown under a 🔎 Search user result - lets the admin manually comp
    PRO to a specific person (friends/testers/"limited free access" -
    real operator request) or revoke it, without that person ever paying.
    Every button carries the searched telegram_id so the resulting
    "admin:grant:"/"admin:revoke:" callback acts on exactly that account,
    not whatever was last searched."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎁 Grant PRO — 30 days", callback_data=f"admin:grant:{telegram_id}:30")],
            [InlineKeyboardButton("🎁 Grant PRO — 365 days", callback_data=f"admin:grant:{telegram_id}:365")],
            [InlineKeyboardButton("❌ Revoke PRO → Free", callback_data=f"admin:revoke:{telegram_id}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin:home")],
        ]
    )


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Send to everyone", callback_data="admin:broadcast:confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin:broadcast:cancel")],
        ]
    )
