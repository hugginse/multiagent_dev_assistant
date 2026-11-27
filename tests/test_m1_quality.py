"""M1 质量红线专项：路径 jail、授权负向、harness 评分、事件顺序（LLM mock）。

对应 plan.md feature 17 与 architecture.md §10。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.graph import build_graph
from app.agents.nodes.agent_node import LLMFn
from app.agents.state import AgentState, TestRecord, initial_state
from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.events import EventType, assert_seq_monotonic, load_events
from app.harness.loader import load_task
from app.harness.runner import run_single_task, score_hidden_tests
from app.harness.schema import TaskDefinition
from app.sandbox.jail import PathJailError, resolve_in_workspace
from app.tools.fs_tools import register_fs_tools
from app.tools.registry import AuthorizationError, ToolError, ToolRegistry
from app.tools.write_tools import register_write_tools


# --------------------------------------------------------------------------- #
# LLM mock：确定性、可断言流
# --------------------------------------------------------------------------- #
def make_mock_llm(*, fail_first: bool = False) -> LLMFn:
    """可脚本化的 LLM mock：记录调用，产出固定 plan/scratch。"""

    calls: list[str] = []

    def llm(system: str, task: TaskDefinition, state: AgentState) -> str:
        calls.append(task.id)
        n = int(state.get("iteration") or 0)
        if fail_first and n == 0:
            return "PLAN\n1. 先探索\n2. 再改\nSCRATCH\n第一轮草稿"
        return "PLAN\n1. 修复\n2. 验证\nSCRATCH\n第二轮草稿"

    llm.calls = calls  # type: ignore[attr-defined]
    return llm


# --------------------------------------------------------------------------- #
# 路径 jail 负向（汇总边界）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evil",
    [
        "../outside",
        "../../etc/passwd",
        "a/../../b",
        "./../x",
        "..",
        "../",
    ],
)
def test_jail_blocks_dotdot_variants(tmp_path: Path, evil: str) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, evil)


def test_jail_blocks_windows_absolute(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "C:/Windows/win.ini")
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "\\\\server\\share\\x")


def test_jail_symlink_escape(tmp_path: Path) -> None:
    import contextlib

    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("s", encoding="utf-8")
    link = ws / "link.txt"
    with contextlib.suppress(OSError):
        link.symlink_to(outside)
    if not link.is_symlink():
        pytest.skip("no symlink")
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "link.txt")


def test_read_write_tools_respect_jail(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ok.txt").write_text("ok", encoding="utf-8")
    reg = ToolRegistry()
    register_fs_tools(reg, ws)
    register_write_tools(reg, ws)

    assert reg.call("read_file", {"path": "ok.txt"}, node="explorer") == "ok"
    with pytest.raises(ToolError, match="越出"):
        reg.call("read_file", {"path": "../ok.txt"}, node="explorer")
    with pytest.raises(ToolError, match="越出"):
        reg.call("write_file", {"path": "../evil.py", "content": "x"}, node="coder")
    with pytest.raises(AuthorizationError):
        reg.call("write_file", {"path": "a.py", "content": "x"}, node="explorer")


# --------------------------------------------------------------------------- #
# 授权负向矩阵
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("node", "tool", "allowed"),
    [
        ("explorer", "read_file", True),
        ("explorer", "write_file", False),
        ("explorer", "run_tests", False),
        ("explorer", "memory_search", False),
        ("coder", "write_file", True),
        ("coder", "read_file", True),
        ("coder", "run_tests", False),
        ("tester", "run_tests", True),
        ("tester", "write_file", False),
        ("planner", "memory_search", True),
        ("planner", "write_file", False),
        ("planner", "run_tests", False),
        ("reviewer", "read_file", True),
        ("reviewer", "write_file", False),
    ],
)
def test_auth_matrix(tmp_path: Path, node: str, tool: str, allowed: bool) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x=1\n", encoding="utf-8")
    reg = ToolRegistry()
    register_fs_tools(reg, ws)
    register_write_tools(reg, ws)

    from app.tools.exec_tools import register_exec_tools
    from app.tools.registry import Tier as T
    from app.tools.registry import ToolSpec

    register_exec_tools(reg, ws, timeout_s=30)
    if "memory_search" not in reg.names():
        reg.register(
            ToolSpec(
                name="memory_search",
                description="m",
                tier=T.M,
                handler=lambda q: [],
            )
        )

    args: dict = {}
    if tool == "read_file":
        args = {"path": "a.py"}
    elif tool == "write_file":
        args = {"path": "w.py", "content": "1"}
    elif tool == "run_tests":
        args = {"path": "tests"}
    elif tool == "memory_search":
        args = {"q": "x"}

    if allowed:
        reg.call(tool, args, node=node)
    else:
        with pytest.raises(AuthorizationError):
            reg.call(tool, args, node=node)


# --------------------------------------------------------------------------- #
# harness 评分：真实执行、隐藏测试注入
# --------------------------------------------------------------------------- #
def test_hidden_scoring_real_pytest_counts(tmp_path: Path) -> None:
    """评分必须真实跑 pytest，解析 passed/failed。"""
    from app.sandbox.workspace import prepare_workspace

    task = load_task("smoke", "T001")
    from app.harness.runner import find_repo_root

    rid = "run_score_test"
    ws = prepare_workspace(find_repo_root("sample_repo"), rid, hidden_tests=None)
    # Agent 期间不可见
    assert not list(ws.rglob("*hidden*"))

    passed, failed, out, rc = score_hidden_tests(ws, task, "smoke", timeout_s=60)
    assert passed + failed > 0
    # 真实执行痕迹：pytest 点号/摘要/错误任一
    assert out.strip(), "评分输出不得为空"
    assert rc == 0 or failed > 0 or "error" in out.lower() or "failed" in out.lower()


def test_run_metrics_fields_present() -> None:
    task = load_task("smoke", "T001")

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=2, failed=0, returncode=0)

    out = run_single_task(
        task, suite="smoke", on_node_test=on_test, with_hidden_scoring=False
    )
    m = out.metrics
    # Gate-M1 报告字段
    for field in (
        "resolve",
        "test_pass_ratio",
        "iterations",
        "tokens_in",
        "tokens_out",
        "wall_s",
        "status",
    ):
        assert hasattr(m, field)
    assert m.wall_s >= 0
    assert 0.0 <= m.test_pass_ratio <= 1.0


# --------------------------------------------------------------------------- #
# 事件顺序（LLM mock）
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'm1.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_event_order_with_llm_mock() -> None:
    """run_started → (node_enter → llm_delta×N → test_result → node_exit)* → run_finished。"""
    task = load_task("smoke", "T001")
    mock = make_mock_llm()
    seen: list = []

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(iteration=int(state.get("iteration") or 0), passed=1, failed=0, returncode=0)

    out = run_single_task(
        task,
        suite="smoke",
        llm=mock,
        on_node_test=on_test,
        with_hidden_scoring=False,
        event_subscribers=[seen.append],
    )

    assert mock.calls  # LLM mock 被调用
    types = [e.type for e in seen]
    assert types[0] is EventType.RUN_STARTED
    assert types[-1] is EventType.RUN_FINISHED
    assert types.count(EventType.NODE_ENTER) >= 1
    assert types.count(EventType.NODE_EXIT) >= 1
    assert EventType.LLM_DELTA in types
    assert EventType.TEST_RESULT in types

    # 相对顺序：node_enter 在 llm_delta 前，llm_delta 在 test_result 前
    i_enter = types.index(EventType.NODE_ENTER)
    i_delta = types.index(EventType.LLM_DELTA)
    i_test = types.index(EventType.TEST_RESULT)
    i_exit = types.index(EventType.NODE_EXIT)
    assert i_enter < i_delta < i_test < i_exit

    # seq 单调 + 落库一致
    assert_seq_monotonic(seen)
    with session_scope() as s:
        stored = load_events(s, out.run_id)
        assert_seq_monotonic(stored)
        assert [e.seq for e in stored] == [e.seq for e in seen]
        assert [e.type for e in stored] == types


def test_llm_mock_streams_multiple_deltas() -> None:
    task = load_task("smoke", "T001")
    seen: list = []
    mock = make_mock_llm()

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=0, failed=0, returncode=0)

    run_single_task(
        task,
        suite="smoke",
        llm=mock,
        on_node_test=on_test,
        with_hidden_scoring=False,
        event_subscribers=[seen.append],
    )
    deltas = [e for e in seen if e.type is EventType.LLM_DELTA]
    assert len(deltas) >= 2  # 多行 → 多 delta，非整段单发
    joined = "".join(e.payload.get("text", "") for e in deltas)
    assert "PLAN" in joined


def test_graph_condition_success_uses_mock_llm() -> None:
    task = TaskDefinition(id="TX", title="t", prompt="p", max_iterations=2)
    mock = make_mock_llm()
    graph = build_graph(llm=mock, on_test=lambda s: TestRecord(iteration=0, passed=1, failed=0, returncode=0), checkpointer=None)
    final = graph.invoke(initial_state(task))
    assert final["status"] == "success"
    assert mock.calls == ["TX"]
    assert final["plan"]


def test_graph_condition_timeout_loop_mock() -> None:
    task = TaskDefinition(id="TY", title="t", prompt="p", max_iterations=3)
    mock = make_mock_llm()

    def always_fail(s: AgentState) -> TestRecord:
        return TestRecord(iteration=int(s.get("iteration") or 0), passed=0, failed=1, returncode=1)

    graph = build_graph(llm=mock, on_test=always_fail, checkpointer=None)
    final = graph.invoke(initial_state(task))
    assert final["status"] == "timeout"
    assert final["iteration"] == 3
    assert len(mock.calls) == 3  # 每轮一次 LLM
