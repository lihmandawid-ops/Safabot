"""🔄 Повторить (learning-core stage, section 8's priority order: due
reviews only, never new words).

Thin wrapper: the whole word -> reveal -> rate -> next word loop, the
callback handler, and the resume logic are shared with 📚 Учить слова -
see handlers/learning.py, which build_learning_session's
include_new_words flag already distinguishes. Routed from
handlers/menu.py.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.learning import show_review_intro

MODE = "learning"


async def show_review_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_review_intro(update, context)
