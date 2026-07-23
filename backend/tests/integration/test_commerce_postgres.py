import os

import pytest
from pydantic import SecretStr
from sqlalchemy import select

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
        assert owned_order is not None
        assert owned_order.order_code == "DH2026000001"
        assert cross_user_order is None
        assert owned_warranty is not None
        assert owned_warranty.serial_number == "SN2600000001"
        assert cross_user_warranty is None
    finally:
        await database.dispose()

