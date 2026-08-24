"""Inline keyboards for 🔁 Повторить - ON-DEMAND REVIEW (repetition-
system stage sections 1-7)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t

# Matches services.notification_service.SLOT_MORNING's value - a bare
# string rather than importing it, since notification_service imports
# notification_keyboard from this module and importing back would be
# circular.
_SLOT_MORNING = "morning"


def review_pool_keyboard() -> InlineKeyboardMarkup:
    """🔄 Повторить (bugfix stage sections 38-42): exactly two options,
    nothing else - no count question, Safabot picks how many words on its
    own (AUTO_REVIEW_COUNT in handlers/review_now.py)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.review_new", get_current_language()), callback_data="revnow:menu")],
            [InlineKeyboardButton(t("revnow.button.review_mastered", get_current_language()), callback_data="revnow:menu:mastered")],
            [InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="revnow:cancel")],
        ]
    )


def mode_picker_keyboard(*, count: int, mastered: bool) -> InlineKeyboardMarkup:
    flag = "1" if mastered else "0"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.flashcard_mode", get_current_language()), callback_data=f"revnow:mode:flashcard:{count}:{flag}")],
            [InlineKeyboardButton(t("revnow.button.quiz_mode", get_current_language()), callback_data=f"revnow:mode:quiz:{count}:{flag}")],
        ]
    )


def flashcard_keyboard() -> InlineKeyboardMarkup:
    """study-flow-rework stage (real user feedback): simplified to just two
    buttons - 🏆 Уже выучено (services.user_word_service.mark_mastered,
    skips straight to MASTERED) and ➡️ Далее (moves to the next word
    without touching this word's repetition schedule at all - explicit
    product decision: a skip is not an answer). The old ✅/❌ Знаю/Не знаю
    grading row (which fed learning_service.record_on_demand_answer) is
    removed from this flow."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.already_learned", get_current_language()), callback_data="revnow:mastered")],
            [InlineKeyboardButton(t("revnow.button.next", get_current_language()), callback_data="revnow:next")],
        ]
    )


def empty_keyboard() -> InlineKeyboardMarkup:
    """study-flow-rework stage sections 20-21: the on-demand-review pool
    being empty is never a dead end - 🆕 Выучить новые слова routes into
    the EXACT SAME "🆕 Получить новые слова" flow as handlers/learning.py's
    own learn:newwords entry point (cross-handler callback_data reuse -
    every CallbackQueryHandler is registered globally in bot.py, so this
    button works with zero new wiring on the learning.py side)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.start_learning", get_current_language()), callback_data="learn:newwords")],
            [InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="revnow:mainmenu")],
        ]
    )


def notification_keyboard(slot: str) -> InlineKeyboardMarkup:
    """🔔 Быстрое повторение (repetition-system stage sections 10, 16-17):
    the flashcard button reuses the on-demand review launcher
    (handlers/review_now.py's "revnow:notif:" branch), which re-reads the
    exact word list this notification was logged with
    (NotificationLog.word_ids) rather than re-selecting - so what the user
    taps into is exactly what they were shown.

    Real user request ("утром после полученных двух новых слов должна
    проходить викторина для повторения всех слов" - in the morning, after
    the two new words, a quiz should run to review ALL words): the
    morning slot's quiz button is the one exception - it launches
    quiz:start (handlers/quiz.py), the SAME "review everything" quiz
    reachable from the main menu, rather than a quiz scoped to just this
    notification's small selected word list. Afternoon/evening keep the
    notification-scoped quiz, since those slots don't add new words."""
    quiz_callback = "quiz:start" if slot == _SLOT_MORNING else f"revnow:notif:{slot}:quiz"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.start_now", get_current_language()), callback_data=f"revnow:notif:{slot}:flashcard")],
            [InlineKeyboardButton(t("revnow.button.quiz_mode", get_current_language()), callback_data=quiz_callback)],
            [InlineKeyboardButton(t("revnow.button.skip", get_current_language()), callback_data="revnow:skip")],
        ]
    )


def completion_keyboard() -> InlineKeyboardMarkup:
    """AI-new-words stage sections 14-15, 26: after a review session, never
    offer a way back into 📚 Учить слова from here - only ▶️ Начать
    следующее повторение (reuses the existing count-free revnow:menu pool-
    choice screen - "which pool" is not the "how many words" question the
    spec forbids asking), 🏆 Викторина, and the main menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("revnow.button.again", get_current_language()), callback_data="revnow:menu")],
            [InlineKeyboardButton(t("quiz.button.start", get_current_language()), callback_data="quiz:start")],
            [InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="revnow:mainmenu")],
        ]
    )
