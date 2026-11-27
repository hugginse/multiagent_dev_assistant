"""记忆 A/B 模式与 episode 沉淀接线测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.eval_cmd_impl import execute_eval, execute_memory_ab
from app.db.session import init_db, reset_engine_for_tests


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ab.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_execute_eval_returns_path(tmp_path: Path) -> None:
    # 用 limit=1 + smoke，不跑 LLM 会很慢——这里只验证签名与错误路径
    code, path = execute_eval(
        suite="no_such_suite", k=1, provider="ollama", memory="off", limit=None
    )
    assert code == 2
    assert path is None


def test_execute_eval_bad_memory() -> None:
    code, path = execute_eval(
        suite="smoke", k=1, provider="ollama", memory="maybe", limit=0
    )
    assert code == 2
    assert path is None


def test_memory_ab_rejects_bad_suite() -> None:
    # 套件不存在 → 第一次 execute_eval 返回 2, None
    code = execute_memory_ab(suite="nope", k=1, provider="ollama", limit=None)
    assert code in {1, 2}


def test_ab_flag_registered() -> None:
    from typer.testing import CliRunner

    from app.cli.main import app

    r = CliRunner().invoke(app, ["eval", "--help"])
    assert r.exit_code == 0
    assert "--ab" in r.stdout


def test_runner_emits_episode_when_memory_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """memory_on 时 run 终态尝试 episode 沉淀（不抛错）。"""
    from app.agents.state import AgentState, TestRecord
    from app.db.session import session_scope
    from app.events import EventType, load_events
    from app.harness.loader import load_task
    from app.harness.runner import run_single_task

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ep_run.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()

    task = load_task("smoke", "T001")

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=1, failed=0, returncode=0)

    out = run_single_task(
        task,
        suite="smoke",
        on_node_test=on_test,
        with_hidden_scoring=False,
        memory_on=True,
    )
    with session_scope() as s:
        evs = load_events(s, out.run_id)
    # memory_on → 至少有 MEMORY_INJECTED（episode 或 search）
    mem_events = [e for e in evs if e.type is EventType.MEMORY_INJECTED]
    assert mem_events, "memory_on 应产生 memory_injected 事件"
    # episode 沉淀（可能因 chroma/embed 失败仅 error，但正常路径有 phase=episode）
    phases = {e.payload.get("phase") for e in mem_events}
    assert "episode" in phases or any(e.payload.get("chars") for e in mem_events)
