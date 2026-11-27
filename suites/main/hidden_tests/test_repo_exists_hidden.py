"""T107 隐藏：InMemoryRepository.exists。"""
from __future__ import annotations

import pytest

from orderlib.repository import InMemoryRepository


def test_exists_true_false() -> None:
    repo: InMemoryRepository[str] = InMemoryRepository()
    assert repo.exists("a") is False
    repo.save("a", "x")
    assert repo.exists("a") is True


def test_exists_empty_key() -> None:
    repo: InMemoryRepository[str] = InMemoryRepository()
    with pytest.raises(ValueError):
        repo.exists("")


def test_exists_after_delete() -> None:
    repo: InMemoryRepository[int] = InMemoryRepository()
    repo.save("k", 1)
    repo.delete("k")
    assert repo.exists("k") is False
