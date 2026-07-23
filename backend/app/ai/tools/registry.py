from dataclasses import dataclass

from app.ai.tools.business import (
    OrderStatusTool,
    ProductSearchTool,
    WarrantyStatusTool,
)
from app.ai.tools.knowledge import KnowledgeBaseTool


@dataclass(frozen=True, slots=True)
class SupportToolSet:
    products: ProductSearchTool
    orders: OrderStatusTool
    warranties: WarrantyStatusTool
    knowledge: KnowledgeBaseTool

    @property
    def names(self) -> frozenset[str]:
        return frozenset(
            {
                self.products.name,
                self.orders.name,
                self.warranties.name,
                self.knowledge.name,
            }
        )

