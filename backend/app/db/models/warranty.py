from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WarrantyStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    VOID = "void"
    PENDING_REVIEW = "pending_review"


class Warranty(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "warranties"
    __table_args__ = (
        UniqueConstraint("order_item_id"),
        UniqueConstraint("serial_number"),
        CheckConstraint("ends_on >= starts_on", name="valid_date_range"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    serial_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[WarrantyStatus] = mapped_column(
        Enum(
            WarrantyStatus,
            native_enum=False,
            length=30,
            values_callable=lambda members: [member.value for member in members],
            create_constraint=True,
            name="warranty_status",
        ),
        nullable=False,
    )
