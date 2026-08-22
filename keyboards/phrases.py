"""Keyboards for 💬 Полезные фразы (native-speaker phrasebook stage)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.i18n import get_current_language, t
from utils.phrase_situations import PRESET_SITUATIONS


def phrases_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("phrases.menu.saved", get_current_language()), callback_data="phr:saved")],
            [InlineKeyboardButton(t("phrases.menu.new", get_current_language()), callback_data="phr:new")],
            [InlineKeyboardButton(t("phrases.menu.popular", get_current_language()), callback_data="phr:popular")],
            [InlineKeyboardButton(t("phrases.menu.back", get_current_language()), callback_data="phr:mainmenu")],
        ]
    )


def situation_picker_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(t(f"phrase_situation.{code}", get_current_language()), callback_data=f"phr:situation:{code}")
        for code in PRESET_SITUATIONS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t("phrases.situation.custom", get_current_language()), callback_data="phr:situation:custom")])
    rows.append([InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:menu")])
    return InlineKeyboardMarkup(rows)


def saved_list_keyboard(phrase_ids: list[int]) -> InlineKeyboardMarkup:
    """One numbered button per saved phrase (⭐ Мои слова's numbered-list
    spirit, but as tappable buttons since a saved-phrases list is
    typically short - no free-text number entry needed)."""
    numbers = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
    rows = []
    for i, phrase_id in enumerate(phrase_ids):
        label = numbers[i] if i < len(numbers) else str(i + 1)
        rows.append([InlineKeyboardButton(label, callback_data=f"phr:open:{phrase_id}")])
    rows.append([InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:menu")])
    return InlineKeyboardMarkup(rows)


def popular_list_keyboard(count: int) -> InlineKeyboardMarkup:
    numbers = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
    rows = []
    for i in range(count):
        label = numbers[i] if i < len(numbers) else str(i + 1)
        rows.append([InlineKeyboardButton(label, callback_data=f"phr:popularopen:{i}")])
    rows.append([InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:menu")])
    return InlineKeyboardMarkup(rows)


def saved_phrase_card_keyboard(phrase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("phrases.button.analyze", get_current_language()), callback_data=f"phr:analyze:saved:{phrase_id}")],
            [InlineKeyboardButton(t("phrases.button.delete", get_current_language()), callback_data=f"phr:delete:{phrase_id}")],
            [InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:saved")],
        ]
    )


def delete_confirm_keyboard(phrase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("phrases.button.delete_confirm", get_current_language()), callback_data=f"phr:delete_confirm:{phrase_id}")],
            [InlineKeyboardButton(t("words.button.cancel", get_current_language()), callback_data=f"phr:open:{phrase_id}")],
        ]
    )


def generated_phrase_keyboard() -> InlineKeyboardMarkup:
    """✨ Новая фраза / 🎯 Своя ситуация result (sections 4, 15, 24): the
    phrase isn't saved yet, so 💾 Сохранить replaces 🗑️ Удалить, and
    🔄 Другая фраза offers a different natural phrasing for the same
    situation without a second AI round-trip through the menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("phrases.button.save", get_current_language()), callback_data="phr:save")],
            [InlineKeyboardButton(t("phrases.button.another", get_current_language()), callback_data="phr:regenerate")],
            [InlineKeyboardButton(t("phrases.button.analyze", get_current_language()), callback_data="phr:analyze:pending")],
            [InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:menu")],
        ]
    )


def popular_phrase_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("phrases.button.save", get_current_language()), callback_data="phr:save")],
            [InlineKeyboardButton(t("phrases.button.analyze", get_current_language()), callback_data="phr:analyze:pending")],
            [InlineKeyboardButton(t("phrases.button.back", get_current_language()), callback_data="phr:popular")],
        ]
    )
