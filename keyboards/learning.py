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
    (study-flow-rework stage sections 1, 38): exactly two genuinely
    distinct ways to get new words, both AI-first (services.
    word_generation_service.generate_candidates) - never a third "random
    from the database" option. 🎯 leads into the existing, unchanged
    topics_keyboard()."""
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


_CANDIDATE_NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")


def candidate_summary_keyboard(remaining_indices: list[int]) -> InlineKeyboardMarkup:
    """study-flow-rework stage sections 2-3, 10: the compact "here are your
    two new words" screen, shown BEFORE either candidate is persisted -
    one "already know" button per still-undecided candidate (never for one
    already marked known), plus ▶️ Начнём изучать to walk the rest through
    full cards."""
    rows = [
        [
            InlineKeyboardButton(
                t("learning.button.candidate_known", get_current_language(), num=_CANDIDATE_NUMBERS[i]),
                callback_data=f"learn:candidate:known:{i}",
            )
        ]
        for i in remaining_indices
    ]
    rows.append([InlineKeyboardButton(t("learning.button.start_studying", get_current_language()), callback_data="learn:candidate:study")])
    return InlineKeyboardMarkup(rows)


def candidate_next_keyboard() -> InlineKeyboardMarkup:
    """Shown under a candidate's full card (study-flow-rework stage
    section 7) when at least one more candidate is still to come - the
    LAST card gets post_study_keyboard() directly instead, skipping an
    extra tap."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("learning.button.next_card", get_current_language()), callback_data="learn:candidate:next")]]
    )


def post_study_keyboard() -> InlineKeyboardMarkup:
    """study-flow-rework stage section 11: shown after the last new-word
    card (or when both candidates were marked already-known before study
    started) - 🔄 Повторить невыученные слова reuses the existing on-demand
    review pool entry point (handlers/review_now.py's revnow:menu, scoped
    to ALL active-learning words, never just these 2 - cross-handler
    callback_data reuse, same pattern as quiz_results_keyboard), 🆕 Получить
    ещё слова restarts this exact same flow, and the main menu - never
    📚 Учить слова as a required next step."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("learning.button.repeat_unlearned", get_current_language()), callback_data="revnow:menu")],
            [InlineKeyboardButton(t("learning.button.get_more_words", get_current_language()), callback_data="learn:newwords")],
            [InlineKeyboardButton(t("quiz.button.main_menu", get_current_language()), callback_data="revnow:mainmenu")],
        ]
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
            # AI-new-words stage sections 16-17, 35, 38: independent of the
            # 4-button grading ladder above - skips straight to MASTERED
            # (learn:mastered:<id>, handlers/learning.py), same bypass
            # 🤔 Я это уже знаю already uses for a brand-new word.
            [InlineKeyboardButton(t("revnow.button.already_learned", get_current_language()), callback_data=f"learn:mastered:{user_word_id}")],
        ]
    )
