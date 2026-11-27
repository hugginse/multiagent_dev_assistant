"""AgentState — 任务级黑板（短期记忆，architecture.md §4.3）。

状态是唯一事实源：节点不互相直接传参，全部读写黑板。

正式 schema（M2）：
- 必填字段在 ``initial_state`` 全部初始化
- ``plan`` / ``test_history`` / ``review`` 经归一化函数保证结构
- LangGraph 更新约定：**整体替换**（非 append reducer）——节点负责读旧写新
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, NotRequired, TypedDict

from app.harness.schema import TaskDefinition

# --------------------------------------------------------------------------- #
# 嵌套记录
# --------------------------------------------------------------------------- #


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
    __test__ = False

    verdict: str  # approve | reject
    reason: str = ""
    root_cause_plan: bool = False  # 连续 reject 且回 planner

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 状态字段常量（文档/测试共用）
# --------------------------------------------------------------------------- #
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "task",
        "plan",
        "exploration",
        "scratch",
        "diff",
        "test_history",
        "review",
        "iteration",
        "max_iterations",
        "memory_context",
        "status",
        "error",
        "node",
        "messages",
    }
)

OPTIONAL_FIELDS: frozenset[str] = frozenset(
    {
        "_replanned",  # 连续 reject 回 planner 仅一次
        "_consecutive_rejects",
        "workspace",  # 可选，tester 兜底路径
    }
)

VALID_STATUS: frozenset[str] = frozenset({"running", "success", "timeout", "error"})
VALID_VERDICT: frozenset[str] = frozenset({"approve", "reject"})


class AgentState(TypedDict, total=False):
    """LangGraph 五节点黑板（M2 正式 schema）。"""

    # --- 只读输入 ---
    task: TaskDefinition
    max_iterations: int
    memory_context: str

    # --- planner ---
    plan: list[dict[str, Any]]

    # --- explorer ---
    exploration: dict[str, str]

    # --- coder ---
    scratch: str
    diff: str

    # --- tester ---
    test_history: list[dict[str, Any]]
    iteration: int

    # --- reviewer ---
    review: dict[str, Any] | None

    # --- 运行时 ---
    status: str
    error: str
    node: str
    messages: NotRequired[list[Any]]

    # --- 循环控制（内部） ---
    _replanned: NotRequired[bool]
    _consecutive_rejects: NotRequired[int]
    workspace: NotRequired[str]


# --------------------------------------------------------------------------- #
# 归一化 / 校验
# --------------------------------------------------------------------------- #


def normalize_plan(raw: Any) -> list[dict[str, Any]]:
    """plan 归一化为 list[dict(step, action, target, done)]。"""
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw, start=1):
            if isinstance(item, PlanStep):
                out.append(item.to_dict())
            elif isinstance(item, dict):
                out.append(
                    {
                        "step": int(item.get("step") or i),
                        "action": str(item.get("action") or item.get("text") or ""),
                        "target": str(item.get("target") or ""),
                        "done": bool(item.get("done", False)),
                    }
                )
            else:
                out.append({"step": i, "action": str(item), "target": "", "done": False})
    return out


def normalize_test_history(raw: Any) -> list[dict[str, Any]]:
    """test_history 归一化。"""
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, TestRecord):
                out.append(item.to_dict())
            elif isinstance(item, dict):
                passed = int(item.get("passed") or 0)
                failed = int(item.get("failed") or 0)
                rc = int(item.get("returncode") or 0)
                out.append(
                    {
                        "iteration": int(item.get("iteration") or 0),
                        "passed": passed,
                        "failed": failed,
                        "output_tail": str(item.get("output_tail") or ""),
                        "returncode": rc,
                        "ok": bool(item.get("ok", failed == 0 and rc == 0)),
                    }
                )
    return out


def normalize_review(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, ReviewRecord):
        return raw.to_dict()
    if isinstance(raw, dict):
        verdict = str(raw.get("verdict") or "reject")
        if verdict not in VALID_VERDICT:
            verdict = "reject"
        return {
            "verdict": verdict,
            "reason": str(raw.get("reason") or ""),
            "root_cause_plan": bool(raw.get("root_cause_plan", False)),
        }
    return None


def normalize_state(state: AgentState) -> AgentState:
    """就地归一化关键字段；返回同一 dict。"""
    state["plan"] = normalize_plan(state.get("plan"))
    state["test_history"] = normalize_test_history(state.get("test_history"))
    state["review"] = normalize_review(state.get("review"))
    state["exploration"] = dict(state.get("exploration") or {})
    state["scratch"] = str(state.get("scratch") or "")
    state["diff"] = str(state.get("diff") or "")
    state["memory_context"] = str(state.get("memory_context") or "")
    state["status"] = str(state.get("status") or "running")
    if state["status"] not in VALID_STATUS:
        state["status"] = "running"
    state["error"] = str(state.get("error") or "")
    state["node"] = str(state.get("node") or "")
    state["iteration"] = int(state.get("iteration") or 0)
    state["max_iterations"] = int(state.get("max_iterations") or 8)
    if "messages" not in state or state["messages"] is None:
        state["messages"] = []
    return state


def validate_state(state: AgentState) -> list[str]:
    """返回问题列表（空 = 合法）。测试与调试用。"""
    problems: list[str] = []
    for f in REQUIRED_FIELDS:
        if f not in state:
            problems.append(f"missing required field: {f}")
    if "task" in state and not isinstance(state["task"], TaskDefinition):
        problems.append("task must be TaskDefinition")
    if "status" in state and state["status"] not in VALID_STATUS:
        problems.append(f"invalid status: {state.get('status')!r}")
    if "iteration" in state and int(state["iteration"]) < 0:
        problems.append("iteration must be >= 0")
    if "max_iterations" in state and int(state["max_iterations"]) < 1:
        problems.append("max_iterations must be >= 1")
    review = state.get("review")
    if review is not None:
        if not isinstance(review, dict):
            problems.append("review must be dict|None")
        elif review.get("verdict") not in VALID_VERDICT:
            problems.append(f"invalid review verdict: {review.get('verdict')!r}")
    if "plan" in state and not isinstance(state["plan"], list):
        problems.append("plan must be list")
    if "test_history" in state and not isinstance(state["test_history"], list):
        problems.append("test_history must be list")
    if "exploration" in state and not isinstance(state["exploration"], dict):
        problems.append("exploration must be dict")
    return problems


def initial_state(
    task: TaskDefinition,
    *,
    memory_context: str = "",
    max_iterations: int | None = None,
) -> AgentState:
    """组装图的输入状态（全部必填字段就位）。"""
    state = AgentState(
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
        _replanned=False,
        _consecutive_rejects=0,
    )
    return normalize_state(state)


def state_fields() -> frozenset[str]:
    """TypedDict 声明的字段名。"""
    return frozenset(AgentState.__annotations__)
