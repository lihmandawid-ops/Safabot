"""Data access for 💬 Полезные фразы's UserPhrase rows (native-speaker
phrasebook stage). Section 16: never a duplicate save - the unique
constraint on (user_id, language_code, normalized_phrase) is the actual
guarantee, add_phrase's pre-check just turns a would-be constraint
violation into a clean "already saved" result the caller can message the
user about instead of a raised IntegrityError.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserPhrase
from utils.text import normalize_word


@dataclass
class AddPhraseResult:
    phrase: UserPhrase
    created: bool


async def find_existing(session: AsyncSession, *, user_id: int, language_code: str, phrase: str) -> UserPhrase | None:
    normalized = normalize_word(phrase)
    result = await session.execute(
        select(UserPhrase).where(
            UserPhrase.user_id == user_id,
            UserPhrase.language_code == language_code,
            UserPhrase.normalized_phrase == normalized,
        )
    )
    return result.scalar_one_or_none()


async def add_phrase(
    session: AsyncSession, *, user_id: int, language_code: str, phrase: str, translation: str,
    pronunciation: str | None = None, register: str | None = None,
    situation: str | None = None, explanation: str | None = None,
) -> AddPhraseResult:
    existing = await find_existing(session, user_id=user_id, language_code=language_code, phrase=phrase)
    if existing is not None:
        return AddPhraseResult(phrase=existing, created=False)

    row = UserPhrase(
        user_id=user_id, language_code=language_code, phrase=phrase, normalized_phrase=normalize_word(phrase),
        translation=translation, pronunciation=pronunciation, register=register,
        situation=situation, explanation=explanation,
    )
    session.add(row)
    await session.flush()
    return AddPhraseResult(phrase=row, created=True)


async def list_phrases(session: AsyncSession, *, user_id: int, language_code: str) -> list[UserPhrase]:
    result = await session.execute(
        select(UserPhrase)
        .where(UserPhrase.user_id == user_id, UserPhrase.language_code == language_code)
        .order_by(UserPhrase.created_at.desc())
    )
    return list(result.scalars().all())


async def get_by_id(session: AsyncSession, phrase_id: int) -> UserPhrase | None:
    result = await session.execute(select(UserPhrase).where(UserPhrase.id == phrase_id))
    return result.scalar_one_or_none()


async def delete_phrase(session: AsyncSession, phrase: UserPhrase) -> None:
    await session.delete(phrase)
    await session.flush()
