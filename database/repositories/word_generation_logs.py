"""Data access for WordGenerationLog (bugfix spec: "для контроля
использования AI и затрат") - one row per
services/word_generation_service.generate_new_words call, logged whether
or not an AI provider actually ended up being called.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import WordGenerationLog


async def log(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    requested_amount: int,
    generated_amount: int,
    provider: str,
) -> WordGenerationLog:
    row = WordGenerationLog(
        user_id=user_id,
        language_code=language_code,
        requested_amount=requested_amount,
        generated_amount=generated_amount,
        provider=provider,
    )
    session.add(row)
    await session.flush()
    return row
