"""add missing events indexes

Revision ID: c4e8a1f07b52
Revises: 3fa0a183de45
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4e8a1f07b52'
down_revision: Union[str, Sequence[str], None] = '3fa0a183de45'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f('ix_events_run_id'), 'events', ['run_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_events_type'), 'events', ['type'], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_events_type'), table_name='events', if_exists=True)
    op.drop_index(op.f('ix_events_run_id'), table_name='events', if_exists=True)