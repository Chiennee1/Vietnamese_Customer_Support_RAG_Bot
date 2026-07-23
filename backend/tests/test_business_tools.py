from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.ai.tools.business import (
    OrderStatusTool,
    ProductSearchTool,
    WarrantyStatusTool,
)
from app.ai.tools.contracts import (
    OrderStatusInput,
    ProductSearchInput,
    RuntimeContext,
    WarrantyStatusInput,
)
from app.core.errors import AppError
from app.db.models.order import OrderStatus
from app.db.models.user import UserRole
from app.db.models.warranty import WarrantyStatus
from app.repositories.commerce import (
    OrderLineResult,
    OrderLookupResult,
    ProductLookupResult,
    WarrantyLookupResult,
)


class FakeProducts:
    async def search(
        self,
        *,
        query: str,
        brand: str | None,
        max_price: Decimal | None,
        storage_gb: int | None,
        color: str | None,
        limit: int,
    ) -> list[ProductLookupResult]:
        return [
            ProductLookupResult(
                variant_id=uuid4(),
                product_name="Demo Phone",
                brand="Demo",
                sku="DEM-001-1",
                model="DP-001",
                color="Đen",
                storage_gb=128,
                ram_gb=8,
                current_price=Decimal("9990000"),
                quantity_available=4,
                checked_at=datetime(2026, 7, 23, tzinfo=UTC),
            )
        ]


class FakeOrders:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.received_user_id: UUID | None = None

    async def get_owned_order(
        self,
        *,
        order_code: str,
        user_id: UUID,
    ) -> OrderLookupResult | None:
        self.received_user_id = user_id
        if user_id != self.owner_id:
            return None
        return OrderLookupResult(
            order_code=order_code,
            status=OrderStatus.SHIPPING,
            total_amount=Decimal("9990000"),
            shipping_tracking_code="TRACK0001",
            estimated_delivery_at=datetime(2026, 7, 25, tzinfo=UTC),
            delivered_at=None,
            items=[
                OrderLineResult(
                    sku="DEM-001-1",
                    product_name="Demo Phone",
                    quantity=1,
                    unit_price=Decimal("9990000"),
                    serial_number="SN2600000001",
                )
            ],
            checked_at=datetime(2026, 7, 23, tzinfo=UTC),
        )


class FakeWarranties:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id

    async def get_owned_warranty(
        self,
        *,
        identifier: str,
        user_id: UUID,
    ) -> WarrantyLookupResult | None:
        if user_id != self.owner_id:
            return None
        return WarrantyLookupResult(
            serial_number="SN2600000001",
            product_name="Demo Phone",
            starts_on=date(2026, 1, 1),
            ends_on=date(2027, 1, 1),
            status=WarrantyStatus.ACTIVE,
            checked_at=datetime(2026, 7, 23, tzinfo=UTC),
        )


def runtime(user_id: UUID) -> RuntimeContext:
    return RuntimeContext(
        request_id="req-1",
        user_id=user_id,
        user_role=UserRole.CUSTOMER,
    )


def test_tool_schemas_forbid_user_id_sql_and_unknown_fields() -> None:
    schema_text = str(OrderStatusInput.model_json_schema()).lower()

    assert "user_id" not in schema_text
    assert "sql" not in schema_text
    with pytest.raises(ValidationError):
        OrderStatusInput.model_validate({"order_code": "DH2026000001", "user_id": str(uuid4())})


async def test_order_tool_binds_owner_from_runtime_context() -> None:
    owner_id = uuid4()
    repository = FakeOrders(owner_id)
    tool = OrderStatusTool(repository)

    result = await tool.execute(
        OrderStatusInput(order_code="DH2026000001"),
        runtime(owner_id),
    )

    assert repository.received_user_id == owner_id
    assert result.order_code == "DH2026000001"
    assert result.status == OrderStatus.SHIPPING


async def test_order_tool_returns_same_not_found_for_cross_user_lookup() -> None:
    owner_id = uuid4()
    tool = OrderStatusTool(FakeOrders(owner_id))

    with pytest.raises(AppError) as caught:
        await tool.execute(
            OrderStatusInput(order_code="DH2026000001"),
            runtime(uuid4()),
        )

    assert caught.value.code == "ORDER_NOT_FOUND"


async def test_product_and_warranty_tools_return_typed_current_data() -> None:
    owner_id = uuid4()
    products = await ProductSearchTool(FakeProducts()).execute(
        ProductSearchInput(query="Demo Phone"),
        runtime(owner_id),
    )
    warranty = await WarrantyStatusTool(FakeWarranties(owner_id)).execute(
        WarrantyStatusInput(identifier="SN2600000001"),
        runtime(owner_id),
    )

    assert products.items[0].current_price == Decimal("9990000")
    assert products.items[0].quantity_available == 4
    assert warranty.status == WarrantyStatus.ACTIVE
