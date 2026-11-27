"""模型单测。"""

from __future__ import annotations

import pytest

from orderlib.models import Order, OrderItem, OrderStatus


def test_line_total() -> None:
    item = OrderItem(sku="A", quantity=3, unit_price_cents=250)
    assert item.line_total_cents() == 750


def test_line_total_rejects_bad_qty() -> None:
    with pytest.raises(ValueError):
        OrderItem(sku="A", quantity=0, unit_price_cents=1).line_total_cents()


def test_order_status_values() -> None:
    assert OrderStatus.PENDING.value == "pending"
    assert OrderStatus.CANCELLED.value == "cancelled"


def test_order_total_quantity() -> None:
    o = Order(
        id="x",
        items=[
            OrderItem(sku="A", quantity=1, unit_price_cents=1),
            OrderItem(sku="B", quantity=2, unit_price_cents=1),
        ],
    )
    assert o.total_quantity() == 3
    assert o.status is OrderStatus.PENDING
