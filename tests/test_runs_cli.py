"""runs 子命令：列表过滤、详情、退出码、events/diff。"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.main import app
from app.db.session import init_db, reset_engine_for_tests, session_scope

runner = CliRunner()


@pytest.fixture(autouse=True)
def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def _seed_run(
    run_id: str = "run_test_1",
    *,
    task_id: str = "T001",
    suite: str = "smoke",
    status: str = "success",
) -> None:
    from app.db.models import RunRow

    with session_scope() as s:
        s.add(
            RunRow(
                id=run_id,
                task_id=task_id,
                suite=suite,
                status=status,
                provider="ollama",
                model="qwen3.5:9b",
                iteration=2,
                metrics_json={"resolve": True, "iterations": 2, "wall_s": 1.5},
                diff_path=None,
            )
        )


def test_list_empty() -> None:
    r = runner.invoke(app, ["runs", "list"])
    assert r.exit_code == 0
    assert "无匹配" in r.stdout or "runs" in r.stdout


def test_list_shows_seeded() -> None:
    _seed_run()
    r = runner.invoke(app, ["runs", "list"])
    assert r.exit_code == 0
    assert "run_test_1" in r.stdout
    assert "T001" in r.stdout


def test_list_filter_task_and_status() -> None:
    _seed_run("r1", task_id="T001", status="success")
    _seed_run("r2", task_id="T002", status="error")
    r = runner.invoke(app, ["runs", "list", "--task", "T002"])
    assert r.exit_code == 0
    assert "T002" in r.stdout
    assert "T001" not in r.stdout

    r2 = runner.invoke(app, ["runs", "list", "--status", "error"])
    assert "error" in r2.stdout
    assert "run_test" not in r2.stdout  # r1 是 success


def test_show_missing_exit_1() -> None:
    r = runner.invoke(app, ["runs", "show", "no_such_run"])
    assert r.exit_code == 1
    assert "不存在" in r.stdout


def test_show_detail() -> None:
    _seed_run()
    r = runner.invoke(app, ["runs", "show", "run_test_1"])
    assert r.exit_code == 0
    assert "run_test_1" in r.stdout
    assert "metrics" in r.stdout


def test_show_events_empty_ok() -> None:
    _seed_run()
    r = runner.invoke(app, ["runs", "show", "run_test_1", "--events"])
    assert r.exit_code == 0
    assert "events" in r.stdout


def test_show_events_with_events() -> None:
    from app.db.models import RunEventRow

    _seed_run()
    with session_scope() as s:
        s.add(
            RunEventRow(
                run_id="run_test_1",
                seq=1,
                type="run_started",
                payload_json={"task_id": "T001"},
            )
        )
        s.add(
            RunEventRow(
                run_id="run_test_1",
                seq=2,
                type="node_enter",
                payload_json={"node": "planner"},
            )
        )
        s.add(
            RunEventRow(
                run_id="run_test_1",
                seq=3,
                type="llm_delta",
                payload_json={"text": "hello"},
            )
        )
        s.flush()
    r = runner.invoke(app, ["runs", "show", "run_test_1", "--events"])
    assert r.exit_code == 0
    assert "run_started" in r.stdout
    assert "node_enter" in r.stdout
    assert "llm_delta" in r.stdout


def test_show_events_limit() -> None:
    from app.db.models import RunEventRow

    _seed_run()
    with session_scope() as s:
        for i in range(1, 6):
            s.add(
                RunEventRow(
                    run_id="run_test_1",
                    seq=i,
                    type="llm_delta",
                    payload_json={"text": f"t{i}"},
                )
            )
    r = runner.invoke(app, ["runs", "show", "run_test_1", "--events", "--limit", "2"])
    assert r.exit_code == 0
    assert "显示前 2" in r.stdout
    assert "其余" in r.stdout


def test_show_diff_missing() -> None:
    _seed_run()
    r = runner.invoke(app, ["runs", "show", "run_test_1", "--diff"])
    assert r.exit_code == 0
    assert "无 diff" in r.stdout or "空 diff" in r.stdout
