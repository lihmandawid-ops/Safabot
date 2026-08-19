"""/start onboarding (spec sections 9 and 35).

Flow for a brand-new user:
    interface language -> learning language -> level -> daily new words
    -> create User + UserLanguage -> start 7-day trial -> show main menu

A returning user (already in the DB) skips straight to the main menu
instead of being asked to re-onboard.

Translation language is set equal to the chosen interface language for
now (the common case from section 2's own example, ru -> en/de/he).
Letting users pick a different translation language is a Settings-level
refinement left for a later stage - TODO(post-mvp).
"""
from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from config import get_settings
from database.database import session_scope
from database.repositories import users as users_repo
from keyboards.language import (
    INTERFACE_LANGUAGE_PREFIX,
    LEARNING_LANGUAGE_PREFIX,
    interface_language_keyboard,
    learning_language_keyboard,
)
from keyboards.main_menu import main_menu_keyboard
from services import subscription_service
from utils.languages import LANGUAGE_BY_CODE
from utils.logging import get_logger

logger = get_logger(__name__)

CHOOSING_INTERFACE_LANGUAGE, CHOOSING_LEARNING_LANGUAGE, CHOOSING_LEVEL, CHOOSING_DAILY_WORDS = range(4)

LEVEL_PREFIX = "onb:level:"
DAILY_WORDS_PREFIX = "onb:words:"

LEVELS: tuple[tuple[str, str], ...] = (
    ("beginner", "🌱 Начинающий"),
    ("intermediate", "🌿 Средний"),
    ("advanced", "🌳 Продвинутый"),
)


def _level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"{LEVEL_PREFIX}{code}")] for code, label in LEVELS]
    )


def _daily_words_keyboard() -> InlineKeyboardMarkup:
    options = get_settings().plan_limits.daily_new_words_options
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(n), callback_data=f"{DAILY_WORDS_PREFIX}{n}") for n in options]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_user = update.effective_user
    assert telegram_user is not None

    async with session_scope() as session:
        existing = await users_repo.get_user_by_telegram_id(session, telegram_user.id)

    if existing is not None:
        await update.message.reply_text(
            f"С возвращением, {existing.first_name or telegram_user.first_name}! 👋",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "👋 Добро пожаловать в Safabot — бот для изучения иностранных языков!\n\n"
        "Сначала выберите язык интерфейса:",
        reply_markup=interface_language_keyboard(),
    )
    return CHOOSING_INTERFACE_LANGUAGE


async def choose_interface_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(INTERFACE_LANGUAGE_PREFIX)
    context.user_data["interface_language"] = code

    await query.edit_message_text(
        f"Язык интерфейса: {LANGUAGE_BY_CODE[code].flag} {LANGUAGE_BY_CODE[code].name_ru}\n\n"
        "Какой язык вы хотите изучать?"
    )
    await query.message.reply_text(
        "Выберите изучаемый язык:", reply_markup=learning_language_keyboard()
    )
    return CHOOSING_LEARNING_LANGUAGE


async def choose_learning_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.removeprefix(LEARNING_LANGUAGE_PREFIX)

    if code == context.user_data.get("interface_language"):
        await query.answer(
            "Изучаемый язык должен отличаться от языка интерфейса.", show_alert=True
        )
        return CHOOSING_LEARNING_LANGUAGE

    context.user_data["learning_language"] = code
    await query.edit_message_text(
        f"Изучаемый язык: {LANGUAGE_BY_CODE[code].flag} {LANGUAGE_BY_CODE[code].name_ru}\n\n"
        "Какой у вас уровень?"
    )
    await query.message.reply_text("Выберите уровень:", reply_markup=_level_keyboard())
    return CHOOSING_LEVEL


async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    level = query.data.removeprefix(LEVEL_PREFIX)
    context.user_data["level"] = level

    level_label = dict(LEVELS)[level]
    await query.edit_message_text(f"Уровень: {level_label}\n\nСколько новых слов в день вы хотите изучать?")
    await query.message.reply_text(
        "Выберите количество новых слов в день:", reply_markup=_daily_words_keyboard()
    )
    return CHOOSING_DAILY_WORDS


async def choose_daily_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    daily_words = int(query.data.removeprefix(DAILY_WORDS_PREFIX))
    context.user_data["daily_words"] = daily_words

    telegram_user = update.effective_user
    settings = get_settings()
    interface_language = context.user_data["interface_language"]
    learning_language = context.user_data["learning_language"]
    level = context.user_data["level"]

    morning = datetime.strptime(settings.default_morning_time, "%H:%M").time()
    afternoon = datetime.strptime(settings.default_afternoon_time, "%H:%M").time()
    evening = datetime.strptime(settings.default_evening_time, "%H:%M").time()

    async with session_scope() as session:
        user = await users_repo.create_user(
            session,
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            interface_language=interface_language,
            timezone=settings.default_timezone,
            current_level=level,
            daily_new_words_limit=daily_words,
            morning_notification_time=morning,
            afternoon_notification_time=afternoon,
            evening_notification_time=evening,
        )
        await users_repo.add_user_language(
            session,
            user_id=user.id,
            language_code=learning_language,
            translation_language=interface_language,
            level=level,
            daily_word_limit=daily_words,
        )
        await subscription_service.start_trial(session, user)

    logger.info("Registered new user telegram_id=%s", telegram_user.id)

    trial_days = settings.trial_days
    learning_lang_name = LANGUAGE_BY_CODE[learning_language].name_ru
    await query.edit_message_text(
        "🎉 Регистрация завершена!\n\n"
        f"Вы изучаете: {LANGUAGE_BY_CODE[learning_language].flag} {learning_lang_name}\n"
        f"Новых слов в день: {daily_words}\n\n"
        f"Вам открыт бесплатный PRO-доступ на {trial_days} дней. Хорошего обучения!"
    )
    await query.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Регистрация отменена. Отправьте /start, чтобы начать заново.")
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
        CHOOSING_LEVEL: [CallbackQueryHandler(choose_level, pattern=f"^{LEVEL_PREFIX}")],
        CHOOSING_DAILY_WORDS: [CallbackQueryHandler(choose_daily_words, pattern=f"^{DAILY_WORDS_PREFIX}")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
