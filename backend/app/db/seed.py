import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.catalog import (
    Inventory,
    Product,
    ProductStatus,
    ProductVariant,
)
from app.db.models.order import Order, OrderItem, OrderStatus
from app.db.models.ticket import (
    SupportTicket,
    TicketSeverity,
    TicketStatus,
)
from app.db.models.user import User, UserRole
from app.db.models.warranty import Warranty, WarrantyStatus
from app.db.session import Database
from app.services.auth import PASSWORD_HASH

BRANDS = ("Apple", "Samsung", "Xiaomi", "OPPO", "Google")
COLORS = ("Đen", "Trắng", "Xanh", "Tím", "Titan tự nhiên")
STORAGE_OPTIONS = (128, 256, 512)
BASE_DATE = date(2026, 7, 23)


@dataclass(slots=True)
class SyntheticDataset:
    users: list[User]
    products: list[Product]
    variants: list[ProductVariant]
    inventory: list[Inventory]
    orders: list[Order]
    order_items: list[OrderItem]
    warranties: list[Warranty]
    tickets: list[SupportTicket]


def stable_uuid(seed: int, entity: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"support-rag:{seed}:{entity}:{index}")


def build_synthetic_dataset(seed: int = 20260723) -> SyntheticDataset:
    rng = random.Random(seed)
    shared_password_hash = PASSWORD_HASH.hash("Demo-customer-2026")

    users = [
        User(
            id=stable_uuid(seed, "user", index),
            email=f"customer{index:04d}@example.test",
            full_name=f"Khách hàng Demo {index:04d}",
            password_hash=shared_password_hash,
            role=(
                UserRole.ADMIN
                if index == 0
                else UserRole.SUPPORT
                if index < 6
                else UserRole.CUSTOMER
            ),
            is_active=index != 499,
        )
        for index in range(500)
    ]

    products: list[Product] = []
    variants: list[ProductVariant] = []
    inventory: list[Inventory] = []
    for product_index in range(100):
        brand = BRANDS[product_index % len(BRANDS)]
        product_id = stable_uuid(seed, "product", product_index)
        product = Product(
            id=product_id,
            name=f"{brand} Demo Phone {product_index + 1}",
            brand=brand,
            description=(
                f"Điện thoại {brand} dùng cho bộ dữ liệu synthetic, "
                "không đại diện cho sản phẩm thương mại thật."
            ),
            status=(ProductStatus.ARCHIVED if product_index >= 95 else ProductStatus.ACTIVE),
        )
        products.append(product)
        for variant_offset in range(3):
            variant_index = product_index * 3 + variant_offset
            variant_id = stable_uuid(seed, "variant", variant_index)
            price = Decimal(4_000_000 + product_index * 175_000 + variant_offset * 900_000)
            variant = ProductVariant(
                id=variant_id,
                product_id=product_id,
                sku=f"{brand[:3].upper()}-{product_index + 1:03d}-{variant_offset + 1}",
                model=f"DP-{product_index + 1:03d}",
                color=COLORS[(product_index + variant_offset) % len(COLORS)],
                storage_gb=STORAGE_OPTIONS[variant_offset],
                ram_gb=(6, 8, 12)[variant_offset],
                current_price=price,
                is_active=product.status == ProductStatus.ACTIVE,
            )
            variants.append(variant)
            for location_offset, location_code in enumerate(("HCM-01", "HN-01")):
                inventory.append(
                    Inventory(
                        id=stable_uuid(
                            seed,
                            "inventory",
                            variant_index * 2 + location_offset,
                        ),
                        variant_id=variant_id,
                        location_code=location_code,
                        quantity_on_hand=(quantity_on_hand := rng.randint(0, 40)),
                        quantity_reserved=rng.randint(0, min(5, quantity_on_hand)),
                    )
                )

    order_statuses = list(OrderStatus)
    orders: list[Order] = []
    order_items: list[OrderItem] = []
    for order_index in range(1_000):
        user = users[6 + order_index % 493]
        variant = variants[order_index % len(variants)]
        order_id = stable_uuid(seed, "order", order_index)
        order_status = order_statuses[order_index % len(order_statuses)]
        orders.append(
            Order(
                id=order_id,
                order_code=f"DH2026{order_index + 1:06d}",
                user_id=user.id,
                status=order_status,
                total_amount=variant.current_price,
                shipping_address_masked=f"***, Quận {(order_index % 12) + 1}, TP.HCM",
                shipping_tracking_code=(
                    f"TRACK{order_index + 1:08d}"
                    if order_status in {OrderStatus.SHIPPING, OrderStatus.DELIVERED}
                    else None
                ),
                estimated_delivery_at=(
                    datetime(2026, 7, 24, tzinfo=UTC) + timedelta(days=order_index % 7)
                    if order_status in {OrderStatus.CONFIRMED, OrderStatus.SHIPPING}
                    else None
                ),
                delivered_at=(
                    datetime(2026, 7, 20, tzinfo=UTC) - timedelta(days=order_index % 30)
                    if order_status == OrderStatus.DELIVERED
                    else None
                ),
            )
        )
        serial = f"SN26{order_index + 1:08d}"
        order_items.append(
            OrderItem(
                id=stable_uuid(seed, "order-item", order_index),
                order_id=order_id,
                variant_id=variant.id,
                quantity=1,
                unit_price=variant.current_price,
                serial_number=serial,
            )
        )

    warranty_statuses = list(WarrantyStatus)
    warranties: list[Warranty] = []
    for warranty_index in range(600):
        order = orders[warranty_index]
        item = order_items[warranty_index]
        warranty_status = warranty_statuses[warranty_index % len(warranty_statuses)]
        starts_on = BASE_DATE - timedelta(days=365 + warranty_index % 180)
        ends_on = (
            BASE_DATE + timedelta(days=180)
            if warranty_status == WarrantyStatus.ACTIVE
            else BASE_DATE - timedelta(days=30)
            if warranty_status == WarrantyStatus.EXPIRED
            else BASE_DATE + timedelta(days=90)
        )
        warranties.append(
            Warranty(
                id=stable_uuid(seed, "warranty", warranty_index),
                order_item_id=item.id,
                user_id=order.user_id,
                serial_number=item.serial_number or "",
                starts_on=starts_on,
                ends_on=ends_on,
                status=warranty_status,
            )
        )

    severities = list(TicketSeverity)
    tickets = [
        SupportTicket(
            id=stable_uuid(seed, "ticket", index),
            ticket_code=f"TK2026{index + 1:06d}",
            user_id=users[6 + index % 493].id,
            conversation_id=None,
            subject=f"Yêu cầu hỗ trợ synthetic {index + 1}",
            category=("delivery", "warranty", "product")[index % 3],
            summary=(
                "Tình huống giả lập để kiểm thử quy trình CSKH; không chứa dữ liệu khách hàng thật."
            ),
            severity=severities[index % len(severities)],
            status=TicketStatus.OPEN,
            idempotency_key=f"seed-ticket-{index + 1}",
        )
        for index in range(200)
    ]

    return SyntheticDataset(
        users=users,
        products=products,
        variants=variants,
        inventory=inventory,
        orders=orders,
        order_items=order_items,
        warranties=warranties,
        tickets=tickets,
    )


async def seed_database(seed: int = 20260723) -> None:
    database = Database(get_settings())
    try:
        async with database.sessions() as session:
            marker = await session.scalar(
                select(User.id).where(User.email == "customer0000@example.test")
            )
            if marker is not None:
                return
            dataset = build_synthetic_dataset(seed)
            session.add_all(dataset.users)
            session.add_all(dataset.products)
            await session.flush()
            session.add_all(dataset.variants)
            await session.flush()
            session.add_all(dataset.inventory)
            session.add_all(dataset.orders)
            await session.flush()
            session.add_all(dataset.order_items)
            await session.flush()
            session.add_all(dataset.warranties)
            session.add_all(dataset.tickets)
            await session.commit()
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(seed_database())
