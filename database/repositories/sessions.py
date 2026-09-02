"""Data access for LearningSession / LearningSessionItem (learning-core
stage, section 24-25). The session and its items ARE the persisted state
of an in-progress 📚 Учить слова / 🔄 Повторить run - handlers/learning.py
never keeps "where the user is" anywhere else, so a bot restart loses
nothing (section 25).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import LearningSession, LearningSessionItem, UserWord, Word
from utils.time import utc_now

_word_chain = (
    selectinload(LearningSession.items)
    .selectinload(LearningSessionItem.user_word)
    .selectinload(UserWord.word)
)
# Three separate loader options sharing the same prefix - chaining a
# single .selectinload() call only follows ONE path, so translations/
# examples/forms (siblings on Word) each need their own branch or a
# handler that reads all three (see handlers/learning.py's word-card
# rendering, which reuses services/word_service.build_word_card) hits a
# MissingGreenlet lazy-load on whichever ones were left out.
_WITH_ITEMS = (
    _word_chain.selectinload(Word.translations),
    _word_chain.selectinload(Word.examples),
    _word_chain.selectinload(Word.forms),
)


async def get_active_session(session: AsyncSession, *, user_id: int, language_code: str) -> LearningSession | None:
    result = await session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.language_code == language_code,
            LearningSession.status == "in_progress",
        )
        .options(*_WITH_ITEMS)
        .order_by(LearningSession.started_at.desc())
    )
    return result.scalars().first()


async def get_session_by_id(session: AsyncSession, session_id: int) -> LearningSession | None:
    result = await session.execute(
        select(LearningSession).where(LearningSession.id == session_id).options(*_WITH_ITEMS)
    )
    return result.scalar_one_or_none()


async def create_session(session: AsyncSession, *, user_id: int, language_code: str) -> LearningSession:
    learning_session = LearningSession(user_id=user_id, language_code=language_code, status="in_progress")
    # Explicitly seed the collection as "loaded" (empty). Without this, the
    # first access to .items after flush() would be treated as an unloaded
    # relationship needing a lazy SELECT - which async SQLAlchemy cannot
    # perform outside a greenlet, raising MissingGreenlet. Verified
    # empirically; this one line is what makes add_session_item's
    # item.session = learning_session (and any later len(...items)) safe.
    learning_session.items = []
    session.add(learning_session)
    await session.flush()
    return learning_session


async def add_session_item(
    session: AsyncSession,
    *,
    learning_session: LearningSession,
    user_word_id: int,
    position: int,
    is_new_word: bool,
) -> LearningSessionItem:
    item = LearningSessionItem(
        user_word_id=user_word_id,
        position=position,
        is_new_word=is_new_word,
    )
    # Assigning through the relationship (not a raw session_id=... FK) is
    # what keeps learning_session.items in sync in memory, so a caller
    # building a session in one go sees the items immediately without a
    # re-fetch from the database.
    item.session = learning_session
    session.add(item)
    learning_session.total_words += 1
    await session.flush()
    return item


def next_incomplete_item(learning_session: LearningSession) -> LearningSessionItem | None:
    """Pure lookup over an already-loaded session's items - no query,
    since get_active_session/get_session_by_id eager-load every item."""
    for item in sorted(learning_session.items, key=lambda i: i.position):
        if not item.completed:
            return item
    return None


async def get_item_for_user_word(
    session: AsyncSession, *, learning_session_id: int, user_word_id: int
) -> LearningSessionItem | None:
    """Confirms `user_word_id` is actually part of THIS session (spec
    section 36: never trust a callback's ids without checking ownership/
    membership) before a rating is allowed to touch it."""
    result = await session.execute(
        select(LearningSessionItem).where(
            LearningSessionItem.session_id == learning_session_id,
            LearningSessionItem.user_word_id == user_word_id,
        )
    )
    return result.scalar_one_or_none()


async def complete_item(session: AsyncSession, item: LearningSessionItem, *, rating: str) -> LearningSessionItem:
    item.completed = True
    item.rating = rating
    learning_session = await session.get(LearningSession, item.session_id)
    learning_session.completed_words += 1
    await session.flush()
    return item


async def complete_session(session: AsyncSession, learning_session: LearningSession, *, now: datetime | None = None) -> LearningSession:
    learning_session.status = "completed"
    learning_session.completed_at = now if now is not None else utc_now()
    await session.flush()
    return learning_session


def session_stats(learning_session: LearningSession) -> dict[str, int]:
    """Section 12's completion screen numbers, computed from the
    already-loaded items - "Правильных" counts every non-"again" rating,
    "Ошибок" counts "again" (matches repetition_service's own correct/
    wrong_delta split)."""
    completed_items = [i for i in learning_session.items if i.completed]
    new_words = sum(1 for i in completed_items if i.is_new_word)
    wrong = sum(1 for i in completed_items if i.rating == "again")
    correct = len(completed_items) - wrong
    return {
        "total_reviewed": len(completed_items),
        "new_words": new_words,
        "correct": correct,
        "wrong": wrong,
    }
