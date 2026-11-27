"""harness runner：workspace、隐藏测试评分、metrics 落库、事件流（LLM stub）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.state import AgentState, TestRecord
from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.events import EventType, assert_seq_monotonic, load_events
from app.harness.loader import load_task
from app.harness.runner import (
    _parse_pytest_counts,
    find_repo_root,
    new_run_id,
    run_single_task,
    score_hidden_tests,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'runner.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_find_repo_root() -> None:
    p = find_repo_root("sample_repo")
    assert (p / "orderlib").is_dir()


def test_parse_pytest_counts() -> None:
    assert _parse_pytest_counts("5 passed in 0.1s") == (5, 0)
    assert _parse_pytest_counts("2 passed, 3 failed in 0.1s") == (2, 3)
    assert _parse_pytest_counts("4 failed in 0.1s") == (0, 4)
    assert _parse_pytest_counts("") == (0, 0)


def test_score_hidden_tests_runs_real_pytest() -> None:
    task = load_task("smoke", "T001")
    # 用临时 workspace：复制 sample_repo 后注入
    from app.sandbox.workspace import prepare_workspace

    rid = new_run_id()
    ws = prepare_workspace(find_repo_root("sample_repo"), rid, hidden_tests=None)
    passed, failed, out, rc = score_hidden_tests(ws, task, "smoke", timeout_s=60)
    # 当前 sample_repo 未实现大小写不敏感 → 隐藏测试应失败（真实执行）
    assert passed + failed > 0
    assert failed > 0 or passed > 0
    assert isinstance(out, str)


def test_run_single_task_stub_llm_end_to_end() -> None:
    task = load_task("smoke", "T001")

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(
            iteration=int(state.get("iteration") or 0),
            passed=1,
            failed=1,
            returncode=1,
            output_tail="1 failed",
        )

    outcome = run_single_task(
        task,
        suite="smoke",
        provider="ollama",
        memory_on=False,
        llm=None,
        on_node_test=on_test,
        with_hidden_scoring=True,
    )
    assert outcome.run_id
    assert outcome.metrics.wall_s >= 0
    assert outcome.metrics.iterations >= 1
    # 真实隐藏测试已执行：resolve 与 pass_ratio 一致
    assert outcome.metrics.resolve is (outcome.metrics.test_pass_ratio == 1.0)
    assert outcome.status in {"success", "timeout", "error"}

    # 事件落库且 seq 单调
    with session_scope() as s:
        events = load_events(s, outcome.run_id)
        assert_seq_monotonic(events)
        types = [e.type for e in events]
        assert types[0] is EventType.RUN_STARTED
        assert types[-1] is EventType.RUN_FINISHED
        assert EventType.LLM_DELTA in types
        assert any(e.payload.get("phase") == "hidden_scoring" for e in events if e.type is EventType.TEST_RESULT)

        from app.db.models import RunRow

        row = s.get(RunRow, outcome.run_id)
        assert row is not None
        assert row.status == outcome.status
        assert row.metrics_json is not None
        assert "resolve" in row.metrics_json
        assert row.diff_path is not None


def test_hidden_tests_absent_from_workspace_during_agent() -> None:
    """Agent 期间 workspace 不含隐藏测试文件。"""
    from app.sandbox.workspace import prepare_workspace

    rid = new_run_id()
    ws = prepare_workspace(find_repo_root("sample_repo"), rid, hidden_tests=None)
    assert not (ws / "test_discount_hidden.py").exists()
    # hidden_tests 目录也不应出现
    matches = list(ws.rglob("*hidden*"))
    assert matches == []


def test_run_id_unique() -> None:
    assert new_run_id() != new_run_id()
