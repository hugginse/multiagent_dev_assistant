"""T109 隐藏：单笔订单金额上限。"""
from __future__ import annotations

import pytest

from orderlib.exceptions import ValidationError
from orderlib.inventory import Inventory
from orderlib.models import OrderItem
from orderlib.orders import OrderService
from orderlib.pricing import grand_total

CAP = 10_000_000


def test_grand_total_cap_enforced() -> None:
    items = [OrderItem(sku="A", quantity=20, unit_price_cents=1_000_000)]
    with pytest.raises(ValidationError):
        grand_total(items)


def test_create_order_over_cap_no_leak() -> None:
    svc = OrderService(Inventory({"A": 100}))
    items = [OrderItem(sku="A", quantity=20, unit_price_cents=1_000_000)]
    with pytest.raises(ValidationError):
        svc.create_order(items)
    assert svc.inventory.get_stock("A") == 100


def test_under_cap_ok() -> None:
    svc = OrderService(Inventory({"A": 100}))
    items = [OrderItem(sku="A", quantity=1, unit_price_cents=1_000)]
    order = svc.create_order(items)
    assert order is not None
    assert grand_total(items) <= CAP
