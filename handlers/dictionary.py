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
from database.models import WordSource, WordStatus
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories import words as words_repo
from keyboards.dictionary import (
    batch_resume_keyboard,
    forms_close_keyboard,
    resume_offer_keyboard,
    search_results_keyboard,
    word_card_keyboard,
)
from services import dictionary_service, pronunciation_service, user_word_service, verb_forms_service, word_service
from services.ai_errors import AIConfigurationError, AIError
from services.ai_service import get_ai_service
from utils.i18n import get_current_language, set_current_language, t
from utils.telegram_helpers import safe_edit_message_reply_markup, safe_edit_message_text
from utils.text import split_word_batch, truncate_text
from utils.word_display import (
    render_conjugation_messages,
    render_forms_text,
    render_word_card_text,
    status_label,
)

MODE = "dictionary"
# Bugfix stage, real-Telegram feedback: 💡 Как использовать? must stay a
# short chat message rather than a wall of text - the prompt asks the AI
# to be brief, this is the guaranteed-outcome safety net regardless of
# how well the model actually complies.
_USAGE_EXPLANATION_MAX_LENGTH = 200


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE, *, entry_source: str = "search") -> None:
    """entry_source distinguishes 📖 Словарь ("search", the default) from
    ⭐ Мои слова → ➕ Добавить слово ("manual") - both land on this exact
    same free-text handler (bugfix spec: never build two add
    implementations), the only difference is which WordSource newly added
    words get tagged with."""
    context.user_data["mode"] = MODE
    context.user_data["dictionary_entry_source"] = entry_source
    prompt_key = "words.add_prompt" if entry_source == "manual" else "dictionary.prompt"
    await update.message.reply_text(t(prompt_key, get_current_language()))


async def _current_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
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
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        raw_words = split_word_batch(text)
        if len(raw_words) > 1:
            await add_word_batch(
                update.message.reply_text, session,
                user=user, current=current, raw_words=raw_words,
                source=_word_source(_entry_source(context)),
            )
            return

        query = raw_words[0] if raw_words else text

        # Real user request: a local hit resolves instantly, but the AI
        # fallback (services.dictionary_service.lookup_word's second half)
        # can take several seconds - show "🔎 Идёт поиск слова..." ONLY
        # when we're actually about to fall through to AI, never for a
        # cached local hit (which would just flash and vanish). Checking
        # locally first also means a real hit here skips the redundant
        # second local lookup that lookup_word would otherwise do internally.
        local_matches = await word_service.search_words(
            session, language_code=current.language_code, query=query, limit=5
        )
        loading_message = None
        if not local_matches:
            loading_message = await update.message.reply_text(t("dictionary.searching", get_current_language()))

        results = local_matches or await dictionary_service.lookup_word(
            session, language_code=current.language_code,
            translation_language=current.translation_language, raw_word=query,
            user_id=user.id, user_level=current.level,
        )

        # Edit the "🔎 Идёт поиск..." placeholder into the real result in
        # place, rather than leaving it behind as a stray extra message.
        send = loading_message.edit_text if loading_message is not None else update.message.reply_text

        if not results:
            await send(t("dictionary.not_found", get_current_language()))
            return

        if len(results) == 1:
            await _send_card(send, session, results[0].id, current.translation_language, user_id=user.id)
            return

        await send(
            t("dictionary.results_header", get_current_language()), reply_markup=search_results_keyboard(results)
        )


