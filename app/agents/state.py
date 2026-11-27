"""AgentState — 任务级黑板（短期记忆，architecture.md §4.3）。

状态是唯一事实源：节点不互相直接传参，全部读写黑板。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, NotRequired, TypedDict

from app.harness.schema import TaskDefinition


@dataclass(slots=True)
class PlanStep:
    step: int
    action: str
    target: str = ""
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TestRecord:
    __test__ = False  # 防止 pytest 误收集为测试类

    iteration: int
    passed: int
    failed: int
    output_tail: str = ""
    returncode: int = 0

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d


@dataclass(slots=True)
class ReviewRecord:
    verdict: str  # approve | reject
    reason: str = ""
    root_cause_plan: bool = False  # 连续 reject 且回 planner

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentState(TypedDict, total=False):
    """LangGraph 状态 schema（M1 单节点；M2 扩五节点字段全量启用）。"""

    task: TaskDefinition
    plan: list[dict[str, Any]]
    exploration: dict[str, str]
    scratch: str
    diff: str
    test_history: list[dict[str, Any]]
    review: dict[str, Any] | None
    iteration: int
    max_iterations: int
    memory_context: str
    status: str  # running | success | timeout | error
    error: str
    node: str  # 当前节点名
    messages: NotRequired[list[Any]]


def initial_state(
    task: TaskDefinition,
    *,
    memory_context: str = "",
    max_iterations: int | None = None,
) -> AgentState:
    """组装图的输入状态。"""
    return AgentState(
        task=task,
        plan=[],
        exploration={},
        scratch="",
        diff="",
        test_history=[],
        review=None,
        iteration=0,
        max_iterations=max_iterations or task.max_iterations,
        memory_context=memory_context,
        status="running",
        error="",
        node="",
        messages=[],
    )
