"""Routes taps on the main menu keyboard (spec section 9) to their
handlers. Sections not implemented yet reply with a short, honest
"coming in Stage N" message instead of pretending to work - see
DEVELOPMENT RULES (spec section 34) for the stage order.

Once a section that expects free-text follow-up (📖 Словарь, ⭐ Мои слова)
is entered, context.user_data["mode"] records which one so the next
non-menu-button message is routed to that section instead of falling
through to "unknown command" - see handlers/dictionary.py and
handlers/words.py for what each mode does with that text.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from handlers import dictionary as dictionary_handler
from handlers import learning as learning_handler
from handlers import review as review_handler
from handlers import settings as settings_handler
from handlers import text_analysis as text_analysis_handler
from handlers import words as words_handler
from keyboards import main_menu
from utils.i18n import t

_COMING_SOON: dict[str, str] = {
    main_menu.PARSE_PHOTO: "Разбор фото (Этап 15)",
    main_menu.PARSE_VOICE: "Разбор голоса (Этап 16)",
    main_menu.PROGRESS: "Мой прогресс (Этап 11)",
    main_menu.PRO: "PRO-подписка (Этап 13)",
}

_LANG = "ru"


async def route_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text

    if text == main_menu.SETTINGS:
        context.user_data.pop("mode", None)
        await settings_handler.show_settings(update, context)
        return

    if text == main_menu.DICTIONARY:
        context.user_data.pop("mode", None)
        await dictionary_handler.start_search(update, context)
        return

    if text == main_menu.MY_WORDS:
        context.user_data.pop("mode", None)
        await words_handler.show_words_menu(update, context)
        return

    if text == main_menu.LEARN_WORDS:
        context.user_data.pop("mode", None)
        await learning_handler.show_learning_intro(update, context)
        return

    if text == main_menu.REVIEW:
        context.user_data.pop("mode", None)
        await review_handler.show_review_menu(update, context)
        return

    if text == main_menu.PARSE_TEXT:
        context.user_data.pop("mode", None)
        await text_analysis_handler.start_text_analysis(update, context)
        return

    label = _COMING_SOON.get(text)
    if label is not None:
        context.user_data.pop("mode", None)
        await update.message.reply_text(t("menu.coming_soon", _LANG, feature=label))
        return

    mode = context.user_data.get("mode")
    if mode == dictionary_handler.MODE:
        await dictionary_handler.handle_search_query(update, context, text)
        return
    if mode == words_handler.MODE:
        await words_handler.handle_text_input(update, context, text)
        return
    if mode == text_analysis_handler.MODE:
        await text_analysis_handler.handle_text_input(update, context, text)
        return

    await update.message.reply_text(t("menu.unknown_command", _LANG))


main_menu_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, route_main_menu)
