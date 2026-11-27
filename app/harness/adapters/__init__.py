"""Benchmark adapters：local 自建套件 + 公开 benchmark 子集。"""

from app.harness.adapters.base import BenchmarkAdapter, get_adapter
from app.harness.adapters.local import LocalSuiteAdapter
from app.harness.adapters.swe_bench import SWEbenchLiteAdapter

__all__ = [
    "BenchmarkAdapter",
    "LocalSuiteAdapter",
    "SWEbenchLiteAdapter",
    "get_adapter",
]
