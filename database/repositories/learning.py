"""Data access for UserWord - a user's personal learning state for a word
(spec section 7-8).

Planned for Stage 5/7 (Words, Repetition), once the UserWord ORM model
exists. Defined here only as the integration point
services/learning_service.py and services/repetition_service.py will call
into.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def get_due_for_review(session: AsyncSession, *, user_id: int, language_code: str):
    """Return UserWord rows whose next_review_at has passed.

    TODO(stage-7): implement once database.models.UserWord exists and the
    repetition algorithm (services/repetition_service.py) is in place.
    """
    raise NotImplementedError("Review scheduling arrives in Stage 7 (Repetition)")
