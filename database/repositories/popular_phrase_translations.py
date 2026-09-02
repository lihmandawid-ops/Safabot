"""Cache for 🔥 Популярные фразы' translations (native-speaker phrasebook
stage bugfix): populated once per (language_code, translation_language)
pair via a single batch AI call, read by every later view - never a live
translation call per phrase or per page. See
database.models.PopularPhraseTranslation for the shape/rationale.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PopularPhraseTranslation


async def get_map(session: AsyncSession, *, language_code: str, translation_language: str) -> dict[int, str]:
    result = await session.execute(
        select(PopularPhraseTranslation).where(
            PopularPhraseTranslation.language_code == language_code,
            PopularPhraseTranslation.translation_language == translation_language,
        )
    )
    return {row.phrase_index: row.translation for row in result.scalars()}


async def bulk_save(
    session: AsyncSession, *, language_code: str, translation_language: str, translations: dict[int, str]
) -> None:
    """Callers only ever pass indices they already confirmed are missing
    from get_map(), same "check then insert" pattern as
    database.repositories.phrases.add_phrase - not a race-proof atomic
    upsert, but this cache only fills once per (language, translation
    language) pair ever, so a rare concurrent double-fill is harmless
    (the unique constraint just means the second write loses)."""
    if not translations:
        return
    for phrase_index, translation in translations.items():
        session.add(
            PopularPhraseTranslation(
                language_code=language_code, translation_language=translation_language,
                phrase_index=phrase_index, translation=translation,
            )
        )
    await session.flush()
