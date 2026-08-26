"""add languages table, extend user and user_language fields

Revision ID: cc37901c0d0f
Revises: b6a5ebfb4cac
Create Date: 2026-08-19 16:56:40.990789

Hand-adjusted after autogenerate: the raw diff represented every rename
(daily_word_limit -> daily_new_words, current_level -> level, etc.) as a
drop+add, which would silently discard any data in those columns. Rewritten
below as batch_op.alter_column(..., new_column_name=...) so existing rows
survive the upgrade.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc37901c0d0f'
down_revision: Union[str, Sequence[str], None] = 'b6a5ebfb4cac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LANGUAGE_SEED_DATA = (
    {"code": "en", "name": "English", "native_name": "English", "active": True},
    {"code": "ru", "name": "Russian", "native_name": "Русский", "active": True},
    {"code": "de", "name": "German", "native_name": "Deutsch", "active": True},
    {"code": "he", "name": "Hebrew", "native_name": "עברית", "active": True},
    {"code": "es", "name": "Spanish", "native_name": "Español", "active": True},
    {"code": "fr", "name": "French", "native_name": "Français", "active": True},
    {"code": "it", "name": "Italian", "native_name": "Italiano", "active": True},
    {"code": "uk", "name": "Ukrainian", "native_name": "Українська", "active": True},
)


def upgrade() -> None:
    """Upgrade schema."""
    languages_table = op.create_table(
        'languages',
        sa.Column('code', sa.String(length=8), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('native_name', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )
    op.bulk_insert(languages_table, list(LANGUAGE_SEED_DATA))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'registration_date', new_column_name='created_at',
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text('(CURRENT_TIMESTAMP)'),
        )
        batch_op.alter_column(
            'current_level', new_column_name='level', existing_type=sa.String(length=32)
        )
        batch_op.alter_column(
            'daily_new_words_limit', new_column_name='daily_new_words', existing_type=sa.Integer()
        )
        batch_op.alter_column(
            'morning_notification_time', new_column_name='morning_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'afternoon_notification_time', new_column_name='afternoon_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'evening_notification_time', new_column_name='evening_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'trial_start_date', new_column_name='trial_start', existing_type=sa.Date()
        )
        batch_op.alter_column(
            'trial_end_date', new_column_name='trial_end', existing_type=sa.Date()
        )
        batch_op.alter_column(
            'subscription_end_date', new_column_name='subscription_end', existing_type=sa.Date()
        )
        batch_op.add_column(sa.Column('subscription_start', sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'updated_at', sa.DateTime(timezone=True),
                server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False,
            )
        )
        batch_op.create_foreign_key(
            'fk_users_interface_language_languages', 'languages', ['interface_language'], ['code']
        )

    with op.batch_alter_table('user_languages', schema=None) as batch_op:
        batch_op.alter_column(
            'daily_word_limit', new_column_name='daily_new_words', existing_type=sa.Integer()
        )
        batch_op.alter_column(
            'is_active', new_column_name='active', existing_type=sa.Boolean()
        )
        batch_op.add_column(
            # Postgres-migration stage: sa.text('0') is a SQLite-only
            # convenience (SQLite has no real BOOLEAN type, so an integer
            # literal default works there) - PostgreSQL's actual BOOLEAN
            # column rejects an integer default expression outright
            # ("column is of type boolean but default expression is of
            # type integer"). sa.false() is valid on both.
            sa.Column('is_current', sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.drop_constraint('uq_user_language', type_='unique')
        batch_op.create_unique_constraint(
            'uq_user_language_pair', ['user_id', 'language_code', 'translation_language']
        )
        batch_op.create_foreign_key(
            'fk_user_languages_language_code_languages', 'languages', ['language_code'], ['code']
        )
        batch_op.create_foreign_key(
            'fk_user_languages_translation_language_languages',
            'languages', ['translation_language'], ['code'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_languages', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_user_languages_translation_language_languages', type_='foreignkey'
        )
        batch_op.drop_constraint('fk_user_languages_language_code_languages', type_='foreignkey')
        batch_op.drop_constraint('uq_user_language_pair', type_='unique')
        batch_op.create_unique_constraint('uq_user_language', ['user_id', 'language_code'])
        batch_op.drop_column('is_current')
        batch_op.alter_column(
            'active', new_column_name='is_active', existing_type=sa.Boolean()
        )
        batch_op.alter_column(
            'daily_new_words', new_column_name='daily_word_limit', existing_type=sa.Integer()
        )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_interface_language_languages', type_='foreignkey')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('subscription_start')
        batch_op.alter_column(
            'subscription_end', new_column_name='subscription_end_date', existing_type=sa.Date()
        )
        batch_op.alter_column(
            'trial_end', new_column_name='trial_end_date', existing_type=sa.Date()
        )
        batch_op.alter_column(
            'trial_start', new_column_name='trial_start_date', existing_type=sa.Date()
        )
        batch_op.alter_column(
            'evening_time', new_column_name='evening_notification_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'afternoon_time', new_column_name='afternoon_notification_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'morning_time', new_column_name='morning_notification_time', existing_type=sa.Time()
        )
        batch_op.alter_column(
            'daily_new_words', new_column_name='daily_new_words_limit', existing_type=sa.Integer()
        )
        batch_op.alter_column('level', new_column_name='current_level', existing_type=sa.String(length=32))
        batch_op.alter_column(
            'created_at', new_column_name='registration_date',
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text('(CURRENT_TIMESTAMP)'),
        )

    op.drop_table('languages')
