"""订单领域模型。金额单位：分（int）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class OrderItem:
    sku: str
    quantity: int
    unit_price_cents: int

    def line_total_cents(self) -> int:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.unit_price_cents < 0:
            raise ValueError("unit_price_cents must be non-negative")
        return self.quantity * self.unit_price_cents


@dataclass(slots=True)
class Order:
    id: str
    items: list[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    discount_code: str | None = None
    created_at: str = ""

    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)
