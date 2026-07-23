from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus,
            native_enum=False,
            length=20,
            values_callable=lambda members: [member.value for member in members],
            create_constraint=True,
            name="product_status",
        ),
        nullable=False,
        default=ProductStatus.ACTIVE,
    )


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("sku"),
        CheckConstraint("storage_gb > 0", name="storage_positive"),
        CheckConstraint("current_price >= 0", name="price_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    color: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    ram_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Inventory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("variant_id", "location_code"),
        CheckConstraint("quantity_on_hand >= 0", name="on_hand_nonnegative"),
        CheckConstraint("quantity_reserved >= 0", name="reserved_nonnegative"),
        CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="reserved_within_on_hand",
        ),
    )

    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_code: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