async def add_word_batch(send, session, *, user, current, raw_words: list[str], source: str) -> None:
    """Bugfix spec: "поддержать одновременный ввод нескольких слов" with a
    numbered ✅/⚠️/❌ summary, reusing dictionary_service.lookup_word and
    user_word_service.add_word_to_learning for every entry - the exact
    same code path a single-word add uses, just looped.

    Public (not underscore-prefixed) because handlers/text_analysis.py's
    "⭐ Добавить все/выбранные" reuses this exact function for words
    picked out of an AI text analysis, instead of a second add-multiple-
    words implementation (AI-integration spec section 16: "использовать
    существующий UserWordService, не создавать отдельную систему
    добавления слов").
    """
    added: list[tuple[int, str, str]] = []
    already: list[tuple[int, str, str]] = []
    paused_buttons: list[tuple[int, str]] = []
    failed: list[tuple[int, str]] = []

    for position, raw_word in enumerate(raw_words, start=1):
        results = await dictionary_service.lookup_word(
            session, language_code=current.language_code,
            translation_language=current.translation_language, raw_word=raw_word, limit=1,
            user_id=user.id, user_level=current.level,
        )
        if not results:
            failed.append((position, raw_word))
            continue

        word = results[0]
        # Real user request: a word added here is a LIVE, user-facing
        # add - it must enter repetition immediately, not sit as an
        # untouched NEW candidate only the (now unreachable) daily-quota
        # flow would ever pick up.
        result = await user_word_service.add_word_to_learning(
            session, user_id=user.id, word_id=word.id, language_code=current.language_code, status=WordStatus.LEARNING
        )
        translation = word.translations[0].translation if word.translations else ""

        if result.outcome in ("created", "restored_from_deleted"):
            result.user_word.source = source
            added.append((position, word.word, translation))
        else:
            already.append((position, word.word, result.user_word.status))
            if result.outcome == "offer_resume_paused":
                paused_buttons.append((result.user_word.id, word.word))

    lines = [t("words.batch_header", get_current_language())]
    if added:
        lines.append("")
        lines.append(t("words.batch_added_header", get_current_language(), count=len(added)))
        lines.extend(
            f"{i}. {word} — {translation}" if translation else f"{i}. {word}" for i, word, translation in added
        )
    if already:
        lines.append("")
        lines.append(t("words.batch_already_header", get_current_language(), count=len(already)))
        lines.extend(f"{i}. {word} ({status_label(status)})" for i, word, status in already)
    if failed:
        lines.append("")
        lines.append(t("words.batch_failed_header", get_current_language(), count=len(failed)))
        lines.extend(f"{i}. {raw_word}" for i, raw_word in failed)

    keyboard = batch_resume_keyboard(paused_buttons) if paused_buttons else None
    await send("\n".join(lines), reply_markup=keyboard)


async def _explain_word_text(card, current, user) -> str:
    """💡 Как использовать? (AI-integration spec section 10). Falls back to
    the word's local usage_note (section 28: Dictionary must never break
    when AI is unavailable), and only as a last resort to a placeholder.
    """
    try:
        # AIService's "interface_language" param picks the prose response
        # language - deliberately current.translation_language here, not
        # user.interface_language (the global menu language): they can
        # differ (a user can browse menus in English while translating
        # this learning language into Hebrew), and the explanation must
        # match the translation, never the menu chrome.
        explanation = await get_ai_service().explain_word(
            card.word.word, language_code=current.language_code,
            translation_language=current.translation_language,
            level=current.level, interface_language=current.translation_language,
            user_id=user.id,
        )
        return truncate_text(explanation, _USAGE_EXPLANATION_MAX_LENGTH)
    except AIConfigurationError:
        pass
    except AIError:
        pass

    notes = [tr.usage_note for tr in card.translations if tr.usage_note]
    return notes[0] if notes else t("card.usage_placeholder", get_current_language())


async def _send_card(send, session, word_id: int, translation_language: str, *, user_id: int) -> None:
    word = await words_repo.get_by_id(session, word_id)
    if word is None:
        return
    # Caller must have already answered the callback query - this can
    # make a real AI call (settings-improvements stage section 13's
    # on-demand pronunciation backfill), and a too-late answer() would be
    # rejected by Telegram the same way any other slow AI-backed action
    # in the bot would be.
    await pronunciation_service.ensure(session, word, translation_language=translation_language, user_id=user_id)
    # level-and-difficulty stage, spec sections 18-25: a local word may
    # only have been translated into a different language than this
    # user's translation_language (a lot of seed data was only ever
    # translated into Russian) - back it before rendering, never show a
    # blank translation line for a word that otherwise exists locally.
    word = await word_service.ensure_translation(session, word, translation_language=translation_language, user_id=user_id)
    card = word_service.build_word_card(word, translation_language=translation_language)
    await send(render_word_card_text(card), reply_markup=word_card_keyboard(word_id))


