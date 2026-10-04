"""add name, position, system_prompt to users

Revision ID: <auto>
Revises: af6ed682704d
Create Date: <auto>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '<auto>'          # ← не трогайте, оставьте как сгенерировалось
down_revision: Union[str, Sequence[str], None] = 'af6ed682704d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Сначала nullable — чтобы не падало на существующих строках
    op.add_column('users', sa.Column('name', sa.String(length=120), nullable=True))
    op.add_column('users', sa.Column('position', sa.String(length=120), nullable=True))
    op.add_column('users', sa.Column('system_prompt', sa.Text(), nullable=True))

    # Заполняем name для существующих пользователей из email
    op.execute(
        "UPDATE users SET name = split_part(email, '@', 1) WHERE name IS NULL"
    )

    # Теперь можно сделать NOT NULL
    op.alter_column('users', 'name', nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'system_prompt')
    op.drop_column('users', 'position')
    op.drop_column('users', 'name')