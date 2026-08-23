"""add example pronunciation

Revision ID: cf17a3a88250
Revises: 1f0fb915fa8c
Create Date: 2026-08-23 15:31:55.809990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf17a3a88250'
down_revision: Union[str, Sequence[str], None] = '1f0fb915fa8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('word_examples', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pronunciation', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('word_examples', schema=None) as batch_op:
        batch_op.drop_column('pronunciation')
