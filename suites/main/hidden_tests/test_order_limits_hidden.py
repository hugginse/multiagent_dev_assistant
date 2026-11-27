"""T103 隐藏：订单条目/数量上限，不泄漏库存。"""
from __future__ import annotations

import pytest

from orderlib.constants import MAX_ITEMS_PER_ORDER, MAX_QUANTITY_PER_ITEM
from orderlib.exceptions import ValidationError
from orderlib.inventory import Inventory
from orderlib.models import OrderItem
from orderlib.orders import OrderService


def _svc() -> OrderService:
    skus = {f"SKU{i}": 10_000 for i in range(MAX_ITEMS_PER_ORDER + 5)}
    return OrderService(Inventory(skus))


def test_too_many_items() -> None:
    svc = _svc()
    items = [
        OrderItem(sku=f"SKU{i}", quantity=1, unit_price_cents=100)
        for i in range(MAX_ITEMS_PER_ORDER + 1)
    ]
    with pytest.raises(ValidationError):
        svc.create_order(items)
    for i in range(MAX_ITEMS_PER_ORDER + 1):
        assert svc.inventory.get_stock(f"SKU{i}") == 10_000


def test_qty_over_limit() -> None:
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_order(
            [OrderItem(sku="SKU0", quantity=MAX_QUANTITY_PER_ITEM + 1, unit_price_cents=1)]
        )
    assert svc.inventory.get_stock("SKU0") == 10_000


def test_at_limit_ok() -> None:
    svc = _svc()
    items = [
        OrderItem(sku=f"SKU{i}", quantity=1, unit_price_cents=100)
        for i in range(MAX_ITEMS_PER_ORDER)
    ]
    order = svc.create_order(items)
    assert order.total_quantity() == MAX_ITEMS_PER_ORDER
