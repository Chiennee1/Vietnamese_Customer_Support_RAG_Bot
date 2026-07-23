import os

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models.user import User
from app.db.session import Database
from app.repositories.commerce import (
    SqlAlchemyOrderRepository,
    SqlAlchemyProductRepository,
    SqlAlchemyWarrantyRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_commerce_repositories_enforce_owner_and_return_live_data() -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    products = SqlAlchemyProductRepository(database.sessions)
    orders = SqlAlchemyOrderRepository(database.sessions)
    warranties = SqlAlchemyWarrantyRepository(database.sessions)

    try:
        async with database.sessions() as session:
            owner = await session.scalar(
                select(User).where(User.email == "customer0006@example.test")
            )
            other = await session.scalar(
                select(User).where(User.email == "customer0007@example.test")
            )
        assert owner is not None
        assert other is not None

        product_results = await products.search(
            query="APP-001-1",
            brand=None,
            max_price=None,
            storage_gb=None,
            color=None,
            limit=5,
        )
        natural_product_results = await products.search(
            query="Samsung Demo Phone 2 bản 256 GB dưới 20 triệu còn hàng?",
            brand="Samsung",
            max_price=None,
            storage_gb=256,
            color=None,
            limit=5,
        )
        brand_product_results = await products.search(
            query="Điện thoại Samsung nào đang còn hàng?",
            brand="Samsung",
            max_price=None,
            storage_gb=None,
            color=None,
            limit=5,
        )
        alias_product_results = await products.search(
            query="Giá điện thoại iPhone hiện tại bao nhiêu?",
            brand="Apple",
            max_price=None,
            storage_gb=None,
            color=None,
            limit=5,
        )
        color_product_results = await products.search(
            query="Apple Demo Phone 1 bản 128 GB màu đen",
            brand="Apple",
            max_price=None,
            storage_gb=128,
            color="Đen",
            limit=5,
        )
        owned_order = await orders.get_owned_order(
            order_code="DH2026000001",
            user_id=owner.id,
        )
        cross_user_order = await orders.get_owned_order(
            order_code="DH2026000001",
            user_id=other.id,
        )
        owned_warranty = await warranties.get_owned_warranty(
            identifier="SN2600000001",
            user_id=owner.id,
        )
        cross_user_warranty = await warranties.get_owned_warranty(
            identifier="SN2600000001",
            user_id=other.id,
        )

        assert product_results[0].sku == "APP-001-1"
        assert product_results[0].quantity_available >= 0
        assert natural_product_results[0].sku == "SAM-002-2"
        assert brand_product_results
        assert all(item.brand == "Samsung" for item in brand_product_results)
        assert alias_product_results
        assert all(item.brand == "Apple" for item in alias_product_results)
        assert color_product_results[0].sku == "APP-001-1"
        assert owned_order is not None
        assert owned_order.order_code == "DH2026000001"
        assert cross_user_order is None
        assert owned_warranty is not None
        assert owned_warranty.serial_number == "SN2600000001"
        assert cross_user_warranty is None
    finally:
        await database.dispose()


@pytest.mark.skipif(
    "TEST_AGENT_DATABASE_URL" not in os.environ,
    reason="TEST_AGENT_DATABASE_URL is required",
)
async def test_agent_database_role_is_read_only() -> None:
    settings = Settings()
    database = Database(
        settings,
        database_url=os.environ["TEST_AGENT_DATABASE_URL"],
    )
    try:
        async with database.sessions() as session:
            identity = await session.scalar(text("SELECT current_user"))
            product_count = await session.scalar(text("SELECT count(*) FROM products"))
            can_update = await session.scalar(
                text(
                    "SELECT has_table_privilege("
                    "current_user, 'products', 'UPDATE'"
                    ")"
                )
            )
            can_create = await session.scalar(
                text(
                    "SELECT has_schema_privilege("
                    "current_user, 'public', 'CREATE'"
                    ")"
                )
            )
        assert identity == "app_agent"
        assert product_count == 100
        assert can_update is False
        assert can_create is False
    finally:
        await database.dispose()
