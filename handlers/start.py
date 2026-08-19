"""/start onboarding (spec sections 5 and 9).

Flow for a brand-new user:
    interface language -> learning language -> translation language
    -> level -> daily new words -> timezone
    -> create User + UserLanguage -> start 7-day trial -> show main menu

A returning user (already in the DB) skips straight to the main menu
instead of being asked to re-onboard.

Conversation state (context.user_data) plus which onboarding step a chat
is on is kept by python-telegram-bot's PicklePersistence (see bot.py), not
just Python process memory - if the bot restarts mid-onboarding, the user
picks up exactly where they left off instead of starting over.

Notification times are NOT asked for during onboarding: spec section 10
only requires saving/editing them, not a full send pipeline yet, so new
users get the config.py defaults (09:00 / 14:00 / 20:00) and can change
them later in Settings.
"""
from __future__ import annotations

from datetime import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from config import get_settings
from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.language import (
    INTERFACE_LANGUAGE_PREFIX,
    LEARNING_LANGUAGE_PREFIX,
    TRANSLATION_LANGUAGE_PREFIX,
    interface_language_keyboard,
    learning_language_keyboard,
    translation_language_keyboard,
)
from keyboards.main_menu import main_menu_keyboard
from services import subscription_service
from utils.i18n import t
from utils.languages import LANGUAGE_BY_CODE
from utils.levels import LEVEL_CODES
from utils.logging import get_logger
from utils.timezones import TIMEZONE_CHOICES

logger = get_logger(__name__)

(
    CHOOSING_INTERFACE_LANGUAGE,
    CHOOSING_LEARNING_LANGUAGE,
    CHOOSING_TRANSLATION_LANGUAGE,
    CHOOSING_LEVEL,
    CHOOSING_DAILY_WORDS,
    CHOOSING_TIMEZONE,
) = range(6)

LEVEL_PREFIX = "onb:level:"
DAILY_WORDS_PREFIX = "onb:words:"
TIMEZONE_PREFIX = "onb:tz:"

# Onboarding always speaks Russian for now (spec section 6: interface
# localization beyond ru is future work); user.interface_language is still
# recorded so the rest of the bot is ready for it once more locales exist.
_LANG = "ru"


def _level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(f"level.{code}", _LANG), callback_data=f"{LEVEL_PREFIX}{code}")]
            for code in LEVEL_CODES
        ]
    )


def _daily_words_keyboard() -> InlineKeyboardMarkup:
    options = get_settings().plan_limits.daily_new_words_options
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(n), callback_data=f"{DAILY_WORDS_PREFIX}{n}") for n in options]]
    )


def _timezone_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(tz.label, callback_data=f"{TIMEZONE_PREFIX}{tz.iana_name}")
        for tz in TIMEZONE_CHOICES
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_user = update.effective_user
    assert telegram_user is not None

    async with session_scope() as session:
        existing = await users_repo.get_by_telegram_id(session, telegram_user.id)

    if existing is not None:
        await update.message.reply_text(
            t("onboarding.returning_user", _LANG, name=existing.first_name or telegram_user.first_name),
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        t("onboarding.welcome", _LANG), reply_markup=interface_language_keyboard()
    )
    return CHOOSING_INTERFACE_LANGUAGE


async def choose_interface_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(INTERFACE_LANGUAGE_PREFIX)
    context.user_data["interface_language"] = code
    lang = LANGUAGE_BY_CODE[code]

    await query.edit_message_text(
        t("onboarding.interface_language_selected", _LANG, flag=lang.flag, name=lang.name_ru)
    )
    await query.message.reply_text(
        t("onboarding.choose_learning_language", _LANG), reply_markup=learning_language_keyboard()
    )
    return CHOOSING_LEARNING_LANGUAGE


async def choose_learning_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(LEARNING_LANGUAGE_PREFIX)
    context.user_data["learning_language"] = code
    lang = LANGUAGE_BY_CODE[code]

    await query.edit_message_text(
        t("onboarding.learning_language_selected", _LANG, flag=lang.flag, name=lang.name_ru)
    )
    await query.message.reply_text(
        t("onboarding.choose_translation_language", _LANG),
        reply_markup=translation_language_keyboard(exclude_learning_language=code),
    )
    return CHOOSING_TRANSLATION_LANGUAGE


