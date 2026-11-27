"""T003 隐藏测试：运费多档重构后的兼容与扩展。评分阶段注入。"""

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


def test_base_shipping_semantics_preserved() -> None:
    assert calculate_shipping(0) == BASE_SHIPPING_CENTS
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS - 1) == BASE_SHIPPING_CENTS
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS) == 0
    assert calculate_shipping(999_999) == 0


def test_express_still_costs_double_base() -> None:
    assert calculate_shipping(0, express=True) == BASE_SHIPPING_CENTS * 2
    # express 即使满额也不包邮
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS, express=True) == BASE_SHIPPING_CENTS * 2


def test_negative_raises_shipping_error() -> None:
    with pytest.raises(ShippingError):
        calculate_shipping(-1)


def test_grand_total_shipping_regression() -> None:
    items = [OrderItem(sku="A", quantity=1, unit_price_cents=2000)]
    assert grand_total(items) == 2000 + BASE_SHIPPING_CENTS
    items_big = [OrderItem(sku="A", quantity=10, unit_price_cents=1000)]
    assert grand_total(items_big) == 10_000  # 满额包邮


def test_calculate_shipping_signature_still_accepts_express_kw() -> None:
    sig = inspect.signature(calculate_shipping)
    assert "express" in sig.parameters
    assert sig.parameters["express"].kind is inspect.Parameter.KEYWORD_ONLY
