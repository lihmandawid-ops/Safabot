"""Keyboards for ⭐ Мои слова: filters, pagination, per-word action menu,
bulk-selection menu, and delete confirmation (spec sections 8, 10-13).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import t
from utils.pagination import NEXT_LABEL, PREVIOUS_LABEL

_LANG = "ru"


def filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.filter.all", _LANG), callback_data="words:filter:all")],
            [InlineKeyboardButton(t("words.filter.new", _LANG), callback_data="words:filter:new")],
            [InlineKeyboardButton(t("words.filter.review", _LANG), callback_data="words:filter:review")],
            [InlineKeyboardButton(t("words.filter.paused", _LANG), callback_data="words:filter:paused")],
            [InlineKeyboardButton(t("words.filter.mastered", _LANG), callback_data="words:filter:mastered")],
            [InlineKeyboardButton(t("words.search_button", _LANG), callback_data="words:search")],
        ]
    )


def list_keyboard(*, has_previous: bool, has_next: bool) -> InlineKeyboardMarkup:
    nav_row = []
    if has_previous:
        nav_row.append(InlineKeyboardButton(PREVIOUS_LABEL, callback_data="words:page:prev"))
    if has_next:
        nav_row.append(InlineKeyboardButton(NEXT_LABEL, callback_data="words:page:next"))

    rows = [nav_row] if nav_row else []
    rows.append([InlineKeyboardButton(t("words.button.back", _LANG), callback_data="words:filters")])
    return InlineKeyboardMarkup(rows)


def single_word_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.review", _LANG), callback_data=f"uw:review:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.pause", _LANG), callback_data=f"uw:pause:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.delete", _LANG), callback_data=f"uw:delete:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.open_card", _LANG), callback_data=f"uw:card:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.back", _LANG), callback_data="uw:list_back")],
        ]
    )


def delete_confirm_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.confirm_delete", _LANG), callback_data=f"uw:delete_confirm:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.cancel", _LANG), callback_data=f"uw:delete_cancel:{user_word_id}")],
        ]
    )


def bulk_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.review", _LANG), callback_data="bulk:review")],
            [InlineKeyboardButton(t("words.button.pause", _LANG), callback_data="bulk:pause")],
            [InlineKeyboardButton(t("words.button.delete", _LANG), callback_data="bulk:delete")],
            [InlineKeyboardButton(t("words.button.cancel", _LANG), callback_data="bulk:cancel")],
        ]
    )


def bulk_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.confirm_delete", _LANG), callback_data="bulk:delete_confirm")],
            [InlineKeyboardButton(t("words.button.cancel", _LANG), callback_data="bulk:cancel")],
        ]
    )
