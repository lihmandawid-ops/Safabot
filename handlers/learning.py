"""📚 Учить слова / 🔄 Повторить (learning-core stage, sections 9-12, 34-36).

Entry points (show_learning_intro / show_review_intro) are reached from
the main menu's plain-text buttons. Everything after that is inline-
keyboard callbacks (learn:*, review:*) - the whole word -> reveal -> rate
-> next word loop lives on ONE message, edited in place (spec section 34:
never bounce the user back to the main menu between words).

No progress is kept in context.user_data: every screen is re-derived from
the user's active LearningSession in the database (see
services/learning_service.py), so a bot restart mid-session loses nothing
(section 25) and every action re-validates that the UserWord being acted
on actually belongs to the current user's own active session (section 36).
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from database.database import session_scope
from database.models import UserWord
from database.repositories import sessions as sessions_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.learning import (
    after_session_keyboard,
    continue_keyboard,
    extra_amount_keyboard,
    known_keyboard,
    learn_menu_keyboard,
    old_words_amount_keyboard,
    rating_keyboard,
    reveal_keyboard,
    start_keyboard,
    start_review_keyboard,
)
from handlers import dictionary as dictionary_handler
from handlers.words import MODE as WORDS_MODE
from keyboards.settings import topics_keyboard
from keyboards.words import filter_keyboard
from services import learning_service, pronunciation_service, word_generation_service, word_service
from services.repetition_service import ReviewGrade
from utils.i18n import get_current_language, set_current_language, t
from utils.languages import LANGUAGE_BY_CODE

MODE = "learning"


async def _current_user_and_language(session, telegram_id: int):
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return None, None
    set_current_language(user.interface_language)
    current = await user_languages_repo.get_current_language(session, user.id)
    return user, current


def _render_front(user_word: UserWord) -> str:
    lang = LANGUAGE_BY_CODE.get(user_word.word.language_code)
    pronunciation = pronunciation_service.display_line(user_word.word)
    return t(
        "learning.card_front", get_current_language(),
        flag=lang.flag if lang else "", word=user_word.word.word, pronunciation=pronunciation,
    )


def _render_back(user_word: UserWord, translation_language: str) -> str:
    card = word_service.build_word_card(user_word.word, translation_language=translation_language)
    lang = LANGUAGE_BY_CODE.get(user_word.word.language_code)
    translation_lang = LANGUAGE_BY_CODE.get(translation_language)
    pronunciation = pronunciation_service.display_line(user_word.word)
    translation_text = ", ".join(tr.translation for tr in card.translations)

    if card.examples:
        example = card.examples[0]
        example_text = t("card.example_label", get_current_language()) + "\n" + example.example_text
        if example.translation:
            example_text += "\n" + example.translation
    else:
        example_text = t("card.no_examples", get_current_language())

    return t(
        "learning.card_back", get_current_language(),
        flag=lang.flag if lang else "", word=user_word.word.word, pronunciation=pronunciation,
        translation_flag=translation_lang.flag if translation_lang else "", translation=translation_text,
        example=example_text,
    )


async def _show_current_word(session, edit, learning_session, translation_language: str, *, user_id: int) -> None:
    if learning_session is None:
        await edit(t("learning.session_gone", get_current_language()))
        return
    item = sessions_repo.next_incomplete_item(learning_session)
    if item is None:
        await edit(t("learning.nothing_to_do", get_current_language()))
        return
    # repetition-system-audit stage section 15: most seed words were
    # inserted without a pronunciation (only AI-generated ones get it for
    # free) - the dictionary card already backfills this on demand
    # (pronunciation_service.ensure), but the learning flow never did, so
    # a seeded word would show "pronunciation unavailable" here even
    # though opening its dictionary card moments later would fix it. A
    # no-op (no AI call) whenever pronunciation is already set.
    await pronunciation_service.ensure(
        session, item.user_word.word, translation_language=translation_language, user_id=user_id,
    )
    # level-and-difficulty stage, spec sections 18-25: same reasoning as
    # the pronunciation backfill above, but for a missing translation - a
    # lot of seed data was only ever translated into Russian, so a
    # learner translating into a different language must never see a
    # blank translation line for an otherwise-known word.
    await word_service.ensure_translation(
        session, item.user_word.word, translation_language=translation_language, user_id=user_id,
    )
    await edit(_render_front(item.user_word), reply_markup=reveal_keyboard(item.user_word_id, is_new_word=item.is_new_word))


async def _compute_intro(session, user, current, *, include_new_words: bool) -> tuple[str, object | None]:
    """Shared by the plain-text entry points (_show_intro) and the
    "learn:intro" inline-button re-entry (bugfix spec section 8/9's
    post-completion keyboard) - returns (text, reply_markup) so callers
    can either reply_text or edit_message_text with it."""
    active = await sessions_repo.get_active_session(session, user_id=user.id, language_code=current.language_code)
    if active is not None and sessions_repo.next_incomplete_item(active) is not None:
        remaining = active.total_words - active.completed_words
        return t("learning.resume", get_current_language(), count=remaining), continue_keyboard()

    due = await learning_service.get_due_reviews(session, user_id=user.id, language_code=current.language_code)
    shortfall = False
    if include_new_words:
        new_words_result = await learning_service.get_new_words_for_today(session, user=user, user_language=current)
        new_words = new_words_result.words
        shortfall = new_words_result.shortfall
    else:
        new_words = []
    total = len(due) + len(new_words)

    if total == 0:
        if include_new_words and shortfall:
            # AI-integration spec section 20/28: distinguish "nothing
            # to do" from "wanted to generate new words but couldn't" -
            # never leave the user guessing why the count is 0.
            return t("learning.generation_unavailable", get_current_language()), (after_session_keyboard() if include_new_words else None)
        key = "learning.nothing_to_do" if include_new_words else "learning.nothing_due"
        return t(key, get_current_language()), (after_session_keyboard() if include_new_words else None)

    if include_new_words:
        text = t("learning.ready", get_current_language(), count=total)
        if shortfall:
            text += "\n\n" + t("learning.generation_unavailable", get_current_language())
        return text, start_keyboard()
    return t("learning.ready_review", get_current_language(), count=total), start_review_keyboard()


async def _show_intro(update: Update, context: ContextTypes.DEFAULT_TYPE, *, include_new_words: bool) -> None:
    async with session_scope() as session:
        user, current = await _current_user_and_language(session, update.effective_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        text, keyboard = await _compute_intro(session, user, current, include_new_words=include_new_words)
        await update.message.reply_text(text, reply_markup=keyboard)


async def show_learning_intro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_intro(update, context, include_new_words=True)


async def show_review_intro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_intro(update, context, include_new_words=False)


async def handle_learning_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await query.edit_message_text(text, reply_markup=reply_markup)

    async with session_scope() as session:
        user, current = await _current_user_and_language(session, query.from_user.id)
        if user is None or current is None:
            await query.answer(t("card.no_language", get_current_language()), show_alert=True)
            return

        if data == "learn:start":
            await query.answer()
            learning_session = await learning_service.build_learning_session(
                session, user=user, user_language=current, include_new_words=True
            )
            await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)

        elif data == "learn:reviewonly":
            await query.answer()
            learning_session = await learning_service.build_learning_session(
                session, user=user, user_language=current, include_new_words=False
            )
            await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)

        elif data == "learn:continue":
            await query.answer()
            learning_session = await sessions_repo.get_active_session(
                session, user_id=user.id, language_code=current.language_code
            )
            await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)

        elif data == "learn:intro":
            await query.answer()
            text, keyboard = await _compute_intro(session, user, current, include_new_words=True)
            await edit(text, reply_markup=keyboard)

        elif data == "learn:menu":
            await query.answer()
            await edit(t("learning.menu.header", get_current_language()), reply_markup=learn_menu_keyboard())

        elif data == "learn:newwords":
            await query.answer()
            result = await word_generation_service.generate_words_ai_first(
                session, user=user, user_language=current, amount=current.daily_new_words,
                trigger="explicit_new_words",
            )
            text = (
                t("learning.generation_failed", get_current_language())
                if not result
                else t("learning.extra_added", get_current_language(), count=len(result))
            )
            await edit(text, reply_markup=after_session_keyboard())

        elif data == "learn:topics":
            await query.answer()
            await edit(
                t("settings.topics_title", get_current_language()),
                reply_markup=topics_keyboard(current.selected_topics),
            )

        elif data == "learn:topicgen":
            await query.answer()
            if not current.selected_topics:
                await edit(t("learning.menu.header", get_current_language()), reply_markup=learn_menu_keyboard())
                return
            result = await word_generation_service.generate_words_ai_first(
                session, user=user, user_language=current, amount=current.daily_new_words,
                topics=current.selected_topics, trigger="explicit_new_words_topic",
            )
            text = (
                t("learning.generation_failed", get_current_language())
                if not result
                else t("learning.extra_added", get_current_language(), count=len(result))
            )
            await edit(text, reply_markup=after_session_keyboard())

        elif data == "learn:extra":
            await query.answer()
            await edit(t("learning.extra_prompt", get_current_language()), reply_markup=extra_amount_keyboard())

        elif data.startswith("learn:extra:"):
            amount = int(data.removeprefix("learn:extra:"))
            await query.answer()
            result = await word_generation_service.generate_extra_words(
                session, user=user, user_language=current, amount=amount
            )
            if result.limit_reached:
                text = t("learning.extra_limit_reached", get_current_language())
            elif not result.words:
                text = t("learning.extra_unavailable", get_current_language())
            else:
                text = t("learning.extra_added", get_current_language(), count=len(result.words))
            await edit(text, reply_markup=after_session_keyboard())

        elif data == "learn:oldwords":
            await query.answer()
            await edit(t("learning.old_words_prompt", get_current_language()), reply_markup=old_words_amount_keyboard())

        elif data.startswith("learn:oldwords:"):
            amount = int(data.removeprefix("learn:oldwords:"))
            await query.answer()
            learning_session = await learning_service.build_old_words_session(
                session, user=user, user_language=current, limit=amount
            )
            if learning_session is None:
                await edit(t("learning.old_words_unavailable", get_current_language()), reply_markup=after_session_keyboard())
                return
            await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)

        elif data == "learn:dictionary":
            await query.answer()
            context.user_data["mode"] = dictionary_handler.MODE
            context.user_data["dictionary_entry_source"] = "search"
            await edit(t("dictionary.prompt", get_current_language()))

        elif data == "learn:mywords":
            await query.answer()
            context.user_data["mode"] = WORDS_MODE
            context.user_data.pop("words_list", None)
            context.user_data.pop("bulk_selection", None)
            context.user_data.pop("words_submode", None)
            await edit(t("words.choose_filter", get_current_language()), reply_markup=filter_keyboard())

        elif data.startswith("learn:know:"):
            # Answer the callback query BEFORE mark_known_and_replace, not
            # after: that call can trigger a real AI request for the
            # replacement word (up to AI_TIMEOUT_SECONDS x retries - tens of
            # seconds), and Telegram rejects a callback-query answer sent
            # too late ("query is too old"), which used to surface as a
            # generic "something went wrong" error with no visible result.
            user_word_id = int(data.removeprefix("learn:know:"))
            await query.answer()
            learning_session = await sessions_repo.get_active_session(
                session, user_id=user.id, language_code=current.language_code
            )
            if learning_session is None:
                await edit(t("learning.session_gone", get_current_language()))
                return
            item = await learning_service.mark_known_and_replace(
                session, user=user, user_language=current, learning_session=learning_session, user_word_id=user_word_id
            )
            if item is None:
                await edit(t("learning.session_gone", get_current_language()))
                return
            finished = await learning_service.finish_session_if_complete(session, user, learning_session)
            if finished:
                stats = sessions_repo.session_stats(learning_session)
                await edit(
                    t(
                        "learning.completion", get_current_language(),
                        total=stats["total_reviewed"], new_words=stats["new_words"],
                        correct=stats["correct"], wrong=stats["wrong"], streak=user.current_streak,
                    ),
                    reply_markup=after_session_keyboard(),
                )
            else:
                await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)

        elif data.startswith("learn:reveal:"):
            user_word_id = int(data.removeprefix("learn:reveal:"))
            learning_session = await sessions_repo.get_active_session(
                session, user_id=user.id, language_code=current.language_code
            )
            item = sessions_repo.next_incomplete_item(learning_session) if learning_session else None
            if item is None or item.user_word_id != user_word_id:
                await query.answer()
                await edit(t("learning.session_gone", get_current_language()))
                return
            await query.answer()
            # repetition-system-audit stage sections 7-11: a word never
            # seen before shows a single acknowledgment, not the 4-button
            # difficulty scale - "how well do you remember this" makes no
            # sense before the first exposure. Only once it's back for a
            # real REVIEW (is_new_word False) does the difficulty scale
            # apply.
            keyboard = known_keyboard(user_word_id) if item.is_new_word else rating_keyboard(user_word_id)
            await edit(
                _render_back(item.user_word, current.translation_language),
                reply_markup=keyboard,
            )

        elif data.startswith("review:"):
            _, uw_id_str, grade_str = data.split(":")
            user_word_id = int(uw_id_str)
            grade = ReviewGrade(grade_str)

            learning_session = await sessions_repo.get_active_session(
                session, user_id=user.id, language_code=current.language_code
            )
            if learning_session is None:
                await query.answer()
                await edit(t("learning.session_gone", get_current_language()))
                return

            item = await learning_service.record_review_answer(session, learning_session, user_word_id, grade=grade)
            if item is None:
                await query.answer()
                await edit(t("learning.session_gone", get_current_language()))
                return

            await query.answer()
            finished = await learning_service.finish_session_if_complete(session, user, learning_session)
            if finished:
                stats = sessions_repo.session_stats(learning_session)
                await edit(
                    t(
                        "learning.completion", get_current_language(),
                        total=stats["total_reviewed"], new_words=stats["new_words"],
                        correct=stats["correct"], wrong=stats["wrong"], streak=user.current_streak,
                    ),
                    reply_markup=after_session_keyboard(),
                )
            else:
                await _show_current_word(session, edit, learning_session, current.translation_language, user_id=user.id)


learning_callback_handler = CallbackQueryHandler(handle_learning_callback, pattern="^(learn|review):")
