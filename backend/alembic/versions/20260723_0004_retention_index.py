"""Add conversation retention index.

Revision ID: 20260723_0004
Revises: 20260723_0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0004"
down_revision: str | None = "20260723_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_updated_at",
        "conversations",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_updated_at",
        table_name="conversations",
    )
