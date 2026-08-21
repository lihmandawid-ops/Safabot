"""✏️ Грамматика (AI-integration spec section 17): free-form grammar Q&A,
e.g. "Why do we say 'went' instead of 'goed'?" - a standalone main-menu
entry, not tied to any specific word/card.

Answered via services.ai_service.get_ai_service().explain_grammar(),
never a direct AI API call from here - and with the learning language,
translation language, interface language, and user level all passed
explicitly (spec section 18: never let the AI guess these).
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from services.ai_errors import AIConfigurationError, AIError
from services.ai_service import get_ai_service
from utils.i18n import get_current_language, set_current_language, t

MODE = "grammar"


async def start_grammar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = MODE
    await update.message.reply_text(t("grammar.prompt", get_current_language()))


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        set_current_language(user.interface_language)
        current = await user_languages_repo.get_current_language(session, user.id)
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        try:
            explanation = await get_ai_service().explain_grammar(
                text,
                language_code=current.language_code,
                level=current.level,
                interface_language=user.interface_language,
                user_id=user.id,
            )
        except AIConfigurationError:
            await update.message.reply_text(t("ai.not_configured", get_current_language()))
            return
        except AIError:
            await update.message.reply_text(t("ai.generic_error", get_current_language()))
            return

        await update.message.reply_text(explanation)
