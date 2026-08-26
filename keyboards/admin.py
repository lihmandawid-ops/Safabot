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


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Send to everyone", callback_data="admin:broadcast:confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin:broadcast:cancel")],
        ]
    )
