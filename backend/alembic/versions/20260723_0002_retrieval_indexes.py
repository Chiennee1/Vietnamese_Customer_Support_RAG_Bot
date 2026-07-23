"""Add hybrid retrieval indexes.

Revision ID: 20260723_0002
Revises: 20260723_0001
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0002"
down_revision: str | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_embedding_hnsw
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_content_fts
        ON knowledge_chunks
        USING gin (to_tsvector('simple', content_normalized))
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_chunks_content_fts",
        table_name="knowledge_chunks",
    )
    op.drop_index(
        "ix_knowledge_chunks_embedding_hnsw",
        table_name="knowledge_chunks",
    )

