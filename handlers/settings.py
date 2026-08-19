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
from keyboards.settings import (
    back_to_settings_keyboard,
    daily_words_pick_keyboard,
    interface_language_pick_keyboard,
    language_switch_keyboard,
    level_pick_keyboard,
    notification_slot_keyboard,
    notification_time_keyboard,
    settings_home_keyboard,
)
from services import subscription_service
from utils.i18n import t
from utils.languages import LANGUAGE_BY_CODE
from utils.logging import get_logger

logger = get_logger(__name__)

_LANG = "ru"


async def _build_summary(session, user) -> str:
    languages = await user_languages_repo.get_user_languages(session, user.id)
    interface_lang = LANGUAGE_BY_CODE.get(user.interface_language)

    lines = [
        t("settings.title", _LANG),
        "",
        t(
            "settings.interface_language",
            _LANG,
            flag=interface_lang.flag if interface_lang else "",
            name=interface_lang.name_ru if interface_lang else user.interface_language,
        ),
        t("settings.level", _LANG, level=t(f"level.{user.level}", _LANG)),
        t("settings.daily_words", _LANG, count=user.daily_new_words),
        t("settings.timezone", _LANG, timezone=user.timezone),
        "",
        t("settings.notifications_on", _LANG)
        if user.notifications_enabled
        else t("settings.notifications_off", _LANG),
        t("settings.morning_time", _LANG, time=user.morning_time.strftime("%H:%M")),
        t("settings.afternoon_time", _LANG, time=user.afternoon_time.strftime("%H:%M")),
        t("settings.evening_time", _LANG, time=user.evening_time.strftime("%H:%M")),
        "",
        t("settings.subscription", _LANG, status=t(f"subscription.status.{user.subscription_status}", _LANG)),
    ]
    if user.trial_end:
        lines.append(t("settings.trial_until", _LANG, date=user.trial_end.isoformat()))

    if languages:
        lines.append("")
        lines.append(t("settings.your_languages", _LANG))
        for ul in languages:
            lang = LANGUAGE_BY_CODE.get(ul.language_code)
            lines.append(
                t(
                    "settings.language_row",
                    _LANG,
                    flag=lang.flag if lang else "",
                    name=lang.name_ru if lang else ul.language_code,
                    level=t(f"level.{ul.level}", _LANG),
                    current_marker=t("settings.current_marker", _LANG) if ul.is_current else "",
                )
            )

    return "\n".join(lines)


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, telegram_user.id)
        if user is None:
            await update.message.reply_text(t("settings.profile_not_found", _LANG))
            return

        user = await subscription_service.refresh_expired_trial(session, user)
        summary = await _build_summary(session, user)

    await update.message.reply_text(summary, reply_markup=settings_home_keyboard())


async def _get_user_or_warn(session, query) -> object | None:
    user = await users_repo.get_by_telegram_id(session, query.from_user.id)
    if user is None:
        await query.answer(t("settings.profile_not_found", _LANG), show_alert=True)
    return user


async def _render_home(query, session, user) -> None:
    summary = await _build_summary(session, user)
    await query.edit_message_text(summary, reply_markup=settings_home_keyboard())


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    async with session_scope() as session:
        user = await _get_user_or_warn(session, query)
        if user is None:
            return

        if data == "set:home":
            await _render_home(query, session, user)

        elif data == "set:lang:list":
            languages = await user_languages_repo.get_user_languages(session, user.id)
            await query.edit_message_text(
                t("settings.pick_current_language", _LANG),
                reply_markup=language_switch_keyboard(languages),
            )

        elif data.startswith("set:lang:pick:"):
            user_language_id = int(data.removeprefix("set:lang:pick:"))
            target = await user_languages_repo.set_active_language(
                session, user_id=user.id, user_language_id=user_language_id
            )
            lang = LANGUAGE_BY_CODE.get(target.language_code)
            await query.answer(
                t(
                    "settings.current_language_updated",
                    _LANG,
                    flag=lang.flag if lang else "",
                    name=lang.name_ru if lang else target.language_code,
                )
            )
            await _render_home(query, session, user)

        elif data == "set:iface:list":
            await query.edit_message_text(
                t("settings.pick_interface_language", _LANG),
                reply_markup=interface_language_pick_keyboard(),
            )

        elif data.startswith("set:iface:pick:"):
            code = data.removeprefix("set:iface:pick:")
            await users_repo.update_user(session, user, interface_language=code)
            lang = LANGUAGE_BY_CODE[code]
            await query.answer(t("settings.interface_language_updated", _LANG, flag=lang.flag, name=lang.name_ru))
            await _render_home(query, session, user)

        elif data == "set:words:list":
            options = get_settings().plan_limits.daily_new_words_options
            await query.edit_message_text(
                t("settings.pick_daily_words", _LANG), reply_markup=daily_words_pick_keyboard(options)
            )

        elif data.startswith("set:words:pick:"):
            count = int(data.removeprefix("set:words:pick:"))
            current = await user_languages_repo.get_current_language(session, user.id)
            if current is not None:
                await user_languages_repo.set_daily_new_words(session, current, count)
            await query.answer(t("settings.daily_words_updated", _LANG, count=count))
            await _render_home(query, session, user)

        elif data == "set:notif:slots":
            await query.edit_message_text(
                t("settings.pick_notification_slot", _LANG), reply_markup=notification_slot_keyboard()
            )

        elif data.startswith("set:notif:slot:"):
            slot = data.removeprefix("set:notif:slot:")
            await query.edit_message_text(
                t("settings.pick_notification_time", _LANG), reply_markup=notification_time_keyboard(slot)
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
                    _LANG,
                    slot=t(f"notification_slot.{slot}", _LANG),
                    time=parsed.strftime("%H:%M"),
                )
            )
            await _render_home(query, session, user)

        elif data == "set:notif:toggle":
            new_value = not user.notifications_enabled
            await users_repo.update_user(session, user, notifications_enabled=new_value)
            await query.answer(
                t("settings.notifications_toggled_on" if new_value else "settings.notifications_toggled_off", _LANG)
            )
            await _render_home(query, session, user)

        elif data == "set:level:list":
            await query.edit_message_text(
                t("settings.pick_level", _LANG), reply_markup=level_pick_keyboard()
            )

        elif data.startswith("set:level:pick:"):
            level = data.removeprefix("set:level:pick:")
            await users_repo.update_user(session, user, level=level)
            await query.answer(t("settings.level_updated", _LANG, level=t(f"level.{level}", _LANG)))
            await _render_home(query, session, user)

        elif data == "set:sub":
            user = await subscription_service.refresh_expired_trial(session, user)
            status_line = t("settings.subscription", _LANG, status=t(f"subscription.status.{user.subscription_status}", _LANG))
            lines = [status_line]
            if user.trial_end:
                lines.append(t("settings.trial_until", _LANG, date=user.trial_end.isoformat()))
            await query.edit_message_text("\n".join(lines), reply_markup=back_to_settings_keyboard())

        else:
            logger.warning("Unhandled settings callback_data: %s", data)


settings_callback_handler = CallbackQueryHandler(handle_settings_callback, pattern="^set:")
