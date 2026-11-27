"""AgentState 正式 schema 测试。"""

from __future__ import annotations

from app.agents.state import (
    REQUIRED_FIELDS,
    VALID_STATUS,
    AgentState,
    PlanStep,
    ReviewRecord,
    TestRecord,
    initial_state,
    normalize_plan,
    normalize_review,
    normalize_state,
    normalize_test_history,
    state_fields,
    validate_state,
)
from app.harness.schema import TaskDefinition


def _task() -> TaskDefinition:
    return TaskDefinition(id="T001", title="t", prompt="p", max_iterations=4)


def test_required_fields_covered_by_typed_dict() -> None:
    ann = state_fields()
    assert ann >= REQUIRED_FIELDS


def test_initial_state_valid() -> None:
    s = initial_state(_task(), memory_context="ctx")
    problems = validate_state(s)
    assert problems == []
    assert s["status"] == "running"
    assert s["iteration"] == 0
    assert s["max_iterations"] == 4
    assert s["memory_context"] == "ctx"
    assert s["plan"] == []
    assert s["test_history"] == []
    assert s["review"] is None
    assert s["messages"] == []


def test_validate_detects_missing_and_bad() -> None:
    s: AgentState = {}
    problems = validate_state(s)
    assert any("missing" in p for p in problems)

    s2 = initial_state(_task())
    s2["status"] = "weird"  # type: ignore[typeddict-unknown-key]
    s2["iteration"] = -1
    problems2 = validate_state(s2)
    assert any("invalid status" in p for p in problems2)
    assert any("iteration" in p for p in problems2)


def test_normalize_plan_from_dicts_and_objects() -> None:
    raw = [
        PlanStep(step=1, action="a"),
        {"step": 2, "action": "b", "target": "x.py"},
        "just a string",
    ]
    out = normalize_plan(raw)
    assert len(out) == 3
    assert out[0]["action"] == "a"
    assert out[1]["target"] == "x.py"
    assert out[2]["step"] == 3


def test_normalize_test_history() -> None:
    rec = TestRecord(iteration=0, passed=2, failed=0, returncode=0)
    out = normalize_test_history([rec, {"iteration": 1, "passed": 0, "failed": 1}])
    assert out[0]["ok"] is True
    assert out[1]["ok"] is False
    assert out[1]["failed"] == 1


def test_normalize_review() -> None:
    assert normalize_review(None) is None
    r = normalize_review(ReviewRecord(verdict="approve", reason="ok"))
    assert r == {"verdict": "approve", "reason": "ok", "root_cause_plan": False}
    bad = normalize_review({"verdict": "maybe"})
    assert bad is not None and bad["verdict"] == "reject"


def test_normalize_state_repairs_bad_status() -> None:
    s = initial_state(_task())
    s["status"] = "nope"  # type: ignore[typeddict-unknown-key]
    normalize_state(s)
    assert s["status"] in VALID_STATUS


def test_state_is_blackboard_replace_semantics() -> None:
    """文档约定：整体替换——测试模拟节点读旧写新。"""
    s = initial_state(_task())
    s["test_history"] = normalize_test_history(s["test_history"] + [{"passed": 1}])
    s["plan"] = normalize_plan(s["plan"] + [{"action": "next"}])
    assert len(s["test_history"]) == 1
    assert len(s["plan"]) == 1
    assert validate_state(s) == []
