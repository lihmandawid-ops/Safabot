"""Keyboards for ⭐ Мои слова: filters, pagination, per-word action menu,
bulk-selection menu, and delete confirmation (spec sections 8, 10-13).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import WordStatus
from utils.i18n import get_current_language, t
from utils.pagination import NEXT_LABEL, PREVIOUS_LABEL


def filter_keyboard() -> InlineKeyboardMarkup:
    """📚 Мои слова (bugfix stage: "Мои слова" restructure; AI-new-words
    stage section 18: plain button labels, no 1️⃣-5️⃣ numbering prefix) -
    EXACTLY 5 sections, nothing else: all words, words not yet mastered
    (NEW+LEARNING+REVIEW+PAUSED - "words:filter:review" wasn't renamed,
    only widened; see user_word_service.FILTER_STATUSES's docstring for
    why NEW/PAUSED belong here too), mastered words, search-your-own-words,
    AI-backed add. The old "Новые"/"Приостановлено" top-level filters are
    gone from THIS screen only - words.py's underlying "new"/"paused"
    filter codes and callback branches are untouched, so no capability is
    actually lost, just no longer a top-level button here. In-list word
    numbering (rendered separately, in _render_list_text) is unaffected -
    only the MENU buttons dropped their emoji-digit prefix."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.filter.all", get_current_language()), callback_data="words:filter:all")],
            [InlineKeyboardButton(t("words.filter.review", get_current_language()), callback_data="words:filter:review")],
            [InlineKeyboardButton(t("words.filter.mastered", get_current_language()), callback_data="words:filter:mastered")],
            [InlineKeyboardButton(t("words.search_button", get_current_language()), callback_data="words:search")],
            [InlineKeyboardButton(t("words.add_button", get_current_language()), callback_data="words:add")],
        ]
    )


def list_keyboard(*, has_previous: bool, has_next: bool) -> InlineKeyboardMarkup:
    nav_row = []
    if has_previous:
        nav_row.append(InlineKeyboardButton(PREVIOUS_LABEL, callback_data="words:page:prev"))
    if has_next:
        nav_row.append(InlineKeyboardButton(NEXT_LABEL, callback_data="words:page:next"))

    rows = [nav_row] if nav_row else []
    rows.append([InlineKeyboardButton(t("words.button.back", get_current_language()), callback_data="words:filters")])
    return InlineKeyboardMarkup(rows)


def single_word_keyboard(user_word_id: int, status: str | None = None, *, filter_code: str | None = None) -> InlineKeyboardMarkup:
    """Manual repetition control (settings-improvements stage section 3):
    the action row reflects the word's ACTUAL current status instead of
    always offering both "add to review" and "pause" - a word that's
    already actively being reviewed has no use for a redundant "add to
    review" tap, and a PAUSED or MASTERED word has no use for "pause".
    `status` is optional only so old code paths that don't have it yet
    keep working; omitting it falls back to the previous always-show-both
    behaviour.

    `filter_code` (real user feedback) is which "Мои слова" section the
    word was opened from - the manage screen's ⏸ pause action means
    something different depending on that section:
    - "review" (📚 Повторение, LEARNING/REVIEW words only): pressing it
      must move the word straight to выученные, same as the flashcard
      review's 🏆 Уже выучено, not just pause it out of the schedule.
    - "all" (📋 Все): the pause action is dropped from this screen
      entirely - it stays reachable from the word's own "Повторение"
      listing instead of duplicating a control here.
    Any other section (or no filter context, e.g. reached via search)
    keeps the original ⏸ pause behaviour."""
    rows = []
    if status == WordStatus.PAUSED or status == WordStatus.MASTERED:
        rows.append([InlineKeyboardButton(t("words.button.review", get_current_language()), callback_data=f"uw:review:{user_word_id}")])
    elif status is None:
        rows.append([InlineKeyboardButton(t("words.button.review", get_current_language()), callback_data=f"uw:review:{user_word_id}")])
        rows.append([InlineKeyboardButton(t("words.button.pause", get_current_language()), callback_data=f"uw:pause:{user_word_id}")])
    elif filter_code == "all":
        pass
    elif filter_code == "review":
        rows.append([InlineKeyboardButton(t("revnow.button.already_learned", get_current_language()), callback_data=f"uw:mastered:{user_word_id}")])
    else:
        rows.append([InlineKeyboardButton(t("words.button.pause", get_current_language()), callback_data=f"uw:pause:{user_word_id}")])
    rows.append([InlineKeyboardButton(t("words.button.delete", get_current_language()), callback_data=f"uw:delete:{user_word_id}")])
    rows.append([InlineKeyboardButton(t("words.button.open_card", get_current_language()), callback_data=f"uw:card:{user_word_id}")])
    rows.append([InlineKeyboardButton(t("words.button.back", get_current_language()), callback_data="uw:list_back")])
    return InlineKeyboardMarkup(rows)


def delete_confirm_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.confirm_delete", get_current_language()), callback_data=f"uw:delete_confirm:{user_word_id}")],
            [InlineKeyboardButton(t("words.button.cancel", get_current_language()), callback_data=f"uw:delete_cancel:{user_word_id}")],
        ]
    )


def bulk_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.review", get_current_language()), callback_data="bulk:review")],
            [InlineKeyboardButton(t("words.button.pause", get_current_language()), callback_data="bulk:pause")],
            [InlineKeyboardButton(t("words.button.delete", get_current_language()), callback_data="bulk:delete")],
            [InlineKeyboardButton(t("words.button.cancel", get_current_language()), callback_data="bulk:cancel")],
        ]
    )


def bulk_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("words.button.confirm_delete", get_current_language()), callback_data="bulk:delete_confirm")],
            [InlineKeyboardButton(t("words.button.cancel", get_current_language()), callback_data="bulk:cancel")],
        ]
    )
