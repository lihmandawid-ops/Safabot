"""Inline keyboards for the ⚙️ Настройки menu (spec section 15).

All callback_data uses the "set:" prefix so handlers/settings.py's single
CallbackQueryHandler can route every settings interaction; being pure
callback routing (no ConversationHandler state), it needs no persistence
to survive a bot restart - the current value always comes straight from
the database.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.learning_service import REVIEW_MODE_CHOICES
from services.notification_service import NOTIFICATION_WORD_COUNT_OPTIONS
from utils.goals import GOAL_CODES
from utils.i18n import get_current_language, t
from utils.industries import PRESET_INDUSTRIES
from utils.languages import SUPPORTED_LANGUAGES, language_display_name
from utils.levels import LEVEL_CODES
from utils.timezones import TIMEZONE_CHOICES
from utils.topics import PRESET_TOPICS

NOTIFICATION_SLOT_TIME_OPTIONS: dict[str, tuple[str, ...]] = {
    "morning": ("06:00", "07:00", "08:00", "09:00", "10:00"),
    "afternoon": ("12:00", "13:00", "14:00", "15:00", "16:00"),
    "evening": ("18:00", "19:00", "20:00", "21:00", "22:00"),
}


def settings_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("settings.menu.language", get_current_language()), callback_data="set:lang:list")],
            [InlineKeyboardButton(t("settings.menu.interface_language", get_current_language()), callback_data="set:iface:list")],
            [InlineKeyboardButton(t("settings.menu.notification_time", get_current_language()), callback_data="set:notif:slots")],
            [InlineKeyboardButton(t("settings.menu.notifications_toggle", get_current_language()), callback_data="set:notif:toggle")],
            [InlineKeyboardButton(t("settings.menu.review_settings", get_current_language()), callback_data="set:revsettings:home")],
            [InlineKeyboardButton(t("settings.menu.difficulty", get_current_language()), callback_data="set:difficulty:list")],
            [InlineKeyboardButton(t("settings.menu.timezone", get_current_language()), callback_data="set:tz:list")],
            [InlineKeyboardButton(t("settings.menu.goal", get_current_language()), callback_data="set:goal:list")],
            [InlineKeyboardButton(t("settings.menu.subscription", get_current_language()), callback_data="set:sub")],
            [InlineKeyboardButton(t("settings.menu.support", get_current_language()), callback_data="set:support")],
        ]
    )


def back_to_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")]]
    )


def language_switch_keyboard(user_languages, *, can_add_more: bool) -> InlineKeyboardMarkup:
    from utils.languages import LANGUAGE_BY_CODE

    rows = []
    for ul in user_languages:
        lang = LANGUAGE_BY_CODE.get(ul.language_code)
        label = f"{lang.flag} {language_display_name(lang)}" if lang else ul.language_code
        if ul.is_current:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"set:lang:pick:{ul.id}")])
    if can_add_more:
        rows.append([InlineKeyboardButton(t("settings.menu.add_language", get_current_language()), callback_data="set:addlang:start")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def add_language_level_keyboard(learning_language: str, translation_language: str) -> InlineKeyboardMarkup:
    # study-flow-rework stage section 30: "🟢 Только начинаю" is a leading
    # button here too, not a new level value - same callback_data as the
    # A1 button below, so picking either stores level="a1".
    rows = [
        [
            InlineKeyboardButton(
                t("level.beginner_button", get_current_language()),
                callback_data=f"set:addlang:level:{learning_language}:{translation_language}:a1",
            )
        ]
    ]
    rows += [
        [
            InlineKeyboardButton(
                t(f"level.{code}", get_current_language()),
                callback_data=f"set:addlang:level:{learning_language}:{translation_language}:{code}",
            )
        ]
        for code in LEVEL_CODES
    ]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:lang:list")])
    return InlineKeyboardMarkup(rows)


def interface_language_pick_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{lang.flag} {language_display_name(lang)}", callback_data=f"set:iface:pick:{lang.code}")
        for lang in SUPPORTED_LANGUAGES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def notification_slot_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("notification_slot.morning", get_current_language()), callback_data="set:notif:slot:morning")],
            [InlineKeyboardButton(t("notification_slot.afternoon", get_current_language()), callback_data="set:notif:slot:afternoon")],
            [InlineKeyboardButton(t("notification_slot.evening", get_current_language()), callback_data="set:notif:slot:evening")],
            [InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")],
        ]
    )


def notification_time_keyboard(slot: str) -> InlineKeyboardMarkup:
    # Encode "09:00" as "0900" in callback_data - a literal ":" would break
    # the "set:notif:time:<slot>:<time>" split in handlers/settings.py.
    options = NOTIFICATION_SLOT_TIME_OPTIONS[slot]
    buttons = [
        InlineKeyboardButton(option, callback_data=f"set:notif:time:{slot}:{option.replace(':', '')}")
        for option in options
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def review_settings_keyboard(user) -> InlineKeyboardMarkup:
    """⚙️ Настройки → 📚 Настройки повторения (repetition-system stage
    section 26): word count for automatic reminders, independent per-slot
    enable/disable toggles, and the saved on-demand review-mode
    preference - reuses User.notification_word_count/morning_enabled/
    afternoon_enabled/evening_enabled/review_mode rather than introducing
    a parallel settings store."""
    count_row = [
        InlineKeyboardButton(
            f"{'✅ ' if n == user.notification_word_count else ''}{n}",
            callback_data=f"set:revsettings:count:{n}",
        )
        for n in NOTIFICATION_WORD_COUNT_OPTIONS
    ]

    slot_fields = (
        ("morning", user.morning_enabled),
        ("afternoon", user.afternoon_enabled),
        ("evening", user.evening_enabled),
    )
    slot_rows = [
        [
            InlineKeyboardButton(
                f"{'☑️' if enabled else '☐'} {t(f'notification_slot.{slot}', get_current_language())}",
                callback_data=f"set:revsettings:slot:{slot}",
            )
        ]
        for slot, enabled in slot_fields
    ]

    mode_labels = {
        "flashcard": t("revnow.button.flashcard_mode", get_current_language()),
        "quiz": t("revnow.button.quiz_mode", get_current_language()),
        "mixed": t("revnow.button.mixed_mode", get_current_language()),
    }
    mode_rows = [
        [
            InlineKeyboardButton(
                f"{'✅ ' if user.review_mode == mode else ''}{mode_labels[mode]}",
                callback_data=f"set:revsettings:mode:{mode}",
            )
        ]
        for mode in REVIEW_MODE_CHOICES
    ]
    mode_rows.append(
        [
            InlineKeyboardButton(
                f"{'✅ ' if user.review_mode is None else ''}{t('settings.review_settings.mode.ask', get_current_language())}",
                callback_data="set:revsettings:mode:ask",
            )
        ]
    )

    rows = [count_row, *slot_rows, *mode_rows]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def difficulty_pick_keyboard() -> InlineKeyboardMarkup:
    """"Уровень сложности изучения языка" (level-and-difficulty stage,
    replaces the old "Мой уровень"): A1-C2 manual picks plus
    🤖 Автоматически, which switches UserLanguage.difficulty_mode back to
    "automatic" so word generation uses the auto-tracked estimated level
    instead - never the other way around (picking a manual level never
    touches that estimate, see services.level_progress_service)."""
    # study-flow-rework stage section 30: "🟢 Только начинаю" is a leading
    # button here too, not a new level value - same callback_data as the
    # A1 button below, so picking either stores the a1 manual difficulty.
    rows = [[InlineKeyboardButton(t("level.beginner_button", get_current_language()), callback_data="set:difficulty:pick:a1")]]
    rows += [
        [InlineKeyboardButton(t(f"level.{code}", get_current_language()), callback_data=f"set:difficulty:pick:{code}")]
        for code in LEVEL_CODES
    ]
    rows.append([InlineKeyboardButton(t("settings.difficulty.automatic", get_current_language()), callback_data="set:difficulty:auto")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def timezone_pick_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(tz.label, callback_data=f"set:tz:pick:{tz.iana_name}")] for tz in TIMEZONE_CHOICES]
    rows.append([InlineKeyboardButton(t("settings.menu.timezone_search", get_current_language()), callback_data="set:tz:search")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def timezone_search_results_keyboard(iana_names: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(name, callback_data=f"set:tz:pick:{name}")] for name in iana_names]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:tz:list")])
    return InlineKeyboardMarkup(rows)


def goal_pick_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t(f"goal.{code}", get_current_language()), callback_data=f"set:goal:pick:{code}")]
        for code in GOAL_CODES
    ]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def industry_pick_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(t(f"industry.{code}", get_current_language()), callback_data=f"set:goal:industry:{code}")
        for code in PRESET_INDUSTRIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t("onboarding.button.other", get_current_language()), callback_data="set:goal:industry:other")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def topics_keyboard(selected_topics: list[str]) -> InlineKeyboardMarkup:
    """One toggle button per preset topic (✅ prefix when selected), one
    remove button per already-selected custom topic (anything in
    `selected_topics` that isn't a preset code), an "add custom" entry,
    a "generate now" trigger once at least one topic is picked, and back.

    Level-and-difficulty stage: relocated from ⚙️ Настройки into
    📚 Учить слова → 🎯 Новые слова по теме (spec section 10 - the
    capability moves, the screen and its callback_data prefix don't
    change, so this stays the exact same tested toggle/add-custom
    mechanics as before, just reached from a new place - back now
    returns to the learning submenu, its only entry point today)."""
    preset_set = set(PRESET_TOPICS)
    rows = []
    for code in PRESET_TOPICS:
        label = t(f"topic.{code}", get_current_language())
        if code in selected_topics:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"set:topics:toggle:{code}")])

    custom_topics = [topic for topic in selected_topics if topic not in preset_set]
    for i, topic in enumerate(custom_topics):
        rows.append([InlineKeyboardButton(f"✅ {topic}", callback_data=f"set:topics:removecustom:{i}")])

    rows.append([InlineKeyboardButton(t("settings.topics_add_custom", get_current_language()), callback_data="set:topics:add_custom")])
    if selected_topics:
        rows.append([InlineKeyboardButton(t("learning.topics.generate_now", get_current_language()), callback_data="learn:topicgen")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="learn:menu")])
    return InlineKeyboardMarkup(rows)


def topic_picker_keyboard() -> InlineKeyboardMarkup:
    """🎯 Новые слова по теме - instant-generation UX stage (spec sections
    14-19): tapping ANY topic here immediately triggers AI generation for
    just that topic - no intermediate "confirm"/"generate" button, unlike
    topics_keyboard() above (which is the older persistent multi-select
    still read by the automatic daily-quota generation's topic hint,
    word_generation_service._topic_hint - handlers/learning.py updates
    that same selected_topics field as a side effect of a tap here too,
    so the automatic flow still benefits from the user's latest explicit
    interest, but this screen itself is single-tap-and-go)."""
    rows = [
        [InlineKeyboardButton(t(f"topic.{code}", get_current_language()), callback_data=f"learn:topicgen:{code}")]
        for code in PRESET_TOPICS
    ]
    rows.append([InlineKeyboardButton(t("settings.topics_add_custom", get_current_language()), callback_data="learn:topics:custom")])
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="learn:menu")])
    return InlineKeyboardMarkup(rows)
