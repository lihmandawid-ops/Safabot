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
    MessageHandler,
    filters,
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
from utils.goals import GOAL_CODES
from utils.i18n import get_current_language, set_current_language, t
from utils.industries import PRESET_INDUSTRIES
from utils.languages import LANGUAGE_BY_CODE, is_supported, language_display_name
from utils.levels import LEVEL_CODES
from utils.logging import get_logger
from utils.telegram_helpers import safe_edit_message_text
from utils.timezones import TIMEZONE_CHOICES

logger = get_logger(__name__)

(
    CHOOSING_INTERFACE_LANGUAGE,
    CHOOSING_LEARNING_LANGUAGE,
    CHOOSING_TRANSLATION_LANGUAGE,
    CHOOSING_LEVEL,
    CHOOSING_DAILY_WORDS,
    CHOOSING_GOAL,
    CHOOSING_INDUSTRY,
    CHOOSING_TIMEZONE,
) = range(8)

LEVEL_PREFIX = "onb:level:"
DAILY_WORDS_PREFIX = "onb:words:"
GOAL_PREFIX = "onb:goal:"
INDUSTRY_PREFIX = "onb:industry:"
TIMEZONE_PREFIX = "onb:tz:"

# repetition-system-audit stage: the very FIRST screen (before any
# language is chosen at all) has no per-user language to read from the
# database yet, so it used to always render in this hardcoded fallback
# regardless of who was looking at it - real bug found via audit: a
# Telegram user with language_code="he" got a Russian welcome message.
# _detect_interface_language() below picks a real starting point instead;
# this constant now only matters as ITS OWN fallback when Telegram sends
# no usable language_code at all. Every screen from
# choose_interface_language onward uses set_current_language(code), so
# the rest of onboarding renders in whichever language the user then
# explicitly picks via the buttons.
_LANG = "en"


def _detect_interface_language(telegram_user) -> str:
    """Telegram's `language_code` (BCP-47, e.g. "he", "en-US", "pt-BR") is
    used ONLY to pick a sensible starting point for the very first
    message - the user still explicitly confirms/picks their interface
    language via interface_language_keyboard() right after, exactly like
    before. Never touches learning_language, which stays a fully separate
    choice a few steps later."""
    code = (telegram_user.language_code or "").split("-")[0].lower()
    return code if is_supported(code) else _LANG


def _level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(f"level.{code}", get_current_language()), callback_data=f"{LEVEL_PREFIX}{code}")]
            for code in LEVEL_CODES
        ]
    )


def _daily_words_keyboard() -> InlineKeyboardMarkup:
    options = get_settings().plan_limits.daily_new_words_options
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(n), callback_data=f"{DAILY_WORDS_PREFIX}{n}") for n in options]]
    )


def _goal_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t(f"goal.{code}", get_current_language()), callback_data=f"{GOAL_PREFIX}{code}")]
        for code in GOAL_CODES
    ]
    rows.append([InlineKeyboardButton(t("onboarding.button.skip", get_current_language()), callback_data=f"{GOAL_PREFIX}skip")])
    return InlineKeyboardMarkup(rows)


def _industry_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(t(f"industry.{code}", get_current_language()), callback_data=f"{INDUSTRY_PREFIX}{code}")
        for code in PRESET_INDUSTRIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t("onboarding.button.other", get_current_language()), callback_data=f"{INDUSTRY_PREFIX}other")])
    rows.append([InlineKeyboardButton(t("onboarding.button.skip", get_current_language()), callback_data=f"{INDUSTRY_PREFIX}skip")])
    return InlineKeyboardMarkup(rows)


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
        set_current_language(existing.interface_language)
        await update.message.reply_text(
            t("onboarding.returning_user", get_current_language(), name=existing.first_name or telegram_user.first_name),
            reply_markup=main_menu_keyboard(get_current_language()),
        )
        return ConversationHandler.END

    context.user_data.clear()
    detected = _detect_interface_language(telegram_user)
    set_current_language(detected)  # so interface_language_keyboard()'s own button labels (language names) match too
    await update.message.reply_text(
        t("onboarding.welcome", detected), reply_markup=interface_language_keyboard()
    )
    return CHOOSING_INTERFACE_LANGUAGE


async def choose_interface_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(INTERFACE_LANGUAGE_PREFIX)
    context.user_data["interface_language"] = code
    set_current_language(code)
    lang = LANGUAGE_BY_CODE[code]

    await safe_edit_message_text(query,
        t("onboarding.interface_language_selected", code, flag=lang.flag, name=language_display_name(lang, code))
    )
    await query.message.reply_text(
        t("onboarding.choose_learning_language", code), reply_markup=learning_language_keyboard()
    )
    return CHOOSING_LEARNING_LANGUAGE


async def choose_learning_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    code = query.data.removeprefix(LEARNING_LANGUAGE_PREFIX)
    context.user_data["learning_language"] = code
    lang = LANGUAGE_BY_CODE[code]

    await safe_edit_message_text(query,
        t("onboarding.learning_language_selected", get_current_language(), flag=lang.flag, name=language_display_name(lang))
    )
    await query.message.reply_text(
        t("onboarding.choose_translation_language", get_current_language()),
        reply_markup=translation_language_keyboard(exclude_learning_language=code),
    )
    return CHOOSING_TRANSLATION_LANGUAGE


