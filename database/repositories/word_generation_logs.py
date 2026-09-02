"""Data access for WordGenerationLog (bugfix spec: "для контроля
использования AI и затрат") - one row per
services/word_generation_service.generate_new_words call, logged whether
or not an AI provider actually ended up being called. `trigger`
distinguishes the normal daily auto-fill from an explicit "➕ Ещё новые
слова" request or a "🤔 Я это уже знаю" replacement, so each can be
capped independently.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
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
    trigger: str = "daily_quota",
) -> WordGenerationLog:
    row = WordGenerationLog(
        user_id=user_id,
        language_code=language_code,
        requested_amount=requested_amount,
        generated_amount=generated_amount,
        provider=provider,
        trigger=trigger,
    )
    session.add(row)
    await session.flush()
    return row


async def sum_generated_today(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    trigger: str,
    day_start: datetime,
    day_end: datetime,
) -> int:
    """How many words were actually added today (generated_amount, not
    requested_amount) under a given trigger - the number
    generate_extra_words checks against MAX_EXTRA_WORDS_PER_DAY."""
    result = await session.execute(
        select(func.coalesce(func.sum(WordGenerationLog.generated_amount), 0)).where(
            WordGenerationLog.user_id == user_id,
            WordGenerationLog.language_code == language_code,
            WordGenerationLog.trigger == trigger,
            WordGenerationLog.created_at >= day_start,
            WordGenerationLog.created_at < day_end,
        )
    )
    return int(result.scalar_one())
