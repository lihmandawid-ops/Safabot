"""Safabot entry point (spec section 34, Stage 2).

Builds the python-telegram-bot Application, wires up the handlers that
exist so far, and runs polling. Run with:

    python bot.py
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ContextTypes

from config import get_settings
from database.database import init_models
from handlers.menu import main_menu_handler
from handlers.start import start_conversation_handler
from utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def on_startup(application: Application) -> None:
    await init_models()
    logger.info("Database ready")


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

    application = Application.builder().token(settings.bot_token).post_init(on_startup).build()

    application.add_handler(start_conversation_handler)
    application.add_handler(main_menu_handler)
    application.add_error_handler(on_error)

    return application


def main() -> None:
    configure_logging()
    application = build_application()
    logger.info("Starting Safabot (polling)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
