"""Safabot entry point (spec section 34, Stage 2).

Builds the python-telegram-bot Application, wires up the handlers that
exist so far, and runs polling. Run with:

    python bot.py
"""
from __future__ import annotations

from pathlib import Path

from telegram import Update
from telegram.ext import Application, ContextTypes, PicklePersistence

from config import BASE_DIR, get_settings
from database.database import init_models, session_scope
from database.repositories import languages as languages_repo
from database.seed import seed_languages
from database.seed_words import seed_words
from handlers.dictionary import dictionary_callback_handler
from handlers.learning import learning_callback_handler
from handlers.menu import main_menu_handler
from handlers.phrases import phrases_callback_handler
from handlers.quiz import quiz_callback_handler
from handlers.review_now import review_now_callback_handler
from handlers.settings import settings_callback_handler
from handlers.start import start_conversation_handler
from handlers.text_analysis import text_analysis_callback_handler
from handlers.words import words_callback_handler
from scheduler.notifications import register_notification_jobs
from services.ai_diagnostics import test_ai_gateway_connection, test_deepseek_connection, test_gemini_connection
from utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

PERSISTENCE_FILE = BASE_DIR / "safabot_persistence.pickle"


async def on_startup(application: Application) -> None:
    await init_models()
    async with session_scope() as session:
        await seed_languages(session)
        languages = await languages_repo.get_all_active(session)
        word_count = await seed_words(session)
    logger.info("Database ready (%d languages seeded, %d words seeded)", len(languages), word_count)

    # Non-blocking: a broken/unconfigured AI connection must never stop
    # the bot from starting - every AI-backed text feature already falls
    # back down the configured provider chain (Vercel AI Gateway -> Gemini
    # -> DeepSeek -> local database) on its own. This just logs whether
    # each configured provider is actually usable, checked in the same
    # priority order get_ai_service() tries them in.
    gateway_result = await test_ai_gateway_connection()
    if not gateway_result.ok:
        logger.warning(
            "Vercel AI Gateway connection check failed (reason=%s): %s", gateway_result.reason, gateway_result.detail
        )

    gemini_result = await test_gemini_connection()
    if not gemini_result.ok:
        logger.warning("Gemini connection check failed (reason=%s): %s", gemini_result.reason, gemini_result.detail)

    deepseek_result = await test_deepseek_connection()
    if not deepseek_result.ok:
        logger.warning(
            "DeepSeek connection check failed (reason=%s): %s", deepseek_result.reason, deepseek_result.detail
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler (spec section 30): log the real exception, tell
    the user something went wrong without leaking internals."""
    logger.exception("Unhandled exception while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "⚠️ Что-то пошло не так. Мы уже разбираемся, попробуйте ещё раз чуть позже."
        )


def build_application() -> Application:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill in your Telegram bot token."
        )

    # Persists ConversationHandler state and user_data to disk (spec
    # section 5: onboarding must survive a bot restart, not just live in
    # process memory).
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

    application = (
        Application.builder()
        .token(settings.bot_token)
        .persistence(persistence)
        .post_init(on_startup)
        .build()
    )

    application.add_handler(start_conversation_handler)
    application.add_handler(settings_callback_handler)
    application.add_handler(dictionary_callback_handler)
    application.add_handler(words_callback_handler)
    application.add_handler(learning_callback_handler)
    application.add_handler(quiz_callback_handler)
    application.add_handler(review_now_callback_handler)
    application.add_handler(text_analysis_callback_handler)
    application.add_handler(phrases_callback_handler)
    application.add_handler(main_menu_handler)
    application.add_error_handler(on_error)

    register_notification_jobs(application)

    return application


def main() -> None:
    configure_logging()
    application = build_application()
    logger.info("Starting Safabot (polling)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
