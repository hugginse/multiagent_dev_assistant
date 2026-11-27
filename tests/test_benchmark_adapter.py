"""BenchmarkAdapter 接口与 SWE-bench Lite 子集测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.harness.adapters import (
    BenchmarkAdapter,
    LocalSuiteAdapter,
    SWEbenchLiteAdapter,
    get_adapter,
)
from app.harness.adapters.swe_bench import EXECUTION_NOTE, MAX_SUBSET


def test_local_adapter_loads_smoke() -> None:
    ad = LocalSuiteAdapter(suite="smoke")
    assert isinstance(ad, BenchmarkAdapter)
    tasks = ad.load_tasks()
    assert len(tasks) == 3
    assert {t.id for t in tasks} == {"T001", "T002", "T003"}


def test_local_adapter_main() -> None:
    tasks = LocalSuiteAdapter(suite="main").load_tasks()
    assert 10 <= len(tasks) <= 15


def test_get_adapter_names() -> None:
    assert get_adapter("local").name == "local"
    assert get_adapter("swe_bench").name == "swe_bench"
    assert get_adapter("swe").name == "swe_bench"
    with pytest.raises(ValueError):
        get_adapter("unknown")


def test_swe_adapter_default_sample() -> None:
    ad = SWEbenchLiteAdapter()
    tasks = ad.load_tasks()
    assert 1 <= len(tasks) <= MAX_SUBSET
    for t in tasks:
        assert t.tags and "swe_bench" in t.tags
        assert EXECUTION_NOTE.split("]")[0] + "]" in t.prompt
        assert "本地" in t.prompt or "Docker" in t.prompt
        assert t.repo == "sample_repo"
        assert t.hidden_tests


def test_swe_adapter_limit() -> None:
    ad = SWEbenchLiteAdapter(limit=1)
    tasks = ad.load_tasks()
    assert len(tasks) == 1


def test_swe_adapter_custom_json(tmp_path: Path) -> None:
    data = [
        {
            "instance_id": "py-x1",
            "repo": "psf/requests",
            "language": "python",
            "problem_statement": "fix bug X",
            "hidden_tests": ["t.py"],
        },
        {
            "instance_id": "js-y1",
            "repo": "facebook/react",
            "language": "javascript",
            "problem_statement": "fix js",
        },
    ]
    p = tmp_path / "swe.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ad = SWEbenchLiteAdapter(path=p)
    tasks = ad.load_tasks()
    # 只收 python
    assert len(tasks) == 1
    assert tasks[0].id.startswith("py_x1") or "py" in tasks[0].id
    assert "fix bug X" in tasks[0].prompt


def test_swe_max_subset() -> None:
    assert MAX_SUBSET <= 10


def test_swe_missing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWE_BENCH_PATH", raising=False)
    monkeypatch.chdir(tmp_path)  # 无 sample
    ad = SWEbenchLiteAdapter(path=tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError):
        ad.load_tasks()


def test_adapter_is_protocol() -> None:
    assert isinstance(LocalSuiteAdapter("smoke"), BenchmarkAdapter)
    assert isinstance(SWEbenchLiteAdapter(), BenchmarkAdapter)
