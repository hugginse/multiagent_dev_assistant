"""T108 隐藏：定价常量迁到 constants 后仍可从 pricing 导入。"""
from __future__ import annotations

from orderlib.constants import BASE_SHIPPING_CENTS as C_BASE
from orderlib.constants import FREE_SHIPPING_THRESHOLD_CENTS as C_FREE
from orderlib.pricing import (
    BASE_SHIPPING_CENTS,
    FREE_SHIPPING_THRESHOLD_CENTS,
    calculate_shipping,
)


def test_values_unchanged() -> None:
    assert BASE_SHIPPING_CENTS == 800
    assert FREE_SHIPPING_THRESHOLD_CENTS == 10_000
    assert C_BASE == BASE_SHIPPING_CENTS
    assert C_FREE == FREE_SHIPPING_THRESHOLD_CENTS


def test_behavior_uses_constants() -> None:
    assert calculate_shipping(0) == BASE_SHIPPING_CENTS
    assert calculate_shipping(FREE_SHIPPING_THRESHOLD_CENTS) == 0
