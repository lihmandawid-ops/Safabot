"""/start onboarding (spec sections 5 and 9).

Flow for a brand-new user:
    learning language -> level (beginner or AI placement test) -> goal
    -> [industry] -> timezone
    -> create User + UserLanguage -> start 7-day trial -> show main menu

Real user request: interface language (and translation_language, which
always equals it - see choose_learning_language below) is never asked -
it's set automatically from Telegram's own `language_code`
(_detect_interface_language). The daily-new-words count is never asked
either, since the live product no longer has a configurable daily quota
- the morning slot always auto-adds a fixed MORNING_NEW_WORD_COUNT (see
services/notification_service.py) regardless of what a user might have
picked here; every user gets config.py's DEFAULT_DAILY_NEW_WORDS.

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
from keyboards.language import LEARNING_LANGUAGE_PREFIX, learning_language_keyboard
from keyboards.main_menu import main_menu_keyboard
from services import subscription_service
from services.ai_errors import AIConfigurationError, AIError
from utils.goals import GOAL_CODES
from utils.i18n import get_current_language, set_current_language, t
from utils.industries import PRESET_INDUSTRIES
from utils.languages import LANGUAGE_BY_CODE, is_supported, language_display_name
from utils.logging import get_logger
from utils.telegram_helpers import safe_edit_message_text
from utils.timezones import TIMEZONE_CHOICES

logger = get_logger(__name__)

(
    CHOOSING_LEARNING_LANGUAGE,
    CHOOSING_LEVEL,
    CHOOSING_LEVEL_PLACEMENT,
    CHOOSING_GOAL,
    CHOOSING_INDUSTRY,
    CHOOSING_TIMEZONE,
) = range(6)

LEVEL_PREFIX = "onb:level:"
BEGINNER_LEVEL_CALLBACK = f"{LEVEL_PREFIX}a1"
PLACEMENT_START_CALLBACK = f"{LEVEL_PREFIX}placement:start"
PLACEMENT_ANSWER_PREFIX = "onb:placement:answer:"
GOAL_PREFIX = "onb:goal:"
INDUSTRY_PREFIX = "onb:industry:"
TIMEZONE_PREFIX = "onb:tz:"

# repetition-system-audit stage: the very FIRST screen (before any
# language is chosen at all) has no per-user language to read from the
# database yet, so it used to always render in this hardcoded fallback
# regardless of who was looking at it - real bug found via audit: a
# Telegram user with language_code="he" got a Russian welcome message.
# _detect_interface_language() below picks a real starting point instead.
# This constant only matters as ITS OWN fallback when Telegram sends no
# usable language_code at all, or one Safabot doesn't support.
_LANG = "en"


def _detect_interface_language(telegram_user) -> str:
    """Real user request: Telegram's `language_code` (BCP-47, e.g. "he",
    "en-US", "pt-BR") now IS the learner's interface_language - never a
    separate onboarding question the way it used to be. translation_
    language always equals interface_language regardless (see
    choose_learning_language below), so this single auto-detected value
    settles both at once. Falls back to _LANG only when Telegram sends no
    usable language_code, or one Safabot doesn't have interface strings
    for - the learner can still change it any time via ⚙️ Настройки."""
    code = (telegram_user.language_code or "").split("-")[0].lower()
    return code if is_supported(code) else _LANG


def _level_keyboard() -> InlineKeyboardMarkup:
    """Real user request: exactly two ways to set a starting level -
    "🟢 Только начинаю" (level=a1, same as the old leading button) or
    "🤖 Узнать мой уровень" (the AI placement test, same one ⚙️
    Настройки → 🎚 Уровень сложности offers) - never the old flat list
    of all 6 CEFR buttons."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("level.beginner_button", get_current_language()), callback_data=BEGINNER_LEVEL_CALLBACK)],
            [InlineKeyboardButton(t("settings.difficulty.find_my_level", get_current_language()), callback_data=PLACEMENT_START_CALLBACK)],
        ]
    )


def _placement_word_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("settings.placement.yes", get_current_language()), callback_data=f"{PLACEMENT_ANSWER_PREFIX}yes"),
                InlineKeyboardButton(t("settings.placement.no", get_current_language()), callback_data=f"{PLACEMENT_ANSWER_PREFIX}no"),
            ]
        ]
    )


