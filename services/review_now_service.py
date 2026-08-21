"""🔁 Повторить - ON-DEMAND REVIEW (repetition-system stage sections 1-7,
16-17).

Word selection (learning_service.get_words_for_on_demand_review) and the
repetition-state write for an answer (learning_service.
record_on_demand_answer) both already live in services/learning_service.py,
reusing the exact same repetition_service algorithm every other review
path uses - this module only turns the selected UserWord rows into the
plain, JSON-serializable dicts handlers/review_now.py renders and stores
in context.user_data, mirroring services/quiz_service.py's pattern (no
LearningSession/LearningSessionItem rows for something this transient).
"""
from __future__ import annotations

from database.models import UserWord
from utils.languages import LANGUAGE_BY_CODE
from utils.word_display import format_pronunciation, translation_for


def build_flashcard_items(user_words: list[UserWord], translation_language: str) -> list[dict]:
    """🔤 Обычное повторение (section 5): unlike the quiz's flashcard-
    style questions, the translation is shown immediately - no separate
    reveal step - so everything needed to render the card is captured
    here up front."""
    items = []
    for uw in user_words:
        translation = translation_for(uw, translation_language)
        if translation is None:
            continue
        lang = LANGUAGE_BY_CODE.get(uw.word.language_code)
        example = uw.word.examples[0].example_text if uw.word.examples else None
        items.append(
            {
                "user_word_id": uw.id,
                "flag": lang.flag if lang else "",
                "word": uw.word.word,
                "translation": translation,
                "pronunciation": format_pronunciation(uw.word),
                "example": example,
            }
        )
    return items
