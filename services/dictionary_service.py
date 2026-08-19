"""Word lookup: local dictionary first, external translation as fallback
(spec section 13).

TODO(stage-9): implement once database.models.Word exists and
translation_service.py is wired to a real provider. Defined here as the
integration point for handlers/dictionary.py.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def lookup_word(session: AsyncSession, *, language_code: str, raw_word: str):
    """Return a word card: from the local DB if present, otherwise via
    translation_service as a fallback, per section 13's 3-step flow."""
    raise NotImplementedError("Dictionary lookup arrives in Stage 9 (Dictionary)")
