"""Personal-learning-state business logic (spec sections 4-13 of the words
stage's brief): add/pause/resume/delete a word, list with filters.

Handlers call this instead of touching database.repositories.user_words
directly - e.g. a handler does `await user_word_service.pause_word(...)`,
never `user_word.status = WordStatus.PAUSED` by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserWord, WordStatus
from database.repositories import user_words as user_words_repo

AddOutcome = Literal["created", "already_active", "restored_from_deleted", "offer_resume_paused"]

# UI-facing filter codes (spec section 8) mapped to the DB statuses they cover.
FILTER_STATUSES: dict[str, list[str] | None] = {
    "all": None,  # None = every non-deleted status (handled by repo's exclude_deleted)
    "new": [WordStatus.NEW],
    "review": [WordStatus.LEARNING, WordStatus.REVIEW],
    "paused": [WordStatus.PAUSED],
    "mastered": [WordStatus.MASTERED],
}


@dataclass
class AddWordResult:
    user_word: UserWord
    outcome: AddOutcome


async def add_word_to_learning(
    session: AsyncSession, *, user_id: int, word_id: int, language_code: str
) -> AddWordResult:
    """Section 6's add flow: create if new, restore if DELETED, offer to
    resume if PAUSED, otherwise report it's already in the dictionary."""
    existing = await user_words_repo.get_user_word(session, user_id=user_id, word_id=word_id)

    if existing is None:
        created = await user_words_repo.add_word(
            session, user_id=user_id, word_id=word_id, language_code=language_code
        )
        return AddWordResult(created, "created")

    if existing.status == WordStatus.DELETED:
        restored = await user_words_repo.restore_word(session, existing)
        return AddWordResult(restored, "restored_from_deleted")

    if existing.status == WordStatus.PAUSED:
        return AddWordResult(existing, "offer_resume_paused")

    return AddWordResult(existing, "already_active")


async def pause_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    """Section 12: PAUSED excludes the word from automatic review without
    deleting it."""
    return await user_words_repo.pause_word(session, user_word)


async def resume_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    """Section 12: bring a PAUSED word back - REVIEW if it had already
    made progress on the repetition ladder, otherwise back to NEW."""
    target_status = WordStatus.REVIEW if user_word.repetition_stage > 0 else WordStatus.NEW
    return await user_words_repo.resume_word(session, user_word, status=target_status)


async def delete_word(session: AsyncSession, user_word: UserWord) -> UserWord:
    """Section 13: soft delete - the shared Word row and other users'
    UserWord rows for it are never touched."""
    return await user_words_repo.delete_word(session, user_word)


async def list_user_words(
    session: AsyncSession, *, user_id: int, language_code: str, status_filter: str = "all"
) -> list[UserWord]:
    statuses = FILTER_STATUSES.get(status_filter, None)
    return await user_words_repo.get_user_words(
        session, user_id=user_id, language_code=language_code, statuses=statuses
    )


async def count_user_words(
    session: AsyncSession, *, user_id: int, language_code: str, status_filter: str = "all"
) -> int:
    statuses = FILTER_STATUSES.get(status_filter, None)
    return await user_words_repo.count_user_words(
        session, user_id=user_id, language_code=language_code, statuses=statuses
    )


async def search_user_words(
    session: AsyncSession, *, user_id: int, language_code: str, query: str
) -> list[UserWord]:
    """Section 19: 🔎 Найти моё слово."""
    return await user_words_repo.search_user_words(
        session, user_id=user_id, language_code=language_code, query=query
    )
