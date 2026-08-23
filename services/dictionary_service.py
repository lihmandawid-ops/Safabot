"""Word lookup: local dictionary first, AI as fallback (bugfix spec, root
cause #1 - "пользователь не может нормально добавлять собственные
слова"; AI-integration spec section 7). Every "add a word" entry point
(📖 Словарь and ⭐ Мои слова → ➕ Добавить слово) calls lookup_word() here
rather than word_service.search_words() directly, so "fall back to AI
when the local dictionary has nothing" lives in exactly one place.

DictionaryProvider is the swappable interface (same philosophy as
services/repetition_service.py's pure algorithm and services/ai_service.py's
AIService): AIDictionaryProvider wraps services.ai_service.get_ai_service()
and is the only implementation today, selected via config.get_settings()
(through get_ai_service() - AI_ENABLED/AI_API_KEY decide whether that's a
real provider or NotConfiguredAIService). A provider is never called
directly from a handler - only through lookup_word().
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word
from database.repositories import words as words_repo
from services import ai_models, word_service
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger

logger = get_logger(__name__)


class DictionaryProvider(ABC):
    @abstractmethod
    async def lookup(
        self, raw_word: str, *, language_code: str, translation_language: str,
        user_level: str | None, user_id: int,
    ) -> ai_models.GeneratedWord | None:
        """A single best-effort match for `raw_word`, or None if the
        provider has nothing (not configured, rate-limited, network
        failure, invalid response, ...) - callers must treat None as "no
        fallback available", never as an error to propagate. The reason is
        logged here so it's not lost, but the user only ever sees a plain
        "not found"."""


class AIDictionaryProvider(DictionaryProvider):
    """Wraps services.ai_service.get_ai_service(). Never raises: any
    AIError (not configured, auth, timeout, rate limit, invalid response,
    ...) is swallowed and reported as "nothing found" so the user still
    gets a clear "not found" message instead of a crash (spec section 28
    - Dictionary must fall back to the local database, never break).
    """

    async def lookup(
        self, raw_word: str, *, language_code: str, translation_language: str,
        user_level: str | None, user_id: int,
    ) -> ai_models.GeneratedWord | None:
        try:
            return await get_ai_service().lookup_word(
                raw_word, language_code=language_code, translation_language=translation_language,
                user_level=user_level, user_id=user_id,
            )
        except AIError as exc:
            logger.info("Dictionary AI fallback unavailable for %r: %s", language_code, type(exc).__name__)
            return None


def get_dictionary_provider() -> DictionaryProvider:
    return AIDictionaryProvider()


async def lookup_word(
    session: AsyncSession,
    *,
    language_code: str,
    translation_language: str,
    raw_word: str,
    user_id: int,
    user_level: str | None = None,
    limit: int = 5,
) -> list[Word]:
    """Local matches first; if there are none, ask the configured
    DictionaryProvider for a single fallback match and persist it as a
    real Word row (so the next lookup of the same word is local again -
    spec section 8: "AI не вызывается каждый раз"). Returns [] only when
    neither the local dictionary nor the provider has anything - the
    caller shows "not found" in that case only.
    """
    local = await word_service.search_words(session, language_code=language_code, query=raw_word, limit=limit)
    if local:
        return local

    provider_word = await _lookup_and_persist(
        session, provider=get_dictionary_provider(),
        raw_word=raw_word, language_code=language_code, translation_language=translation_language,
        user_level=user_level, user_id=user_id,
    )
    return [provider_word] if provider_word is not None else []


async def _lookup_and_persist(
    session: AsyncSession, *, provider: DictionaryProvider, raw_word: str, language_code: str,
    translation_language: str, user_level: str | None, user_id: int,
) -> Word | None:
    data = await provider.lookup(
        raw_word, language_code=language_code, translation_language=translation_language,
        user_level=user_level, user_id=user_id,
    )
    if data is None:
        return None

    word, was_created = await word_service.get_or_create_word(
        session,
        language_code=language_code,
        word=data.word,
        part_of_speech=data.part_of_speech,
        pronunciation=data.pronunciation,
        phonetic=data.phonetic,
        definition=data.definition,
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
            session, word_id=word.id, language_code=translation_language,
            translation=translation.translation, usage_note=translation.usage_note,
        )
    for example in data.examples:
        await words_repo.add_example(
            session, word_id=word.id, example_text=example.text, translation=example.translation,
            pronunciation=example.pronunciation,
        )
    if data.part_of_speech == "verb" and data.verb_forms:
        for form_type, form in data.verb_forms.items():
            await words_repo.add_form(session, word_id=word.id, form_type=form_type, form=form)

    # `word` only has its bare fields set in memory - translations/examples
    # were inserted via words_repo directly, never through word.translations
    # .append(), so that relationship collection is not safely readable
    # without a lazy-load (unsupported under async SQLAlchemy). Re-fetch
    # through find_exact, which eager-loads the full chain, before handing
    # the Word back to a caller that will render a card from it.
    return await words_repo.find_exact(session, language_code=language_code, normalized_word=word.normalized_word)
