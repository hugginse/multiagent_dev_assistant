"""run_events 全节点覆盖：node_enter/exit、tool_call/result、test_result、seq 单调。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.state import AgentState, TestRecord
from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.events import EventType, assert_seq_monotonic, load_events
from app.harness.loader import load_task
from app.harness.runner import run_single_task


@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'evcov.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def _pass_test(state: AgentState) -> TestRecord:
    return TestRecord(
        iteration=int(state.get("iteration") or 0),
        passed=2,
        failed=0,
        returncode=0,
    )


def test_run_events_cover_all_five_nodes() -> None:
    task = load_task("smoke", "T001")
    seen: list = []

    out = run_single_task(
        task,
        suite="smoke",
        on_node_test=_pass_test,
        with_hidden_scoring=True,
        event_subscribers=[seen.append],
    )

    with session_scope() as s:
        evs = load_events(s, out.run_id)

    assert_seq_monotonic(evs)
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))

    types = [e.type for e in evs]
    assert types[0] is EventType.RUN_STARTED
    assert types[-1] is EventType.RUN_FINISHED

    enters = [e.payload.get("node") for e in evs if e.type is EventType.NODE_ENTER]
    exits = [e.payload.get("node") for e in evs if e.type is EventType.NODE_EXIT]
    for n in ("planner", "explorer", "coder", "tester", "reviewer"):
        assert n in enters, f"missing node_enter: {n} (got {enters})"
        assert n in exits, f"missing node_exit: {n} (got {exits})"
        assert enters.count(n) == exits.count(n), f"{n} enter/exit 不配对"

    assert any(e.type is EventType.TOOL_CALL for e in evs)
    assert any(e.type is EventType.TOOL_RESULT for e in evs)

    test_results = [e for e in evs if e.type is EventType.TEST_RESULT]
    assert len(test_results) >= 2
    phases = {e.payload.get("phase", "agent") for e in test_results}
    assert "hidden_scoring" in phases

    assert any(e.type is EventType.LLM_DELTA for e in evs)
    assert len(seen) == len(evs)


def test_node_enter_after_run_started_exit_before_finished() -> None:
    task = load_task("smoke", "T001")
    out = run_single_task(
        task,
        suite="smoke",
        on_node_test=_pass_test,
        with_hidden_scoring=False,
    )
    with session_scope() as s:
        evs = load_events(s, out.run_id)

    first_enter = next(i for i, e in enumerate(evs) if e.type is EventType.NODE_ENTER)
    assert evs[0].type is EventType.RUN_STARTED
    assert first_enter > 0

    last_exit = max(i for i, e in enumerate(evs) if e.type is EventType.NODE_EXIT)
    assert evs[-1].type is EventType.RUN_FINISHED
    assert last_exit < len(evs) - 1

    # 每个 node_enter 都能找到同名 node_exit
    for e in evs:
        if e.type is EventType.NODE_ENTER:
            n = e.payload.get("node")
            assert any(
                x.type is EventType.NODE_EXIT and x.payload.get("node") == n for x in evs
            ), f"node {n} 缺少 exit"


def test_tool_events_carry_node_name() -> None:
    task = load_task("smoke", "T001")
    out = run_single_task(
        task,
        suite="smoke",
        on_node_test=_pass_test,
        with_hidden_scoring=False,
    )
    with session_scope() as s:
        evs = load_events(s, out.run_id)
    tool_calls = [e for e in evs if e.type is EventType.TOOL_CALL]
    assert tool_calls
    for e in tool_calls:
        assert e.payload.get("node"), "tool_call 必须带 node"
        assert e.payload.get("name")
