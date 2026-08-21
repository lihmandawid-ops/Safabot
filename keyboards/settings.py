"""Inline keyboards for the ⚙️ Настройки menu (spec section 15).

All callback_data uses the "set:" prefix so handlers/settings.py's single
CallbackQueryHandler can route every settings interaction; being pure
callback routing (no ConversationHandler state), it needs no persistence
to survive a bot restart - the current value always comes straight from
the database.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t
from utils.languages import SUPPORTED_LANGUAGES, language_display_name
from utils.levels import LEVEL_CODES
from utils.timezones import TIMEZONE_CHOICES

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
            [InlineKeyboardButton(t("settings.menu.daily_words", get_current_language()), callback_data="set:words:list")],
            [InlineKeyboardButton(t("settings.menu.notification_time", get_current_language()), callback_data="set:notif:slots")],
            [InlineKeyboardButton(t("settings.menu.notifications_toggle", get_current_language()), callback_data="set:notif:toggle")],
            [InlineKeyboardButton(t("settings.menu.level", get_current_language()), callback_data="set:level:list")],
            [InlineKeyboardButton(t("settings.menu.timezone", get_current_language()), callback_data="set:tz:list")],
            [InlineKeyboardButton(t("settings.menu.subscription", get_current_language()), callback_data="set:sub")],
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
    rows = [
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


def add_language_words_keyboard(
    learning_language: str, translation_language: str, level: str, options: tuple[int, ...]
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    str(n),
                    callback_data=f"set:addlang:words:{learning_language}:{translation_language}:{level}:{n}",
                )
                for n in options
            ],
            [InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:lang:list")],
        ]
    )


def interface_language_pick_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{lang.flag} {language_display_name(lang)}", callback_data=f"set:iface:pick:{lang.code}")
        for lang in SUPPORTED_LANGUAGES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")])
    return InlineKeyboardMarkup(rows)


def daily_words_pick_keyboard(options: tuple[int, ...]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(str(n), callback_data=f"set:words:pick:{n}") for n in options],
            [InlineKeyboardButton(t("settings.menu.back", get_current_language()), callback_data="set:home")],
        ]
    )


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


def level_pick_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t(f"level.{code}", get_current_language()), callback_data=f"set:level:pick:{code}")]
        for code in LEVEL_CODES
    ]
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
