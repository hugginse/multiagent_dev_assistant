"""有界循环策略单测：路由、触顶 timeout、回 planner 仅一次。"""

from __future__ import annotations

from app.agents.loop import (
    after_reviewer,
    after_tester,
    hit_max,
    loop_trace,
    max_iterations_of,
    should_mark_timeout,
    should_replan,
)
from app.agents.state import AgentState, initial_state
from app.harness.schema import TaskDefinition


def _state(**kw) -> AgentState:
    task = TaskDefinition(id="T", title="t", prompt="p", max_iterations=kw.pop("max_iterations", 3))
    s = initial_state(task)
    s.update(kw)
    return s


def test_max_iterations_from_task() -> None:
    s = _state(max_iterations=5)
    assert max_iterations_of(s) == 5


def test_hit_max_boundary() -> None:
    s = _state(iteration=2, max_iterations=3)
    assert not hit_max(s)
    s["iteration"] = 3
    assert hit_max(s)
    assert should_mark_timeout(s)


def test_after_tester_routes() -> None:
    # fail → coder
    s = _state(test_history=[{"ok": False, "failed": 1, "passed": 0}], iteration=1)
    assert after_tester(s) == "coder"
    # pass → reviewer
    s = _state(test_history=[{"ok": True, "failed": 0, "passed": 2}], iteration=1)
    assert after_tester(s) == "reviewer"
    # 触顶 → end
    s = _state(test_history=[{"ok": False}], iteration=3, max_iterations=3)
    assert after_tester(s) == "__end__"
    # error → end
    s = _state(status="error", iteration=1)
    assert after_tester(s) == "__end__"


def test_after_reviewer_routes() -> None:
    # approve → end
    s = _state(review={"verdict": "approve"}, iteration=1)
    assert after_reviewer(s) == "__end__"
    # reject → coder
    s = _state(review={"verdict": "reject", "root_cause_plan": False}, iteration=1)
    assert after_reviewer(s) == "coder"
    # reject plan root cause → planner（未 replan）
    s = _state(review={"verdict": "reject", "root_cause_plan": True}, iteration=1)
    assert after_reviewer(s) == "planner"
    # 已 replan → 只能回 coder
    s = _state(
        review={"verdict": "reject", "root_cause_plan": True},
        _replanned=True,
        iteration=1,
    )
    assert after_reviewer(s) == "coder"
    # 触顶 → end
    s = _state(review={"verdict": "reject"}, iteration=3, max_iterations=3)
    assert after_reviewer(s) == "__end__"


def test_should_replan_only_once() -> None:
    s = _state(review={"verdict": "reject", "root_cause_plan": True})
    assert should_replan(s)
    s["_replanned"] = True
    assert not should_replan(s)
    # approve 不触发
    s2 = _state(review={"verdict": "approve", "root_cause_plan": True})
    assert not should_replan(s2)


def test_loop_trace() -> None:
    s = _state(iteration=2, max_iterations=4, _consecutive_rejects=1)
    t = loop_trace(s)
    assert t["iteration"] == 2
    assert t["max"] == 4
    assert t["hit_max"] is False
    assert t["rejects"] == 1
    assert t["replanned"] is False
