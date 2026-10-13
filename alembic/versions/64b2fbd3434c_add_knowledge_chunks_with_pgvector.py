"""add knowledge_chunks with pgvector

Revision ID: 64b2fbd3434c
Revises: c4e8a1f07b52
Create Date: 2026-10-10 ...
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision: str = '64b2fbd3434c'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1f07b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 768


def upgrade() -> None:
    # 1. Расширение pgvector — обязательно ДО создания таблицы с типом vector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Таблица
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('doc_id', sa.String(length=255), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('embedding', Vector(EMBED_DIM), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_knowledge_chunks_doc_id'),
        'knowledge_chunks',
        ['doc_id'],
        unique=False,
    )

    # 3. HNSW-индекс для быстрого поиска ближайших соседей.
    #    Без него поиск работает, но O(n) — медленно на больших базах.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding")
    op.drop_index(op.f('ix_knowledge_chunks_doc_id'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    # Расширение НЕ удаляем: оно может использоваться другими таблицами.