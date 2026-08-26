"""Keyboards for the Telegram Stars PRO subscription flow (commercial
layer). Every screen here routes through handlers/payments.py's single
"pay:" CallbackQueryHandler.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t


def paywall_keyboard() -> InlineKeyboardMarkup:
    """⭐ Safabot PRO screen: one clear call to action - tapping it starts
    the real Telegram Stars invoice (handlers/payments.py's "pay:buy"
    branch), never a fake "PRO activated" shortcut."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("pro.button.buy", get_current_language()), callback_data="pay:buy")]]
    )


def limit_reached_keyboard() -> InlineKeyboardMarkup:
    """Shown instead of a bare error when a FREE user hits their daily
    AI-generation limit (services.limits_service) - the button goes
    straight to the paywall, not back to a dead end."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("limits.button.get_pro", get_current_language()), callback_data="pay:paywall")]]
    )
