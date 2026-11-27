"""T101 隐藏：折扣码大小写不敏感。"""
from __future__ import annotations

import pytest

from orderlib.exceptions import ValidationError
from orderlib.pricing import discount_amount


def test_lowercase_code() -> None:
    assert discount_amount(1000, "save10") == 100


def test_mixed_case() -> None:
    assert discount_amount(1000, "Save20") == 200


def test_padded_case() -> None:
    assert discount_amount(1000, "  new5  ") == 50


def test_unknown_still_raises() -> None:
    with pytest.raises(ValidationError):
        discount_amount(1000, "save99")