async def choose_translation_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    code = query.data.removeprefix(TRANSLATION_LANGUAGE_PREFIX)

    if code == context.user_data.get("learning_language"):
        await query.answer(t("onboarding.translation_language_must_differ", get_current_language()), show_alert=True)
        return CHOOSING_TRANSLATION_LANGUAGE

    context.user_data["translation_language"] = code
    lang = LANGUAGE_BY_CODE[code]

    await safe_edit_message_text(query,
        t("onboarding.translation_language_selected", get_current_language(), flag=lang.flag, name=language_display_name(lang))
    )
    await query.message.reply_text(t("onboarding.choose_level", get_current_language()), reply_markup=_level_keyboard())
    return CHOOSING_LEVEL


async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    level = query.data.removeprefix(LEVEL_PREFIX)
    context.user_data["level"] = level

    await safe_edit_message_text(query,
        t("onboarding.level_selected", get_current_language(), level=t(f"level.{level}", get_current_language()))
    )
    await query.message.reply_text(
        t("onboarding.choose_daily_words", get_current_language()), reply_markup=_daily_words_keyboard()
    )
    return CHOOSING_DAILY_WORDS


async def choose_daily_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    daily_words = int(query.data.removeprefix(DAILY_WORDS_PREFIX))
    context.user_data["daily_words"] = daily_words

    await safe_edit_message_text(query, t("onboarding.daily_words_selected", get_current_language(), count=daily_words))
    await query.message.reply_text(t("onboarding.choose_goal", get_current_language()), reply_markup=_goal_keyboard())
    return CHOOSING_GOAL


async def choose_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Settings-improvements stage section 18: optional, skippable - only
    "work" leads anywhere further (a follow-up industry question,
    section 20); every other choice (including skip) goes straight to
    the timezone step, same as before this stage existed."""
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    code = query.data.removeprefix(GOAL_PREFIX)
    goal = None if code == "skip" else code
    context.user_data["learning_goal"] = goal

    if goal == "work":
        await safe_edit_message_text(query, t("goal.work", get_current_language()))
        await query.message.reply_text(
            t("onboarding.choose_industry", get_current_language()), reply_markup=_industry_keyboard()
        )
        return CHOOSING_INDUSTRY

    await safe_edit_message_text(query,
        t(f"goal.{goal}", get_current_language()) if goal else t("onboarding.button.skip", get_current_language())
    )
    await query.message.reply_text(
        t("onboarding.choose_timezone", get_current_language()), reply_markup=_timezone_keyboard()
    )
    return CHOOSING_TIMEZONE


async def choose_industry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    code = query.data.removeprefix(INDUSTRY_PREFIX)

    if code == "other":
        await safe_edit_message_text(query, t("onboarding.industry_custom_prompt", get_current_language()))
        return CHOOSING_INDUSTRY

    industry = None if code == "skip" else code
    context.user_data["work_industry"] = industry
    await safe_edit_message_text(query,
        t(f"industry.{industry}", get_current_language()) if industry else t("onboarding.button.skip", get_current_language())
    )
    await query.message.reply_text(
        t("onboarding.choose_timezone", get_current_language()), reply_markup=_timezone_keyboard()
    )
    return CHOOSING_TIMEZONE


async def choose_industry_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Free-text answer to "✏️ Другое" (or typed directly without tapping
    any preset button - both are equally valid ways to answer)."""
    set_current_language(context.user_data.get("interface_language"))
    from utils.topics import MAX_CUSTOM_TOPIC_LENGTH

    industry = update.message.text.strip()[:MAX_CUSTOM_TOPIC_LENGTH]
    context.user_data["work_industry"] = industry or None
    await update.message.reply_text(
        t("onboarding.choose_timezone", get_current_language()), reply_markup=_timezone_keyboard()
    )
    return CHOOSING_TIMEZONE


async def choose_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))
    timezone = query.data.removeprefix(TIMEZONE_PREFIX)

    telegram_user = update.effective_user
    settings = get_settings()
    interface_language = context.user_data["interface_language"]
    learning_language = context.user_data["learning_language"]
    translation_language = context.user_data["translation_language"]
    level = context.user_data["level"]
    daily_words = context.user_data["daily_words"]
    learning_goal = context.user_data.get("learning_goal")
    work_industry = context.user_data.get("work_industry") if learning_goal == "work" else None

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
            learning_goal=learning_goal,
            work_industry=work_industry,
        )
        await subscription_service.start_trial(session, user)

    logger.info("Registered new user telegram_id=%s", telegram_user.id)

    trial_days = settings.trial_days
    learning_lang = LANGUAGE_BY_CODE[learning_language]
    await safe_edit_message_text(query,
        t(
            "onboarding.registration_complete",
            get_current_language(),
            flag=learning_lang.flag,
            name=language_display_name(learning_lang),
            daily_words=daily_words,
            trial_days=trial_days,
        )
    )
    await query.message.reply_text(
        t("onboarding.main_menu_ready", get_current_language()),
        reply_markup=main_menu_keyboard(get_current_language()),
    )
    context.user_data.clear()
    return ConversationHandler.END


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    set_current_language(context.user_data.get("interface_language"))
    context.user_data.clear()
    await update.message.reply_text(t("onboarding.cancelled", get_current_language()))
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
        CHOOSING_GOAL: [CallbackQueryHandler(choose_goal, pattern=f"^{GOAL_PREFIX}")],
        CHOOSING_INDUSTRY: [
            CallbackQueryHandler(choose_industry, pattern=f"^{INDUSTRY_PREFIX}"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, choose_industry_custom),
        ],
        CHOOSING_TIMEZONE: [CallbackQueryHandler(choose_timezone, pattern=f"^{TIMEZONE_PREFIX}")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="onboarding",
    persistent=True,
)
