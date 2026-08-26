"""Tier-aware usage limits (commercial layer): FREE users get a bounded
number of AI-generated words per day from 🆕 Получить новые слова / 🎯 по
теме (services.word_generation_service.generate_candidates) - Safabot's
most resource-intensive feature, a live AI call per request. TRIAL and
PRO (services.subscription_service.has_pro_access) are unlimited.

Reuses the exact same local_day_bounds + WordGenerationLog +
sum_generated_today pattern services.word_generation_service.
generate_extra_words already established for MAX_EXTRA_WORDS_PER_DAY -
no new counting mechanism, no new table. `generate_candidates` already
tags its own writes with trigger "explicit_new_words" (🆕) or
"explicit_new_words_topic" (🎯) - both count against the same daily pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.models import User
from database.repositories import word_generation_logs as generation_logs_repo
from services.subscription_service import has_pro_access
from utils.logging import get_logger
from utils.time import local_day_bounds, utc_now

logger = get_logger(__name__)

_AI_GENERATION_TRIGGERS = ("explicit_new_words", "explicit_new_words_topic")


@dataclass(frozen=True)
class GenerationLimitCheck:
    allowed: bool
    used_today: int
    limit: int | None  # None means unlimited for this user right now


async def check_ai_generation_limit(
    session: AsyncSession, *, user: User, language_code: str, now: datetime | None = None
) -> GenerationLimitCheck:
    """Never blocks TRIAL/PRO. Never raises - a broken limit check must
    degrade to "allowed" rather than block a FREE user's learning
    entirely (same never-break-the-flow convention as the rest of the
    word-generation stack)."""
    if has_pro_access(user):
        return GenerationLimitCheck(allowed=True, used_today=0, limit=None)

    limit = get_settings().plan_limits.free_daily_ai_generation_limit
    if limit is None:
        return GenerationLimitCheck(allowed=True, used_today=0, limit=None)

    try:
        now = now if now is not None else utc_now()
        day_start, day_end = local_day_bounds(now, user.timezone)
        used = 0
        for trigger in _AI_GENERATION_TRIGGERS:
            used += await generation_logs_repo.sum_generated_today(
                session, user_id=user.id, language_code=language_code, trigger=trigger,
                day_start=day_start, day_end=day_end,
            )
    except Exception:
        logger.exception("AI generation limit check failed user_id=%s", user.id)
        return GenerationLimitCheck(allowed=True, used_today=0, limit=limit)

    return GenerationLimitCheck(allowed=used < limit, used_today=used, limit=limit)
