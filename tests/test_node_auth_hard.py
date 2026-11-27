"""节点级工具授权硬校验：explorer 只 R、coder R+W、tester R+X；越权事件 rejected。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.nodes.explorer import explorer_node
from app.agents.nodes.reviewer import reviewer_node

# 别名：避免 pytest 把 tester_node 当测试收集
from app.agents.nodes.tester import tester_node as run_tester_node
from app.agents.nodes.tool_dispatch import dispatch_tool
from app.agents.state import initial_state
from app.events import EventStore, EventType
from app.harness.schema import TaskDefinition
from app.tools.build import build_registry
from app.tools.memory_tools import clear_memory_store
from app.tools.registry import Tier


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "orderlib").mkdir(parents=True)
    (root / "orderlib" / "pricing.py").write_text("x=1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return root


@pytest.fixture()
def reg(ws: Path):
    clear_memory_store()
    yield build_registry(ws, timeout_s=30)
    clear_memory_store()


@pytest.fixture()
def events(reg, tmp_path: Path):
    from app.db.models import RunRow
    from app.db.session import init_db, reset_engine_for_tests, session_scope

    reset_engine_for_tests()
    import os

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'auth.db'}"
    init_db()
    with session_scope() as s:
        s.add(
            RunRow(
                id="run_auth",
                task_id="T",
                suite="smoke",
                status="running",
                provider="ollama",
                model="m",
            )
        )
        store = EventStore(s, "run_auth")
        yield store
    reset_engine_for_tests()


def _task() -> TaskDefinition:
    return TaskDefinition(id="T001", title="修折扣码", prompt="p", max_iterations=3)


def test_explorer_cannot_write_event_rejected(reg, events, ws: Path) -> None:
    state = initial_state(_task())
    explorer_node(state, events=events, tools=reg, workspace=ws)
    # 正常 list_dir 成功
    ok, _ = dispatch_tool(reg, events, node="explorer", name="list_dir", args={"path": "."})
    assert ok
    # 越权写
    ok2, msg = dispatch_tool(
        reg, events, node="explorer", name="write_file", args={"path": "a.py", "content": "1"}
    )
    assert not ok2
    assert "授权拒绝" in msg

    from app.db.session import session_scope
    from app.events import load_events

    with session_scope() as s:
        evs = load_events(s, "run_auth")
    rejected = [
        e
        for e in evs
        if e.type is EventType.TOOL_RESULT and e.payload.get("rejected") is True
    ]
    assert rejected, "越权必须在事件中可见为 rejected"
    assert rejected[0].payload["name"] == "write_file"
    assert rejected[0].payload["node"] == "explorer"


def test_cannot_exec_from_coder_or_planner(reg, events, ws: Path) -> None:
    ok, msg = dispatch_tool(reg, events, node="coder", name="run_tests", args={"path": "tests"})
    assert not ok and "授权拒绝" in msg
    ok2, msg2 = dispatch_tool(
        reg, events, node="planner", name="write_file", args={"path": "x", "content": "y"}
    )
    assert not ok2 and "授权拒绝" in msg2
    ok3, msg3 = dispatch_tool(
        reg, events, node="reviewer", name="run_lint", args={"path": "."}
    )
    assert not ok3 and "授权拒绝" in msg3


def test_tester_can_exec_coder_cannot(reg, events, ws: Path) -> None:
    # tester 允许 run_tests（真实执行，短超时）
    ok, summary = dispatch_tool(
        reg, events, node="tester", name="run_tests", args={"path": "tests"}
    )
    assert ok, summary
    # coder 不允许
    ok2, _ = dispatch_tool(reg, events, node="coder", name="run_tests", args={"path": "tests"})
    assert not ok2


def test_planner_memory_allowed_write_denied(reg, events, ws: Path) -> None:
    ok, _ = dispatch_tool(
        reg, events, node="planner", name="memory_search", args={"query": "约定"}
    )
    assert ok
    ok2, _ = dispatch_tool(
        reg, events, node="planner", name="memory_save", args={"title": "t", "content": "c"}
    )
    # memory_save 是 M，planner 有 M → 允许
    assert ok2
    # 但 explorer 无 M
    ok3, msg = dispatch_tool(
        reg, events, node="explorer", name="memory_search", args={"query": "x"}
    )
    assert not ok3 and "授权拒绝" in msg


def test_node_tiers_contract() -> None:
    from app.tools.registry import NODE_TIERS

    assert NODE_TIERS["explorer"] == frozenset({Tier.R})
    assert NODE_TIERS["coder"] == frozenset({Tier.R, Tier.W})
    assert NODE_TIERS["tester"] == frozenset({Tier.R, Tier.X})
    assert Tier.X not in NODE_TIERS["coder"]
    assert Tier.W not in NODE_TIERS["explorer"]


def test_graph_nodes_emit_tool_events_with_registry(reg, events, ws: Path) -> None:
    """五节点跑通时 explorer/coder 产生 tool_call；registry 拒绝不崩图。"""
    from app.agents.graph import build_graph
    from app.agents.state import TestRecord

    def pass_test(s):
        return TestRecord(iteration=int(s.get("iteration") or 0), passed=1, failed=0, returncode=0)

    graph = build_graph(
        on_test=pass_test,
        events=events,
        tools=reg,
        workspace=ws,
        checkpointer=None,
        five_node=True,
    )
    state = initial_state(_task())
    state["workspace"] = str(ws)
    final = graph.invoke(state)
    assert final["status"] == "success"

    from app.db.session import session_scope
    from app.events import load_events

    with session_scope() as s:
        evs = load_events(s, "run_auth")
    calls = [e for e in evs if e.type is EventType.TOOL_CALL]
    assert calls, "图运行应产生 tool_call"
    nodes = {e.payload.get("node") for e in calls}
    assert "explorer" in nodes or "planner" in nodes or "coder" in nodes
    # 无崩图
    assert final.get("review", {}).get("verdict") == "approve"


def test_reviewer_cannot_write(reg, events, ws: Path) -> None:
    state = initial_state(_task())
    state["test_history"] = [{"ok": True, "passed": 1, "failed": 0, "returncode": 0}]
    reviewer_node(state, events=events, tools=reg)
    ok, msg = dispatch_tool(
        reg, events, node="reviewer", name="write_file", args={"path": "z", "content": "1"}
    )
    assert not ok and "授权拒绝" in msg


def test_tester_node_no_workspace_safe(reg, events, ws: Path) -> None:
    """无 workspace/on_test 时 tester 不递归跑 pytest。"""
    state = initial_state(_task())
    out = run_tester_node(state, events=events, tools=reg, on_test=None)
    assert out["test_history"]
    assert out["test_history"][0]["output_tail"].startswith("(no workspace")
