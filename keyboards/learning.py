"""Keyboards for the 📚 Учить слова / 🔄 Повторить flow (learning-core
stage, sections 9-12, 35).

Rating buttons deliberately carry only a UserWord id and the grade in
callback_data (`review:<id>:<grade>`) - never the word text (spec section
3/35: keep callback_data compact, never put user-facing content there).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.repetition_service import ReviewGrade
from utils.i18n import get_current_language, t


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("learning.button.start", get_current_language()), callback_data="learn:start")],
            [InlineKeyboardButton(t("learning.button.pick_words", get_current_language()), callback_data="learn:menu")],
        ]
    )


def learn_menu_keyboard() -> InlineKeyboardMarkup:
    """📚 Учить слова -> "how should new words be picked" submenu
    (level-and-difficulty stage, spec sections 10-16): exactly two ways to
    get new words, both AI-first (services.word_generation_service.
    generate_words_ai_first) - never a third "random from the database"
    option. 🎯 leads into the existing, unchanged topics_keyboard()."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("learning.button.new_words_now", get_current_language()), callback_data="learn:newwords")],
            [InlineKeyboardButton(t("learning.button.new_words_topic", get_current_language()), callback_data="learn:topics")],
            [InlineKeyboardButton(t("card.button.back", get_current_language()), callback_data="learn:intro")],
        ]
    )


def start_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("learning.button.start", get_current_language()), callback_data="learn:reviewonly")]])


def continue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("learning.button.continue", get_current_language()), callback_data="learn:continue")]])


def reveal_keyboard(user_word_id: int, *, is_new_word: bool = False) -> InlineKeyboardMarkup:
    """"🤔 Я это уже знаю" (bugfix stage section 12) only makes sense for a
    word the user hasn't started learning yet - a due review is, by
    definition, already something they're partway through."""
    rows = [[InlineKeyboardButton(t("learning.button.reveal", get_current_language()), callback_data=f"learn:reveal:{user_word_id}")]]
    if is_new_word:
        rows.append([InlineKeyboardButton(t("learning.button.know", get_current_language()), callback_data=f"learn:know:{user_word_id}")])
    return InlineKeyboardMarkup(rows)


def after_session_keyboard() -> InlineKeyboardMarkup:
    """Shown once nothing more is due today (bugfix stage section 8/9,
    extended in the settings-improvements stage section 4): lets the user
    immediately ask for more new words, review old ones again, jump to
    ⭐ Мои слова or 📖 Словарь, instead of having to go back to the
    plain-text main menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("learning.button.old_words", get_current_language()), callback_data="learn:oldwords")],
            [InlineKeyboardButton(t("quiz.button.start", get_current_language()), callback_data="quiz:start")],
            [InlineKeyboardButton(t("learning.button.learn_more", get_current_language()), callback_data="learn:intro")],
            [InlineKeyboardButton(t("learning.button.pick_words", get_current_language()), callback_data="learn:menu")],
            [InlineKeyboardButton(t("learning.button.extra", get_current_language()), callback_data="learn:extra")],
            [InlineKeyboardButton(t("learning.button.mywords", get_current_language()), callback_data="learn:mywords")],
            [InlineKeyboardButton(t("learning.button.dictionary", get_current_language()), callback_data="learn:dictionary")],
        ]
    )


def old_words_amount_keyboard() -> InlineKeyboardMarkup:
    from services.learning_service import OLD_WORDS_REVIEW_OPTIONS

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(str(n), callback_data=f"learn:oldwords:{n}")
                for n in OLD_WORDS_REVIEW_OPTIONS
            ],
            [InlineKeyboardButton(t("card.button.back", get_current_language()), callback_data="learn:intro")],
        ]
    )


def extra_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("learning.button.extra_2", get_current_language()), callback_data="learn:extra:2"),
                InlineKeyboardButton(t("learning.button.extra_4", get_current_language()), callback_data="learn:extra:4"),
                InlineKeyboardButton(t("learning.button.extra_8", get_current_language()), callback_data="learn:extra:8"),
            ],
            [InlineKeyboardButton(t("card.button.back", get_current_language()), callback_data="learn:intro")],
        ]
    )


def known_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    """First exposure to a brand-new word (repetition-system-audit stage
    sections 7-11): the 4-button difficulty scale doesn't make sense
    before the user has ever tried to recall it - a single acknowledgment
    reuses the SAME GOOD grade and review: callback the 4-button
    keyboard's own "🙂 Помню" button uses, so the word enters the exact
    same repetition system as every other answer (no second scoring
    path), just without asking for a difficulty judgment on something
    never seen before."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("learning.button.learned", get_current_language()), callback_data=f"review:{user_word_id}:{ReviewGrade.GOOD.value}")]]
    )


def rating_keyboard(user_word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("learning.rating.again", get_current_language()), callback_data=f"review:{user_word_id}:{ReviewGrade.AGAIN.value}"),
                InlineKeyboardButton(t("learning.rating.hard", get_current_language()), callback_data=f"review:{user_word_id}:{ReviewGrade.HARD.value}"),
            ],
            [
                InlineKeyboardButton(t("learning.rating.good", get_current_language()), callback_data=f"review:{user_word_id}:{ReviewGrade.GOOD.value}"),
                InlineKeyboardButton(t("learning.rating.easy", get_current_language()), callback_data=f"review:{user_word_id}:{ReviewGrade.EASY.value}"),
            ],
        ]
    )
