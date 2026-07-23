from app.ai.tools.contracts import (
    OrderStatusInput,
    OrderStatusOutput,
    ProductItem,
    ProductSearchInput,
    ProductSearchOutput,
    RuntimeContext,
    WarrantyStatusInput,
    WarrantyStatusOutput,
)
from app.core.errors import AppError
from app.repositories.commerce import (
    OrderRepository,
    ProductRepository,
    WarrantyRepository,
)


class ProductSearchTool:
    name = "search_products"

    def __init__(self, products: ProductRepository) -> None:
        self.products = products

    async def execute(
        self,
        payload: ProductSearchInput,
        context: RuntimeContext,
    ) -> ProductSearchOutput:
        del context
        items = await self.products.search(
            query=payload.query,
            brand=payload.brand,
            max_price=payload.max_price,
            storage_gb=payload.storage_gb,
            color=payload.color,
            limit=payload.limit,
        )
        if not items:
            raise AppError(
                code="PRODUCT_NOT_FOUND",
                message="Không tìm thấy sản phẩm trong dữ liệu hiện tại.",
                status_code=404,
            )
        return ProductSearchOutput(items=[ProductItem.model_validate(item) for item in items])


class OrderStatusTool:
    name = "get_order_status"

    def __init__(self, orders: OrderRepository) -> None:
        self.orders = orders

    async def execute(
        self,
        payload: OrderStatusInput,
        context: RuntimeContext,
    ) -> OrderStatusOutput:
        order = await self.orders.get_owned_order(
            order_code=payload.order_code,
            user_id=context.user_id,
        )
        if order is None:
            raise AppError(
                code="ORDER_NOT_FOUND",
                message="Không tìm thấy đơn hàng trong dữ liệu bạn có quyền truy cập.",
                status_code=404,
            )
        return OrderStatusOutput.model_validate(order, from_attributes=True)


class WarrantyStatusTool:
    name = "check_warranty"

    def __init__(self, warranties: WarrantyRepository) -> None:
        self.warranties = warranties

    async def execute(
        self,
        payload: WarrantyStatusInput,
        context: RuntimeContext,
    ) -> WarrantyStatusOutput:
        warranty = await self.warranties.get_owned_warranty(
            identifier=payload.identifier,
            user_id=context.user_id,
        )
        if warranty is None:
            raise AppError(
                code="WARRANTY_NOT_FOUND",
                message="Không tìm thấy bảo hành trong dữ liệu bạn có quyền truy cập.",
                status_code=404,
            )
        return WarrantyStatusOutput.model_validate(warranty, from_attributes=True)
