"""Orchestrates the daily learning flow (spec sections 10-11): picking the
day's new words, queuing due reviews, and applying review answers.

TODO(stage-6/7): implement once database.models.Word/UserWord and
services/repetition_service.py exist. Defined here as the integration
point for handlers/learning.py and handlers/review.py, and for
scheduler/notifications.py's three daily sends.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def get_new_words_for_today(session: AsyncSession, *, user_id: int, language_code: str):
    raise NotImplementedError("New-word selection arrives in Stage 6 (Learning)")


async def get_words_due_for_review(session: AsyncSession, *, user_id: int, language_code: str):
    raise NotImplementedError("Review queueing arrives in Stage 7 (Repetition)")
