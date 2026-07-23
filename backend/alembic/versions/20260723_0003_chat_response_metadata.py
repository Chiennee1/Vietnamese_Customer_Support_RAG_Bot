"""Add customer-visible chat response metadata.

Revision ID: 20260723_0003
Revises: 20260723_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260723_0003"
down_revision: str | None = "20260723_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("human_reason", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "suggested_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("ticket_code", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "ticket_code")
    op.drop_column("messages", "suggested_actions")
    op.drop_column("messages", "human_reason")
