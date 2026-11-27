"""有界循环策略（architecture.md §4.2）。

规则：
- tester fail → coder（iteration < max）
- tester pass → reviewer
- reviewer reject → coder
- reviewer 连续 reject 且根因是计划错误 → planner（**仅一次**）
- 触顶 → status=timeout，仍产出当前 diff 与报告（失败也是数据）

条件边函数对 state 的就地修改**不会**写回 LangGraph 状态，
因此本模块只做**纯路由决策**；status / _replanned 的写入在节点包装器完成。
"""

from __future__ import annotations

from typing import Any, Literal

from app.agents.state import AgentState
from app.config import get_settings

Route = Literal["planner", "explorer", "coder", "tester", "reviewer", "__end__"]


def max_iterations_of(state: AgentState) -> int:
    return int(state.get("max_iterations") or get_settings().max_iterations)


def hit_max(state: AgentState) -> bool:
    return int(state.get("iteration") or 0) >= max_iterations_of(state)


def should_mark_timeout(state: AgentState) -> bool:
    """节点包装器：iteration 已达上限则应写 status=timeout。"""
    return int(state.get("iteration") or 0) >= max_iterations_of(state)


def after_tester(state: AgentState) -> Route:
    if state.get("status") == "error":
        return "__end__"
    if hit_max(state):
        return "__end__"
    history = state.get("test_history") or []
    last = history[-1] if history else {}
    if last.get("ok"):
        return "reviewer"
    return "coder"


def after_reviewer(state: AgentState) -> Route:
    if hit_max(state):
        return "__end__"
    review = state.get("review") or {}
    if review.get("verdict") == "approve":
        return "__end__"
    # 连续 reject 且回 planner 仅一次：_replanned 由 reviewer 包装器写入
    if review.get("root_cause_plan") and not state.get("_replanned"):
        return "planner"
    return "coder"


def should_replan(state: AgentState) -> bool:
    """reviewer 包装器：是否需要标记 _replanned 并回 planner。"""
    review = state.get("review") or {}
    return bool(
        review.get("verdict") == "reject"
        and review.get("root_cause_plan")
        and not state.get("_replanned")
    )


def loop_trace(state: AgentState) -> dict[str, Any]:
    """调试/测试用：当前循环画像。"""
    return {
        "iteration": int(state.get("iteration") or 0),
        "max": max_iterations_of(state),
        "hit_max": hit_max(state),
        "status": state.get("status"),
        "replanned": bool(state.get("_replanned")),
        "rejects": int(state.get("_consecutive_rejects") or 0),
        "review": state.get("review"),
        "test_history_len": len(state.get("test_history") or []),
    }
