"""套件 YAML 加载与校验。

目录约定::

    suites/<name>/
      tasks/*.yaml
      hidden_tests/          # 可选，按任务 hidden_tests 相对路径注入
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.harness.schema import TaskDefinition

SUITES_ROOT = Path(__file__).resolve().parents[2] / "suites"


class SuiteError(Exception):
    """套件加载失败。"""


def suite_dir(suite: str, *, root: Path | None = None) -> Path:
    base = root or SUITES_ROOT
    d = base / suite
    if not d.is_dir():
        raise SuiteError(f"套件不存在: {d}")
    return d


def load_task_file(path: Path) -> TaskDefinition:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SuiteError(f"YAML 解析失败 {path}: {e}") from e
    if not isinstance(raw, dict):
        raise SuiteError(f"任务文件必须是映射: {path}")
    try:
        return TaskDefinition.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise SuiteError(f"任务校验失败 {path}: {e}") from e


def load_tasks(suite: str, *, root: Path | None = None) -> list[TaskDefinition]:
    d = suite_dir(suite, root=root)
    task_dir = d / "tasks"
    if not task_dir.is_dir():
        raise SuiteError(f"缺少 tasks 目录: {task_dir}")
    files = sorted(task_dir.glob("*.yaml")) + sorted(task_dir.glob("*.yml"))
    # 去重（同名 .yaml/.yml）
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in files:
        if f.resolve() not in seen:
            seen.add(f.resolve())
            unique_files.append(f)
    if not unique_files:
        raise SuiteError(f"套件 {suite} 无任务文件")
    tasks = [load_task_file(f) for f in unique_files]
    ids = [t.id for t in tasks]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SuiteError(f"任务 id 重复: {sorted(dup)}")
    return tasks


def load_task(suite: str, task_id: str, *, root: Path | None = None) -> TaskDefinition:
    for t in load_tasks(suite, root=root):
        if t.id == task_id:
            return t
    raise SuiteError(f"任务不存在: {task_id} @ {suite}")


def hidden_tests_dir(suite: str, *, root: Path | None = None) -> Path:
    return suite_dir(suite, root=root) / "hidden_tests"


def resolve_hidden_test_paths(suite: str, task: TaskDefinition, *, root: Path | None = None) -> list[Path]:
    """把任务里的 hidden_tests 相对路径解析为绝对文件列表（不存在则报错）。"""
    base = hidden_tests_dir(suite, root=root)
    out: list[Path] = []
    for rel in task.hidden_tests:
        p = base / rel
        if not p.exists():
            raise SuiteError(f"隐藏测试文件不存在: {p}")
        out.append(p)
    return out
