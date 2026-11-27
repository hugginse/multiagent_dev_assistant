"""T106 隐藏：取消回滚库存。"""
from __future__ import annotations

import pytest

from orderlib.exceptions import InvalidOrderStateError
from orderlib.inventory import Inventory
from orderlib.models import OrderItem, OrderStatus
from orderlib.orders import OrderService


def _svc() -> OrderService:
    return OrderService(Inventory({"SKU1": 10}))


def test_cancel_pending_releases() -> None:
    svc = _svc()
    o = svc.create_order([OrderItem(sku="SKU1", quantity=4, unit_price_cents=100)])
    assert svc.inventory.get_stock("SKU1") == 6
    svc.cancel(o.id)
    assert svc.inventory.get_stock("SKU1") == 10
    assert svc.get(o.id).status is OrderStatus.CANCELLED


def test_cancel_paid_releases() -> None:
    svc = _svc()
    o = svc.create_order([OrderItem(sku="SKU1", quantity=3, unit_price_cents=100)])
    svc.pay(o.id)
    svc.cancel(o.id)
    assert svc.inventory.get_stock("SKU1") == 10


def test_cancel_shipped_raises() -> None:
    svc = _svc()
    o = svc.create_order([OrderItem(sku="SKU1", quantity=1, unit_price_cents=100)])
    svc.pay(o.id)
    svc.ship(o.id)
    with pytest.raises(InvalidOrderStateError):
        svc.cancel(o.id)
    assert svc.inventory.get_stock("SKU1") == 9
