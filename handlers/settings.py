"""⚙️ Настройки (spec section 15).

Entry point (show_settings) is reached from the main menu's plain-text
"⚙️ Настройки" button; every subsequent interaction is inline-keyboard
callbacks routed through settings_callback_handler. Because it's pure
callback routing keyed off the database (no ConversationHandler state),
it needs no persistence to survive a bot restart - whatever is on screen
next time is simply re-derived from the current row.

"📚 Количество слов" edits the CURRENT language's UserLanguage.daily_new_words
(spec section 8: stored per learning language). "💎 Подписка" is read-only
here - buying/renewing PRO is Stage 13 (Telegram Stars).
"""
from __future__ import annotations

from datetime import time

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import get_settings
from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.language import settings_add_learning_language_keyboard
from keyboards.settings import (
    add_language_level_keyboard,
    addlang_goal_pick_keyboard,
    addlang_industry_pick_keyboard,
    back_to_settings_keyboard,
    difficulty_pick_keyboard,
    goal_pick_keyboard,
    industry_pick_keyboard,
    interface_language_pick_keyboard,
    language_switch_keyboard,
    notification_slot_keyboard,
    notification_time_keyboard,
    placement_translate_keyboard,
    placement_word_keyboard,
    reset_confirm_keyboard,
    review_settings_keyboard,
    settings_home_keyboard,
    timezone_pick_keyboard,
    timezone_search_results_keyboard,
    topics_keyboard,
)
from keyboards.main_menu import main_menu_keyboard
from services import level_placement_service, subscription_service
from services.ai_errors import AIConfigurationError, AIError
from services.learning_service import REVIEW_MODE_CHOICES
from utils.i18n import get_current_language, set_current_language, t
from utils.languages import LANGUAGE_BY_CODE, language_display_name
from utils.logging import get_logger
from utils.support import support_message
from utils.telegram_helpers import safe_edit_message_text
from utils.timezones import TIMEZONE_BY_NAME, is_valid_timezone, search_timezones
from utils.topics import MAX_CUSTOM_TOPIC_LENGTH, MAX_SELECTED_TOPICS, PRESET_TOPICS

logger = get_logger(__name__)

MODE = "settings_timezone_search"
_PRESET_TOPIC_SET = set(PRESET_TOPICS)


