"""Word lookup: local dictionary first, AI provider as fallback (bugfix
spec, root cause #1 - "пользователь не может нормально добавлять
собственные слова"). Every "add a word" entry point (📖 Словарь and
⭐ Мои слова → ➕ Добавить слово) calls lookup_word() here rather than
word_service.search_words() directly, so "fall back to a provider when the
local dictionary has nothing" lives in exactly one place.

DictionaryProvider is the swappable interface (same philosophy as
services/repetition_service.py's pure algorithm and services/ai_service.py's
AIService): AIDictionaryProvider wraps services.ai_service.get_ai_service()
and is the only implementation today, selected via config.get_settings().
A provider is never called directly from a handler - only through
lookup_word().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word
from database.repositories import words as words_repo
from services import ai_word_schema, word_service
from services.ai_service import get_ai_service


@dataclass
class WordData:
    """A validated word ready to be persisted as a Word row (the same
    shape services/ai_word_schema.WordEntry produces)."""

    word: str
    translations: list[str] = field(default_factory=list)
    part_of_speech: str | None = None
    phonetic: str | None = None
    examples: list[ai_word_schema.ExampleEntry] = field(default_factory=list)
    difficulty: str | None = None
    category: str | None = None


class DictionaryProvider(ABC):
    @abstractmethod
    async def lookup(self, raw_word: str, *, language_code: str, translation_language: str) -> WordData | None:
        """A single best-effort match for `raw_word`, or None if the
        provider has nothing (including "not configured" or "call
        failed") - callers must treat None as "no fallback available",
        never as an error to propagate."""


class AIDictionaryProvider(DictionaryProvider):
    """Wraps services.ai_service.get_ai_service(). Never raises: a
    NotConfiguredAIService (AI_PROVIDER=none, today's default) or any
    provider failure is swallowed and reported as "nothing found" so the
    user still gets a clear "not found" message instead of a crash.
    """

    async def lookup(self, raw_word: str, *, language_code: str, translation_language: str) -> WordData | None:
        try:
            raw = await get_ai_service().analyze_word(raw_word, language_code=language_code)
        except Exception:
            return None

        entry = ai_word_schema.parse_word_entry(raw)
        if entry is None:
            return None
        return WordData(
            word=entry.word,
            translations=entry.translations,
            part_of_speech=entry.part_of_speech,
            phonetic=entry.phonetic,
            examples=entry.examples,
            difficulty=entry.difficulty,
            category=entry.category,
        )


def get_dictionary_provider() -> DictionaryProvider:
    return AIDictionaryProvider()


async def lookup_word(
    session: AsyncSession,
    *,
    language_code: str,
    translation_language: str,
    raw_word: str,
    limit: int = 5,
) -> list[Word]:
    """Local matches first; if there are none, ask the configured
    DictionaryProvider for a single fallback match and persist it as a
    real Word row (so the next lookup of the same word is local again).
    Returns [] only when neither the local dictionary nor the provider has
    anything - the caller shows "not found" in that case only.
    """
    local = await word_service.search_words(session, language_code=language_code, query=raw_word, limit=limit)
    if local:
        return local

    provider_word = await _lookup_and_persist(
        session, provider=get_dictionary_provider(),
        raw_word=raw_word, language_code=language_code, translation_language=translation_language,
    )
    return [provider_word] if provider_word is not None else []


async def _lookup_and_persist(
    session: AsyncSession, *, provider: DictionaryProvider, raw_word: str, language_code: str, translation_language: str
) -> Word | None:
    data = await provider.lookup(raw_word, language_code=language_code, translation_language=translation_language)
    if data is None:
        return None

    word, was_created = await word_service.get_or_create_word(
        session,
        language_code=language_code,
        word=data.word,
        part_of_speech=data.part_of_speech,
        phonetic=data.phonetic,
        difficulty=data.difficulty,
        category=data.category,
    )
    if not was_created:
        # Provider echoed back a word we already have locally (e.g. a
        # spelling variant that normalizes to an existing entry) - the
        # existing row is authoritative, nothing more to persist.
        return word

    for translation in data.translations:
        await words_repo.add_translation(
            session, word_id=word.id, language_code=translation_language, translation=translation
        )
    for example in data.examples:
        await words_repo.add_example(session, word_id=word.id, example_text=example.text, translation=example.translation)

    # `word` only has its bare fields set in memory - translations/examples
    # were inserted via words_repo directly, never through word.translations
    # .append(), so that relationship collection is not safely readable
    # without a lazy-load (unsupported under async SQLAlchemy). Re-fetch
    # through find_exact, which eager-loads the full chain, before handing
    # the Word back to a caller that will render a card from it.
    return await words_repo.find_exact(session, language_code=language_code, normalized_word=word.normalized_word)
