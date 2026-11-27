"""T102 隐藏：运费规则。"""
from __future__ import annotations

import pytest

from orderlib.pricing import (
    BASE_SHIPPING_CENTS,
    FREE_SHIPPING_THRESHOLD_CENTS,
    ShippingError,
    calculate_shipping,
)


def test_negative_raises() -> None:
    with pytest.raises(ShippingError):
        calculate_shipping(-1)


def test_express_double_even_over_threshold() -> None:
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS, express=True) == BASE_SHIPPING_CENTS * 2


def test_free_shipping_at_threshold() -> None:
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS) == 0


def test_base_below_threshold() -> None:
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS - 1) == BASE_SHIPPING_CENTS
