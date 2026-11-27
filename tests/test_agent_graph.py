"""AgentState / 单节点循环 / LangGraph 有界循环测试（LLM stub，无网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.graph import build_graph, graph_structure_summary, run_agent_task
from app.agents.nodes.agent_node import _default_llm, agent_node
from app.agents.state import AgentState, PlanStep, ReviewRecord, TestRecord, initial_state
from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.events import EventStore, EventType, assert_seq_monotonic, load_events
from app.harness.schema import TaskDefinition


@pytest.fixture()
def task() -> TaskDefinition:
    return TaskDefinition(
        id="T001",
        title="demo",
        repo="sample_repo",
        prompt="修复折扣码",
        hidden_tests=["x.py"],
        max_iterations=3,
    )


def test_initial_state(task: TaskDefinition) -> None:
    s = initial_state(task, memory_context="ctx")
    assert s["task"].id == "T001"
    assert s["iteration"] == 0
    assert s["status"] == "running"
    assert s["max_iterations"] == 3
    assert s["memory_context"] == "ctx"


def test_plan_step_and_test_record() -> None:
    p = PlanStep(step=1, action="read")
    assert p.to_dict()["action"] == "read"
    ok = TestRecord(iteration=0, passed=2, failed=0, returncode=0)
    bad = TestRecord(iteration=1, passed=1, failed=1, returncode=1)
    assert ok.ok and not bad.ok
    r = ReviewRecord(verdict="reject", reason="no")
    assert r.to_dict()["verdict"] == "reject"


def test_default_llm_stub_parses_plan(task: TaskDefinition) -> None:
    text = _default_llm("", task, initial_state(task))
    assert "PLAN" in text and "SCRATCH" in text


def test_agent_node_advances_iteration(task: TaskDefinition) -> None:
    s = initial_state(task)
    out = agent_node(s)
    assert out["iteration"] == 1
    assert out["node"] == "agent"
    assert out["plan"], "应解析出计划"
    assert len(out["test_history"]) == 1


def test_agent_node_success_when_tests_pass(task: TaskDefinition) -> None:
    from app.agents.state import TestRecord as TR

    s = initial_state(task)

    def on_test(_state: AgentState) -> TR:
        return TR(iteration=0, passed=3, failed=0, returncode=0)

    out = agent_node(s, on_test=on_test)
    assert out["status"] == "success"


def test_agent_node_timeout_when_maxed(task: TaskDefinition) -> None:
    from app.agents.state import TestRecord as TR

    s = initial_state(task)
    s["iteration"] = 2  # max=3，本轮后到 3

    def on_test(_state: AgentState) -> TR:
        return TR(iteration=2, passed=0, failed=1, returncode=1)

    out = agent_node(s, on_test=on_test)
    assert out["iteration"] == 3
    assert out["status"] == "timeout"


def test_graph_structure() -> None:
    summary = graph_structure_summary()
    # M2 默认五节点
    assert summary["nodes"] == ["planner", "explorer", "coder", "tester", "reviewer"]
    assert summary["entry"] == "planner"
    assert any("tester" in e for e in summary["edges"])


def test_graph_runs_with_stub_llm(task: TaskDefinition) -> None:
    graph = build_graph(llm=None, on_test=None, checkpointer=None, five_node=False)
    state = initial_state(task)
    final = graph.invoke(state)
    # stub 测试 returncode=0 → success
    assert final["status"] in {"success", "running", "timeout"}
    assert final["iteration"] >= 1


def test_graph_bounded_loop_hits_max(task: TaskDefinition) -> None:
    from app.agents.state import TestRecord as TR

    def always_fail(_s: AgentState) -> TR:
        return TR(iteration=int(_s.get("iteration") or 0), passed=0, failed=1, returncode=1)

    graph = build_graph(on_test=always_fail, checkpointer=None, five_node=False)
    state = initial_state(task)  # max_iterations=3
    final = graph.invoke(state)
    assert final["status"] == "timeout"
    assert final["iteration"] == 3
    assert len(final["test_history"]) == 3


def test_run_agent_task_with_checkpointer(
    task: TaskDefinition, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cp.db'}")
    reset_engine_for_tests()
    init_db()
    from app.db.session import create_checkpointer

    cp = create_checkpointer()
    final = run_agent_task(task, run_id="run_cp_test", checkpointer=cp)
    assert final["status"] in {"success", "timeout", "running"}
    # checkpoint 可读
    got = cp.get_tuple({"configurable": {"thread_id": "run_cp_test", "checkpoint_ns": ""}})
    assert got is not None
    reset_engine_for_tests()


def test_event_order_and_seq(
    task: TaskDefinition, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ev.db'}")
    reset_engine_for_tests()
    init_db()
    run_id = "run_ev_1"
    with session_scope() as s:
        from app.db.models import RunRow

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
        collected: list = []
        store.subscribe(collected.append)
        store.emit(EventType.RUN_STARTED, {"task_id": task.id})
        s.flush()
        agent_node(initial_state(task), events=store)
        store.emit(EventType.RUN_FINISHED, {"status": "success"})

        events = load_events(s, run_id)
        assert_seq_monotonic(events)
        types = [e.type for e in events]
        assert types[0] is EventType.RUN_STARTED
        assert types[-1] is EventType.RUN_FINISHED
        assert EventType.NODE_ENTER in types
        assert EventType.LLM_DELTA in types
        assert EventType.TEST_RESULT in types
        assert EventType.NODE_EXIT in types
        # 实时订阅与落库一致
        assert len(collected) == len(events)
    reset_engine_for_tests()
