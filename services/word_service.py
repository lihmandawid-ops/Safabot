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
