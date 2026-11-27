"""harness 指标扩展：tool_calls 按 tier、max_hit、pass@k k>1。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.state import AgentState, TestRecord
from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.events import Event, EventType, count_tool_calls_by_tier, load_events
from app.harness.loader import load_task
from app.harness.report import (
    aggregate_tool_calls_by_tier,
    build_report,
    compute_pass_at_k,
    max_hit_rate,
)
from app.harness.runner import run_single_task


@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'metrics.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_count_tool_calls_by_tier_from_events() -> None:
    events = [
        Event(type=EventType.TOOL_CALL, payload={"name": "read_file", "tier": "R"}, seq=1),
        Event(type=EventType.TOOL_CALL, payload={"name": "list_dir", "tier": "R"}, seq=2),
        Event(type=EventType.TOOL_CALL, payload={"name": "write_file", "tier": "W"}, seq=3),
        Event(type=EventType.TOOL_CALL, payload={"name": "run_tests", "tier": "X"}, seq=4),
        Event(type=EventType.TOOL_CALL, payload={"name": "mystery"}, seq=5),
        Event(type=EventType.NODE_ENTER, payload={}, seq=6),
    ]
    counts = count_tool_calls_by_tier(events)
    assert counts == {"R": 2, "W": 1, "X": 1, "unknown": 1}


def test_pass_at_k_k1_equals_resolve() -> None:
    items = [
        {"task_id": "A", "resolve": True},
        {"task_id": "A", "resolve": False},
        {"task_id": "B", "resolve": False},
        {"task_id": "B", "resolve": False},
    ]
    p = compute_pass_at_k(items, ["A", "B"], k=1)
    assert p["A"] == 0.5
    assert p["B"] == 0.0


def test_pass_at_k_k3_unbiased() -> None:
    # n=4, c=1, k=3 → 1 - C(3,3)/C(4,3) = 1 - 1/4 = 0.75
    items = [{"task_id": "T", "resolve": i == 0} for i in range(4)]
    p = compute_pass_at_k(items, ["T"], k=3)
    assert abs(p["T"] - 0.75) < 1e-9


def test_pass_at_k_all_fail_zero() -> None:
    items = [{"task_id": "T", "resolve": False} for _ in range(5)]
    assert compute_pass_at_k(items, ["T"], k=3)["T"] == 0.0


def test_pass_at_k_all_pass_one() -> None:
    items = [{"task_id": "T", "resolve": True} for _ in range(5)]
    assert compute_pass_at_k(items, ["T"], k=3)["T"] == 1.0


def test_aggregate_tool_calls_and_max_hit() -> None:
    items = [
        {"tool_calls": {"R": 2, "X": 1}, "max_hit": True},
        {"tool_calls": {"R": 1, "W": 3}, "max_hit": False},
        {"tool_calls": {}, "max_hit": True},
    ]
    assert aggregate_tool_calls_by_tier(items) == {"R": 3, "X": 1, "W": 3}
    assert max_hit_rate(items) == pytest.approx(2 / 3)


def test_build_report_includes_tier_and_max_hit() -> None:
    items = [
        {
            "task_id": "T001",
            "sample": 1,
            "resolve": True,
            "pass_ratio": 1.0,
            "iterations": 2,
            "max_hit": False,
            "tool_calls": {"R": 3, "X": 1},
            "tokens_in": 0,
            "tokens_out": 0,
            "wall_s": 1.0,
            "status": "success",
        },
        {
            "task_id": "T001",
            "sample": 2,
            "resolve": False,
            "pass_ratio": 0.0,
            "iterations": 8,
            "max_hit": True,
            "tool_calls": {"R": 5},
            "tokens_in": 0,
            "tokens_out": 0,
            "wall_s": 2.0,
            "status": "timeout",
        },
    ]
    rep = build_report(
        eval_id="e",
        suite="smoke",
        k=2,
        provider="ollama",
        model="m",
        memory_on=False,
        items=items,
    )
    assert rep.tool_calls_by_tier == {"R": 8, "X": 1}
    assert rep.max_hit_rate == 0.5
    assert "T001" in rep.pass_at_k
    assert rep.pass_at_k["T001"] == 1.0  # n=2,c=1,k=2 → 1 - C(1,2)/C(2,2)=1
    md = __import__("app.harness.report", fromlist=["render_markdown"]).render_markdown(rep)
    assert "tool_calls" in md
    assert "max_hit" in md


def test_run_single_task_records_tool_calls_and_max_hit() -> None:
    task = load_task("smoke", "T001")

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(
            iteration=int(state.get("iteration") or 0),
            passed=0,
            failed=1,
            returncode=1,
        )

    outcome = run_single_task(
        task,
        suite="smoke",
        on_node_test=on_test,
        with_hidden_scoring=False,
    )
    m = outcome.metrics
    # 五节点会走 planner memory_search(M) / explorer list_dir(R) / coder read_file(R)
    assert m.tool_calls, "应统计到 tool_calls"
    assert any(t in m.tool_calls for t in ("R", "W", "X", "M", "unknown"))
    # always fail → 触顶 max_hit
    assert m.max_hit is True
    assert m.iterations >= 1

    with session_scope() as s:
        evs = load_events(s, outcome.run_id)
    counted = count_tool_calls_by_tier(evs)
    assert counted == m.tool_calls