async def choose_translation_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(TRANSLATION_LANGUAGE_PREFIX)

    if code == context.user_data.get("learning_language"):
        await query.answer(t("onboarding.translation_language_must_differ", _LANG), show_alert=True)
        return CHOOSING_TRANSLATION_LANGUAGE

    context.user_data["translation_language"] = code
    lang = LANGUAGE_BY_CODE[code]

    await query.edit_message_text(
        t("onboarding.translation_language_selected", _LANG, flag=lang.flag, name=lang.name_ru)
    )
    await query.message.reply_text(t("onboarding.choose_level", _LANG), reply_markup=_level_keyboard())
    return CHOOSING_LEVEL


async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    level = query.data.removeprefix(LEVEL_PREFIX)
    context.user_data["level"] = level

    await query.edit_message_text(
        t("onboarding.level_selected", _LANG, level=t(f"level.{level}", _LANG))
    )
    await query.message.reply_text(
        t("onboarding.choose_daily_words", _LANG), reply_markup=_daily_words_keyboard()
    )
    return CHOOSING_DAILY_WORDS


async def choose_daily_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    daily_words = int(query.data.removeprefix(DAILY_WORDS_PREFIX))
    context.user_data["daily_words"] = daily_words

    await query.edit_message_text(t("onboarding.daily_words_selected", _LANG, count=daily_words))
    await query.message.reply_text(
        t("onboarding.choose_timezone", _LANG), reply_markup=_timezone_keyboard()
    )
    return CHOOSING_TIMEZONE


async def choose_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    timezone = query.data.removeprefix(TIMEZONE_PREFIX)

    telegram_user = update.effective_user
    settings = get_settings()
    interface_language = context.user_data["interface_language"]
    learning_language = context.user_data["learning_language"]
    translation_language = context.user_data["translation_language"]
    level = context.user_data["level"]
    daily_words = context.user_data["daily_words"]

    morning = _parse_time(settings.default_morning_time)
    afternoon = _parse_time(settings.default_afternoon_time)
    evening = _parse_time(settings.default_evening_time)

    async with session_scope() as session:
        user = await users_repo.create_user(
            session,
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            interface_language=interface_language,
            timezone=timezone,
            level=level,
            daily_new_words=daily_words,
            morning_time=morning,
            afternoon_time=afternoon,
            evening_time=evening,
        )
        await user_languages_repo.add_language(
            session,
            user_id=user.id,
            language_code=learning_language,
            translation_language=translation_language,
            level=level,
            daily_new_words=daily_words,
        )
        await subscription_service.start_trial(session, user)

    logger.info("Registered new user telegram_id=%s", telegram_user.id)

    trial_days = settings.trial_days
    learning_lang = LANGUAGE_BY_CODE[learning_language]
    await query.edit_message_text(
        t(
            "onboarding.registration_complete",
            _LANG,
            flag=learning_lang.flag,
            name=learning_lang.name_ru,
            daily_words=daily_words,
            trial_days=trial_days,
        )
    )
    await query.message.reply_text(t("onboarding.main_menu_ready", _LANG), reply_markup=main_menu_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(t("onboarding.cancelled", _LANG))
    return ConversationHandler.END


start_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSING_INTERFACE_LANGUAGE: [
            CallbackQueryHandler(choose_interface_language, pattern=f"^{INTERFACE_LANGUAGE_PREFIX}")
        ],
        CHOOSING_LEARNING_LANGUAGE: [
            CallbackQueryHandler(choose_learning_language, pattern=f"^{LEARNING_LANGUAGE_PREFIX}")
        ],
        CHOOSING_TRANSLATION_LANGUAGE: [
            CallbackQueryHandler(choose_translation_language, pattern=f"^{TRANSLATION_LANGUAGE_PREFIX}")
        ],
        CHOOSING_LEVEL: [CallbackQueryHandler(choose_level, pattern=f"^{LEVEL_PREFIX}")],
        CHOOSING_DAILY_WORDS: [CallbackQueryHandler(choose_daily_words, pattern=f"^{DAILY_WORDS_PREFIX}")],
        CHOOSING_TIMEZONE: [CallbackQueryHandler(choose_timezone, pattern=f"^{TIMEZONE_PREFIX}")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="onboarding",
    persistent=True,
)
