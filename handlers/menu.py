"""Routes taps on the main menu keyboard (spec section 9) to their
handlers. Sections not implemented yet reply with a short, honest
"coming in Stage N" message instead of pretending to work - see
DEVELOPMENT RULES (spec section 34) for the stage order.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from handlers import settings as settings_handler
from keyboards import main_menu

_COMING_SOON: dict[str, str] = {
    main_menu.LEARN_WORDS: "Учить слова (Этап 6)",
    main_menu.REVIEW: "Повторить (Этап 7)",
    main_menu.DICTIONARY: "Словарь (Этап 9)",
    main_menu.MY_WORDS: "Мои слова (Этап 8)",
    main_menu.PARSE_PHOTO: "Разбор фото (Этап 15)",
    main_menu.PARSE_TEXT: "Разбор текста (Этап 14, AI)",
    main_menu.PARSE_VOICE: "Разбор голоса (Этап 16)",
    main_menu.PROGRESS: "Мой прогресс (Этап 11)",
    main_menu.PRO: "PRO-подписка (Этап 13)",
}


async def route_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text

    if text == main_menu.SETTINGS:
        await settings_handler.show_settings(update, context)
        return

    label = _COMING_SOON.get(text)
    if label is not None:
        await update.message.reply_text(f"🚧 Раздел «{label}» пока в разработке. Загляните позже!")
        return

    await update.message.reply_text("Не понимаю эту команду. Используйте меню ниже.")


main_menu_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, route_main_menu)
