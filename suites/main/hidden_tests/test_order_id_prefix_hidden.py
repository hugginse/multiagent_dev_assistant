"""T110 隐藏：订单号前缀。"""
from __future__ import annotations

import re

import pytest

from orderlib.constants import ORDER_ID_PREFIX
from orderlib.utils import new_order_id, reset_id_counter


def test_single_char_prefix_raises() -> None:
    with pytest.raises(ValueError):
        new_order_id("x")


def test_short_prefix_ok_and_format() -> None:
    reset_id_counter()
    oid = new_order_id("ab")
    assert re.fullmatch(r"ab-\d{6}-[0-9a-f]{8}", oid), oid


def test_counter_resets() -> None:
    reset_id_counter()
    a = new_order_id("ord")
    reset_id_counter()
    b = new_order_id("ord")
    assert a.split("-")[1] == b.split("-")[1] == "000001"


def test_default_prefix_from_constants() -> None:
    assert ORDER_ID_PREFIX == "ord"
    reset_id_counter()
    assert new_order_id(ORDER_ID_PREFIX).startswith("ord-")
