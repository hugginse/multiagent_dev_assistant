"""极简内存仓储（演示分层，供 refactor 任务使用）。"""

from __future__ import annotations

from typing import Generic, TypeVar

from orderlib.exceptions import NotFoundError

T = TypeVar("T")


class InMemoryRepository(Generic[T]):
    """按 str key 存取的通用内存仓储。"""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def save(self, key: str, item: T) -> T:
        if not key:
            raise ValueError("key must not be empty")
        self._items[key] = item
        return item

    def get(self, key: str) -> T:
        if key not in self._items:
            raise NotFoundError(f"key not found: {key}")
        return self._items[key]

    def delete(self, key: str) -> None:
        if key not in self._items:
            raise NotFoundError(f"key not found: {key}")
        del self._items[key]

    def all(self) -> list[T]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)
