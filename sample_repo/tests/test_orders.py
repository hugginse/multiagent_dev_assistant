"""订单服务集成单测。"""

from __future__ import annotations

import pytest

from orderlib import OrderService
from orderlib.exceptions import (
    InvalidOrderStateError,
    NotFoundError,
    ValidationError,
)
from orderlib.inventory import Inventory
from orderlib.models import OrderItem, OrderStatus


@pytest.fixture()
def svc() -> OrderService:
    inv = Inventory({"SKU1": 10, "SKU2": 5})
    return OrderService(inv)


def _item(sku: str = "SKU1", qty: int = 2, price: int = 1000) -> OrderItem:
    return OrderItem(sku=sku, quantity=qty, unit_price_cents=price)


def test_create_and_pay_ship(svc: OrderService) -> None:
    order = svc.create_order([_item()])
    assert order.status is OrderStatus.PENDING
    assert svc.inventory.get_stock("SKU1") == 8

    svc.pay(order.id)
    assert svc.get(order.id).status is OrderStatus.PAID

    svc.ship(order.id)
    assert svc.get(order.id).status is OrderStatus.SHIPPED


def test_cancel_pending_releases_nothing_already_released(svc: OrderService) -> None:
    # pending 时库存已预扣；取消应回滚
    order = svc.create_order([_item(qty=2)])
    assert svc.inventory.get_stock("SKU1") == 8
    svc.cancel(order.id)
    assert svc.get(order.id).status is OrderStatus.CANCELLED
    assert svc.inventory.get_stock("SKU1") == 10


def test_cancel_paid_releases_stock(svc: OrderService) -> None:
    order = svc.create_order([_item(qty=2)])
    svc.pay(order.id)
    svc.cancel(order.id)
    assert svc.inventory.get_stock("SKU1") == 10


def test_cannot_ship_unpaid(svc: OrderService) -> None:
    order = svc.create_order([_item()])
    with pytest.raises(InvalidOrderStateError):
        svc.ship(order.id)


def test_cannot_pay_twice(svc: OrderService) -> None:
    order = svc.create_order([_item()])
    svc.pay(order.id)
    with pytest.raises(InvalidOrderStateError):
        svc.pay(order.id)


def test_create_empty_rejected(svc: OrderService) -> None:
    with pytest.raises(ValidationError):
        svc.create_order([])


def test_unknown_sku_rejected(svc: OrderService) -> None:
    with pytest.raises(NotFoundError):
        svc.create_order([_item(sku="NOPE")])


def test_unknown_discount_rolls_back_stock(svc: OrderService) -> None:
    with pytest.raises(ValidationError):
        svc.create_order([_item()], discount_code="BADCODE")
    assert svc.inventory.get_stock("SKU1") == 10


def test_amount_due(svc: OrderService) -> None:
    order = svc.create_order([_item(qty=1, price=2000)])
    # 2000 < 10000 → +800 shipping
    assert svc.amount_due_cents(order.id) == 2800


def test_list_orders_filter(svc: OrderService) -> None:
    a = svc.create_order([_item()])
    svc.create_order([_item(sku="SKU2")])
    svc.pay(a.id)
    paid = svc.list_orders(status=OrderStatus.PAID)
    assert len(paid) == 1
    assert paid[0].id == a.id
