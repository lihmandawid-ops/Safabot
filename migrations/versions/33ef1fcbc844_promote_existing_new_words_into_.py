"""promote existing NEW words into repetition

Revision ID: 33ef1fcbc844
Revises: 419e4442367b
Create Date: 2026-08-24 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33ef1fcbc844'
down_revision: Union[str, Sequence[str], None] = '419e4442367b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data-only migration: real user request - "Новые слова так же нужно
    добавлять сразу в повторение" (new words must also enter repetition
    immediately). Every LIVE add-word path (📖 Словарь/➕ Добавить слово,
    📚 Учить слова's candidate cards, the auto-added morning words, ➕ Ещё
    новые слова) now creates UserWord rows as LEARNING instead of NEW -
    but that only affects brand-new rows going forward. A user_words row
    already sitting as NEW from before this fix was added via one of
    those exact same live paths (the daily-quota flow that actually
    creates NEW rows is unreachable from any live button - see
    services/word_generation_service.py), so it is stuck: excluded from
    every due-review query, with no UI action left that would ever
    advance it out of NEW. Backfill those existing rows into LEARNING so
    the fix applies retroactively, not just to words added after
    deployment. next_review_at was already set at creation time (see
    database/repositories/user_words.py's add_word), so a promoted row
    is immediately due without needing any date reset here."""
    op.execute("UPDATE user_words SET status = 'learning' WHERE status = 'new'")


def downgrade() -> None:
    """Data-only migration; which rows were genuinely NEW vs migrated
    here is not recoverable, and the fix this applies is a product
    decision, not something a downgrade should silently undo. No-op."""
    pass
