"""T104 隐藏：运费多档重构后语义兼容。"""
from __future__ import annotations

import inspect

import pytest

from orderlib.models import OrderItem
from orderlib.pricing import (
    BASE_SHIPPING_CENTS,
    FREE_SHIPPING_THRESHOLD_CENTS,
    ShippingError,
    calculate_shipping,
    grand_total,
)


def test_base_semantics() -> None:
    assert calculate_shipping(0) == BASE_SHIPPING_CENTS
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS - 1) == BASE_SHIPPING_CENTS
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS) == 0
    assert calculate_shipping(999_999) == 0


def test_express_double() -> None:
    assert calculate_shipping(0, express=True) == BASE_SHIPPING_CENTS * 2
    assert (
        calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS, express=True)
        == BASE_SHIPPING_CENTS * 2
    )


def test_negative() -> None:
    with pytest.raises(ShippingError):
        calculate_shipping(-1)


def test_grand_total_compat() -> None:
    items = [OrderItem(sku="A", quantity=1, unit_price_cents=2000)]
    assert grand_total(items) == 2000 + BASE_SHIPPING_CENTS
    big = [OrderItem(sku="A", quantity=10, unit_price_cents=1000)]
    assert grand_total(big) == 10_000


def test_signature_has_express() -> None:
    sig = inspect.signature(calculate_shipping)
    assert "express" in sig.parameters
