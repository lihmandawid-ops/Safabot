"""⭐ Мои слова (spec sections 7-13, 19 of the words stage's brief):
numbered list, single/bulk selection by position, filters, pagination,
delete confirmation.

Entry point (show_words_menu) is reached from the main menu's plain-text
"⭐ Мои слова" button, which sets context.user_data["mode"] = "my_words"
(see handlers/menu.py's router) so free-text messages that follow (a
number, "2,5,7", or a personal-dictionary search query) are routed here
instead of being treated as unknown commands.

Numbering is intentionally NOT a database id (spec section 9): position N
on the currently displayed page is resolved through
context.user_data["words_list"]["ids"][N-1], a cache that is only ever
populated with THIS user's own UserWord ids for the page just shown. A
stale or out-of-range number is rejected rather than guessed at.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.models import UserWord
from handlers import dictionary as dictionary_handler
from keyboards.dictionary import word_card_keyboard
from keyboards.words import (
    bulk_action_keyboard,
    bulk_delete_confirm_keyboard,
    delete_confirm_keyboard,
    filter_keyboard,
    list_keyboard,
    single_word_keyboard,
)
from services import pronunciation_service, user_word_service, word_service
from utils.i18n import get_current_language, set_current_language, t
from utils.pagination import paginate
from utils.telegram_helpers import safe_edit_message_text
from utils.text import parse_number_list
from utils.word_display import render_word_card_text, status_label

MODE = "my_words"
PAGE_SIZE = 10


async def show_words_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = MODE
    context.user_data.pop("words_list", None)
    context.user_data.pop("bulk_selection", None)
    context.user_data.pop("words_submode", None)
    await update.message.reply_text(t("words.choose_filter", get_current_language()), reply_markup=filter_keyboard())


async def _current_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _translation_for(user_word: UserWord, translation_language: str) -> str:
    matches = [tr.translation for tr in user_word.word.translations if tr.language_code == translation_language]
    if matches:
        return matches[0]
    return user_word.word.translations[0].translation if user_word.word.translations else ""


def _format_next_review(when: datetime | None) -> str:
    if when is None:
        return t("words.manage_next_review_none", get_current_language())
    when_date = when.date() if isinstance(when, datetime) else when
    today = date.today()
    if when_date == today:
        label = t("words.today", get_current_language())
    elif when_date == today + timedelta(days=1):
        label = t("words.tomorrow", get_current_language())
    else:
        label = when_date.strftime("%d.%m.%Y")
    return t("words.manage_next_review", get_current_language(), when=label)


def _render_list_text(items, translation_language: str, page: int, total_pages: int) -> str:
    lines = [t("words.title", get_current_language()), ""]
    for i, uw in enumerate(items, start=1):
        lines.append(f"{i}. {uw.word.word} — {_translation_for(uw, translation_language)}")
    if total_pages > 1:
        lines.append(t("words.page_footer", get_current_language(), page=page, total=total_pages))
    lines.append("")
    lines.append(t("words.prompt_number", get_current_language()))
    return "\n".join(lines)


async def _backfill_translations(session, items, translation_language: str, *, user_id: int) -> None:
    """Root cause of "перевод не меняется после смены языка интерфейса":
    a word added under a DIFFERENT translation_language has no
    WordTranslation row for the new one yet - _translation_for() used to
    silently fall back to whatever language WAS stored. No-op, no AI call,
    once a translation for this exact language already exists (same
    on-demand backfill word_service.ensure_translation already uses for
    the full card views)."""
    for uw in items:
        if not any(tr.language_code == translation_language for tr in uw.word.translations):
            await word_service.ensure_translation(
                session, uw.word, translation_language=translation_language, user_id=user_id
            )


async def _render_page(send, session, context, *, user_id: int, language_code: str, translation_language: str, filter_code: str, page: int) -> None:
    items = await user_word_service.list_user_words(
        session, user_id=user_id, language_code=language_code, status_filter=filter_code
    )
    page_obj = paginate(items, page, page_size=PAGE_SIZE)

    if not page_obj.items:
        context.user_data.pop("words_list", None)
        await send(t("words.empty", get_current_language()), reply_markup=list_keyboard(has_previous=False, has_next=False))
        return

    await _backfill_translations(session, page_obj.items, translation_language, user_id=user_id)

    context.user_data["words_list"] = {
        "kind": "filter",
        "filter": filter_code,
        "language_code": language_code,
        "translation_language": translation_language,
        "page": page_obj.page_number,
        "ids": [uw.id for uw in page_obj.items],
    }
    text = _render_list_text(page_obj.items, translation_language, page_obj.page_number, page_obj.total_pages)
    await send(text, reply_markup=list_keyboard(has_previous=page_obj.has_previous, has_next=page_obj.has_next))


async def _render_search_results(send, session, context, *, user_id: int, language_code: str, translation_language: str, query: str) -> None:
    items = (await user_word_service.search_user_words(
        session, user_id=user_id, language_code=language_code, query=query
    ))[:PAGE_SIZE]

    if not items:
        context.user_data.pop("words_list", None)
        await send(t("words.search_not_found", get_current_language()), reply_markup=list_keyboard(has_previous=False, has_next=False))
        return

    await _backfill_translations(session, items, translation_language, user_id=user_id)

    context.user_data["words_list"] = {
        "kind": "search",
        "query": query,
        "language_code": language_code,
        "translation_language": translation_language,
        "page": 1,
        "ids": [uw.id for uw in items],
    }
    lines = [t("words.search_results_header", get_current_language()), ""]
    for i, uw in enumerate(items, start=1):
        lines.append(f"{i}. {uw.word.word} — {_translation_for(uw, translation_language)}")
    lines.append("")
    lines.append(t("words.prompt_number", get_current_language()))
    await send("\n".join(lines), reply_markup=list_keyboard(has_previous=False, has_next=False))


async def _refresh_list(send, session, context, *, user_id: int) -> None:
    cache = context.user_data.get("words_list")
    if cache is None:
        await send(t("words.list_expired", get_current_language()))
        return
    if cache["kind"] == "search":
        await _render_search_results(
            send, session, context,
            user_id=user_id, language_code=cache["language_code"],
            translation_language=cache["translation_language"], query=cache["query"],
        )
    else:
        await _render_page(
            send, session, context,
            user_id=user_id, language_code=cache["language_code"],
            translation_language=cache["translation_language"],
            filter_code=cache["filter"], page=cache["page"],
        )


async def _render_manage_screen(
    send, session, user_word_id: int, translation_language: str, *, user_id: int, number: int | None = None
) -> None:
    user_word = await user_words_repo.get_by_id(session, user_word_id)
    if user_word is None:
        return
    # Root cause of "перевод не меняется после смены языка интерфейса" -
    # see _backfill_translations' docstring.
    if not any(tr.language_code == translation_language for tr in user_word.word.translations):
        await word_service.ensure_translation(
            session, user_word.word, translation_language=translation_language, user_id=user_id
        )
    header = (
        t("words.manage_header", get_current_language(), number=number, word=user_word.word.word)
        if number is not None
        else user_word.word.word
    )
    lines = [
        header,
        "",
        t("words.manage_translation", get_current_language(), translation=_translation_for(user_word, translation_language)),
        t("words.manage_status", get_current_language(), status=status_label(user_word.status)),
        _format_next_review(user_word.next_review_at),
    ]
    await send("\n".join(lines), reply_markup=single_word_keyboard(user_word.id, user_word.status))


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    async with session_scope() as session:
        user, current = await _current_language(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        if context.user_data.get("words_submode") == "search":
            context.user_data.pop("words_submode", None)
            await _render_search_results(
                update.message.reply_text, session, context,
                user_id=user.id, language_code=current.language_code,
                translation_language=current.translation_language, query=text,
            )
            return

        cache = context.user_data.get("words_list")
        if cache is None:
            await update.message.reply_text(t("words.list_expired", get_current_language()))
            return

        try:
            numbers = parse_number_list(text)
        except ValueError:
            await update.message.reply_text(t("words.invalid_number", get_current_language()))
            return

        ids = cache["ids"]
        out_of_range = [n for n in numbers if n < 1 or n > len(ids)]
        if out_of_range:
            key = "words.bulk_out_of_range" if len(numbers) > 1 else "words.number_out_of_range"
            await update.message.reply_text(
                t(key, get_current_language(), numbers=", ".join(str(n) for n in out_of_range))
            )
            return

        if len(numbers) == 1:
            user_word_id = ids[numbers[0] - 1]
            await _render_manage_screen(
                update.message.reply_text, session, user_word_id, cache["translation_language"],
                user_id=user.id, number=numbers[0],
            )
            return

        selected_ids = [ids[n - 1] for n in numbers]
        context.user_data["bulk_selection"] = selected_ids
        selected_words = await user_words_repo.get_user_words(session, user_id=user.id, language_code=current.language_code)
        by_id = {uw.id: uw for uw in selected_words}
        lines = [t("words.bulk_header", get_current_language())]
        for n in numbers:
            uw = by_id.get(ids[n - 1])
            if uw is not None:
                lines.append(f"{n}. {uw.word.word}")
        await update.message.reply_text("\n".join(lines), reply_markup=bulk_action_keyboard())


async def handle_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async with session_scope() as session:
        user, current = await _current_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        async def edit(text, reply_markup=None):
            await safe_edit_message_text(query, text, reply_markup=reply_markup)

        if data == "words:filters":
            context.user_data.pop("words_list", None)
            await query.answer()
            await edit(t("words.choose_filter", get_current_language()), reply_markup=filter_keyboard())

        elif data.startswith("words:filter:"):
            filter_code = data.removeprefix("words:filter:")
            await query.answer()
            await _render_page(
                edit, session, context, user_id=user.id, language_code=current.language_code,
                translation_language=current.translation_language, filter_code=filter_code, page=1,
            )

        elif data == "words:search":
            context.user_data["words_submode"] = "search"
            await query.answer()
            await edit(t("words.search_prompt", get_current_language()))

        elif data == "words:add":
            # Reuses handlers/dictionary.py's free-text handler wholesale
            # (bugfix spec: never build a second add implementation) - it
            # already does local-search-then-DictionaryProvider-fallback,
            # single-word confirmation cards, batch input, and duplicate
            # detection. Only the entry mode + prompt text differ.
            context.user_data["mode"] = dictionary_handler.MODE
            context.user_data["dictionary_entry_source"] = "manual"
            context.user_data.pop("words_list", None)
            context.user_data.pop("bulk_selection", None)
            context.user_data.pop("words_submode", None)
            await query.answer()
            await edit(t("words.add_prompt", get_current_language()))

        elif data.startswith("words:page:"):
            direction = data.removeprefix("words:page:")
            cache = context.user_data.get("words_list")
            await query.answer()
            if cache is None or cache.get("kind") != "filter":
                await edit(t("words.list_expired", get_current_language()))
                return
            new_page = cache["page"] + (1 if direction == "next" else -1)
            await _render_page(
                edit, session, context, user_id=user.id, language_code=current.language_code,
                translation_language=current.translation_language, filter_code=cache["filter"], page=new_page,
            )

        elif data == "uw:list_back":
            await query.answer()
            await _refresh_list(edit, session, context, user_id=user.id)

        elif data.startswith("uw:review:"):
            uw_id = int(data.removeprefix("uw:review:"))
            user_word = await user_words_repo.get_by_id(session, uw_id)
            if user_word is not None and user_word.user_id == user.id:
                await user_word_service.resume_word(session, user_word)
                await query.answer(t("words.resumed_single", get_current_language()))
                await _render_manage_screen(edit, session, uw_id, current.translation_language, user_id=user.id)

        elif data.startswith("uw:pause:"):
            uw_id = int(data.removeprefix("uw:pause:"))
            user_word = await user_words_repo.get_by_id(session, uw_id)
            if user_word is not None and user_word.user_id == user.id:
                await user_word_service.pause_word(session, user_word)
                await query.answer(t("words.paused_single", get_current_language()))
                await _render_manage_screen(edit, session, uw_id, current.translation_language, user_id=user.id)

        elif data.startswith("uw:delete:"):
            uw_id = int(data.removeprefix("uw:delete:"))
            user_word = await user_words_repo.get_by_id(session, uw_id)
            if user_word is not None and user_word.user_id == user.id:
                await query.answer()
                await edit(
                    t("words.delete_confirm", get_current_language(), word=user_word.word.word),
                    reply_markup=delete_confirm_keyboard(uw_id),
                )

        elif data.startswith("uw:delete_confirm:"):
            uw_id = int(data.removeprefix("uw:delete_confirm:"))
            user_word = await user_words_repo.get_by_id(session, uw_id)
            if user_word is not None and user_word.user_id == user.id:
                await user_word_service.delete_word(session, user_word)
                await query.answer(t("words.deleted", get_current_language()))
                await _refresh_list(edit, session, context, user_id=user.id)

        elif data.startswith("uw:delete_cancel:"):
            uw_id = int(data.removeprefix("uw:delete_cancel:"))
            await query.answer()
            await _render_manage_screen(edit, session, uw_id, current.translation_language, user_id=user.id)

        elif data.startswith("uw:card:"):
            uw_id = int(data.removeprefix("uw:card:"))
            user_word = await user_words_repo.get_by_id(session, uw_id)
            if user_word is not None and user_word.user_id == user.id:
                await query.answer()
                # query.answer() must come before this - ensure_pronunciation
                # can make a real AI call (settings-improvements stage
                # section 13's on-demand backfill), and Telegram rejects a
                # too-late answer the same way a slow AI-backed action
                # anywhere else in the bot would.
                await pronunciation_service.ensure(
                    session, user_word.word, translation_language=current.translation_language, user_id=user.id
                )
                # level-and-difficulty stage, spec sections 18-25: same
                # reasoning as the pronunciation backfill above, but for a
                # missing translation.
                await word_service.ensure_translation(
                    session, user_word.word, translation_language=current.translation_language, user_id=user.id
                )
                card = await word_service.get_word_card(
                    session, word_id=user_word.word_id, translation_language=current.translation_language
                )
                await edit(
                    render_word_card_text(card, status=user_word.status),
                    reply_markup=word_card_keyboard(user_word.word_id, back_callback=f"uw:card_back:{uw_id}"),
                )

        elif data.startswith("uw:card_back:"):
            uw_id = int(data.removeprefix("uw:card_back:"))
            await query.answer()
            await _render_manage_screen(edit, session, uw_id, current.translation_language, user_id=user.id)

        elif data in ("bulk:review", "bulk:pause"):
            ids = context.user_data.get("bulk_selection") or []
            count = 0
            for uw_id in ids:
                user_word = await user_words_repo.get_by_id(session, uw_id)
                if user_word is None or user_word.user_id != user.id:
                    continue
                if data == "bulk:review":
                    await user_word_service.resume_word(session, user_word)
                else:
                    await user_word_service.pause_word(session, user_word)
                count += 1
            context.user_data.pop("bulk_selection", None)
            key = "words.bulk_resumed" if data == "bulk:review" else "words.bulk_paused"
            await query.answer(t(key, get_current_language(), count=count))
            await _refresh_list(edit, session, context, user_id=user.id)

        elif data == "bulk:delete":
            ids = context.user_data.get("bulk_selection") or []
            await query.answer()
            await edit(t("words.delete_confirm_bulk", get_current_language(), count=len(ids)), reply_markup=bulk_delete_confirm_keyboard())

        elif data == "bulk:delete_confirm":
            ids = context.user_data.get("bulk_selection") or []
            count = 0
            for uw_id in ids:
                user_word = await user_words_repo.get_by_id(session, uw_id)
                if user_word is None or user_word.user_id != user.id:
                    continue
                await user_word_service.delete_word(session, user_word)
                count += 1
            context.user_data.pop("bulk_selection", None)
            await query.answer(t("words.bulk_deleted", get_current_language(), count=count))
            await _refresh_list(edit, session, context, user_id=user.id)

        elif data == "bulk:cancel":
            context.user_data.pop("bulk_selection", None)
            await query.answer(t("words.bulk_cancelled", get_current_language()))
            await _refresh_list(edit, session, context, user_id=user.id)


words_callback_handler = CallbackQueryHandler(handle_words_callback, pattern="^(words|uw|bulk):")
