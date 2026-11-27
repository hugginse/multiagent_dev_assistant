"""库存单测。"""

from __future__ import annotations

import pytest

from orderlib.exceptions import InsufficientStockError, NotFoundError, ValidationError
from orderlib.inventory import Inventory


def test_reserve_and_release() -> None:
    inv = Inventory({"A": 5})
    inv.reserve("A", 3)
    assert inv.get_stock("A") == 2
    inv.release("A", 3)
    assert inv.get_stock("A") == 5


def test_insufficient_stock() -> None:
    inv = Inventory({"A": 1})
    with pytest.raises(InsufficientStockError):
        inv.reserve("A", 2)


def test_unknown_sku() -> None:
    inv = Inventory()
    with pytest.raises(NotFoundError):
        inv.get_stock("ZZ")
    with pytest.raises(NotFoundError):
        inv.reserve("ZZ", 1)


def test_set_stock_validation() -> None:
    inv = Inventory()
    with pytest.raises(ValidationError):
        inv.set_stock("A", -1)
    with pytest.raises(ValidationError):
        inv.set_stock("", 1)
