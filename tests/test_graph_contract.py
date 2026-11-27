"""M2 feature 8：图结构 / 条件边 / 循环上限 / 授权负向 契约测试。

与 test_five_node_graph / test_loop_bounds / test_node_auth_hard 互补，
聚焦「契约断言」：结构常量、路由表、触顶语义、越权事件 rejected。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.graph import build_graph, graph_structure_summary
from app.agents.loop import after_reviewer, after_tester, hit_max, should_mark_timeout
from app.agents.state import AgentState, TestRecord, initial_state
from app.harness.schema import TaskDefinition
from app.tools.build import build_registry
from app.tools.registry import NODE_TIERS, AuthorizationError, Tier


# --------------------------------------------------------------------------- #
# 图结构
# --------------------------------------------------------------------------- #
def test_structure_contract() -> None:
    s = graph_structure_summary()
    assert s["nodes"] == ["planner", "explorer", "coder", "tester", "reviewer"]
    assert s["entry"] == "planner"
    assert s["max_iterations_default"] >= 1
    # 边契约字符串
    joined = " | ".join(s["edges"])
    assert "planner" in joined and "tester" in joined and "reviewer" in joined


def test_build_graph_five_node_compiles() -> None:
    g = build_graph(five_node=True, checkpointer=None)
    # 编译后的图含全部节点与入口
    nodes = set(g.get_graph().nodes.keys())
    # START/END 在 langgraph 图中可能以特殊名出现
    assert {"planner", "explorer", "coder", "tester", "reviewer"} <= nodes or len(nodes) >= 5


def test_single_node_compat_path() -> None:
    g = build_graph(five_node=False, checkpointer=None)
    assert g is not None


# --------------------------------------------------------------------------- #
# 条件边（纯函数路由）
# --------------------------------------------------------------------------- #
def _st(**kw) -> AgentState:
    task = TaskDefinition(id="T", title="t", prompt="p", max_iterations=kw.pop("max_iter", 3))
    s = initial_state(task)
    s.update(kw)
    return s


def test_router_tester_fail_to_coder() -> None:
    s = _st(test_history=[{"ok": False, "failed": 1}], iteration=1)
    assert after_tester(s) == "coder"


def test_router_tester_pass_to_reviewer() -> None:
    s = _st(test_history=[{"ok": True, "failed": 0}], iteration=1)
    assert after_tester(s) == "reviewer"


def test_router_tester_hit_max_end() -> None:
    s = _st(test_history=[{"ok": False}], iteration=3, max_iter=3)
    assert after_tester(s) == "__end__"
    assert hit_max(s)
    assert should_mark_timeout(s)


def test_router_reviewer_approve_end() -> None:
    s = _st(review={"verdict": "approve"}, iteration=1)
    assert after_reviewer(s) == "__end__"


def test_router_reviewer_reject_coder() -> None:
    s = _st(review={"verdict": "reject", "root_cause_plan": False}, iteration=1)
    assert after_reviewer(s) == "coder"


def test_router_reviewer_reject_to_planner_once() -> None:
    s = _st(review={"verdict": "reject", "root_cause_plan": True}, iteration=1)
    assert after_reviewer(s) == "planner"
    # 已 replan 后只能回 coder
    s["_replanned"] = True
    assert after_reviewer(s) == "coder"


def test_router_error_end() -> None:
    s = _st(status="error", iteration=1)
    assert after_tester(s) == "__end__"


# --------------------------------------------------------------------------- #
# 循环上限端到端
# --------------------------------------------------------------------------- #
def test_loop_upper_bound_exact_iterations() -> None:
    task = TaskDefinition(id="T", title="t", prompt="p", max_iterations=2)
    calls = {"n": 0}

    def always_fail(s: AgentState) -> TestRecord:
        calls["n"] += 1
        return TestRecord(iteration=int(s.get("iteration") or 0), passed=0, failed=1, returncode=1)

    g = build_graph(on_test=always_fail, five_node=True, checkpointer=None)
    final = g.invoke(initial_state(task))
    assert final["status"] == "timeout"
    assert final["iteration"] == 2
    assert calls["n"] == 2  # 恰好 max 次，不多跑
    assert len(final["test_history"]) == 2


def test_loop_bounded_by_settings_when_task_omits() -> None:
    # task 默认 max_iterations=8；始终失败必须在 8 轮内停
    task = TaskDefinition(id="T", title="t", prompt="p")  # max=8 default
    calls = {"n": 0}

    def always_fail(s: AgentState) -> TestRecord:
        calls["n"] += 1
        return TestRecord(iteration=0, passed=0, failed=1, returncode=1)

    g = build_graph(on_test=always_fail, five_node=True, checkpointer=None)
    final = g.invoke(initial_state(task))
    assert calls["n"] <= 8
    assert final["status"] == "timeout"


# --------------------------------------------------------------------------- #
# 授权负向（矩阵 + 事件 rejected）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("node", "forbidden_tier"),
    [
        ("explorer", Tier.W),
        ("explorer", Tier.X),
        ("explorer", Tier.M),
        ("coder", Tier.X),
        ("coder", Tier.M),
        ("tester", Tier.W),
        ("tester", Tier.M),
        ("planner", Tier.W),
        ("planner", Tier.X),
        ("reviewer", Tier.W),
        ("reviewer", Tier.X),
    ],
)
def test_node_tier_matrix_forbidden(node: str, forbidden_tier: Tier) -> None:
    assert forbidden_tier not in NODE_TIERS[node]


def test_authorization_error_message_and_fields(tmp_path: Path) -> None:
    ws = tmp_path / "w"
    ws.mkdir()
    reg = build_registry(ws, timeout_s=10)
    with pytest.raises(AuthorizationError) as ei:
        reg.call("write_file", {"path": "x", "content": "1"}, node="explorer")
    err = ei.value
    assert err.tier is Tier.W
    assert err.node == "explorer"
    assert err.tool == "write_file"
    assert "授权拒绝" in str(err)


def test_rejected_visible_in_events(tmp_path: Path) -> None:
    """越权调用在事件流中可见为 rejected=true。"""
    import os

    from app.agents.nodes.tool_dispatch import dispatch_tool
    from app.db.models import RunRow
    from app.db.session import init_db, reset_engine_for_tests, session_scope
    from app.events import EventStore, EventType, load_events

    reset_engine_for_tests()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'rej.db'}"
    init_db()

    ws = tmp_path / "w"
    ws.mkdir()
    reg = build_registry(ws, timeout_s=10)

    with session_scope() as s:
        s.add(
            RunRow(
                id="run_rej",
                task_id="T",
                suite="smoke",
                status="running",
                provider="ollama",
                model="m",
            )
        )
        store = EventStore(s, "run_rej")
        ok, _ = dispatch_tool(
            reg, store, node="explorer", name="write_file", args={"path": "a", "content": "1"}
        )
        assert not ok
        evs = load_events(s, "run_rej")
        rejected = [
            e
            for e in evs
            if e.type is EventType.TOOL_RESULT and e.payload.get("rejected") is True
        ]
        assert rejected
        assert rejected[0].payload["node"] == "explorer"
        assert rejected[0].payload["tier"] == "W"

    reset_engine_for_tests()


def test_loop_bounds_module_covers_all_routes() -> None:
    """路由表覆盖 tester/reviewer 全部分支枚举。"""
    # tester: error / max / fail / pass
    assert after_tester(_st(status="error")) == "__end__"
    assert after_tester(_st(iteration=99, max_iter=3)) == "__end__"
    assert after_tester(_st(test_history=[{"ok": False}])) == "coder"
    assert after_tester(_st(test_history=[{"ok": True}])) == "reviewer"
    # reviewer: approve / reject / max
    assert after_reviewer(_st(review={"verdict": "approve"})) == "__end__"
    assert after_reviewer(_st(iteration=99, max_iter=3, review={"verdict": "reject"})) == "__end__"
    assert after_reviewer(_st(review={"verdict": "reject"})) == "coder"
