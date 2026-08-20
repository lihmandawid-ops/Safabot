"""📖 Словарь (spec section 14 of the words stage's brief).

Entry point (start_search) is reached from the main menu's plain-text
"📖 Словарь" button, which sets context.user_data["mode"] = "dictionary"
(see handlers/menu.py's router) so the next free-text message the user
sends is treated as a search query rather than an unknown command.
Search is always scoped to the user's CURRENT learning language (spec
section 13 of the users stage: the one language marked ACTIVE) - a word
found here is only ever offered for learning under that language.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.models import WordSource
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from keyboards.dictionary import (
    batch_resume_keyboard,
    resume_offer_keyboard,
    search_results_keyboard,
    word_card_keyboard,
)
from services import dictionary_service, user_word_service, word_service
from utils.i18n import t
from utils.text import split_word_batch
from utils.word_display import render_forms_text, render_word_card_text, status_label

_LANG = "ru"
MODE = "dictionary"


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE, *, entry_source: str = "search") -> None:
    """entry_source distinguishes 📖 Словарь ("search", the default) from
    ⭐ Мои слова → ➕ Добавить слово ("manual") - both land on this exact
    same free-text handler (bugfix spec: never build two add
    implementations), the only difference is which WordSource newly added
    words get tagged with."""
    context.user_data["mode"] = MODE
    context.user_data["dictionary_entry_source"] = entry_source
    prompt_key = "words.add_prompt" if entry_source == "manual" else "dictionary.prompt"
    await update.message.reply_text(t(prompt_key, _LANG))


async def _current_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _entry_source(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("dictionary_entry_source", "search")


def _word_source(entry_source: str) -> str:
    return WordSource.MANUAL if entry_source == "manual" else WordSource.DICTIONARY


async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    async with session_scope() as session:
        user, current = await _current_language(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", _LANG))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", _LANG))
            return

        raw_words = split_word_batch(text)
        if len(raw_words) > 1:
            await _handle_batch_add(
                update.message.reply_text, session,
                user=user, current=current, raw_words=raw_words,
                source=_word_source(_entry_source(context)),
            )
            return

        query = raw_words[0] if raw_words else text
        results = await dictionary_service.lookup_word(
            session, language_code=current.language_code,
            translation_language=current.translation_language, raw_word=query,
        )

        if not results:
            await update.message.reply_text(t("dictionary.not_found", _LANG))
            return

        if len(results) == 1:
            await _send_card(update.message.reply_text, session, results[0].id, current.translation_language)
            return

        await update.message.reply_text(
            t("dictionary.results_header", _LANG), reply_markup=search_results_keyboard(results)
        )


async def _handle_batch_add(send, session, *, user, current, raw_words: list[str], source: str) -> None:
    """Bugfix spec: "поддержать одновременный ввод нескольких слов" with a
    numbered ✅/⚠️/❌ summary, reusing dictionary_service.lookup_word and
    user_word_service.add_word_to_learning for every entry - the exact
    same code path a single-word add uses, just looped.
    """
    added: list[tuple[int, str, str]] = []
    already: list[tuple[int, str, str]] = []
    paused_buttons: list[tuple[int, str]] = []
    failed: list[tuple[int, str]] = []

    for position, raw_word in enumerate(raw_words, start=1):
        results = await dictionary_service.lookup_word(
            session, language_code=current.language_code,
            translation_language=current.translation_language, raw_word=raw_word, limit=1,
        )
        if not results:
            failed.append((position, raw_word))
            continue

        word = results[0]
        result = await user_word_service.add_word_to_learning(
            session, user_id=user.id, word_id=word.id, language_code=current.language_code
        )
        translation = word.translations[0].translation if word.translations else ""

        if result.outcome in ("created", "restored_from_deleted"):
            result.user_word.source = source
            added.append((position, word.word, translation))
        else:
            already.append((position, word.word, result.user_word.status))
            if result.outcome == "offer_resume_paused":
                paused_buttons.append((result.user_word.id, word.word))

    lines = [t("words.batch_header", _LANG)]
    if added:
        lines.append("")
        lines.append(t("words.batch_added_header", _LANG, count=len(added)))
        lines.extend(
            f"{i}. {word} — {translation}" if translation else f"{i}. {word}" for i, word, translation in added
        )
    if already:
        lines.append("")
        lines.append(t("words.batch_already_header", _LANG, count=len(already)))
        lines.extend(f"{i}. {word} ({status_label(status)})" for i, word, status in already)
    if failed:
        lines.append("")
        lines.append(t("words.batch_failed_header", _LANG, count=len(failed)))
        lines.extend(f"{i}. {raw_word}" for i, raw_word in failed)

    keyboard = batch_resume_keyboard(paused_buttons) if paused_buttons else None
    await send("\n".join(lines), reply_markup=keyboard)


async def _send_card(send, session, word_id: int, translation_language: str) -> None:
    card = await word_service.get_word_card(session, word_id=word_id, translation_language=translation_language)
    if card is None:
        return
    await send(render_word_card_text(card), reply_markup=word_card_keyboard(word_id))


async def handle_dictionary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async with session_scope() as session:
        user, current = await _current_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", _LANG), show_alert=True)
            return

        if data.startswith("dict:open:"):
            word_id = int(data.removeprefix("dict:open:"))
            await query.answer()
            await _send_card(
                lambda text, reply_markup=None: query.message.reply_text(text, reply_markup=reply_markup),
                session,
                word_id,
                current.translation_language,
            )

        elif data == "dict:back":
            await query.answer()
            await query.edit_message_text(t("dictionary.prompt", _LANG))

        elif data.startswith("card:add:"):
            word_id = int(data.removeprefix("card:add:"))
            result = await user_word_service.add_word_to_learning(
                session, user_id=user.id, word_id=word_id, language_code=current.language_code
            )
            if result.outcome == "created":
                result.user_word.source = _word_source(_entry_source(context))
                await query.answer(t("dictionary.added", _LANG), show_alert=True)
            elif result.outcome == "restored_from_deleted":
                result.user_word.source = _word_source(_entry_source(context))
                await query.answer(t("dictionary.restored", _LANG), show_alert=True)
            elif result.outcome == "offer_resume_paused":
                await query.answer()
                await query.message.reply_text(
                    t("dictionary.offer_resume", _LANG), reply_markup=resume_offer_keyboard(result.user_word.id)
                )
            else:
                # already_active: never a silent generic message (bugfix
                # spec) - show the word's real current status so the user
                # understands why nothing changed.
                await query.answer(
                    t("dictionary.already_active_status", _LANG, status=status_label(result.user_word.status)),
                    show_alert=True,
                )

        elif data.startswith("card:forms:"):
            word_id = int(data.removeprefix("card:forms:"))
            card = await word_service.get_word_card(session, word_id=word_id)
            await query.answer(render_forms_text(card) if card else t("card.no_forms", _LANG), show_alert=True)

        elif data.startswith("card:pronounce:"):
            word_id = int(data.removeprefix("card:pronounce:"))
            card = await word_service.get_word_card(session, word_id=word_id)
            text = (
                t("card.pronunciation_line", _LANG, pronunciation=card.word.pronunciation)
                if card and card.word.pronunciation
                else t("card.pronunciation_placeholder", _LANG)
            )
            await query.answer(text, show_alert=True)

        elif data.startswith("card:usage:"):
            word_id = int(data.removeprefix("card:usage:"))
            card = await word_service.get_word_card(session, word_id=word_id, translation_language=current.translation_language)
            notes = [tr.usage_note for tr in card.translations if tr.usage_note] if card else []
            text = notes[0] if notes else t("card.usage_placeholder", _LANG)
            await query.answer(text, show_alert=True)

        elif data.startswith("dict:resume:"):
            user_word_id = int(data.removeprefix("dict:resume:"))
            user_word = await user_words_repo.get_by_id(session, user_word_id)
            if user_word is not None and user_word.user_id == user.id:
                await user_word_service.resume_word(session, user_word)
                await query.answer()
                await query.edit_message_text(t("words.resumed_single", _LANG))

        elif data.startswith("dict:resume_no:"):
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)


dictionary_callback_handler = CallbackQueryHandler(handle_dictionary_callback, pattern="^(dict|card):")
