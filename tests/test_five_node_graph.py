"""五节点图结构与条件边测试（LLM stub，无网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.graph import build_graph, graph_structure_summary, run_agent_task
from app.agents.state import AgentState, TestRecord, initial_state
from app.db.session import init_db, reset_engine_for_tests
from app.events import EventStore, EventType, assert_seq_monotonic, load_events
from app.harness.schema import TaskDefinition


@pytest.fixture()
def task() -> TaskDefinition:
    return TaskDefinition(
        id="T001",
        title="demo",
        repo="sample_repo",
        prompt="修折扣码",
        max_iterations=4,
    )


@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'm2.db'}")
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_structure_summary() -> None:
    s = graph_structure_summary()
    assert s["nodes"] == ["planner", "explorer", "coder", "tester", "reviewer"]
    assert s["entry"] == "planner"
    assert any("tester" in e for e in s["edges"])


def test_five_node_happy_path_approve(task: TaskDefinition) -> None:
    def always_pass(s: AgentState) -> TestRecord:
        return TestRecord(
            iteration=int(s.get("iteration") or 0), passed=3, failed=0, returncode=0
        )

    graph = build_graph(on_test=always_pass, checkpointer=None, five_node=True)
    final = graph.invoke(initial_state(task))
    assert final["status"] == "success"
    assert final["plan"], "planner 应产出计划"
    assert final["exploration"], "explorer 应产出摘要"
    assert final["test_history"], "tester 应有记录"
    assert final["review"] and final["review"]["verdict"] == "approve"


def test_tester_fail_loops_to_coder(task: TaskDefinition) -> None:
    calls = {"n": 0}

    def fail_then_pass(s: AgentState) -> TestRecord:
        calls["n"] += 1
        if calls["n"] <= 1:
            return TestRecord(iteration=0, passed=0, failed=2, returncode=1)
        return TestRecord(iteration=calls["n"] - 1, passed=2, failed=0, returncode=0)

    graph = build_graph(on_test=fail_then_pass, checkpointer=None, five_node=True)
    final = graph.invoke(initial_state(task))
    # 第一轮 fail → coder → tester pass → reviewer approve
    assert calls["n"] >= 2
    assert final["status"] == "success"
    assert len(final["test_history"]) >= 2
    assert final["test_history"][0]["failed"] > 0
    assert final["test_history"][-1]["failed"] == 0


def test_reviewer_reject_loops_to_coder(task: TaskDefinition) -> None:
    """测试过但 LLM reviewer 拒绝 → 回 coder。"""

    def pass_test(s: AgentState) -> TestRecord:
        return TestRecord(iteration=int(s.get("iteration") or 0), passed=1, failed=0, returncode=0)

    reject_then_approve = {"n": 0}

    def fake_llm(system: str, t: TaskDefinition, s: AgentState) -> str:
        node = s.get("node") or ""
        # planner/explorer 产出 plan
        if node in {"", "planner"} or not s.get("plan"):
            return "PLAN\n1. do a\n2. do b\nSCRATCH\nx"
        if node == "reviewer":
            reject_then_approve["n"] += 1
            if reject_then_approve["n"] == 1:
                return "REJECT: 需要更完整的错误处理"
            return "APPROVE: looks good"
        return "PLAN\n1. fix\nSCRATCH\nscratch"

    graph = build_graph(llm=fake_llm, on_test=pass_test, checkpointer=None, five_node=True)
    final = graph.invoke(initial_state(task))
    assert reject_then_approve["n"] >= 2
    assert final["status"] == "success"
    assert final["review"]["verdict"] == "approve"


def test_bounded_loop_timeout(task: TaskDefinition) -> None:
    def always_fail(s: AgentState) -> TestRecord:
        return TestRecord(
            iteration=int(s.get("iteration") or 0), passed=0, failed=1, returncode=1
        )

    graph = build_graph(on_test=always_fail, checkpointer=None, five_node=True)
    final = graph.invoke(initial_state(task))  # max_iterations=4
    assert final["status"] == "timeout"
    assert final["iteration"] == 4
    assert len(final["test_history"]) == 4
    # 失败也是数据：仍有 plan/diff 字段
    assert final.get("plan") is not None


def test_consecutive_reject_returns_to_planner_once(task: TaskDefinition) -> None:
    """连续 reject 2 次 → planner（仅一次），之后 reject 回 coder。"""
    visited: list[str] = []

    def pass_test(s: AgentState) -> TestRecord:
        return TestRecord(iteration=int(s.get("iteration") or 0), passed=1, failed=0, returncode=0)

    def fake_llm(system: str, t: TaskDefinition, s: AgentState) -> str:
        node = s.get("node") or ""
        visited.append(node)
        if node == "reviewer":
            # 永远 reject → 第二次应触发回 planner，第三次后只能回 coder 直到触顶
            return "REJECT: no"
        return "PLAN\n1. x\nSCRATCH\ny"

    graph = build_graph(llm=fake_llm, on_test=pass_test, checkpointer=None, five_node=True)
    final = graph.invoke(initial_state(task))
    # 触顶 timeout
    assert final["status"] == "timeout"
    # 至少回过一次 planner（在初始 planner 之后）
    assert visited.count("planner") >= 2
    # planner 出现次数 = 1 初始 + 1 回退（仅一次）
    assert visited.count("planner") <= 3


def test_run_agent_task_five_node(task: TaskDefinition, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cp.db'}")
    reset_engine_for_tests()
    init_db()
    from app.db.session import create_checkpointer

    def always_pass(s: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=1, failed=0, returncode=0)

    cp = create_checkpointer()
    final = run_agent_task(
        task,
        run_id="run_m2_five",
        on_test=always_pass,
        checkpointer=cp,
        five_node=True,
    )
    assert final["status"] == "success"
    got = cp.get_tuple({"configurable": {"thread_id": "run_m2_five", "checkpoint_ns": ""}})
    assert got is not None


def test_events_cover_five_nodes(task: TaskDefinition) -> None:
    from app.db.models import RunRow
    from app.db.session import session_scope

    def always_pass(s: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=1, failed=0, returncode=0)

    run_id = "run_m2_events"
    with session_scope() as s:
        s.add(
            RunRow(
                id=run_id,
                task_id=task.id,
                suite="smoke",
                status="running",
                provider="ollama",
                model="qwen3.5:9b",
            )
        )
        store = EventStore(s, run_id)
        graph = build_graph(on_test=always_pass, events=store, checkpointer=None, five_node=True)
        graph.invoke(initial_state(task))
        store.emit(EventType.RUN_FINISHED, {"status": "success"})

        evs = load_events(s, run_id)
        assert_seq_monotonic(evs)
        types = [e.type for e in evs]
        assert types[0] is EventType.RUN_STARTED or EventType.NODE_ENTER in types
        node_enters = [
            e.payload.get("node")
            for e in evs
            if e.type is EventType.NODE_ENTER
        ]
        for n in ("planner", "explorer", "coder", "tester", "reviewer"):
            assert n in node_enters, f"缺少节点事件: {n}（实际 {node_enters}）"
