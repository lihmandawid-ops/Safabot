"""🔤 Все формы (repetition-system stage sections 18-25; bidirectional-
dictionary stage sections 14-18): generates a full, language-appropriate
verb conjugation via the existing AIService, cached on Word.verb_conjugation
so a repeat tap never re-calls DeepSeek. Falls back to whatever flat
WordForm rows already exist (populated at word-generation time, spec
section 20's "verb_forms" AI field) for a word that isn't a verb, or when
the AI call itself fails - the card always shows SOMETHING reasonable
rather than an error.

A freshly generated table caches each form as {"form": str, "pronunciation":
str|null, "person_label": str|null, "translation": str|null} (global
pronunciation rule section 49 - one pronunciation per individual conjugated
form; bidirectional-dictionary sections 14-18 - person_label/translation
are both native-language text). Because person_label/translation are
native-language-dependent (unlike form/pronunciation, which are purely
about the learning language), the cache is scoped per translation_language:
{translation_language: {tense: [...]}}. Word.verb_conjugation is a
schema-less JSON column, so an OLDER row cached before this change - a flat
{tense: [...]} shape with no per-language wrapping - keeps working forever:
it predates person_label/translation entirely, so it's language-independent
and safe to keep serving as-is to any translation_language (just without
those two fields) rather than forcing a regeneration.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word
from database.repositories import words as words_repo
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger

logger = get_logger(__name__)


def _is_legacy_flat_shape(cached: dict) -> bool:
    """True for the pre-existing {tense: [...]} shape (values are lists),
    False for the newer {translation_language: {tense: [...]}} shape
    (values are dicts) introduced alongside person_label/translation."""
    first_value = next(iter(cached.values()), None)
    return isinstance(first_value, list)


async def get_or_generate_conjugation(
    session: AsyncSession, word: Word, *, translation_language: str, user_id: int
) -> dict[str, list] | None:
    """None means no AI-generated conjugation table is available - the
    caller falls back to word.forms (the older flat WordForm list) or a
    "not available" message. Never raises: an AI failure here must not
    break 🔤 Все формы, only degrade it."""
    cached = word.verb_conjugation
    if cached:
        if _is_legacy_flat_shape(cached):
            return cached
        if translation_language in cached:
            return cached[translation_language]

    if not (word.is_verb or word.part_of_speech == "verb"):
        return None

    try:
        result = await get_ai_service().generate_verb_conjugation(
            word.word, language_code=word.language_code,
            translation_language=translation_language, user_id=user_id,
        )
    except AIError:
        logger.warning("Verb conjugation generation failed for word_id=%s", word.id)
        return None

    forms = {
        tense: [
            {
                "form": item.form,
                "pronunciation": item.pronunciation,
                "person_label": item.person_label,
                "translation": item.translation,
            }
            for item in items
        ]
        for tense, items in result.forms.items()
    }
    merged = dict(cached) if cached and not _is_legacy_flat_shape(cached) else {}
    merged[translation_language] = forms
    await words_repo.set_verb_conjugation(session, word, merged)
    return forms
