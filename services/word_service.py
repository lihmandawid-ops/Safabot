"""Shared-dictionary business logic: search and word-card assembly (spec
sections 1-3, 14-17 of the words stage's brief).

Handlers call this instead of touching database.repositories.words
directly, and instead of building card data by hand from raw ORM rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Word, WordExample, WordForm, WordTranslation
from database.repositories import words as words_repo
from utils.text import normalize_word


@dataclass
class WordCard:
    word: Word
    translations: list[WordTranslation] = field(default_factory=list)
    examples: list[WordExample] = field(default_factory=list)
    forms: list[WordForm] = field(default_factory=list)


def build_word_card(word: Word, *, translation_language: str | None = None) -> WordCard:
    translations = [
        t for t in word.translations if translation_language is None or t.language_code == translation_language
    ]
    return WordCard(word=word, translations=translations, examples=list(word.examples), forms=list(word.forms))


async def search_words(session: AsyncSession, *, language_code: str, query: str, limit: int = 5) -> list[Word]:
    return await words_repo.search(session, language_code=language_code, query=query, limit=limit)


async def get_word_card(
    session: AsyncSession, *, word_id: int, translation_language: str | None = None
) -> WordCard | None:
    word = await words_repo.get_by_id(session, word_id)
    if word is None:
        return None
    return build_word_card(word, translation_language=translation_language)


async def ensure_pronunciation(session: AsyncSession, word: Word, *, translation_language: str, user_id: int) -> Word:
    """On-demand AI backfill (settings-improvements stage section 13): a
    Word row that predates reliable AI pronunciation generation, or where
    generation genuinely returned null that one time, is not stuck
    showing "not available" forever - the next time its card is actually
    opened, one more attempt is made. A no-op (no AI call at all) when
    pronunciation is already set, so this never re-asks for a word that
    already has one. Swallows every AI failure the same way the normal
    dictionary lookup does (services.dictionary_service.AIDictionaryProvider)
    - a missing pronunciation must never turn into a visible error."""
    if word.pronunciation:
        return word

    from services.dictionary_service import get_dictionary_provider

    result = await get_dictionary_provider().lookup(
        word.word, language_code=word.language_code, translation_language=translation_language,
        user_level=None, user_id=user_id,
    )
    if result is None or (not result.pronunciation and not result.phonetic):
        return word
    return await words_repo.set_pronunciation(session, word, pronunciation=result.pronunciation, phonetic=result.phonetic)


async def get_or_create_word(
    session: AsyncSession, *, language_code: str, word: str, **fields: object
) -> tuple[Word, bool]:
    """Returns (word, was_created). Used by seeding and, later, by AI/OCR
    ingestion flows that need to guarantee a Word row exists."""
    normalized = normalize_word(word)
    existing = await words_repo.find_exact(session, language_code=language_code, normalized_word=normalized)
    if existing is not None:
        return existing, False

    created = await words_repo.create(
        session, language_code=language_code, word=word, normalized_word=normalized, **fields
    )
    return created, True
