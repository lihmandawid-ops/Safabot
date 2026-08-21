"""🔄 Повторить (repetition-system stage sections 1-2): ON-DEMAND REVIEW -
triggers immediately regardless of next_review_at, unlike the old
due-gated flow this used to call (handlers.learning.show_review_intro,
kept as-is for internal callers that still want the strict due-only
behavior). See handlers/review_now.py for the actual count-picker /
mode-picker / flashcard / quiz flow. Routed from handlers/menu.py.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.review_now import show_review_now_menu

MODE = "learning"


async def show_review_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_review_now_menu(update, context)
