"""Data access for the shared dictionary: Word, WordTranslation,
WordExample, WordForm (spec sections 1-3, 17, 20).

Search/lookup queries eager-load translations/examples/forms via
selectinload so callers (services/word_service.py) can build a word card
after the session that fetched them is done, without a lazy-load MissingGreenlet
surprise from SQLAlchemy's async mode.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import UserWord, Word, WordExample, WordForm, WordTranslation
from utils.text import normalize_word

_WITH_RELATIONS = (
    selectinload(Word.translations),
    selectinload(Word.examples),
    selectinload(Word.forms),
)


async def get_by_id(session: AsyncSession, word_id: int) -> Word | None:
    result = await session.execute(
        select(Word).where(Word.id == word_id).options(*_WITH_RELATIONS)
    )
    return result.scalar_one_or_none()


async def find_exact(session: AsyncSession, *, language_code: str, normalized_word: str) -> Word | None:
    result = await session.execute(
        select(Word)
        .where(Word.language_code == language_code, Word.normalized_word == normalized_word)
        .options(*_WITH_RELATIONS)
    )
    return result.scalar_one_or_none()


async def search(
    session: AsyncSession, *, language_code: str, query: str, limit: int = 5
) -> list[Word]:
    """Section 14: exact -> normalized -> partial match, scoped to one
    language so "gehen" in German never matches a homograph elsewhere."""
    normalized_query = normalize_word(query)
    if not normalized_query:
        return []

    exact = await find_exact(session, language_code=language_code, normalized_word=normalized_query)
    if exact is not None:
        return [exact]

    result = await session.execute(
        select(Word)
        .where(
            Word.language_code == language_code,
            or_(
                Word.normalized_word.like(f"{normalized_query}%"),
                Word.normalized_word.like(f"%{normalized_query}%"),
            ),
        )
        .options(*_WITH_RELATIONS)
        .order_by(Word.normalized_word)
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def get_by_language(
    session: AsyncSession, *, language_code: str, limit: int = 50, offset: int = 0
) -> list[Word]:
    result = await session.execute(
        select(Word)
        .where(Word.language_code == language_code)
        .order_by(Word.normalized_word)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def find_unknown_words_for_generation(
    session: AsyncSession, *, user_id: int, language_code: str, level: str, limit: int, topics: list[str] | None = None
) -> list[Word]:
    """Word rows in `language_code` the user has NO UserWord row for at
    all - regardless of status (bugfix spec: "не уже известные пользователю
    ни в каком статусе") - the local candidate pool
    services/word_generation_service.py draws from before ever calling an
    AI provider. Prefers words matching the user's level, same as
    learning.get_new_word_candidates, without hard-excluding the rest.

    `topics` (settings-improvements stage section 22's 🎯 Темы обучения)
    additionally prefers words whose .category is one of the user's
    selected topics - ranked ABOVE the level match, so a topic-relevant
    word at the "wrong" difficulty still beats an on-level word from an
    unrelated topic. Never excludes non-matching words: a sparse or
    empty selected_topics list must still return a full candidate list."""
    if limit <= 0:
        return []
    level_match = case((Word.difficulty == level, 0), else_=1)
    topic_match = case((Word.category.in_(topics), 0), else_=1) if topics else case((True, 1))
    known_subquery = (
        select(UserWord.id).where(UserWord.user_id == user_id, UserWord.word_id == Word.id).exists()
    )
    result = await session.execute(
        select(Word)
        .where(Word.language_code == language_code, ~known_subquery)
        .options(*_WITH_RELATIONS)
        .order_by(topic_match, level_match, Word.id)
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def get_verb_forms(session: AsyncSession, word_id: int) -> list[WordForm]:
    result = await session.execute(select(WordForm).where(WordForm.word_id == word_id))
    return list(result.scalars().all())


async def set_pronunciation(
    session: AsyncSession, word: Word, *, pronunciation: str | None, phonetic: str | None
) -> Word:
    """On-demand backfill (settings-improvements stage section 13) for a
    Word row that predates reliable AI pronunciation generation, or where
    the AI genuinely returned null once - never overwrites an existing
    non-null value, so a manually-curated seed entry is never clobbered
    by a later AI guess."""
    if pronunciation and not word.pronunciation:
        word.pronunciation = pronunciation
    if phonetic and not word.phonetic:
        word.phonetic = phonetic
    await session.flush()
    return word


async def create(session: AsyncSession, *, language_code: str, word: str, **fields: Any) -> Word:
    normalized = fields.pop("normalized_word", None) or normalize_word(word)
    new_word = Word(language_code=language_code, word=word, normalized_word=normalized, **fields)
    session.add(new_word)
    await session.flush()
    return new_word


async def add_translation(
    session: AsyncSession,
    *,
    word_id: int,
    language_code: str,
    translation: str,
    definition: str | None = None,
    usage_note: str | None = None,
) -> WordTranslation:
    row = WordTranslation(
        word_id=word_id,
        language_code=language_code,
        translation=translation,
        definition=definition,
        usage_note=usage_note,
    )
    session.add(row)
    await session.flush()
    return row


async def add_example(
    session: AsyncSession,
    *,
    word_id: int,
    example_text: str,
    translation: str | None = None,
    level: str | None = None,
) -> WordExample:
    row = WordExample(word_id=word_id, example_text=example_text, translation=translation, level=level)
    session.add(row)
    await session.flush()
    return row


async def add_form(
    session: AsyncSession,
    *,
    word_id: int,
    form_type: str,
    form: str,
    grammatical_info: str | None = None,
) -> WordForm:
    row = WordForm(word_id=word_id, form_type=form_type, form=form, grammatical_info=grammatical_info)
    session.add(row)
    await session.flush()
    return row
