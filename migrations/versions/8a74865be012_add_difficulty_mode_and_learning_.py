"""add difficulty_mode and learning_difficulty to user_languages; migrate level codes to CEFR

Revision ID: 8a74865be012
Revises: 41c7a4563507
Create Date: 2026-08-22 12:15:05.912959

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a74865be012'
down_revision: Union[str, Sequence[str], None] = '41c7a4563507'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Level-and-difficulty stage: the old 5-tier custom scale is replaced by
# the standard 6-tier CEFR scale (utils.levels.LEGACY_LEVEL_MAP is the
# same mapping, kept in sync here since a migration must never import
# application code that might change later).
_LEVEL_MAP = {
    "beginner": "a1",
    "elementary": "a2",
    "intermediate": "b1",
    "upper_intermediate": "b2",
    "advanced": "c1",
}


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # 1) Remap every existing level/difficulty value from the old 5-tier
    # scale to CEFR, on every table that stores one - no rows are ever
    # dropped or nulled, only their string value is rewritten.
    for old, new in _LEVEL_MAP.items():
        conn.execute(sa.text("UPDATE users SET level = :new WHERE level = :old"), {"new": new, "old": old})
        conn.execute(sa.text("UPDATE user_languages SET level = :new WHERE level = :old"), {"new": new, "old": old})
        conn.execute(sa.text("UPDATE words SET difficulty = :new WHERE difficulty = :old"), {"new": new, "old": old})

    # 2) New columns - difficulty_mode defaults to "manual" (spec:
    # existing users must never have their behavior silently change to
    # "automatic"), learning_difficulty backfills from the now-CEFR
    # `level` so a manual pick starts out matching what the learner was
    # already getting, not some other default.
    with op.batch_alter_table('user_languages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('difficulty_mode', sa.String(length=16), nullable=False, server_default='manual'))
        batch_op.add_column(sa.Column('learning_difficulty', sa.String(length=32), nullable=False, server_default='a1'))

    conn.execute(sa.text("UPDATE user_languages SET learning_difficulty = level"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_languages', schema=None) as batch_op:
        batch_op.drop_column('learning_difficulty')
        batch_op.drop_column('difficulty_mode')

    conn = op.get_bind()
    for old, new in _LEVEL_MAP.items():
        conn.execute(sa.text("UPDATE users SET level = :old WHERE level = :new"), {"new": new, "old": old})
        conn.execute(sa.text("UPDATE user_languages SET level = :old WHERE level = :new"), {"new": new, "old": old})
        conn.execute(sa.text("UPDATE words SET difficulty = :old WHERE difficulty = :new"), {"new": new, "old": old})
