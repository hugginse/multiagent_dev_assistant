"""订单服务：下单 / 支付 / 取消 / 查询。"""

from __future__ import annotations

from orderlib.exceptions import (
    InvalidOrderStateError,
    NotFoundError,
    ValidationError,
)
from orderlib.inventory import Inventory
from orderlib.models import Order, OrderItem, OrderStatus
from orderlib.pricing import grand_total
from orderlib.utils import new_order_id, utc_now_iso


class OrderService:
    """内存版订单服务（演示用，非持久化）。"""

    def __init__(self, inventory: Inventory | None = None) -> None:
        self.inventory = inventory or Inventory()
        self._orders: dict[str, Order] = {}

    def create_order(
        self,
        items: list[OrderItem],
        *,
        discount_code: str | None = None,
        express: bool = False,
    ) -> Order:
        if not items:
            raise ValidationError("order must have at least one item")
        for it in items:
            if not it.sku:
                raise ValidationError("item sku must not be empty")
            if it.quantity <= 0:
                raise ValidationError("item quantity must be positive")
            # 确保 sku 已登记
            self.inventory.get_stock(it.sku)
            self.inventory.reserve(it.sku, it.quantity)

        order = Order(
            id=new_order_id(),
            items=list(items),
            status=OrderStatus.PENDING,
            discount_code=discount_code,
            created_at=utc_now_iso(),
        )
        # 触发定价校验（未知折扣码等）——失败则回滚库存
        try:
            _ = grand_total(items, discount_code, express=express)
        except Exception:
            for it in items:
                self.inventory.release(it.sku, it.quantity)
            raise
        self._orders[order.id] = order
        return order

    def get(self, order_id: str) -> Order:
        if order_id not in self._orders:
            raise NotFoundError(f"order not found: {order_id}")
        return self._orders[order_id]

    def pay(self, order_id: str) -> Order:
        order = self.get(order_id)
        if order.status is not OrderStatus.PENDING:
            raise InvalidOrderStateError(
                f"cannot pay order in status {order.status.value}"
            )
        order.status = OrderStatus.PAID
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.get(order_id)
        if order.status in {OrderStatus.SHIPPED, OrderStatus.CANCELLED}:
            raise InvalidOrderStateError(
                f"cannot cancel order in status {order.status.value}"
            )
        if order.status in {OrderStatus.PENDING, OrderStatus.PAID}:
            # 创建时已预扣；取消（未发货）必须回滚库存
            for it in order.items:
                self.inventory.release(it.sku, it.quantity)
        order.status = OrderStatus.CANCELLED
        return order

    def ship(self, order_id: str) -> Order:
        order = self.get(order_id)
        if order.status is not OrderStatus.PAID:
            raise InvalidOrderStateError(
                f"cannot ship order in status {order.status.value}"
            )
        order.status = OrderStatus.SHIPPED
        return order

    def amount_due_cents(self, order_id: str, *, express: bool = False) -> int:
        order = self.get(order_id)
        return grand_total(order.items, order.discount_code, express=express)

    def list_orders(self, status: OrderStatus | None = None) -> list[Order]:
        orders = list(self._orders.values())
        if status is not None:
            orders = [o for o in orders if o.status is status]
        return orders
