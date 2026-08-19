"""Data access for Word (spec section 7).

Planned for Stage 5 (Words), once the Word ORM model exists. Defined here
only as the integration point handlers/dictionary.py and
handlers/words.py will call into - deliberately not implemented yet so we
don't ship dead schema/queries against a table that doesn't exist.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def find_word(session: AsyncSession, *, language_code: str, normalized_word: str):
    """Look up a word in the shared dictionary by its normalized form.

    TODO(stage-5): implement once database.models.Word exists.
    """
    raise NotImplementedError("Word lookup arrives in Stage 5 (Words)")
