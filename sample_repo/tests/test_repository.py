"""仓储与常量单测。"""

from __future__ import annotations

import pytest

from orderlib.constants import MAX_ITEMS_PER_ORDER, ORDER_ID_PREFIX
from orderlib.exceptions import NotFoundError
from orderlib.repository import InMemoryRepository


def test_repository_crud() -> None:
    repo: InMemoryRepository[dict] = InMemoryRepository()
    repo.save("a", {"x": 1})
    assert repo.get("a") == {"x": 1}
    assert repo.count() == 1
    repo.delete("a")
    assert repo.count() == 0
    with pytest.raises(NotFoundError):
        repo.get("a")


def test_repository_empty_key() -> None:
    repo: InMemoryRepository[str] = InMemoryRepository()
    with pytest.raises(ValueError):
        repo.save("", "v")


def test_constants() -> None:
    assert MAX_ITEMS_PER_ORDER == 50
    assert ORDER_ID_PREFIX == "ord"
