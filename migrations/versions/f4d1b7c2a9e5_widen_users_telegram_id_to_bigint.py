"""widen users.telegram_id to bigint

Telegram user ids have already outgrown signed 32-bit: ids above
2_147_483_647 are routinely handed out, and real production rows carry
them. SQLite stores every INTEGER as 64-bit, so the too-narrow column
type was invisible there - but on PostgreSQL the same mapping becomes a
real INT4 and rejects such an id with "value out of int32 range",
which is exactly what blocked the SQLite -> PostgreSQL data migration.

Revision ID: f4d1b7c2a9e5
Revises: c1c8e4be6faa
Create Date: 2026-08-28 15:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4d1b7c2a9e5'
down_revision: Union[str, Sequence[str], None] = 'c1c8e4be6faa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Deliberately dialect-aware rather than a blanket batch_alter_table:
    # on SQLite, INTEGER is already 64-bit, so the only thing a batch
    # operation would accomplish is a full table rebuild (drop/recreate
    # plus every index and foreign key) to reach a state the database is
    # already in. Existing SQLite deployments - including a rollback
    # from PostgreSQL back to the SQLite file - should not pay that risk
    # for a no-op.
    if op.get_bind().dialect.name == "sqlite":
        return

    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "sqlite":
        return

    # Narrowing back to INTEGER will fail if any stored id exceeds
    # 32-bit - which is the correct outcome: that data cannot be
    # represented in the older column type, and silently truncating it
    # would corrupt user identity.
    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
