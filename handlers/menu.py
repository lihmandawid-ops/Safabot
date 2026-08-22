"""Routes taps on the main menu keyboard (spec section 9) to their
handlers. Sections not implemented yet reply with a short, honest
"coming in Stage N" message instead of pretending to work - see
DEVELOPMENT RULES (spec section 34) for the stage order.

Once a section that expects free-text follow-up (📖 Словарь, ⭐ Мои слова)
is entered, context.user_data["mode"] records which one so the next
non-menu-button message is routed to that section instead of falling
through to "unknown command" - see handlers/dictionary.py and
handlers/words.py for what each mode does with that text.

settings-improvements stage: this is the single choke point almost every
plain-text update passes through, so it's also where
utils.i18n.set_current_language() gets set for the whole update - every
t() call made anywhere further down the same call chain (including
inside handlers this dispatches to) picks it up automatically. Button
taps are matched via keyboards.main_menu.resolve_menu_action() rather
than comparing `text` against a fixed Russian string, since the same
button now renders in whichever language the user has chosen.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from database.database import session_scope
from database.repositories import users as users_repo
from handlers import dictionary as dictionary_handler
from handlers import grammar as grammar_handler
from handlers import learning as learning_handler
from handlers import media as media_handler
from handlers import phrases as phrases_handler
from handlers import review as review_handler
from handlers import settings as settings_handler
from handlers import text_analysis as text_analysis_handler
from handlers import words as words_handler
from keyboards import main_menu
from keyboards.main_menu import resolve_menu_action
from utils.i18n import set_current_language, t

_COMING_SOON: dict[str, str] = {
    main_menu.PROGRESS: "menu.feature.progress",
    main_menu.PRO: "menu.feature.pro",
}

_LANG = "ru"


async def route_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
    set_current_language(user.interface_language if user else None)
    language = user.interface_language if user else _LANG

    text = update.message.text
    action = resolve_menu_action(text)

    if action == main_menu.SETTINGS:
        context.user_data.pop("mode", None)
        await settings_handler.show_settings(update, context)
        return

    if action == main_menu.DICTIONARY:
        context.user_data.pop("mode", None)
        await dictionary_handler.start_search(update, context)
        return

    if action == main_menu.MY_WORDS:
        context.user_data.pop("mode", None)
        await words_handler.show_words_menu(update, context)
        return

    if action == main_menu.LEARN_WORDS:
        context.user_data.pop("mode", None)
        await learning_handler.show_learning_intro(update, context)
        return

    if action == main_menu.REVIEW:
        context.user_data.pop("mode", None)
        await review_handler.show_review_menu(update, context)
        return

    if action == main_menu.PARSE_TEXT:
        context.user_data.pop("mode", None)
        await text_analysis_handler.start_text_analysis(update, context)
        return

    if action == main_menu.GRAMMAR:
        context.user_data.pop("mode", None)
        await grammar_handler.start_grammar(update, context)
        return

    if action == main_menu.PHRASES:
        context.user_data.pop("mode", None)
        await phrases_handler.show_phrases_menu(update, context)
        return

    if action == main_menu.PARSE_PHOTO:
        context.user_data.pop("mode", None)
        await media_handler.prompt_for_photo(update, context)
        return

    if action == main_menu.PARSE_VOICE:
        context.user_data.pop("mode", None)
        await media_handler.prompt_for_voice(update, context)
        return

    feature_key = _COMING_SOON.get(action) if action else None
    if feature_key is not None:
        context.user_data.pop("mode", None)
        await update.message.reply_text(t("menu.coming_soon", language, feature=t(feature_key, language)))
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
    if mode == grammar_handler.MODE:
        await grammar_handler.handle_text_input(update, context, text)
        return
    if mode == settings_handler.MODE:
        await settings_handler.handle_text_input(update, context, text)
        return
    if mode == phrases_handler.MODE:
        await phrases_handler.handle_text_input(update, context, text)
        return

    await update.message.reply_text(t("menu.unknown_command", language))


main_menu_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, route_main_menu)
