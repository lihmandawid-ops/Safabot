"""Data access for UserWord - one user's personal learning state for one
Word (spec sections 4-6, 20 of this stage's brief).

Kept as thin CRUD/query functions on purpose: deciding WHEN to pause,
restore a deleted word, or reject a duplicate add is business logic that
belongs in services/user_word_service.py, not here.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import UserWord, Word, WordStatus
from utils.text import normalize_word
from utils.time import utc_now

_WITH_WORD = (selectinload(UserWord.word).selectinload(Word.translations),)


async def get_user_word(session: AsyncSession, *, user_id: int, word_id: int) -> UserWord | None:
    result = await session.execute(
        select(UserWord)
        .where(UserWord.user_id == user_id, UserWord.word_id == word_id)
        .options(*_WITH_WORD)
    )
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_word_id: int) -> UserWord | None:
    result = await session.execute(
        select(UserWord).where(UserWord.id == user_word_id).options(*_WITH_WORD)
    )
    return result.scalar_one_or_none()


async def add_word(
    session: AsyncSession, *, user_id: int, word_id: int, language_code: str
) -> UserWord:
    user_word = UserWord(
        user_id=user_id,
        word_id=word_id,
        language_code=language_code,
        status=WordStatus.NEW,
        next_review_at=utc_now(),
    )
    session.add(user_word)
    await session.flush()
    return user_word


async def pause_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    user_word.status = WordStatus.PAUSED
    user_word.is_paused = True
    await session.flush()
    return user_word


async def resume_word(session: AsyncSession, user_word: UserWord, *, status: str) -> UserWord:
    user_word.status = status
    user_word.is_paused = False
    await session.flush()
    return user_word


async def delete_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    """Soft delete: never remove the row (spec section 13 - the shared
    Word must survive, and a re-add later should be able to restore this
    exact history instead of starting over)."""
    user_word.status = WordStatus.DELETED
    await session.flush()
    return user_word


async def restore_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    user_word.status = WordStatus.NEW
    user_word.is_paused = False
    await session.flush()
    return user_word


async def get_user_words(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str | None = None,
    statuses: list[str] | None = None,
    exclude_deleted: bool = True,
    limit: int | None = None,
    offset: int = 0,
) -> list[UserWord]:
    stmt = select(UserWord).where(UserWord.user_id == user_id).options(*_WITH_WORD)
    if language_code is not None:
        stmt = stmt.where(UserWord.language_code == language_code)
    if statuses is not None:
        stmt = stmt.where(UserWord.status.in_(statuses))
    elif exclude_deleted:
        stmt = stmt.where(UserWord.status != WordStatus.DELETED)
    # SQLite's CURRENT_TIMESTAMP is second-resolution, so several words
    # added within the same second would otherwise tie and could reorder
    # between renders - fatal for numbering stability (spec section 9).
    # UserWord.id is monotonically increasing, so it's a stable tiebreaker.
    stmt = stmt.order_by(UserWord.added_at, UserWord.id)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_review_words(session: AsyncSession, *, user_id: int, language_code: str | None = None) -> list[UserWord]:
    return await get_user_words(session, user_id=user_id, language_code=language_code, statuses=[WordStatus.REVIEW])


async def get_mastered_words(session: AsyncSession, *, user_id: int, language_code: str | None = None) -> list[UserWord]:
    return await get_user_words(session, user_id=user_id, language_code=language_code, statuses=[WordStatus.MASTERED])


async def get_paused_words(session: AsyncSession, *, user_id: int, language_code: str | None = None) -> list[UserWord]:
    return await get_user_words(session, user_id=user_id, language_code=language_code, statuses=[WordStatus.PAUSED])


async def count_user_words(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str | None = None,
    statuses: list[str] | None = None,
    exclude_deleted: bool = True,
) -> int:
    stmt = select(func.count()).select_from(UserWord).where(UserWord.user_id == user_id)
    if language_code is not None:
        stmt = stmt.where(UserWord.language_code == language_code)
    if statuses is not None:
        stmt = stmt.where(UserWord.status.in_(statuses))
    elif exclude_deleted:
        stmt = stmt.where(UserWord.status != WordStatus.DELETED)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def search_user_words(
    session: AsyncSession, *, user_id: int, language_code: str, query: str
) -> list[UserWord]:
    normalized_query = normalize_word(query)
    stmt = (
        select(UserWord)
        .join(Word, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user_id,
            UserWord.language_code == language_code,
            UserWord.status != WordStatus.DELETED,
            Word.normalized_word.like(f"%{normalized_query}%"),
        )
        .options(*_WITH_WORD)
        .order_by(Word.normalized_word)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
