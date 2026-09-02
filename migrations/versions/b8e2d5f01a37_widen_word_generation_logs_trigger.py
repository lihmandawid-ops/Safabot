"""widen word_generation_logs.trigger to 32 chars

services/word_generation_service.py has been writing the trigger value
"explicit_new_words_topic" (24 characters) into a String(16) column.
SQLite does not enforce declared VARCHAR lengths, so this was stored
without complaint and never surfaced in testing; PostgreSQL enforces
them and rejects the row with "value too long for type character
varying(16)", which blocked the SQLite -> PostgreSQL data migration.

Revision ID: b8e2d5f01a37
Revises: f4d1b7c2a9e5
Create Date: 2026-08-28 15:21:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2d5f01a37'
down_revision: Union[str, Sequence[str], None] = 'f4d1b7c2a9e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Dialect-aware for the same reason as f4d1b7c2a9e5: SQLite ignores
    # VARCHAR lengths entirely, so widening one there is a no-op that
    # would otherwise cost a full batch table rebuild.
    if op.get_bind().dialect.name == "sqlite":
        return

    op.alter_column(
        "word_generation_logs",
        "trigger",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "sqlite":
        return

    # Note: on any database that already holds a 24-character
    # "explicit_new_words_topic" row this narrowing will fail rather
    # than silently truncate. That is the intended behaviour - the
    # value genuinely does not fit the older type.
    op.alter_column(
        "word_generation_logs",
        "trigger",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
