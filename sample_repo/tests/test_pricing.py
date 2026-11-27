"""定价单测。"""

from __future__ import annotations

import pytest

from orderlib.exceptions import ValidationError
from orderlib.models import OrderItem
from orderlib.pricing import (
    ShippingError,
    calculate_shipping,
    discount_amount,
    grand_total,
    subtotal,
)


def _items() -> list[OrderItem]:
    return [OrderItem(sku="A", quantity=10, unit_price_cents=500)]  # 5000 分


def test_subtotal() -> None:
    assert subtotal(_items()) == 5000


def test_subtotal_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        subtotal([])


def test_discount_unknown_code() -> None:
    with pytest.raises(ValidationError):
        discount_amount(1000, "NOPE")


def test_discount_save10() -> None:
    # 基线只保证规范大写码；大小写不敏感由隐藏测试约束（T001）
    assert discount_amount(1000, "SAVE10") == 100
    assert discount_amount(1000, "NEW5") == 50


def test_shipping_free_over_threshold() -> None:
    assert calculate_shipping(10_000) == 0
    assert calculate_shipping(9_999) == 800


def test_shipping_negative_raises() -> None:
    with pytest.raises(ShippingError):
        calculate_shipping(-1)


def test_grand_total_with_discount_and_ship() -> None:
    # 5000 - 10% (500) = 4500 + ship 800 = 5300
    assert grand_total(_items(), "SAVE10") == 5300
