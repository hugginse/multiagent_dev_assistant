"""套件加载与 smoke 任务校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.harness.loader import (
    SuiteError,
    load_task,
    load_tasks,
    resolve_hidden_test_paths,
    suite_dir,
)
from app.harness.schema import TaskDefinition

ROOT = Path(__file__).resolve().parents[1]


def test_suite_dir_smoke_exists() -> None:
    d = suite_dir("smoke")
    assert (d / "tasks").is_dir()
    assert (d / "hidden_tests").is_dir()


def test_load_smoke_has_three_tasks() -> None:
    tasks = load_tasks("smoke")
    assert len(tasks) == 3
    ids = {t.id for t in tasks}
    assert ids == {"T001", "T002", "T003"}
    for t in tasks:
        assert t.prompt.strip()
        assert t.hidden_tests
        assert t.repo == "sample_repo"
        assert t.difficulty in {"easy", "medium", "hard"}


def test_load_single_task() -> None:
    t = load_task("smoke", "T001")
    assert t.title
    assert "discount" in t.prompt.lower() or "折扣" in t.prompt


def test_hidden_tests_resolve() -> None:
    tasks = load_tasks("smoke")
    for t in tasks:
        paths = resolve_hidden_test_paths("smoke", t)
        assert paths
        for p in paths:
            assert p.exists()
            # Agent 不可见：文件不在 tasks 旁边
            assert "hidden_tests" in p.parts


def test_hidden_tests_not_inside_tasks() -> None:
    d = suite_dir("smoke")
    for f in (d / "tasks").glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        # prompt 字段不应包含隐藏测试文件名（防泄漏到 prompt）
        # 允许 hidden_tests: 列表字段出现文件名
        body = text.split("hidden_tests:", 1)[0]
        assert "test_discount_hidden" not in body
        assert "test_order_limits_hidden" not in body
        assert "test_shipping_tiers_hidden" not in body


def test_invalid_task_yaml(tmp_path: Path) -> None:
    tasks = tmp_path / "bad" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / "bad" / "hidden_tests").mkdir()
    (tasks / "bad.yaml").write_text(
        "id: X\ntitle: y\nprompt: p\ndifficulty: impossible\n", encoding="utf-8"
    )
    with pytest.raises(SuiteError, match="difficulty"):
        load_tasks("bad", root=tmp_path)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    tasks = tmp_path / "dup" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / "dup" / "hidden_tests").mkdir()
    content = "id: T1\ntitle: a\nprompt: p\n"
    (tasks / "a.yaml").write_text(content, encoding="utf-8")
    (tasks / "b.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(SuiteError, match="重复"):
        load_tasks("dup", root=tmp_path)


def test_task_definition_defaults() -> None:
    t = TaskDefinition(id="T", title="t", prompt="p")
    assert t.max_iterations == 8
    assert t.timeout_s == 300.0
    assert t.repo == "sample_repo"
