"""库存：扣减与回滚。"""

from __future__ import annotations

from orderlib.exceptions import InsufficientStockError, NotFoundError, ValidationError


class Inventory:
    """sku -> 可用数量。"""

    def __init__(self, stock: dict[str, int] | None = None) -> None:
        self._stock: dict[str, int] = {}
        if stock:
            for sku, qty in stock.items():
                self.set_stock(sku, qty)

    def set_stock(self, sku: str, quantity: int) -> None:
        if not sku:
            raise ValidationError("sku must not be empty")
        if quantity < 0:
            raise ValidationError("quantity must be non-negative")
        self._stock[sku] = quantity

    def get_stock(self, sku: str) -> int:
        if sku not in self._stock:
            raise NotFoundError(f"unknown sku: {sku}")
        return self._stock[sku]

    def has(self, sku: str) -> bool:
        return sku in self._stock

    def reserve(self, sku: str, quantity: int) -> None:
        """扣减库存；不足抛 InsufficientStockError（已知 sku）。"""
        if quantity <= 0:
            raise ValidationError("quantity must be positive")
        if sku not in self._stock:
            raise NotFoundError(f"unknown sku: {sku}")
        if self._stock[sku] < quantity:
            raise InsufficientStockError(
                f"sku {sku}: have {self._stock[sku]}, need {quantity}"
            )
        self._stock[sku] -= quantity

    def release(self, sku: str, quantity: int) -> None:
        """回滚库存（取消订单用）。"""
        if quantity <= 0:
            raise ValidationError("quantity must be positive")
        if sku not in self._stock:
            raise NotFoundError(f"unknown sku: {sku}")
        self._stock[sku] += quantity

    def snapshot(self) -> dict[str, int]:
        return dict(self._stock)
