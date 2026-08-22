"""💬 Полезные фразы (native-speaker phrasebook stage).

Entry point (show_phrases_menu) is reached from the main menu's plain-
text "💬 Полезные фразы" button, which sets context.user_data["mode"] so
the next free-text message (used only for 🎯 Своя ситуация) is routed
here instead of being treated as an unknown command - same pattern as
every other free-text-capable section (handlers/dictionary.py,
handlers/text_analysis.py, handlers/settings.py's "<mode>_submode" key).

📖 Разобрать / ➕ Добавить слова deliberately do NOT reimplement word
extraction or the add-to-learning flow: they call the exact same
AIService.analyze_text() 📝 Разбор текста already uses (key_words are
already "the significant words worth learning" - the exact semantics
section 19 asks for) and hand off into handlers.text_analysis's existing
render_results()/results_keyboard()/add_all/add_selected machinery, so a
phrase's words are added through the one existing UserWordService path
every other word-add flow uses.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.repositories import phrases as phrases_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from handlers import text_analysis as text_analysis_handler
from keyboards.main_menu import main_menu_keyboard
from keyboards.phrases import (
    delete_confirm_keyboard,
    generated_phrase_keyboard,
    phrases_menu_keyboard,
    popular_list_keyboard,
    popular_phrase_keyboard,
    saved_list_keyboard,
    saved_phrase_card_keyboard,
    situation_picker_keyboard,
)
from keyboards.text_analysis import results_keyboard
from services import phrase_service
from services.ai_errors import AIConfigurationError, AIError
from services.ai_service import get_ai_service
from services.phrase_service import POPULAR_PHRASES_PAGE_SIZE
from utils.i18n import get_current_language, set_current_language, t
from utils.languages import LANGUAGE_BY_CODE
from utils.phrase_situations import MAX_CUSTOM_SITUATION_LENGTH, PRESET_SITUATIONS
from utils.popular_phrases import get_popular_phrases

_NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")

MODE = "phrases"


async def _current_user_and_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _render_card(
    *, language_code: str, phrase_text: str, translation_language: str, translation_text: str,
    pronunciation: str | None, explanation: str | None = None,
) -> str:
    """Section 3's card layout - the phrase, its translation, its
    pronunciation (the same "card.pronunciation_line"/"...placeholder"
    keys every other pronunciation-showing screen uses, global
    pronunciation rule section 37), and an optional one-line usage note."""
    lang = LANGUAGE_BY_CODE.get(language_code)
    translation_lang = LANGUAGE_BY_CODE.get(translation_language)
    lines = [f"{lang.flag if lang else ''} {phrase_text}".strip(), ""]
    lines.append(f"{translation_lang.flag if translation_lang else ''} {translation_text}".strip())
    lines.append("")
    if pronunciation:
        lines.append(t("card.pronunciation_line", get_current_language(), pronunciation=pronunciation))
    else:
        lines.append(t("card.pronunciation_placeholder", get_current_language()))
    if explanation:
        lines.append("")
        lines.append(f"💡 {explanation}")
    return "\n".join(lines)


async def show_phrases_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = MODE
    context.user_data.pop("phrases_submode", None)
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
        set_current_language(user.interface_language if user else None)
    await update.message.reply_text(t("phrases.menu.title", get_current_language()), reply_markup=phrases_menu_keyboard())


async def _render_saved_list(edit, session, user_id: int, language_code: str) -> None:
    saved = await phrases_repo.list_phrases(session, user_id=user_id, language_code=language_code)
    if not saved:
        await edit(t("phrases.saved.empty", get_current_language()), reply_markup=phrases_menu_keyboard())
        return
    lines = [t("phrases.saved.header", get_current_language()), ""]
    numbers = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
    for i, phrase in enumerate(saved):
        label = numbers[i] if i < len(numbers) else f"{i + 1}."
        lines.append(f"{label} {phrase.phrase}")
    await edit("\n".join(lines), reply_markup=saved_list_keyboard([p.id for p in saved]))


async def _render_popular_page(edit, session, user, current, page: int) -> None:
    """🔥 Популярные фразы pagination (bugfix stage sections 3, 8-10): each
    entry shows its phrase, pronunciation, and translation directly in
    the list - no tap required just to see a translation - and paging
    never calls AI, since get_translated_popular_phrases already cached
    every translation for this (learning, translation) language pair
    before this is ever called."""
    all_entries = await phrase_service.get_translated_popular_phrases(
        session, language_code=current.language_code, translation_language=current.translation_language,
        user_id=user.id,
    )
    if not all_entries:
        await edit(t("phrases.popular.empty", get_current_language()), reply_markup=phrases_menu_keyboard())
        return

    last_page = (len(all_entries) - 1) // POPULAR_PHRASES_PAGE_SIZE
    page = max(0, min(page, last_page))
    start = page * POPULAR_PHRASES_PAGE_SIZE
    page_entries = all_entries[start : start + POPULAR_PHRASES_PAGE_SIZE]

    lang = LANGUAGE_BY_CODE.get(current.language_code)
    translation_lang = LANGUAGE_BY_CODE.get(current.translation_language)
    lines = [t("phrases.popular.header", get_current_language())]
    for entry in page_entries:
        label = _NUMBER_EMOJI[entry.index] if entry.index < len(_NUMBER_EMOJI) else f"{entry.index + 1}."
        lines.append("")
        lines.append(f"{label} {lang.flag if lang else ''} {entry.phrase}".strip())
        if entry.pronunciation:
            lines.append(t("card.pronunciation_line", get_current_language(), pronunciation=entry.pronunciation))
        else:
            lines.append(t("card.pronunciation_placeholder", get_current_language()))
        translation_text = entry.translation or t("phrases.popular.translation_unavailable", get_current_language())
        lines.append(f"{translation_lang.flag if translation_lang else ''} {translation_text}".strip())

    keyboard = popular_list_keyboard(
        [entry.index for entry in page_entries], page=page, has_prev=page > 0, has_next=page < last_page,
    )
    await edit("\n".join(lines), reply_markup=keyboard)


async def _generate_and_show(edit, *, user, current, situation_code: str, situation_text: str, exclude: list[str]) -> None:
    try:
        result = await phrase_service.generate_phrase(
            user=user, user_language=current, situation_code=situation_code,
            situation_text=situation_text, exclude_phrases=exclude,
        )
    except AIConfigurationError:
        await edit(t("ai.not_configured", get_current_language()), reply_markup=phrases_menu_keyboard())
        return
    except AIError:
        await edit(t("ai.generic_error", get_current_language()), reply_markup=phrases_menu_keyboard())
        return

    context_data = {
        "phrase": result.phrase, "translation": result.translation, "pronunciation": result.pronunciation,
        "explanation": result.explanation, "register": result.register_type,
        "situation_code": situation_code, "situation_text": situation_text,
        "seen": exclude + [result.phrase],
    }
    return context_data, result


async def _handle_custom_situation_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    situation = text.strip()[:MAX_CUSTOM_SITUATION_LENGTH]
    context.user_data.pop("phrases_submode", None)
    if not situation:
        await update.message.reply_text(t("phrases.situation.custom_empty", get_current_language()))
        return

    async with session_scope() as session:
        user, current = await _current_user_and_language(session, update.effective_user.id)
        if user is None or current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        async def edit(text_: str, reply_markup=None) -> None:
            await update.message.reply_text(text_, reply_markup=reply_markup)

        outcome = await _generate_and_show(
            edit, user=user, current=current, situation_code="custom", situation_text=situation, exclude=[],
        )
        if outcome is None:
            return
        gen_state, result = outcome
        context.user_data["phrase_gen"] = gen_state
        await update.message.reply_text(
            _render_card(
                language_code=current.language_code, phrase_text=result.phrase,
                translation_language=current.translation_language, translation_text=result.translation,
                pronunciation=result.pronunciation, explanation=result.explanation,
            ),
            reply_markup=generated_phrase_keyboard(),
        )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if context.user_data.get("phrases_submode") == "custom_situation":
        await _handle_custom_situation_input(update, context, text)
        return
    await update.message.reply_text(t("menu.unknown_command", get_current_language()))


async def _run_phrase_analysis(query, session, user, current, phrase_text: str) -> None:
    try:
        result = await get_ai_service().analyze_text(
            phrase_text, language_code=current.language_code, translation_language=current.translation_language,
            # bugfix stage: this must match translation_language, not the
            # global interface_language - the two can differ (see the same
            # fix in handlers/dictionary.py, handlers/grammar.py,
            # handlers/text_analysis.py).
            interface_language=current.translation_language, user_id=user.id,
        )
    except AIConfigurationError:
        await query.message.reply_text(t("ai.not_configured", get_current_language()))
        return
    except AIError:
        await query.message.reply_text(t("ai.generic_error", get_current_language()))
        return

    key_words = [(kw.word, kw.translation, kw.pronunciation) for kw in result.key_words]
    phrases = [(ph.phrase, ph.pronunciation) for ph in result.useful_phrases]
    text_analysis_handler_context = {"words": [kw.word for kw in result.key_words]}
    await query.message.reply_text(
        text_analysis_handler.render_results(result.original_text, result.translation, result.pronunciation, key_words, phrases),
        reply_markup=results_keyboard() if key_words else None,
    )
    return text_analysis_handler_context


async def handle_phrases_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await query.edit_message_text(text, reply_markup=reply_markup)

    async with session_scope() as session:
        user, current = await _current_user_and_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        if data == "phr:menu":
            await query.answer()
            context.user_data["mode"] = MODE
            context.user_data.pop("phrases_submode", None)
            await edit(t("phrases.menu.title", get_current_language()), reply_markup=phrases_menu_keyboard())

        elif data == "phr:mainmenu":
            await query.answer()
            context.user_data.pop("mode", None)
            context.user_data.pop("phrases_submode", None)
            await query.message.reply_text(
                t("onboarding.main_menu_ready", get_current_language()), reply_markup=main_menu_keyboard(get_current_language())
            )

        elif data == "phr:saved":
            await query.answer()
            await _render_saved_list(edit, session, user.id, current.language_code)

        elif data.startswith("phr:open:"):
            phrase_id = int(data.removeprefix("phr:open:"))
            await query.answer()
            phrase = await phrases_repo.get_by_id(session, phrase_id)
            if phrase is None or phrase.user_id != user.id:
                await edit(t("phrases.not_found", get_current_language()), reply_markup=phrases_menu_keyboard())
                return
            await edit(
                _render_card(
                    language_code=phrase.language_code, phrase_text=phrase.phrase,
                    translation_language=current.translation_language, translation_text=phrase.translation,
                    pronunciation=phrase.pronunciation, explanation=phrase.explanation,
                ),
                reply_markup=saved_phrase_card_keyboard(phrase.id),
            )

        elif data.startswith("phr:delete_confirm:"):
            phrase_id = int(data.removeprefix("phr:delete_confirm:"))
            phrase = await phrases_repo.get_by_id(session, phrase_id)
            if phrase is not None and phrase.user_id == user.id:
                await phrases_repo.delete_phrase(session, phrase)
                await query.answer(t("phrases.deleted", get_current_language()))
            else:
                await query.answer()
            await _render_saved_list(edit, session, user.id, current.language_code)

        elif data.startswith("phr:delete:"):
            phrase_id = int(data.removeprefix("phr:delete:"))
            await query.answer()
            await edit(t("phrases.delete_confirm_prompt", get_current_language()), reply_markup=delete_confirm_keyboard(phrase_id))

        elif data == "phr:new":
            await query.answer()
            await edit(t("phrases.situation.prompt", get_current_language()), reply_markup=situation_picker_keyboard())

        elif data == "phr:situation:custom":
            await query.answer()
            context.user_data["mode"] = MODE
            context.user_data["phrases_submode"] = "custom_situation"
            await edit(t("phrases.situation.custom_prompt", get_current_language()))

        elif data.startswith("phr:situation:"):
            code = data.removeprefix("phr:situation:")
            if code not in PRESET_SITUATIONS:
                await query.answer()
                return
            await query.answer()
            outcome = await _generate_and_show(edit, user=user, current=current, situation_code=code, situation_text="", exclude=[])
            if outcome is None:
                return
            gen_state, result = outcome
            context.user_data["phrase_gen"] = gen_state
            await edit(
                _render_card(
                    language_code=current.language_code, phrase_text=result.phrase,
                    translation_language=current.translation_language, translation_text=result.translation,
                    pronunciation=result.pronunciation, explanation=result.explanation,
                ),
                reply_markup=generated_phrase_keyboard(),
            )

        elif data == "phr:regenerate":
            await query.answer()
            state = context.user_data.get("phrase_gen")
            if state is None:
                await edit(t("phrases.expired", get_current_language()), reply_markup=phrases_menu_keyboard())
                return
            outcome = await _generate_and_show(
                edit, user=user, current=current, situation_code=state["situation_code"],
                situation_text=state["situation_text"], exclude=state["seen"],
            )
            if outcome is None:
                return
            gen_state, result = outcome
            context.user_data["phrase_gen"] = gen_state
            await edit(
                _render_card(
                    language_code=current.language_code, phrase_text=result.phrase,
                    translation_language=current.translation_language, translation_text=result.translation,
                    pronunciation=result.pronunciation, explanation=result.explanation,
                ),
                reply_markup=generated_phrase_keyboard(),
            )

        elif data == "phr:save":
            gen_state = context.user_data.get("phrase_gen")
            pop_state = context.user_data.get("phrase_popular")
            source = gen_state or pop_state
            if source is None:
                await query.answer()
                await edit(t("phrases.expired", get_current_language()), reply_markup=phrases_menu_keyboard())
                return
            saved = await phrases_repo.add_phrase(
                session, user_id=user.id, language_code=current.language_code, phrase=source["phrase"],
                translation=source["translation"], pronunciation=source.get("pronunciation"),
                register=source.get("register"), situation=source.get("situation_code") or source.get("situation"),
                explanation=source.get("explanation"),
            )
            key = "phrases.saved_ok" if saved.created else "phrases.already_saved"
            await query.answer(t(key, get_current_language()))
            context.user_data.pop("phrase_gen", None)
            context.user_data.pop("phrase_popular", None)
            await edit(
                _render_card(
                    language_code=saved.phrase.language_code, phrase_text=saved.phrase.phrase,
                    translation_language=current.translation_language, translation_text=saved.phrase.translation,
                    pronunciation=saved.phrase.pronunciation, explanation=saved.phrase.explanation,
                ),
                reply_markup=saved_phrase_card_keyboard(saved.phrase.id),
            )

        elif data.startswith("phr:popularopen:"):
            index = int(data.removeprefix("phr:popularopen:"))
            entries = get_popular_phrases(current.language_code)
            if index < 0 or index >= len(entries):
                await query.answer()
                return
            await query.answer()
            # Cached-only (bugfix stage section 10/15): the translation
            # cache was already filled by whichever _render_popular_page
            # call got here first - opening a specific phrase never makes
            # its own AI call, and pronunciation never has, since it's
            # always the static seed data's own Latin transcription.
            translated = await phrase_service.get_translated_popular_phrases(
                session, language_code=current.language_code, translation_language=current.translation_language,
                user_id=user.id,
            )
            entry = translated[index]
            translation = entry.translation or t("phrases.popular.translation_unavailable", get_current_language())

            context.user_data["phrase_popular"] = {
                "phrase": entry.phrase, "translation": translation, "pronunciation": entry.pronunciation,
                "situation": entry.situation,
            }
            back_page = entry.index // POPULAR_PHRASES_PAGE_SIZE
            await edit(
                _render_card(
                    language_code=current.language_code, phrase_text=entry.phrase,
                    translation_language=current.translation_language, translation_text=translation,
                    pronunciation=entry.pronunciation,
                ),
                reply_markup=popular_phrase_keyboard(back_page),
            )

        elif data.startswith("phr:popular:"):
            page = int(data.removeprefix("phr:popular:"))
            await query.answer()
            await _render_popular_page(edit, session, user, current, page)

        elif data == "phr:populargen":
            # ✨ Сгенерировать ещё (sections 21-37): a completely separate
            # action from ➡️ Следующие фразы above - this is the ONLY
            # popular-phrases button that calls AI. The reentrancy flag
            # blocks a second tap while one request is already in flight
            # (section 35), and is always cleared in `finally` so a
            # success, an AIError, or an unexpected exception all leave it
            # clear for the next tap.
            if context.user_data.get("phrases_generating_popular"):
                await query.answer(t("phrases.popular.generating_wait", get_current_language()), show_alert=True)
                return
            await query.answer()
            context.user_data["phrases_generating_popular"] = True
            await edit(t("phrases.popular.generating", get_current_language()))
            try:
                new_entries = await phrase_service.generate_more_popular_phrases(
                    session, user=user, user_language=current, amount=8,
                )
            except AIConfigurationError:
                await edit(t("ai.not_configured", get_current_language()), reply_markup=phrases_menu_keyboard())
                return
            except AIError:
                await edit(t("phrases.popular.generate_failed", get_current_language()), reply_markup=phrases_menu_keyboard())
                return
            finally:
                context.user_data.pop("phrases_generating_popular", None)

            if not new_entries:
                await edit(t("phrases.popular.no_new_phrases", get_current_language()), reply_markup=phrases_menu_keyboard())
                return

            target_page = new_entries[0].index // POPULAR_PHRASES_PAGE_SIZE
            await _render_popular_page(edit, session, user, current, target_page)

        elif data.startswith("phr:analyze:saved:"):
            phrase_id = int(data.removeprefix("phr:analyze:saved:"))
            await query.answer()
            phrase = await phrases_repo.get_by_id(session, phrase_id)
            if phrase is None or phrase.user_id != user.id:
                await query.message.reply_text(t("phrases.not_found", get_current_language()))
                return
            ta_state = await _run_phrase_analysis(query, session, user, current, phrase.phrase)
            if ta_state is not None:
                context.user_data["mode"] = text_analysis_handler.MODE
                context.user_data["text_analysis"] = ta_state

        elif data == "phr:analyze:pending":
            await query.answer()
            source = context.user_data.get("phrase_gen") or context.user_data.get("phrase_popular")
            if source is None:
                await query.message.reply_text(t("phrases.expired", get_current_language()))
                return
            ta_state = await _run_phrase_analysis(query, session, user, current, source["phrase"])
            if ta_state is not None:
                context.user_data["mode"] = text_analysis_handler.MODE
                context.user_data["text_analysis"] = ta_state


phrases_callback_handler = CallbackQueryHandler(handle_phrases_callback, pattern="^phr:")
