"""T002 隐藏测试：订单条目数与数量上限。评分阶段注入。"""

from __future__ import annotations

import pytest

from orderlib.constants import MAX_ITEMS_PER_ORDER, MAX_QUANTITY_PER_ITEM
from orderlib.exceptions import ValidationError
from orderlib.inventory import Inventory
from orderlib.models import OrderItem
from orderlib.orders import OrderService
from orderlib.pricing import subtotal


def _svc() -> OrderService:
    skus = {f"SKU{i}": 10_000 for i in range(MAX_ITEMS_PER_ORDER + 5)}
    return OrderService(Inventory(skus))


def test_too_many_items_rejected() -> None:
    svc = _svc()
    items = [
        OrderItem(sku=f"SKU{i}", quantity=1, unit_price_cents=100)
        for i in range(MAX_ITEMS_PER_ORDER + 1)
    ]
    with pytest.raises(ValidationError):
        svc.create_order(items)
    # 不得泄漏库存：全部应仍为满仓
    inv = svc.inventory
    for i in range(MAX_ITEMS_PER_ORDER + 1):
        assert inv.get_stock(f"SKU{i}") == 10_000


def test_exactly_max_items_allowed() -> None:
    svc = _svc()
    items = [
        OrderItem(sku=f"SKU{i}", quantity=1, unit_price_cents=100)
        for i in range(MAX_ITEMS_PER_ORDER)
    ]
    order = svc.create_order(items)
    assert order.total_quantity() == MAX_ITEMS_PER_ORDER


def test_quantity_per_item_limit() -> None:
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_order(
            [OrderItem(sku="SKU0", quantity=MAX_QUANTITY_PER_ITEM + 1, unit_price_cents=1)]
        )
    assert svc.inventory.get_stock("SKU0") == 10_000


def test_validation_before_reserve_for_item_count() -> None:
    """条目数超限时，第一件也不应被扣减（校验先于扣减）。"""
    svc = _svc()
    items = [
        OrderItem(sku=f"SKU{i}", quantity=1, unit_price_cents=100)
        for i in range(MAX_ITEMS_PER_ORDER + 1)
    ]
    with pytest.raises(ValidationError):
        svc.create_order(items)
    assert svc.inventory.get_stock("SKU0") == 10_000
    assert subtotal([items[0]]) == 100
