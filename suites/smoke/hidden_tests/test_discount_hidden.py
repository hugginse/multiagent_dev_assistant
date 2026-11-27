"""T001 隐藏测试：折扣码大小写与未知码。评分阶段注入，Agent 全程不可见。"""

from __future__ import annotations

import pytest

from orderlib.exceptions import ValidationError
from orderlib.models import OrderItem
from orderlib.pricing import discount_amount, grand_total


def test_discount_case_insensitive() -> None:
    assert discount_amount(1000, "SAVE10") == 100
    assert discount_amount(1000, "save10") == 100
    assert discount_amount(1000, "  Save10  ") == 100


def test_unknown_discount_raises() -> None:
    with pytest.raises(ValidationError):
        discount_amount(1000, "NOPE")
    with pytest.raises(ValidationError):
        discount_amount(1000, "save100")


def test_no_code_zero_discount() -> None:
    assert discount_amount(1000, None) == 0
    assert discount_amount(1000, "") == 0


def test_grand_total_case_insensitive() -> None:
    items = [OrderItem(sku="A", quantity=10, unit_price_cents=500)]
    assert grand_total(items, "save10") == grand_total(items, "SAVE10")


def test_discount_never_exceeds_subtotal() -> None:
    # 折扣 100% 上限保护：即使未来加入 100% 码也不得为负
    items = [OrderItem(sku="A", quantity=1, unit_price_cents=100)]
    total = grand_total(items, "SAVE20")
    assert total >= 0
