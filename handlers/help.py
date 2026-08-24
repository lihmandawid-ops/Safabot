"""/help (real user request): a second, always-reachable way to find the
🆘 support contact - independent of ⚙️ Настройки, for a user hitting an
error bad enough that navigating the menu isn't appealing.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from database.database import session_scope
from database.repositories import users as users_repo
from utils.i18n import get_current_language, set_current_language
from utils.support import support_message


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user
    assert telegram_user is not None

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, telegram_user.id)

    set_current_language(user.interface_language if user is not None else get_current_language())
    await update.message.reply_text(support_message(get_current_language()))
