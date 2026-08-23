"""⚙️ Настройки (spec section 15).

Entry point (show_settings) is reached from the main menu's plain-text
"⚙️ Настройки" button; every subsequent interaction is inline-keyboard
callbacks routed through settings_callback_handler. Because it's pure
callback routing keyed off the database (no ConversationHandler state),
it needs no persistence to survive a bot restart - whatever is on screen
next time is simply re-derived from the current row.

"📚 Количество слов" edits the CURRENT language's UserLanguage.daily_new_words
(spec section 8: stored per learning language). "👤 Мой уровень" edits the
user-wide User.level (the profile-level default). "💎 Подписка" is read-only
here - buying/renewing PRO is Stage 13 (Telegram Stars).
"""
from __future__ import annotations

from datetime import time

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import get_settings
from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.language import settings_add_learning_language_keyboard
from keyboards.settings import (
    add_language_level_keyboard,
    add_language_words_keyboard,
    back_to_settings_keyboard,
    daily_words_pick_keyboard,
    difficulty_pick_keyboard,
    goal_pick_keyboard,
    industry_pick_keyboard,
    interface_language_pick_keyboard,
    language_switch_keyboard,
    notification_slot_keyboard,
    notification_time_keyboard,
    review_settings_keyboard,
    settings_home_keyboard,
    timezone_pick_keyboard,
    timezone_search_results_keyboard,
    topics_keyboard,
)
from keyboards.main_menu import main_menu_keyboard
from services import subscription_service
from services.learning_service import REVIEW_MODE_CHOICES
from services.notification_service import NOTIFICATION_WORD_COUNT_OPTIONS
from utils.i18n import get_current_language, set_current_language, t
from utils.languages import LANGUAGE_BY_CODE, language_display_name
from utils.logging import get_logger
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
        t("settings.level", get_current_language(), level=t(f"level.{user.level}", get_current_language())),
        t("settings.daily_words", get_current_language(), count=user.daily_new_words),
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
            await query.answer()
            learning_code, translation_code, level = data.removeprefix("set:addlang:level:").split(":")
            options = get_settings().plan_limits.daily_new_words_options
            await safe_edit_message_text(query,
                t("settings.pick_daily_words", get_current_language()),
                reply_markup=add_language_words_keyboard(learning_code, translation_code, level, options),
            )

        elif data.startswith("set:addlang:words:"):
            learning_code, translation_code, level, count = data.removeprefix("set:addlang:words:").split(":")
            try:
                new_language = await user_languages_repo.add_language(
                    session, user_id=user.id, language_code=learning_code,
                    translation_language=translation_code, level=level, daily_new_words=int(count),
                )
            except user_languages_repo.DuplicateUserLanguageError:
                await query.answer(t("settings.add_language_duplicate", get_current_language()), show_alert=True)
                return
            await user_languages_repo.set_active_language(session, user_id=user.id, user_language_id=new_language.id)
            lang = LANGUAGE_BY_CODE[learning_code]
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

        elif data == "set:words:list":
            await query.answer()
            options = get_settings().plan_limits.daily_new_words_options
            await safe_edit_message_text(query,
                t("settings.pick_daily_words", get_current_language()), reply_markup=daily_words_pick_keyboard(options)
            )

        elif data.startswith("set:words:pick:"):
            count = int(data.removeprefix("set:words:pick:"))
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is not None:
                await user_languages_repo.set_daily_new_words(session, current, count)
            await query.answer(t("settings.daily_words_updated", get_current_language(), count=count))
            await _render_home(query, session, user)

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

        elif data.startswith("set:revsettings:count:"):
            count = int(data.removeprefix("set:revsettings:count:"))
            if count not in NOTIFICATION_WORD_COUNT_OPTIONS:
                await query.answer()
                return
            await users_repo.update_user(session, user, notification_word_count=count)
            await query.answer(t("settings.review_settings.count_updated", get_current_language(), count=count))
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

        else:
            await query.answer()
            logger.warning("Unhandled settings callback_data: %s", data)


settings_callback_handler = CallbackQueryHandler(handle_settings_callback, pattern="^set:")
