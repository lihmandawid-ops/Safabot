"""📝 Разбор текста (AI-integration spec sections 15-16).

Entry point (start_text_analysis) is reached from the main menu's plain-
text "📝 Разобрать текст" button, which sets context.user_data["mode"] =
"text_analysis" (see handlers/menu.py's router) so the next free-text
message is treated as either a new text to analyze, or - if results are
already on screen - a number selection like "1,3" picking specific key
words out of them (same UX as ⭐ Мои слова's numbered bulk-select).

Adding words (⭐ Добавить все / ⭐ Добавить выбранные) reuses
handlers.dictionary.add_word_batch wholesale - the exact same lookup +
UserWordService path 📖 Словарь and ➕ Добавить слово use, just tagged
source=WordSource.AI since these came out of an AI text analysis
(spec section 16: never a second add-words implementation).
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import get_settings
from database.database import session_scope
from database.models import WordSource
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from handlers.dictionary import add_word_batch
from keyboards.text_analysis import results_keyboard, selection_keyboard
from services.ai_errors import AIConfigurationError, AIError
from services.ai_service import get_ai_service
from utils.i18n import t
from utils.text import parse_number_list

_LANG = "ru"
MODE = "text_analysis"


async def start_text_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = MODE
    context.user_data.pop("text_analysis", None)
    await update.message.reply_text(t("text_analysis.prompt", _LANG))


async def _current_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _render_results(text: str, translation: str, key_words: list[tuple[str, str]], phrases: list[str]) -> str:
    lines = [t("text_analysis.title", _LANG), "", text, translation]
    if key_words:
        lines.append("")
        lines.append(t("text_analysis.key_words_header", _LANG))
        lines.extend(f"{i}. {word} — {translation}" for i, (word, translation) in enumerate(key_words, start=1))
    else:
        lines.append("")
        lines.append(t("text_analysis.no_key_words", _LANG))
    if phrases:
        lines.append("")
        lines.append(t("text_analysis.phrases_header", _LANG))
        lines.extend(f"- {phrase}" for phrase in phrases)
    lines.append("")
    lines.append(t("text_analysis.select_hint", _LANG))
    return "\n".join(lines)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    cache = context.user_data.get("text_analysis")
    if cache is not None:
        try:
            numbers = parse_number_list(text)
        except ValueError:
            numbers = None
        if numbers is not None:
            await _handle_selection(update, context, cache, numbers)
            return
        # Not a number list - treat as a brand new text to analyze,
        # replacing whatever was cached from the previous one.

    max_length = get_settings().max_text_length
    if len(text) > max_length:
        await update.message.reply_text(t("text_analysis.too_long", _LANG, max_length=max_length))
        return

    async with session_scope() as session:
        user, current = await _current_language(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", _LANG))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", _LANG))
            return

        try:
            result = await get_ai_service().analyze_text(
                text, language_code=current.language_code,
                translation_language=current.translation_language,
                interface_language=user.interface_language, user_id=user.id,
            )
        except AIConfigurationError:
            context.user_data.pop("text_analysis", None)
            await update.message.reply_text(t("ai.not_configured", _LANG))
            return
        except AIError:
            context.user_data.pop("text_analysis", None)
            await update.message.reply_text(t("ai.generic_error", _LANG))
            return

        key_words = [(kw.word, kw.translation) for kw in result.key_words]
        context.user_data["text_analysis"] = {"words": [kw.word for kw in result.key_words]}
        await update.message.reply_text(
            _render_results(result.original_text, result.translation, key_words, result.useful_phrases),
            reply_markup=results_keyboard() if key_words else None,
        )


async def _handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, cache: dict, numbers: list[int]) -> None:
    words = cache["words"]
    out_of_range = [n for n in numbers if n < 1 or n > len(words)]
    if out_of_range:
        await update.message.reply_text(
            t("text_analysis.out_of_range", _LANG, numbers=", ".join(str(n) for n in out_of_range))
        )
        return

    selected = [words[n - 1] for n in numbers]
    context.user_data["text_analysis"]["selected"] = selected
    lines = [t("text_analysis.selected_header", _LANG)]
    lines.extend(f"{n}. {words[n - 1]}" for n in numbers)
    await update.message.reply_text("\n".join(lines), reply_markup=selection_keyboard())


async def handle_text_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    cache = context.user_data.get("text_analysis")

    if data == "textan:cancel":
        await query.answer(t("text_analysis.cancelled", _LANG))
        return

    if cache is None:
        await query.answer(t("text_analysis.expired", _LANG), show_alert=True)
        return

    if data == "textan:add_all":
        raw_words = cache.get("words") or []
    elif data == "textan:add_selected":
        raw_words = cache.get("selected") or []
    else:
        return

    if not raw_words:
        await query.answer(t("text_analysis.expired", _LANG), show_alert=True)
        return

    await query.answer()
    async with session_scope() as session:
        user, current = await _current_language(session, query.from_user.id)
        if user is None or current is None:
            await query.message.reply_text(t("card.no_language", _LANG))
            return
        await add_word_batch(
            query.message.reply_text, session,
            user=user, current=current, raw_words=raw_words, source=WordSource.AI,
        )
    context.user_data.pop("text_analysis", None)


text_analysis_callback_handler = CallbackQueryHandler(handle_text_analysis_callback, pattern="^textan:")
