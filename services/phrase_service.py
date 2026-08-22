"""💬 Полезные фразы (native-speaker phrasebook stage): turns a picked
situation (or free-text custom one) into ONE natural, native-speaker
phrase via services.ai_service.generate_native_phrase, and persists a
saved phrase through database.repositories.phrases - no new AI schema
validation or dedup logic lives in the handler, both stay here so
handlers/phrases.py only orchestrates Telegram I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserLanguage
from database.repositories import phrases as phrases_repo
from database.repositories import popular_phrase_translations as popular_translations_repo
from services import ai_models
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger
from utils.phrase_situations import PRESET_SITUATIONS
from utils.popular_phrases import get_popular_phrases

logger = get_logger(__name__)

# 🔥 Популярные фразы pagination (bugfix stage section 9): 4-8 phrases per
# page, matching the spec's own example of 5.
POPULAR_PHRASES_PAGE_SIZE = 5

# Section 10-11: a short, unambiguous English description for each preset
# code, sent to the AI regardless of interface_language (every AI prompt
# in this codebase is English for consistency) - kept separate from the
# button's own localized label (locales/*.json "phrase_situation.<code>")
# shown to the user, so a Russian/Hebrew/etc. label never has to double as
# the literal AI instruction.
_SITUATION_HINTS: dict[str, str] = {
    "work": "at work / in the workplace, talking to a colleague or manager",
    "shopping": "shopping in a store, talking to a cashier or shop assistant",
    "restaurant": "at a restaurant or cafe, ordering food or talking to staff",
    "travel": "traveling (airport, train station, asking for directions)",
    "hotel": "at a hotel, checking in/out or talking to hotel staff",
    "transport": "using transport (taxi, bus, train), talking to a driver or asking about a ride",
    "meeting": "meeting or introducing yourself to someone new",
    "daily_life": "an everyday daily-life situation (home, neighbors, errands)",
    "socializing": "casual socializing / small talk with someone",
    "phone": "on a phone call",
    "doctor": "at the doctor's or a medical appointment",
    "bank": "at a bank, handling a banking matter",
    "study": "studying, at school or in a class",
    "customer_service": "providing customer service to a client professionally",
}


def situation_hint(situation_code: str) -> str:
    """The English description sent to the AI for a preset code, or the
    text itself for a custom (free-text) situation - callers never need
    to know which kind they're holding."""
    return _SITUATION_HINTS.get(situation_code, situation_code)


def industry_hint(user_language: UserLanguage) -> str | None:
    """Same gate word_generation_service._industry_hint uses: only
    meaningful when learning_goal is actually "work"."""
    if user_language.learning_goal == "work" and user_language.work_industry:
        return user_language.work_industry
    return None


async def generate_phrase(
    *, user: User, user_language: UserLanguage, situation_code: str, situation_text: str,
    exclude_phrases: list[str] | None = None,
) -> ai_models.NativePhraseResult:
    """Never swallows AIError - callers (handlers/phrases.py) decide the
    user-facing fallback, same convention every other AI-backed handler
    in this codebase follows (e.g. handlers/text_analysis.py)."""
    return await get_ai_service().generate_native_phrase(
        language_code=user_language.language_code,
        translation_language=user_language.translation_language,
        level=user_language.level,
        situation=situation_hint(situation_code) if situation_code in PRESET_SITUATIONS else situation_text,
        industry=industry_hint(user_language),
        topics=user_language.selected_topics or None,
        exclude_phrases=exclude_phrases,
        user_id=user.id,
    )


async def save_phrase(
    session: AsyncSession, *, user_id: int, language_code: str, result: ai_models.NativePhraseResult,
    situation_code: str | None = None,
) -> phrases_repo.AddPhraseResult:
    """Section 16: dedup is enforced by database.repositories.phrases.add_phrase
    itself (case-insensitive, per user+language) - this is a thin field
    mapping from the AI result shape to the storage shape, nothing more."""
    return await phrases_repo.add_phrase(
        session, user_id=user_id, language_code=language_code,
        phrase=result.phrase, translation=result.translation, pronunciation=result.pronunciation,
        register=result.register_type, situation=situation_code or result.situation, explanation=result.explanation,
    )


@dataclass(frozen=True)
class TranslatedPopularPhrase:
    """One 🔥 Популярные фразы entry, fully ready to render: the static
    seed phrase + its own Latin pronunciation (utils.popular_phrases -
    both are already about the phrase itself, never touched by
    translation), plus its translation for whichever translation_language
    the viewer currently has - `translation` is "" only if the AI batch
    call that would have filled it has never succeeded (AI unconfigured
    or failed both times) - callers show a placeholder in that case."""

    index: int
    phrase: str
    pronunciation: str
    translation: str
    situation: str


async def get_translated_popular_phrases(
    session: AsyncSession, *, language_code: str, translation_language: str, user_id: int,
) -> list[TranslatedPopularPhrase]:
    """Root-cause fix for the 🔥 Популярные фразы pronunciation bug: the
    old flow called AIService.analyze_text() live, on every card open,
    whose pronunciation field was (before this same bugfix) generated
    "using the translation language's own spelling conventions" - i.e.
    Cyrillic for a Russian interface - which in practice sometimes came
    back reading like a copy of the translation. Popular-phrase
    pronunciation now NEVER touches AI at all: it's the static seed data's
    own already-Latin, already-phrase-specific pronunciation. Only the
    TRANSLATION is fetched from AI, and only via one small BATCH call per
    (language_code, translation_language) pair, cached forever afterward
    (database.repositories.popular_phrase_translations) - so browsing,
    re-opening, and paging through the list all read from the DB, never
    calling AI again once a language pair has been translated once.
    """
    entries = get_popular_phrases(language_code)
    if not entries:
        return []

    cached = await popular_translations_repo.get_map(
        session, language_code=language_code, translation_language=translation_language
    )
    missing = [i for i in range(len(entries)) if i not in cached]
    if missing:
        try:
            translated = await get_ai_service().translate_phrases(
                [entries[i].phrase for i in missing],
                language_code=language_code, translation_language=translation_language, user_id=user_id,
            )
        except AIError:
            logger.warning(
                "Popular-phrase batch translation failed language_code=%s translation_language=%s",
                language_code, translation_language,
            )
            translated = []

        new_entries = dict(zip(missing, translated))  # tolerates a short/empty result gracefully
        if new_entries:
            await popular_translations_repo.bulk_save(
                session, language_code=language_code, translation_language=translation_language,
                translations=new_entries,
            )
            cached.update(new_entries)

    return [
        TranslatedPopularPhrase(
            index=i, phrase=entry.phrase, pronunciation=entry.pronunciation,
            translation=cached.get(i, ""), situation=entry.situation,
        )
        for i, entry in enumerate(entries)
    ]
