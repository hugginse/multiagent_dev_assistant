"""T112 隐藏：register_discount_code。"""
from __future__ import annotations

import pytest

from orderlib.exceptions import ValidationError
from orderlib.pricing import DISCOUNT_CODES, discount_amount, register_discount_code


def test_register_and_use() -> None:
    register_discount_code("bronze5", 5)
    assert discount_amount(1000, "bronze5") == 50
    assert discount_amount(1000, "BRONZE5") == 50


def test_register_invalid_percent() -> None:
    with pytest.raises(ValueError):
        register_discount_code("bad0", 0)
    with pytest.raises(ValueError):
        register_discount_code("bad101", 101)


def test_register_normalizes_code() -> None:
    register_discount_code("  silver15  ", 15)
    assert discount_amount(1000, "silver15") == 150
    assert "SILVER15" in DISCOUNT_CODES


def test_default_codes_still_work() -> None:
    assert discount_amount(1000, "SAVE10") == 100
    with pytest.raises(ValidationError):
        discount_amount(1000, "nope")
