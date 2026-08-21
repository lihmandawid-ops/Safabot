"""🔤 Все формы (repetition-system stage sections 18-25): generates a full,
language-appropriate verb conjugation via the existing AIService, cached
on Word.verb_conjugation so a repeat tap never re-calls DeepSeek. Falls
back to whatever flat WordForm rows already exist (populated at word-
generation time, spec section 20's "verb_forms" AI field) for a word that
isn't a verb, or when the AI call itself fails - the card always shows
SOMETHING reasonable rather than an error.

A freshly generated table caches each form as {"form": str, "pronunciation":
str|null} (global pronunciation rule section 49 - one pronunciation per
individual conjugated form, not one shared pronunciation for the whole
verb). Word.verb_conjugation is a schema-less JSON column, so older rows
cached before this change keep their original flat list[str] shape
forever - utils.word_display.render_conjugation_messages reads both
shapes directly rather than this module reshaping old cache entries.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word
from database.repositories import words as words_repo
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger

logger = get_logger(__name__)


async def get_or_generate_conjugation(
    session: AsyncSession, word: Word, *, user_id: int
) -> dict[str, list] | None:
    """None means no AI-generated conjugation table is available - the
    caller falls back to word.forms (the older flat WordForm list) or a
    "not available" message. Never raises: an AI failure here must not
    break 🔤 Все формы, only degrade it."""
    if word.verb_conjugation:
        return word.verb_conjugation

    if not (word.is_verb or word.part_of_speech == "verb"):
        return None

    try:
        result = await get_ai_service().generate_verb_conjugation(
            word.word, language_code=word.language_code, user_id=user_id,
        )
    except AIError:
        logger.warning("Verb conjugation generation failed for word_id=%s", word.id)
        return None

    forms = {
        tense: [{"form": item.form, "pronunciation": item.pronunciation} for item in items]
        for tense, items in result.forms.items()
    }
    await words_repo.set_verb_conjugation(session, word, forms)
    return forms
