"""工具函数单测。"""

from __future__ import annotations

import pytest

from orderlib.utils import new_order_id, reset_id_counter, utc_now_iso


def test_new_order_id_format() -> None:
    reset_id_counter()
    a = new_order_id()
    b = new_order_id()
    assert a.startswith("ord-")
    assert a != b


def test_new_order_id_bad_prefix() -> None:
    with pytest.raises(ValueError):
        new_order_id("bad-prefix!")


def test_utc_now_iso_has_tz() -> None:
    s = utc_now_iso()
    assert "T" in s
    assert "+" in s or s.endswith("Z") or "+00:00" in s