async def _build_summary(session, user) -> str:
    languages = await user_languages_repo.get_user_languages(session, user.id)
    interface_lang = LANGUAGE_BY_CODE.get(user.interface_language)

    lines = [
        t("settings.title", get_current_language()),
        "",
        t(
            "settings.interface_language",
            get_current_language(),
            flag=interface_lang.flag if interface_lang else "",
            name=language_display_name(interface_lang) if interface_lang else user.interface_language,
        ),
        t("settings.timezone", get_current_language(), timezone=user.timezone),
    ]
    current_language = next((ul for ul in languages if ul.is_current), None)
    if current_language is not None:
        lines.append(
            t("settings.current_goal", get_current_language(), goal=t(f"goal.{current_language.learning_goal}", get_current_language()))
            if current_language.learning_goal
            else t("settings.current_goal_none", get_current_language())
        )
        if current_language.selected_topics:
            topic_labels = ", ".join(
                t(f"topic.{topic}", get_current_language()) if topic in _PRESET_TOPIC_SET else topic
                for topic in current_language.selected_topics
            )
            lines.append(t("settings.current_topics", get_current_language(), topics=topic_labels))
        else:
            lines.append(t("settings.current_topics_none", get_current_language()))
    lines += [
        "",
        t("settings.notifications_on", get_current_language())
        if user.notifications_enabled
        else t("settings.notifications_off", get_current_language()),
        t("settings.morning_time", get_current_language(), time=user.morning_time.strftime("%H:%M")),
        t("settings.afternoon_time", get_current_language(), time=user.afternoon_time.strftime("%H:%M")),
        t("settings.evening_time", get_current_language(), time=user.evening_time.strftime("%H:%M")),
        "",
        t("settings.subscription", get_current_language(), status=t(f"subscription.status.{user.subscription_status}", get_current_language())),
    ]
    if user.trial_end:
        lines.append(t("settings.trial_until", get_current_language(), date=user.trial_end.isoformat()))

    if languages:
        lines.append("")
        lines.append(t("settings.your_languages", get_current_language()))
        for ul in languages:
            lang = LANGUAGE_BY_CODE.get(ul.language_code)
            lines.append(
                t(
                    "settings.language_row",
                    get_current_language(),
                    flag=lang.flag if lang else "",
                    name=language_display_name(lang) if lang else ul.language_code,
                    level=t(f"level.{ul.level}", get_current_language()),
                    current_marker=t("settings.current_marker", get_current_language()) if ul.is_current else "",
                )
            )

    return "\n".join(lines)


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, telegram_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
            return
        set_current_language(user.interface_language)

        user = await subscription_service.refresh_expired_trial(session, user)
        summary = await _build_summary(session, user)

    await update.message.reply_text(summary, reply_markup=settings_home_keyboard())


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Every free-text step in Settings routes through here via
    context.user_data["mode"] == MODE (same pattern handlers/dictionary.py
    etc. use), branching further on "settings_submode" the same way
    handlers/words.py's "words_submode" tells its own free-text handler
    apart from plain number selection - 🔎 Другой часовой пояс (bugfix
    stage) is the default/no-submode case, kept exactly as it was."""
    submode = context.user_data.get("settings_submode")

    if submode == "topics_custom":
        await _handle_custom_topic_input(update, context, text)
        return
    if submode == "industry_custom":
        await _handle_custom_industry_input(update, context, text)
        return
    if submode == "addlang_industry_custom":
        await _handle_addlang_custom_industry_input(update, context, text)
        return
    if submode == "placement_answer":
        await _handle_placement_answer_input(update, context, text)
        return

    matches = search_timezones(text)
    if not matches:
        await update.message.reply_text(t("settings.timezone_search_empty", get_current_language()))
        return
    await update.message.reply_text(
        t("settings.timezone_search_results", get_current_language()), reply_markup=timezone_search_results_keyboard(matches)
    )


async def _handle_custom_topic_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    context.user_data.pop("settings_submode", None)
    context.user_data.pop("mode", None)
    topic = text.strip()[:MAX_CUSTOM_TOPIC_LENGTH]
    if not topic:
        return

    async with session_scope() as session:
        user = await _get_user_or_warn_message(session, update)
        if user is None:
            return
        current = await user_languages_repo.get_current_language(session, user.id)
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return
        topics = list(current.selected_topics)
        if topic not in topics:
            if len(topics) >= MAX_SELECTED_TOPICS:
                await update.message.reply_text(t("settings.topics_limit_reached", get_current_language(), max=MAX_SELECTED_TOPICS))
                return
            topics.append(topic)
            await user_languages_repo.set_topics(session, current, topics=topics)
        await update.message.reply_text(t("settings.topics_title", get_current_language()), reply_markup=topics_keyboard(topics))


async def _handle_custom_industry_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    context.user_data.pop("settings_submode", None)
    context.user_data.pop("mode", None)
    industry = text.strip()[:MAX_CUSTOM_TOPIC_LENGTH]
    if not industry:
        return

    async with session_scope() as session:
        user = await _get_user_or_warn_message(session, update)
        if user is None:
            return
        current = await user_languages_repo.get_current_language(session, user.id)
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return
        await user_languages_repo.set_goal(session, current, learning_goal="work", work_industry=industry)
        await update.message.reply_text(t("settings.industry_updated", get_current_language()))


async def _handle_addlang_custom_industry_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """"✏️ Другое" answer to the add-language flow's work-industry
    question (set:addlang:industry:other) - the free-text counterpart of
    _handle_custom_industry_input, but creates the pending NEW language
    instead of updating the current one."""
    context.user_data.pop("settings_submode", None)
    context.user_data.pop("mode", None)
    pending = context.user_data.pop("addlang_pending", None)
    industry = text.strip()[:MAX_CUSTOM_TOPIC_LENGTH]
    if pending is None or not industry:
        return

    async with session_scope() as session:
        user = await _get_user_or_warn_message(session, update)
        if user is None:
            return
        new_language = await _create_pending_new_language(session, user, pending, goal="work", work_industry=industry)
        if new_language is None:
            await update.message.reply_text(
                t("settings.add_language_duplicate", get_current_language()), reply_markup=settings_home_keyboard()
            )
            return
        lang = LANGUAGE_BY_CODE[pending["learning_code"]]
        await update.message.reply_text(
            t("settings.add_language_added", get_current_language(), flag=lang.flag, name=language_display_name(lang)),
            reply_markup=settings_home_keyboard(),
        )


async def _handle_placement_answer_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """The free-text half of 🤖 Узнать мой уровень's flow - only a
    "translate"-kind question ever puts settings_submode into this
    state (see _render_placement_question); a "word" question is
    answered via ✅/❌ buttons instead, in handle_settings_callback."""
    state = context.user_data.get("placement_test")
    if state is None:
        context.user_data.pop("settings_submode", None)
        context.user_data.pop("mode", None)
        await update.message.reply_text(t("settings.placement.expired", get_current_language()))
        return

    answer = text.strip()
    if not answer:
        return
    state["answers"].append(answer)
    state["index"] += 1

    async with session_scope() as session:
        user = await _get_user_or_warn_message(session, update)
        if user is None:
            return
        if state["index"] >= len(state["questions"]):
            await _finish_placement_test(update.message.reply_text, context, session, user, state)
        else:
            await _render_placement_question(update.message.reply_text, context, state)


async def _get_user_or_warn_message(session, update: Update) -> object | None:
    user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
    if user is None:
        await update.message.reply_text(t("settings.profile_not_found", get_current_language()))
        return None
    set_current_language(user.interface_language)
    return user


async def _get_user_or_warn(session, query) -> object | None:
    user = await users_repo.get_by_telegram_id(session, query.from_user.id)
    if user is None:
        await query.answer(t("settings.profile_not_found", get_current_language()), show_alert=True)
        return None
    set_current_language(user.interface_language)
    return user


async def _render_home(query, session, user) -> None:
    summary = await _build_summary(session, user)
    await safe_edit_message_text(query, summary, reply_markup=settings_home_keyboard())


async def _render_placement_question(send, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    """🤖 Узнать мой уровень (real user request): renders whichever of
    the 6 placement-test questions state["index"] currently points at.
    "word" questions are answered by tapping ✅/❌ (no free text needed);
    "translate" questions switch context.user_data into settings.py's
    own free-text mode so the next message the user sends is treated as
    their translation attempt (or their "нет") - handle_text_input's
    "placement_answer" submode routes it back here."""
    question = state["questions"][state["index"]]
    header = t(
        "settings.placement.question_header", get_current_language(),
        current=state["index"] + 1, total=len(state["questions"]),
    )
    if question["kind"] == "word":
        context.user_data.pop("mode", None)
        context.user_data.pop("settings_submode", None)
        text = f"{header}\n\n" + t("settings.placement.word_prompt", get_current_language(), word=question["prompt"])
        await send(text, reply_markup=placement_word_keyboard())
    else:
        context.user_data["mode"] = MODE
        context.user_data["settings_submode"] = "placement_answer"
        text = f"{header}\n\n" + t("settings.placement.translate_prompt", get_current_language(), sentence=question["prompt"])
        await send(text, reply_markup=placement_translate_keyboard())


async def _finish_placement_test(send, context: ContextTypes.DEFAULT_TYPE, session, user, state: dict) -> None:
    context.user_data.pop("placement_test", None)
    context.user_data.pop("mode", None)
    context.user_data.pop("settings_submode", None)

    addlang = state.get("addlang")
    if addlang is not None:
        await _finish_placement_test_for_new_language(send, context, session, user, state, addlang)
        return

    current = await user_languages_repo.get_current_language(session, user.id)
    if current is None:
        await send(t("card.no_language", get_current_language()), reply_markup=difficulty_pick_keyboard())
        return

    await send(t("settings.placement.grading", get_current_language()))
    try:
        level = await level_placement_service.grade_placement_test(
            language_code=current.language_code, translation_language=current.translation_language,
            questions=state["questions"], answers=state["answers"], user_id=user.id,
        )
    except AIConfigurationError:
        await send(t("ai.not_configured", get_current_language()), reply_markup=difficulty_pick_keyboard())
        return
    except AIError:
        await send(t("ai.generic_error", get_current_language()), reply_markup=difficulty_pick_keyboard())
        return

    await user_languages_repo.set_manual_difficulty(session, current, level=level)
    await send(
        t("settings.placement.result", get_current_language(), level=t(f"level.{level}", get_current_language())),
        reply_markup=difficulty_pick_keyboard(),
    )


async def _finish_placement_test_for_new_language(
    send, context: ContextTypes.DEFAULT_TYPE, session, user, state: dict, addlang: dict
) -> None:
    """The 🤖 Узнать мой уровень branch of adding a NEW language: unlike
    _finish_placement_test's original case there is no existing
    UserLanguage row to update. The graded level doesn't create the row
    either - same as the direct level-pick branch (set:addlang:level:),
    it stashes the pending choice and asks the goal question next; the
    row is only created once that's answered too (real user request:
    the goal question must appear here exactly like it does at
    onboarding, so both paths into this screen have to go through it)."""
    learning_code, translation_code = addlang["learning_code"], addlang["translation_code"]
    await send(t("settings.placement.grading", get_current_language()))
    try:
        level = await level_placement_service.grade_placement_test(
            language_code=learning_code, translation_language=translation_code,
            questions=state["questions"], answers=state["answers"], user_id=user.id,
        )
    except AIConfigurationError:
        await send(t("ai.not_configured", get_current_language()), reply_markup=settings_home_keyboard())
        return
    except AIError:
        await send(t("ai.generic_error", get_current_language()), reply_markup=settings_home_keyboard())
        return

    context.user_data["addlang_pending"] = {
        "learning_code": learning_code, "translation_code": translation_code, "level": level,
    }
    await send(
        t("settings.placement.level_then_goal", get_current_language(), level=t(f"level.{level}", get_current_language())),
        reply_markup=addlang_goal_pick_keyboard(),
    )


async def _create_pending_new_language(session, user, pending: dict, *, goal: str | None, work_industry: str | None):
    """Shared tail of the add-language flow (direct level pick, placement
    test, and the goal/industry questions that now follow either one):
    actually create the UserLanguage row once every question has been
    answered. Returns None on a duplicate language+translation pair
    instead of raising, so callers can show the existing duplicate
    message without a try/except of their own."""
    try:
        new_language = await user_languages_repo.add_language(
            session, user_id=user.id, language_code=pending["learning_code"],
            translation_language=pending["translation_code"], level=pending["level"],
            daily_new_words=get_settings().plan_limits.daily_new_words_options[0],
            learning_goal=goal, work_industry=work_industry,
        )
    except user_languages_repo.DuplicateUserLanguageError:
        return None
    await user_languages_repo.set_active_language(session, user_id=user.id, user_language_id=new_language.id)
    return new_language


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every branch below answers the callback query exactly once - never
    unconditionally up front AND again with a toast message, since
    Telegram rejects a second answerCallbackQuery for the same query
    (a real bug found via live testing: the toast-text branches used to
    answer twice, the second call raised, and _render_home never ran -
    the settings screen silently never updated for language/level/daily-
    words/notification changes)."""
    query = update.callback_query
    data = query.data

    async def edit(text: str, reply_markup=None) -> None:
        await safe_edit_message_text(query, text, reply_markup=reply_markup)

    async with session_scope() as session:
        user = await _get_user_or_warn(session, query)
        if user is None:
            return

        if data == "set:home":
            await query.answer()
            context.user_data.pop("mode", None)
            context.user_data.pop("settings_submode", None)
            await _render_home(query, session, user)

        elif data == "set:lang:list":
            await query.answer()
            languages = await user_languages_repo.get_user_languages(session, user.id)
            max_languages = (
                get_settings().plan_limits.pro_max_languages
                if subscription_service.has_pro_access(user)
                else get_settings().plan_limits.free_max_languages
            )
            await safe_edit_message_text(query,
                t("settings.pick_current_language", get_current_language()),
                reply_markup=language_switch_keyboard(languages, can_add_more=len(languages) < max_languages),
            )

        elif data == "set:addlang:start":
            languages = await user_languages_repo.get_user_languages(session, user.id)
            max_languages = (
                get_settings().plan_limits.pro_max_languages
                if subscription_service.has_pro_access(user)
                else get_settings().plan_limits.free_max_languages
            )
            if len(languages) >= max_languages:
                await query.answer(t("settings.add_language_limit_reached", get_current_language(), max=max_languages), show_alert=True)
                return
            await query.answer()
            await safe_edit_message_text(query,
                t("settings.add_language_pick_learning", get_current_language()),
                reply_markup=settings_add_learning_language_keyboard(),
            )

        elif data.startswith("set:addlang:learn:"):
            await query.answer()
            learning_code = data.removeprefix("set:addlang:learn:")
            # study-flow-rework stage sections 4-6: no separate "which
            # language to translate into" question - translation_language
            # always equals the user's own interface_language.
            translation_code = user.interface_language
            await safe_edit_message_text(query,
                t("settings.pick_level", get_current_language()),
                reply_markup=add_language_level_keyboard(learning_code, translation_code),
            )

        elif data.startswith("set:addlang:level:"):
            # study-flow-rework stage (real user feedback): the bot must
            # never offer/generate words on its own outside an explicit
            # 📚 Учить слова tap - the old "how many new words per day?"
            # step here fed the retired auto-quota generator
            # (learning_service.get_new_words_for_today, unreachable from
            # any screen since "Учить слова" was reworked to always
            # generate exactly 2 words on request).
            # Real user request: onboarding already asks "Для чего вы
            # изучаете этот язык?" (learning_goal, section 18) - adding a
            # language later never did. The level pick no longer creates
            # the row immediately; it stashes the pending choice and asks
            # the same goal question next, exactly like onboarding does.
            learning_code, translation_code, level = data.removeprefix("set:addlang:level:").split(":")
            await query.answer()
            context.user_data["addlang_pending"] = {
                "learning_code": learning_code, "translation_code": translation_code, "level": level,
            }
            await edit(t("settings.pick_goal", get_current_language()), reply_markup=addlang_goal_pick_keyboard())

        elif data.startswith("set:addlang:placement:start:"):
            # 🤖 Узнать мой уровень when adding a NEW language (real user
            # request - this button used to only exist for changing the
            # difficulty of a language already added). Reuses the exact
            # same placement_test state/question-rendering machinery as
            # ⚙️ Настройки → 🎚 Уровень сложности изучения языка; the
            # "addlang" marker in the stored state is how
            # _finish_placement_test tells the two flows apart, since the
            # language doesn't exist as a UserLanguage row yet here.
            learning_code, translation_code = data.removeprefix("set:addlang:placement:start:").split(":")
            await query.answer()
            await edit(t("settings.placement.generating", get_current_language()))
            try:
                questions = await level_placement_service.start_placement_test(
                    language_code=learning_code, translation_language=translation_code, user_id=user.id,
                )
            except AIConfigurationError:
                await edit(t("ai.not_configured", get_current_language()), reply_markup=add_language_level_keyboard(learning_code, translation_code))
                return
            except AIError:
                await edit(t("ai.generic_error", get_current_language()), reply_markup=add_language_level_keyboard(learning_code, translation_code))
                return
            context.user_data["placement_test"] = {
                "questions": questions, "index": 0, "answers": [],
                "addlang": {"learning_code": learning_code, "translation_code": translation_code},
            }
            await _render_placement_question(edit, context, context.user_data["placement_test"])

        elif data.startswith("set:addlang:goal:"):
            # Real user request: the "Для чего вы изучаете этот язык?"
            # step (already asked at onboarding) is now also asked here,
            # right after the level pick or placement test - see
            # set:addlang:level: / _finish_placement_test_for_new_language
            # for where "addlang_pending" gets set.
            code = data.removeprefix("set:addlang:goal:")
            pending = context.user_data.get("addlang_pending")
            if pending is None:
                await query.answer(t("settings.addlang.expired", get_current_language()), show_alert=True)
                return
            goal = None if code == "skip" else code
            if goal == "work":
                await query.answer()
                await edit(t("settings.pick_industry", get_current_language()), reply_markup=addlang_industry_pick_keyboard())
                return
            context.user_data.pop("addlang_pending", None)
            new_language = await _create_pending_new_language(session, user, pending, goal=goal, work_industry=None)
            if new_language is None:
                await query.answer(t("settings.add_language_duplicate", get_current_language()), show_alert=True)
                return
            lang = LANGUAGE_BY_CODE[pending["learning_code"]]
            await query.answer(t("settings.add_language_added", get_current_language(), flag=lang.flag, name=language_display_name(lang)))
            await _render_home(query, session, user)

        elif data.startswith("set:addlang:industry:"):
            code = data.removeprefix("set:addlang:industry:")
            pending = context.user_data.get("addlang_pending")
            if pending is None:
                await query.answer(t("settings.addlang.expired", get_current_language()), show_alert=True)
                return
            if code == "other":
                context.user_data["mode"] = MODE
                context.user_data["settings_submode"] = "addlang_industry_custom"
                await query.answer()
                await edit(t("onboarding.industry_custom_prompt", get_current_language()))
                return
            context.user_data.pop("addlang_pending", None)
            industry = None if code == "skip" else code
            new_language = await _create_pending_new_language(session, user, pending, goal="work", work_industry=industry)
            if new_language is None:
                await query.answer(t("settings.add_language_duplicate", get_current_language()), show_alert=True)
                return
            lang = LANGUAGE_BY_CODE[pending["learning_code"]]
            await query.answer(t("settings.add_language_added", get_current_language(), flag=lang.flag, name=language_display_name(lang)))
            await _render_home(query, session, user)

        elif data.startswith("set:lang:pick:"):
            user_language_id = int(data.removeprefix("set:lang:pick:"))
            target = await user_languages_repo.set_active_language(
                session, user_id=user.id, user_language_id=user_language_id
            )
            lang = LANGUAGE_BY_CODE.get(target.language_code)
            await query.answer(
                t(
                    "settings.current_language_updated",
                    get_current_language(),
                    flag=lang.flag if lang else "",
                    name=language_display_name(lang) if lang else target.language_code,
                )
            )
            await _render_home(query, session, user)

        elif data == "set:iface:list":
            await query.answer()
            await safe_edit_message_text(query,
                t("settings.pick_interface_language", get_current_language()),
                reply_markup=interface_language_pick_keyboard(),
            )

        elif data.startswith("set:iface:pick:"):
            code = data.removeprefix("set:iface:pick:")
            await users_repo.update_user(session, user, interface_language=code)
            # study-flow-rework stage sections 5-6: translation_language
            # always equals interface_language - propagate to every
            # language this user already studies, not just new ones.
            await user_languages_repo.set_translation_language_for_all(session, user_id=user.id, translation_language=code)
            set_current_language(code)
            lang = LANGUAGE_BY_CODE[code]
            await query.answer(t("settings.interface_language_updated", code, flag=lang.flag, name=language_display_name(lang, code)))
            await _render_home(query, session, user)
            # The persistent reply keyboard at the bottom carries no
            # callback_data - it only updates when a NEW ReplyKeyboardMarkup
            # is sent, so the language switch has to explicitly resend it,
            # not just edit the inline settings screen above.
            await query.message.reply_text(
                t("settings.main_menu_updated", code), reply_markup=main_menu_keyboard(code)
            )

        elif data == "set:goal:list":
            await query.answer()
            await safe_edit_message_text(query,
                t("settings.pick_goal", get_current_language()), reply_markup=goal_pick_keyboard()
            )

        elif data.startswith("set:goal:pick:"):
            goal = data.removeprefix("set:goal:pick:")
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            if goal == "work":
                await user_languages_repo.set_goal(session, current, learning_goal=goal, work_industry=current.work_industry)
                await query.answer()
                await safe_edit_message_text(query,
                    t("settings.pick_industry", get_current_language()), reply_markup=industry_pick_keyboard()
                )
                return
            # Any goal other than "work" must never keep a stale
            # work_industry around (settings-improvements stage section
            # 20 - the same rule handlers/start.py's onboarding flow
            # follows for a freshly-created UserLanguage).
            await user_languages_repo.set_goal(session, current, learning_goal=goal, work_industry=None)
            await query.answer(t("settings.goal_updated", get_current_language()))
            await _render_home(query, session, user)

        elif data.startswith("set:goal:industry:"):
            code = data.removeprefix("set:goal:industry:")
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            if code == "other":
                context.user_data["mode"] = MODE
                context.user_data["settings_submode"] = "industry_custom"
                await query.answer()
                await safe_edit_message_text(query, t("onboarding.industry_custom_prompt", get_current_language()))
                return
            await user_languages_repo.set_goal(session, current, learning_goal="work", work_industry=code)
            await query.answer(t("settings.industry_updated", get_current_language()))
            await _render_home(query, session, user)

        elif data == "set:topics:list":
            await query.answer()
            context.user_data.pop("mode", None)
            context.user_data.pop("settings_submode", None)
            current = await user_languages_repo.get_current_language(session, user.id)
            topics = current.selected_topics if current is not None else []
            await safe_edit_message_text(query, t("settings.topics_title", get_current_language()), reply_markup=topics_keyboard(topics))

        elif data.startswith("set:topics:toggle:"):
            code = data.removeprefix("set:topics:toggle:")
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            topics = list(current.selected_topics)
            if code in topics:
                topics.remove(code)
            elif len(topics) >= MAX_SELECTED_TOPICS:
                await query.answer(t("settings.topics_limit_reached", get_current_language(), max=MAX_SELECTED_TOPICS), show_alert=True)
                return
            else:
                topics.append(code)
            await user_languages_repo.set_topics(session, current, topics=topics)
            await query.answer()
            await safe_edit_message_text(query, t("settings.topics_title", get_current_language()), reply_markup=topics_keyboard(topics))

        elif data.startswith("set:topics:removecustom:"):
            index = int(data.removeprefix("set:topics:removecustom:"))
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            topics = list(current.selected_topics)
            custom_topics = [topic for topic in topics if topic not in _PRESET_TOPIC_SET]
            if 0 <= index < len(custom_topics):
                topics.remove(custom_topics[index])
                await user_languages_repo.set_topics(session, current, topics=topics)
            await query.answer()
            await safe_edit_message_text(query, t("settings.topics_title", get_current_language()), reply_markup=topics_keyboard(topics))

        elif data == "set:topics:add_custom":
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            if len(current.selected_topics) >= MAX_SELECTED_TOPICS:
                await query.answer(t("settings.topics_limit_reached", get_current_language(), max=MAX_SELECTED_TOPICS), show_alert=True)
                return
            context.user_data["mode"] = MODE
            context.user_data["settings_submode"] = "topics_custom"
            await query.answer()
            await safe_edit_message_text(query, t("settings.topics_custom_prompt", get_current_language()))

        elif data == "set:notif:slots":
            await query.answer()
            await safe_edit_message_text(query,
                t("settings.pick_notification_slot", get_current_language()), reply_markup=notification_slot_keyboard()
            )

        elif data.startswith("set:notif:slot:"):
            await query.answer()
            slot = data.removeprefix("set:notif:slot:")
            await safe_edit_message_text(query,
                t("settings.pick_notification_time", get_current_language()), reply_markup=notification_time_keyboard(slot)
            )

        elif data.startswith("set:notif:time:"):
            _, _, _, slot, raw_time = data.split(":")
            parsed = time(int(raw_time[:2]), int(raw_time[2:]))
            field_by_slot = {
                "morning": "morning_time",
                "afternoon": "afternoon_time",
                "evening": "evening_time",
            }
            await users_repo.update_user(session, user, **{field_by_slot[slot]: parsed})
            await query.answer(
                t(
                    "settings.notification_time_updated",
                    get_current_language(),
                    slot=t(f"notification_slot.{slot}", get_current_language()),
                    time=parsed.strftime("%H:%M"),
                )
            )
            await _render_home(query, session, user)

        elif data == "set:notif:toggle":
            new_value = not user.notifications_enabled
            await users_repo.update_user(session, user, notifications_enabled=new_value)
            await query.answer(
                t("settings.notifications_toggled_on" if new_value else "settings.notifications_toggled_off", get_current_language())
            )
            await _render_home(query, session, user)

        elif data == "set:revsettings:home":
            await query.answer()
            await safe_edit_message_text(query,
                t("settings.review_settings.header", get_current_language()), reply_markup=review_settings_keyboard(user)
            )

        elif data.startswith("set:revsettings:slot:"):
            slot = data.removeprefix("set:revsettings:slot:")
            field_by_slot = {
                "morning": "morning_enabled",
                "afternoon": "afternoon_enabled",
                "evening": "evening_enabled",
            }
            if slot not in field_by_slot:
                await query.answer()
                return
            new_value = not getattr(user, field_by_slot[slot])
            await users_repo.update_user(session, user, **{field_by_slot[slot]: new_value})
            key = "settings.review_settings.slot_toggled_on" if new_value else "settings.review_settings.slot_toggled_off"
            await query.answer(t(key, get_current_language(), slot=t(f"notification_slot.{slot}", get_current_language())))
            await safe_edit_message_text(query,
                t("settings.review_settings.header", get_current_language()), reply_markup=review_settings_keyboard(user)
            )

        elif data.startswith("set:revsettings:mode:"):
            mode = data.removeprefix("set:revsettings:mode:")
            if mode != "ask" and mode not in REVIEW_MODE_CHOICES:
                await query.answer()
                return
            await users_repo.update_user(session, user, review_mode=None if mode == "ask" else mode)
            await query.answer(t("settings.review_settings.mode_updated", get_current_language()))
            await safe_edit_message_text(query,
                t("settings.review_settings.header", get_current_language()), reply_markup=review_settings_keyboard(user)
            )

        elif data == "set:difficulty:list":
            await query.answer()
            context.user_data.pop("placement_test", None)
            context.user_data.pop("mode", None)
            context.user_data.pop("settings_submode", None)
            await safe_edit_message_text(query,
                t("settings.pick_difficulty", get_current_language()), reply_markup=difficulty_pick_keyboard()
            )

        elif data.startswith("set:difficulty:pick:"):
            level = data.removeprefix("set:difficulty:pick:")
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            await user_languages_repo.set_manual_difficulty(session, current, level=level)
            await query.answer(t("settings.difficulty_updated", get_current_language(), level=t(f"level.{level}", get_current_language())))
            await _render_home(query, session, user)

        elif data == "set:difficulty:auto":
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            await user_languages_repo.set_automatic_difficulty(session, current)
            await query.answer(t("settings.difficulty_auto_updated", get_current_language()))
            await _render_home(query, session, user)

        elif data == "set:difficulty:placement:start":
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is None:
                await query.answer(t("card.no_language", get_current_language()), show_alert=True)
                return
            await query.answer()
            await edit(t("settings.placement.generating", get_current_language()))
            try:
                questions = await level_placement_service.start_placement_test(
                    language_code=current.language_code, translation_language=current.translation_language, user_id=user.id,
                )
            except AIConfigurationError:
                await edit(t("ai.not_configured", get_current_language()), reply_markup=difficulty_pick_keyboard())
                return
            except AIError:
                await edit(t("ai.generic_error", get_current_language()), reply_markup=difficulty_pick_keyboard())
                return
            context.user_data["placement_test"] = {"questions": questions, "index": 0, "answers": []}
            await _render_placement_question(edit, context, context.user_data["placement_test"])

        elif data.startswith("set:placement:answer:"):
            state = context.user_data.get("placement_test")
            if state is None:
                await query.answer(t("settings.placement.expired", get_current_language()), show_alert=True)
                return
            await query.answer()
            answer = data.removeprefix("set:placement:answer:")
            state["answers"].append(answer)
            state["index"] += 1
            if state["index"] >= len(state["questions"]):
                await _finish_placement_test(edit, context, session, user, state)
            else:
                await _render_placement_question(edit, context, state)

        elif data == "set:placement:cancel":
            await query.answer()
            state = context.user_data.pop("placement_test", None)
            context.user_data.pop("mode", None)
            context.user_data.pop("settings_submode", None)
            addlang = state.get("addlang") if state else None
            if addlang is not None:
                await edit(
                    t("settings.placement.cancelled", get_current_language()),
                    reply_markup=add_language_level_keyboard(addlang["learning_code"], addlang["translation_code"]),
                )
            else:
                await edit(t("settings.placement.cancelled", get_current_language()), reply_markup=difficulty_pick_keyboard())

        elif data == "set:tz:list":
            await query.answer()
            context.user_data.pop("mode", None)
            context.user_data.pop("settings_submode", None)
            await safe_edit_message_text(query, t("settings.pick_timezone", get_current_language()), reply_markup=timezone_pick_keyboard())

        elif data == "set:tz:search":
            await query.answer()
            context.user_data.pop("settings_submode", None)
            context.user_data["mode"] = MODE
            await safe_edit_message_text(query, t("settings.timezone_search_prompt", get_current_language()))

        elif data.startswith("set:tz:pick:"):
            iana_name = data.removeprefix("set:tz:pick:")
            if not is_valid_timezone(iana_name):
                await query.answer(t("settings.timezone_search_empty", get_current_language()), show_alert=True)
                return
            context.user_data.pop("mode", None)
            await users_repo.update_user(session, user, timezone=iana_name)
            label = TIMEZONE_BY_NAME[iana_name].label if iana_name in TIMEZONE_BY_NAME else iana_name
            await query.answer(t("settings.timezone_updated", get_current_language(), name=label))
            await _render_home(query, session, user)

        elif data == "set:sub":
            await query.answer()
            user = await subscription_service.refresh_expired_trial(session, user)
            status_line = t("settings.subscription", get_current_language(), status=t(f"subscription.status.{user.subscription_status}", get_current_language()))
            lines = [status_line]
            if user.trial_end:
                lines.append(t("settings.trial_until", get_current_language(), date=user.trial_end.isoformat()))
            await safe_edit_message_text(query, "\n".join(lines), reply_markup=back_to_settings_keyboard())

        elif data == "set:support":
            await query.answer()
            await safe_edit_message_text(
                query, support_message(get_current_language()), reply_markup=back_to_settings_keyboard()
            )

        elif data == "set:reset:confirm":
            await query.answer()
            await safe_edit_message_text(
                query, t("settings.reset.warning", get_current_language()), reply_markup=reset_confirm_keyboard()
            )

        elif data == "set:reset:cancel":
            await query.answer()
            await _render_home(query, session, user)

        elif data == "set:reset:do":
            # 🗑 Сброс бота (real user request): irreversible, so answer
            # BEFORE the delete - same reasoning as every other slow/
            # destructive action in this codebase (never risk a too-late
            # callback-query answer once the row is already gone).
            await query.answer()
            await users_repo.delete_user(session, user)
            await safe_edit_message_text(query, t("settings.reset.done", get_current_language()))
            await query.message.reply_text(
                t("settings.reset.restart_hint", get_current_language()), reply_markup=ReplyKeyboardRemove()
            )
            context.user_data.clear()

        else:
            await query.answer()
            logger.warning("Unhandled settings callback_data: %s", data)


settings_callback_handler = CallbackQueryHandler(handle_settings_callback, pattern="^set:")
