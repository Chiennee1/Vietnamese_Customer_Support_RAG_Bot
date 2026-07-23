from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.order import OrderStatus
from app.db.models.user import UserRole
from app.db.models.warranty import WarrantyStatus


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    request_id: str
    user_id: UUID
    user_role: UserRole


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductSearchInput(StrictToolInput):
    query: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=100)
    max_price: Decimal | None = Field(default=None, ge=0)
    storage_gb: int | None = Field(default=None, ge=16, le=2048)
    limit: int = Field(default=5, ge=1, le=10)


class ProductItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: UUID
    product_name: str
    brand: str
    sku: str
    model: str
    color: str
    storage_gb: int
    ram_gb: int | None
    current_price: Decimal
    quantity_available: int
    checked_at: datetime


class ProductSearchOutput(BaseModel):
    items: list[ProductItem]


class OrderStatusInput(StrictToolInput):
    order_code: str = Field(
        min_length=6,
        max_length=40,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class OrderLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    serial_number: str | None


class OrderStatusOutput(BaseModel):
    order_code: str
    status: OrderStatus
    total_amount: Decimal
    shipping_tracking_code: str | None
    estimated_delivery_at: datetime | None
    delivered_at: datetime | None
    items: list[OrderLine]
    checked_at: datetime


class WarrantyStatusInput(StrictToolInput):
    identifier: str = Field(
        min_length=4,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class WarrantyStatusOutput(BaseModel):
    serial_number: str
    product_name: str
    starts_on: date
    ends_on: date
    status: WarrantyStatus
    checked_at: datetime


class KnowledgeSearchInput(StrictToolInput):
    query: str = Field(min_length=2, max_length=500)
    category: str | None = Field(default=None, max_length=80)


class CitationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    document_id: UUID
    chunk_id: UUID
    title: str
    version: str
    section_path: list[str]
    page: int | None
    excerpt: str


class KnowledgeSearchOutput(BaseModel):
    evidence: list[str]
    citations: list[CitationOutput]
    insufficient: bool
    conflict: bool
    requires_human: bool
