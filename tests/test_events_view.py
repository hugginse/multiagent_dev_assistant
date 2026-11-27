"""终端事件订阅视图与 run 实时流测试。"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from app.cli.events_view import TerminalEventSubscriber
from app.events import Event, EventType


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    c = Console(file=buf, force_terminal=False, width=200, soft_wrap=True)
    return c, buf


def test_subscriber_prints_event_types() -> None:
    c, buf = _console()
    sub = TerminalEventSubscriber(console_=c)
    sub(Event(type=EventType.RUN_STARTED, payload={"task_id": "T001", "suite": "smoke", "provider": "ollama", "model": "m", "memory_on": False}, seq=1))
    sub(Event(type=EventType.NODE_ENTER, payload={"node": "agent", "iteration": 0}, seq=2))
    sub(Event(type=EventType.LLM_DELTA, payload={"text": "你好"}, seq=3))
    sub(Event(type=EventType.LLM_DELTA, payload={"text": "世界"}, seq=4))
    sub(Event(type=EventType.TEST_RESULT, payload={"passed": 1, "failed": 0, "ok": True, "phase": "agent"}, seq=5))
    sub(Event(type=EventType.RUN_FINISHED, payload={"status": "success", "metrics": {"resolve": True, "test_pass_ratio": 1.0, "iterations": 1, "wall_s": 0.1}}, seq=6))
    sub.finish()
    out = buf.getvalue()
    assert "run_started" in out
    assert "node_enter" in out
    assert "你好世界" in out  # 真流式连续，不换行切片
    assert "test_result" in out
    assert "run_finished" in out


def test_llm_delta_suppressed_when_disabled() -> None:
    c, buf = _console()
    sub = TerminalEventSubscriber(show_llm_delta=False, console_=c)
    sub(Event(type=EventType.LLM_DELTA, payload={"text": "secret"}, seq=1))
    sub.finish()
    assert "secret" not in buf.getvalue()


def test_tool_and_error_events() -> None:
    c, buf = _console()
    sub = TerminalEventSubscriber(console_=c)
    sub(Event(type=EventType.TOOL_CALL, payload={"name": "read_file", "args": {"path": "a.py"}}, seq=1))
    sub(Event(type=EventType.TOOL_RESULT, payload={"name": "read_file", "ok": True, "summary": "ok"}, seq=2))
    sub(Event(type=EventType.ERROR, payload={"message": "boom"}, seq=3))
    sub.finish()
    out = buf.getvalue()
    assert "tool_call" in out
    assert "read_file" in out
    assert "tool_result" in out
    assert "boom" in out


@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.session import init_db, reset_engine_for_tests

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli_run.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_run_single_task_with_subscriber_collects_live_events() -> None:
    """订阅者在 run 过程中被实时调用（与落库条数一致）。"""
    from app.agents.state import AgentState, TestRecord
    from app.harness.loader import load_task
    from app.harness.runner import run_single_task

    task = load_task("smoke", "T001")
    seen: list[Event] = []

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(
            iteration=int(state.get("iteration") or 0),
            passed=1,
            failed=1,
            returncode=1,
        )

    outcome = run_single_task(
        task,
        suite="smoke",
        on_node_test=on_test,
        event_subscribers=[seen.append],
    )
    assert len(seen) >= 4
    assert seen[0].type is EventType.RUN_STARTED
    assert seen[-1].type is EventType.RUN_FINISHED
    assert any(e.type is EventType.LLM_DELTA for e in seen)
    # seq 单调且从 1 开始
    seqs = [e.seq for e in seen]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1
    assert outcome.run_id
