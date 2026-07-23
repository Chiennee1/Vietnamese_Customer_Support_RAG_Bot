"""Create the production-oriented core schema.

Revision ID: 20260723_0001
Revises:
"""
from collections.abc import Sequence
from typing import Any

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260723_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "role IN ('customer','support','admin')",
            name="ck_users_user_role",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "products",
        uuid_pk(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="ck_products_product_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_brand", "products", ["brand"])

    op.create_table(
        "product_variants",
        uuid_pk(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("color", sa.String(80), nullable=False),
        sa.Column("storage_gb", sa.Integer(), nullable=False),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "storage_gb > 0",
            name="ck_product_variants_storage_positive",
        ),
        sa.CheckConstraint(
            "current_price >= 0",
            name="ck_product_variants_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_variants_product_id_products",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_variants"),
        sa.UniqueConstraint("sku", name="uq_product_variants_sku"),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index("ix_product_variants_sku", "product_variants", ["sku"])
    op.create_index("ix_product_variants_model", "product_variants", ["model"])

    op.create_table(
        "inventory",
        uuid_pk(),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("location_code", sa.String(40), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "quantity_on_hand >= 0",
            name="ck_inventory_on_hand_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity_reserved >= 0",
            name="ck_inventory_reserved_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="ck_inventory_reserved_within_on_hand",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name="fk_inventory_variant_id_product_variants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inventory"),
        sa.UniqueConstraint(
            "variant_id",
            "location_code",
            name="uq_inventory_variant_id",
        ),
    )
    op.create_index("ix_inventory_variant_id", "inventory", ["variant_id"])

    op.create_table(
        "orders",
        uuid_pk(),
        sa.Column("order_code", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("shipping_address_masked", sa.String(255), nullable=False),
        sa.Column("shipping_tracking_code", sa.String(100), nullable=True),
        sa.Column("estimated_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','packing','shipping','delivered','cancelled')",
            name="ck_orders_order_status",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_orders_total_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_orders_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("order_code", name="uq_orders_order_code"),
    )
    op.create_index("ix_orders_order_code", "orders", ["order_code"])
    op.create_index("ix_orders_user_id", "orders", ["user_id"])

    op.create_table(
        "order_items",
        uuid_pk(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("serial_number", sa.String(100), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_order_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="ck_order_items_unit_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_items_order_id_orders",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name="fk_order_items_variant_id_product_variants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.UniqueConstraint("serial_number", name="uq_order_items_serial_number"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_variant_id", "order_items", ["variant_id"])
    op.create_index("ix_order_items_serial_number", "order_items", ["serial_number"])

    op.create_table(
        "warranties",
        uuid_pk(),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("serial_number", sa.String(100), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('active','expired','void','pending_review')",
            name="ck_warranties_warranty_status",
        ),
        sa.CheckConstraint(
            "ends_on >= starts_on",
            name="ck_warranties_valid_date_range",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name="fk_warranties_order_item_id_order_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_warranties_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warranties"),
        sa.UniqueConstraint("order_item_id", name="uq_warranties_order_item_id"),
        sa.UniqueConstraint("serial_number", name="uq_warranties_serial_number"),
    )
    op.create_index("ix_warranties_order_item_id", "warranties", ["order_item_id"])
    op.create_index("ix_warranties_user_id", "warranties", ["user_id"])
    op.create_index("ix_warranties_serial_number", "warranties", ["serial_number"])

    op.create_table(
        "knowledge_documents",
        uuid_pk(),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('uploaded','processing','ready','published','archived','failed')",
            name="ck_knowledge_documents_document_status",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_knowledge_documents_uploaded_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_documents"),
        sa.UniqueConstraint(
            "checksum",
            "version",
            name="uq_knowledge_documents_checksum",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_checksum",
        "knowledge_documents",
        ["checksum"],
    )
    op.create_index(
        "ix_knowledge_documents_status",
        "knowledge_documents",
        ["status"],
    )
    op.create_index(
        "ix_knowledge_documents_effective_from",
        "knowledge_documents",
        ["effective_from"],
    )
    op.create_index(
        "ix_knowledge_documents_effective_to",
        "knowledge_documents",
        ["effective_to"],
    )

    op.create_table(
        "knowledge_chunks",
        uuid_pk(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_normalized", sa.Text(), nullable=False),
        sa.Column("section_path", postgresql.JSONB(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunks_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name="ck_knowledge_chunks_token_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name="fk_knowledge_chunks_document_id_knowledge_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_id",
        ),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    op.create_table(
        "conversations",
        uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_conversations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "messages",
        uuid_pk(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(60), nullable=True),
        sa.Column("route", sa.String(30), nullable=True),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("requires_human", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "role IN ('user','assistant')",
            name="ck_messages_message_role",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "tool_executions",
        uuid_pk(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("safe_metadata", postgresql.JSONB(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('success','failed','timeout')",
            name="ck_tool_executions_tool_execution_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_tool_executions_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_tool_executions_message_id_messages",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_executions"),
    )
    op.create_index(
        "ix_tool_executions_conversation_id",
        "tool_executions",
        ["conversation_id"],
    )

    op.create_table(
        "support_tickets",
        uuid_pk(),
        sa.Column("ticket_code", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "severity IN ('normal','high','critical')",
            name="ck_support_tickets_ticket_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open','in_review','resolved')",
            name="ck_support_tickets_ticket_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_support_tickets_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_support_tickets_conversation_id_conversations",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_tickets"),
        sa.UniqueConstraint("ticket_code", name="uq_support_tickets_ticket_code"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_support_tickets_idempotency_key",
        ),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])

    op.create_table(
        "feedback",
        uuid_pk(),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "rating IN ('positive','negative')",
            name="ck_feedback_feedback_rating",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_feedback_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_feedback_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_feedback_message_id"),
    )
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"])
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    for table in (
        "feedback",
        "support_tickets",
        "tool_executions",
        "messages",
        "conversations",
        "knowledge_chunks",
        "knowledge_documents",
        "warranties",
        "order_items",
        "orders",
        "inventory",
        "product_variants",
        "products",
        "users",
    ):
        op.drop_table(table)
