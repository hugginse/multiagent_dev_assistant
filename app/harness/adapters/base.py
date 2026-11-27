"""BenchmarkAdapter 接口（architecture.md §6.5）。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.harness.schema import TaskDefinition


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """统一任务加载接口。"""

    name: str

    def load_tasks(self) -> list[TaskDefinition]:
        """返回可被 harness 执行的任务列表。"""
        ...


def get_adapter(name: str, **kwargs: object) -> BenchmarkAdapter:
    """按名取 adapter：local | swe_bench。"""
    from app.harness.adapters.local import LocalSuiteAdapter
    from app.harness.adapters.swe_bench import SWEbenchLiteAdapter

    norm = (name or "local").strip().lower()
    if norm in {"local", "suite"}:
        return LocalSuiteAdapter(**kwargs)  # type: ignore[arg-type]
    if norm in {"swe_bench", "swe", "swebench"}:
        return SWEbenchLiteAdapter(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"未知 adapter: {name!r}（可用: local, swe_bench）")
