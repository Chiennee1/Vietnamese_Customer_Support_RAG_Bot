from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.catalog import Inventory, Product, ProductStatus, ProductVariant
from app.db.models.order import Order, OrderItem, OrderStatus
from app.db.models.warranty import Warranty, WarrantyStatus


@dataclass(frozen=True, slots=True)
class ProductLookupResult:
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


@dataclass(frozen=True, slots=True)
class OrderLineResult:
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    serial_number: str | None


@dataclass(frozen=True, slots=True)
class OrderLookupResult:
    order_code: str
    status: OrderStatus
    total_amount: Decimal
    shipping_tracking_code: str | None
    estimated_delivery_at: datetime | None
    delivered_at: datetime | None
    items: list[OrderLineResult]
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class WarrantyLookupResult:
    serial_number: str
    product_name: str
    starts_on: date
    ends_on: date
    status: WarrantyStatus
    checked_at: datetime


class ProductRepository(Protocol):
    async def search(
        self,
        *,
        query: str,
        brand: str | None,
        max_price: Decimal | None,
        storage_gb: int | None,
        limit: int,
    ) -> list[ProductLookupResult]: ...


class OrderRepository(Protocol):
    async def get_owned_order(
        self,
        *,
        order_code: str,
        user_id: UUID,
    ) -> OrderLookupResult | None: ...


class WarrantyRepository(Protocol):
    async def get_owned_warranty(
        self,
        *,
        identifier: str,
        user_id: UUID,
    ) -> WarrantyLookupResult | None: ...


class SqlAlchemyProductRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def search(
        self,
        *,
        query: str,
        brand: str | None,
        max_price: Decimal | None,
        storage_gb: int | None,
        limit: int,
    ) -> list[ProductLookupResult]:
        normalized_query = query.strip()
        escaped_query = (
            normalized_query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        available = func.coalesce(
            func.sum(Inventory.quantity_on_hand - Inventory.quantity_reserved),
            0,
        ).label("quantity_available")
        exact_priority = case(
            (func.lower(ProductVariant.sku) == normalized_query.lower(), 0),
            (func.lower(ProductVariant.model) == normalized_query.lower(), 1),
            else_=2,
        )
        filters = [
            Product.status == ProductStatus.ACTIVE,
            ProductVariant.is_active.is_(True),
            or_(
                ProductVariant.sku.ilike(f"%{escaped_query}%", escape="\\"),
                ProductVariant.model.ilike(f"%{escaped_query}%", escape="\\"),
                Product.name.ilike(f"%{escaped_query}%", escape="\\"),
                Product.description.ilike(f"%{escaped_query}%", escape="\\"),
            ),
        ]
        if brand:
            filters.append(Product.brand.ilike(brand))
        if max_price is not None:
            filters.append(ProductVariant.current_price <= max_price)
        if storage_gb is not None:
            filters.append(ProductVariant.storage_gb == storage_gb)

        statement = (
            select(Product, ProductVariant, available)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
            .where(*filters)
            .group_by(Product.id, ProductVariant.id)
            .order_by(exact_priority, ProductVariant.current_price)
            .limit(limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        checked_at = datetime.now(UTC)
        return [
            ProductLookupResult(
                variant_id=variant.id,
                product_name=product.name,
                brand=product.brand,
                sku=variant.sku,
                model=variant.model,
                color=variant.color,
                storage_gb=variant.storage_gb,
                ram_gb=variant.ram_gb,
                current_price=variant.current_price,
                quantity_available=int(quantity_available),
                checked_at=checked_at,
            )
            for product, variant, quantity_available in rows
        ]


class SqlAlchemyOrderRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_owned_order(
        self,
        *,
        order_code: str,
        user_id: UUID,
    ) -> OrderLookupResult | None:
        async with self.sessions() as session:
            order = await session.scalar(
                select(Order).where(
                    func.upper(Order.order_code) == order_code.upper(),
                    Order.user_id == user_id,
                )
            )
            if order is None:
                return None
            rows = (
                await session.execute(
                    select(OrderItem, ProductVariant, Product)
                    .join(ProductVariant, ProductVariant.id == OrderItem.variant_id)
                    .join(Product, Product.id == ProductVariant.product_id)
                    .where(OrderItem.order_id == order.id)
                    .order_by(OrderItem.created_at)
                )
            ).all()
            return OrderLookupResult(
                order_code=order.order_code,
                status=order.status,
                total_amount=order.total_amount,
                shipping_tracking_code=order.shipping_tracking_code,
                estimated_delivery_at=order.estimated_delivery_at,
                delivered_at=order.delivered_at,
                items=[
                    OrderLineResult(
                        sku=variant.sku,
                        product_name=product.name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        serial_number=item.serial_number,
                    )
                    for item, variant, product in rows
                ],
                checked_at=datetime.now(UTC),
            )


class SqlAlchemyWarrantyRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_owned_warranty(
        self,
        *,
        identifier: str,
        user_id: UUID,
    ) -> WarrantyLookupResult | None:
        statement = (
            select(Warranty, Product)
            .join(OrderItem, OrderItem.id == Warranty.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .join(ProductVariant, ProductVariant.id == OrderItem.variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                Warranty.user_id == user_id,
                or_(
                    func.upper(Warranty.serial_number) == identifier.upper(),
                    func.upper(Order.order_code) == identifier.upper(),
                ),
            )
            .limit(1)
        )
        async with self.sessions() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        warranty, product = row
        return WarrantyLookupResult(
            serial_number=warranty.serial_number,
            product_name=product.name,
            starts_on=warranty.starts_on,
            ends_on=warranty.ends_on,
            status=warranty.status,
            checked_at=datetime.now(UTC),
        )
