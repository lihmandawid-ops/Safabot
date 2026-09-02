"""raise notification word count minimum to 8

Revision ID: 419e4442367b
Revises: 08ef631ace73
Create Date: 2026-08-24 15:25:17.608217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '419e4442367b'
down_revision: Union[str, Sequence[str], None] = '08ef631ace73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data-only migration: users.notification_word_count's Python-side
    default moved from 4 to 8 (real user request - every repetition
    process must cover at least 8 words), which only affects brand-new
    rows. Backfill existing users whose saved preference is below the
    new minimum so the guarantee actually holds for everyone, not just
    new signups."""
    op.execute("UPDATE users SET notification_word_count = 8 WHERE notification_word_count < 8")


def downgrade() -> None:
    """Data-only migration; the previous per-user values are not
    recoverable, and the guarantee this raises is a product decision,
    not something a downgrade should silently undo. No-op."""
    pass
