"""T105 隐藏：list_orders 状态过滤。"""
from __future__ import annotations

from orderlib.inventory import Inventory
from orderlib.models import OrderItem, OrderStatus
from orderlib.orders import OrderService


def _svc() -> OrderService:
    return OrderService(Inventory({"SKU1": 10, "SKU2": 10}))


def _item(qty: int = 1) -> OrderItem:
    return OrderItem(sku="SKU1", quantity=qty, unit_price_cents=100)


def test_filter_none_returns_all() -> None:
    svc = _svc()
    svc.create_order([_item()])
    svc.create_order([_item()])
    assert len(svc.list_orders()) == 2


def test_filter_by_status() -> None:
    svc = _svc()
    a = svc.create_order([_item()])
    b = svc.create_order([_item()])
    svc.pay(a.id)
    paid = svc.list_orders(status=OrderStatus.PAID)
    assert [o.id for o in paid] == [a.id]
    pending = svc.list_orders(status=OrderStatus.PENDING)
    assert [o.id for o in pending] == [b.id]


def test_filter_empty() -> None:
    svc = _svc()
    assert svc.list_orders(status=OrderStatus.SHIPPED) == []