async def _render_level_placement_question(send, state: dict) -> None:
    """Same rendering shape as handlers/settings.py's own
    _render_placement_question - "word" questions get a yes/no keyboard,
    "translate" questions are answered as free text (routed back here by
    choose_level_placement_translate, matched on the ConversationHandler's
    own CHOOSING_LEVEL_PLACEMENT state - no separate mode/submode
    bookkeeping needed here the way settings.py's free-text dispatcher
    requires, since a ConversationHandler state already IS that routing)."""
    question = state["questions"][state["index"]]
    header = t(
        "settings.placement.question_header", get_current_language(),
        current=state["index"] + 1, total=len(state["questions"]),
    )
    if question["kind"] == "word":
        text = f"{header}\n\n" + t("settings.placement.word_prompt", get_current_language(), word=question["prompt"])
        await send(text, reply_markup=_placement_word_keyboard())
    else:
        text = f"{header}\n\n" + t("settings.placement.translate_prompt", get_current_language(), sentence=question["prompt"])
        await send(text)


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
    # Real user request: interface_language is set from Telegram's own
    # language_code, never asked - straight to the one question that
    # genuinely needs the learner's input (which language to learn).
    detected = _detect_interface_language(telegram_user)
    context.user_data["interface_language"] = detected
    set_current_language(detected)
    await update.message.reply_text(
        t("onboarding.welcome", detected), reply_markup=learning_language_keyboard()
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
    # study-flow-rework stage sections 4-6: the separate "which language to
    # translate into" question is removed entirely - translation_language
    # always equals interface_language (set in choose_timezone below).
    await query.message.reply_text(t("onboarding.choose_level", get_current_language()), reply_markup=_level_keyboard())
    return CHOOSING_LEVEL


async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    set_current_language(context.user_data.get("interface_language"))

    if query.data == PLACEMENT_START_CALLBACK:
        return await _start_level_placement(update, context)

    level = query.data.removeprefix(LEVEL_PREFIX)
    context.user_data["level"] = level

    await safe_edit_message_text(query,
        t("onboarding.level_selected", get_current_language(), level=t(f"level.{level}", get_current_language()))
    )
    await query.message.reply_text(t("onboarding.choose_goal", get_current_language()), reply_markup=_goal_keyboard())
    return CHOOSING_GOAL


async def _start_level_placement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """🤖 Узнать мой уровень during onboarding (real user request): same
    AI-graded 6-question test ⚙️ Настройки → 🎚 Уровень сложности offers
    (services/level_placement_service.py), reused as-is - only the
    surrounding storage differs, since there's no UserLanguage row to
    write into yet (that only gets created once onboarding finishes, in
    choose_timezone), so the result is kept in context.user_data["level"]
    like every other onboarding answer instead of being persisted here."""
    from services import level_placement_service

    query = update.callback_query
    await safe_edit_message_text(query, t("settings.placement.generating", get_current_language()))
    try:
        questions = await level_placement_service.start_placement_test(
            language_code=context.user_data["learning_language"],
            translation_language=context.user_data["interface_language"],
            user_id=update.effective_user.id,
        )
    except AIConfigurationError:
        await query.message.reply_text(t("ai.not_configured", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL
    except AIError:
        await query.message.reply_text(t("ai.generic_error", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL

    state = {"questions": questions, "index": 0, "answers": []}
    context.user_data["placement_test"] = state

    async def send(text: str, reply_markup=None) -> None:
        await query.message.reply_text(text, reply_markup=reply_markup)

    await _render_level_placement_question(send, state)
    return CHOOSING_LEVEL_PLACEMENT


async def choose_level_placement_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """A "word" question's ✅/❌ tap."""
    query = update.callback_query
    set_current_language(context.user_data.get("interface_language"))
    state = context.user_data.get("placement_test")
    if state is None:
        await query.answer()
        await safe_edit_message_text(query, t("settings.placement.expired", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL

    await query.answer()
    state["answers"].append(query.data.removeprefix(PLACEMENT_ANSWER_PREFIX))
    state["index"] += 1
    if state["index"] >= len(state["questions"]):
        return await _finish_level_placement(update, context, state)

    async def send(text: str, reply_markup=None) -> None:
        await safe_edit_message_text(query, text, reply_markup=reply_markup)

    await _render_level_placement_question(send, state)
    return CHOOSING_LEVEL_PLACEMENT


async def choose_level_placement_translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """A "translate" question's free-text answer (or "нет"). The state's
    CURRENT question must actually be "translate" kind - this handler
    matches any text message in this state, so a stray message sent while
    a "word" question (button-answered) is showing must be ignored rather
    than silently recorded as that question's answer, same guard
    handlers/settings.py's own submode-gated dispatch gives for free."""
    set_current_language(context.user_data.get("interface_language"))
    state = context.user_data.get("placement_test")
    if state is None:
        await update.message.reply_text(t("settings.placement.expired", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL
    if state["questions"][state["index"]]["kind"] != "translate":
        return CHOOSING_LEVEL_PLACEMENT

    answer = (update.message.text or "").strip()
    if not answer:
        return CHOOSING_LEVEL_PLACEMENT

    state["answers"].append(answer)
    state["index"] += 1
    if state["index"] >= len(state["questions"]):
        return await _finish_level_placement(update, context, state)

    async def send(text: str, reply_markup=None) -> None:
        await update.message.reply_text(text, reply_markup=reply_markup)

    await _render_level_placement_question(send, state)
    return CHOOSING_LEVEL_PLACEMENT


async def _finish_level_placement(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict) -> int:
    from services import level_placement_service

    context.user_data.pop("placement_test", None)
    query = update.callback_query

    async def send(text: str, reply_markup=None) -> None:
        # The last answer may have come in as a callback query (a "word"
        # question) or a plain message (a "translate" question) - edit in
        # place for the former, reply fresh for the latter, same dual-
        # entry pattern _render_level_placement_question's callers use.
        if query is not None:
            await safe_edit_message_text(query, text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)

    await send(t("settings.placement.grading", get_current_language()))
    try:
        level = await level_placement_service.grade_placement_test(
            language_code=context.user_data["learning_language"],
            translation_language=context.user_data["interface_language"],
            questions=state["questions"], answers=state["answers"],
            user_id=update.effective_user.id,
        )
    except AIConfigurationError:
        await send(t("ai.not_configured", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL
    except AIError:
        await send(t("ai.generic_error", get_current_language()), reply_markup=_level_keyboard())
        return CHOOSING_LEVEL

    context.user_data["level"] = level
    await send(t("onboarding.level_placement_result", get_current_language(), level=t(f"level.{level}", get_current_language())))
    # Always a NEW message (never editing the result above in place),
    # same dual-entry dispatch as `send` just above.
    if query is not None:
        await query.message.reply_text(t("onboarding.choose_goal", get_current_language()), reply_markup=_goal_keyboard())
    else:
        await update.message.reply_text(t("onboarding.choose_goal", get_current_language()), reply_markup=_goal_keyboard())
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
    # study-flow-rework stage sections 4-6: translation_language is never a
    # separate onboarding choice - it always equals interface_language.
    translation_language = interface_language
    level = context.user_data["level"]
    # Real user request: no longer an onboarding question - the live
    # product has no configurable daily quota anyway (the morning slot
    # always auto-adds a fixed MORNING_NEW_WORD_COUNT regardless of this
    # value - see services/notification_service.py), so every user just
    # gets config.py's DEFAULT_DAILY_NEW_WORDS.
    daily_words = settings.default_daily_new_words
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
        CHOOSING_LEARNING_LANGUAGE: [
            CallbackQueryHandler(choose_learning_language, pattern=f"^{LEARNING_LANGUAGE_PREFIX}")
        ],
        CHOOSING_LEVEL: [CallbackQueryHandler(choose_level, pattern=f"^{LEVEL_PREFIX}")],
        CHOOSING_LEVEL_PLACEMENT: [
            CallbackQueryHandler(choose_level_placement_answer, pattern=f"^{PLACEMENT_ANSWER_PREFIX}"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, choose_level_placement_translate),
        ],
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