async def handle_dictionary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async with session_scope() as session:
        user, current = await _current_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        if data.startswith("dict:open:"):
            word_id = int(data.removeprefix("dict:open:"))
            await query.answer()
            await _send_card(
                lambda text, reply_markup=None: query.message.reply_text(text, reply_markup=reply_markup),
                session,
                word_id,
                current.translation_language,
                user_id=user.id,
            )

        elif data == "dict:back":
            await query.answer()
            await safe_edit_message_text(query, t("dictionary.prompt", get_current_language()))

        elif data.startswith("card:add:"):
            word_id = int(data.removeprefix("card:add:"))
            # Real user request: same as the batch-add path above - a
            # live add must enter repetition immediately.
            result = await user_word_service.add_word_to_learning(
                session, user_id=user.id, word_id=word_id, language_code=current.language_code, status=WordStatus.LEARNING
            )
            if result.outcome == "created":
                result.user_word.source = _word_source(_entry_source(context))
                await query.answer(t("dictionary.added", get_current_language()), show_alert=True)
            elif result.outcome == "restored_from_deleted":
                result.user_word.source = _word_source(_entry_source(context))
                await query.answer(t("dictionary.restored", get_current_language()), show_alert=True)
            elif result.outcome == "offer_resume_paused":
                await query.answer()
                await query.message.reply_text(
                    t("dictionary.offer_resume", get_current_language()), reply_markup=resume_offer_keyboard(result.user_word.id)
                )
            else:
                # already_active: never a silent generic message (bugfix
                # spec) - show the word's real current status so the user
                # understands why nothing changed.
                await query.answer(
                    t("dictionary.already_active_status", get_current_language(), status=status_label(result.user_word.status)),
                    show_alert=True,
                )

        elif data.startswith("card:forms:"):
            # repetition-system stage sections 18-21: verb forms are shown
            # as a real, standalone message with a ✖️ Закрыть button that
            # deletes it - a show_alert popup is too small and must never
            # be used here again.
            word_id = int(data.removeprefix("card:forms:"))
            await query.answer()
            word = await words_repo.get_by_id(session, word_id)
            if word is None:
                await query.message.reply_text(t("card.no_forms", get_current_language()), reply_markup=forms_close_keyboard())
                return

            conjugation = await verb_forms_service.get_or_generate_conjugation(
                session, word, translation_language=current.translation_language, user_id=user.id
            )
            if conjugation:
                for chunk in render_conjugation_messages(word, conjugation):
                    await query.message.reply_text(chunk, reply_markup=forms_close_keyboard())
                return

            card = await word_service.get_word_card(session, word_id=word_id)
            text = render_forms_text(card) if card else t("card.no_forms", get_current_language())
            await query.message.reply_text(text, reply_markup=forms_close_keyboard())

        elif data == "card:formsclose":
            await query.answer()
            await query.message.delete()

        elif data.startswith("card:pronounce:"):
            word_id = int(data.removeprefix("card:pronounce:"))
            card = await word_service.get_word_card(session, word_id=word_id)
            text = (
                pronunciation_service.display_line(card.word)
                if card
                else t("card.pronunciation_placeholder", get_current_language())
            )
            await query.answer(text, show_alert=True)

        elif data.startswith("card:usage:"):
            word_id = int(data.removeprefix("card:usage:"))
            card = await word_service.get_word_card(session, word_id=word_id, translation_language=current.translation_language)
            await query.answer()
            if card is None:
                await query.message.reply_text(t("card.usage_placeholder", get_current_language()))
                return
            await query.message.reply_text(await _explain_word_text(card, current, user))

        elif data.startswith("card:report:"):
            # "⚠️ Неверный перевод" (bugfix, real-user report on the
            # Hebrew shared dictionary): re-asks the AI fresh for this
            # word and replaces ONLY this translation_language's
            # translations - without this, a bad AI response for a real
            # word is permanent, since search_words/
            # find_unknown_words_for_generation only ever call AI when no
            # local Word row exists yet.
            word_id = int(data.removeprefix("card:report:"))
            await query.answer()
            word = await words_repo.get_by_id(session, word_id)
            if word is None:
                await query.message.reply_text(t("card.report_failed", get_current_language()))
                return
            updated = await word_service.report_wrong_translation(
                session, word, translation_language=current.translation_language, user_id=user.id,
            )
            if not updated:
                await query.message.reply_text(t("card.report_failed", get_current_language()))
                return
            await query.message.reply_text(t("card.report_success", get_current_language()))
            await _send_card(query.message.reply_text, session, word_id, current.translation_language, user_id=user.id)

        elif data.startswith("dict:resume:"):
            user_word_id = int(data.removeprefix("dict:resume:"))
            user_word = await user_words_repo.get_by_id(session, user_word_id)
            if user_word is not None and user_word.user_id == user.id:
                await user_word_service.resume_word(session, user_word)
                await query.answer()
                await safe_edit_message_text(query, t("words.resumed_single", get_current_language()))

        elif data.startswith("dict:resume_no:"):
            await query.answer()
            await safe_edit_message_reply_markup(query, reply_markup=None)


dictionary_callback_handler = CallbackQueryHandler(handle_dictionary_callback, pattern="^(dict|card):")
