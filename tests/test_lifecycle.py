"""CLI 生命周期：workspace 清理与僵尸 run 修复。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.cli.lifecycle import reset_cleanup_flag, startup_cleanup
from app.db.session import init_db, reset_engine_for_tests, session_scope


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'life.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    reset_engine_for_tests()
    reset_cleanup_flag()
    init_db()
    yield
    reset_engine_for_tests()
    reset_cleanup_flag()


def test_cleanup_removes_stale_workspace(tmp_path: Path) -> None:
    import os

    from app.sandbox.workspace import workspace_path

    stale = workspace_path("run_old")
    stale.mkdir(parents=True)
    (stale / "x.txt").write_text("x", encoding="utf-8")
    old = time.time() - 10 * 86400
    os.utime(stale, (old, old))

    fresh = workspace_path("run_new")
    fresh.mkdir(parents=True)

    stats = startup_cleanup(max_age_days=7, force=True, quiet=True)
    assert "run_old" in stats["workspaces_removed"]
    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_repairs_running_runs() -> None:
    from app.db.models import RunRow

    with session_scope() as s:
        s.add(
            RunRow(
                id="run_zombie",
                task_id="T001",
                suite="smoke",
                status="running",
                provider="ollama",
                model="m",
            )
        )
        s.add(
            RunRow(
                id="run_ok",
                task_id="T001",
                suite="smoke",
                status="success",
                provider="ollama",
                model="m",
            )
        )

    stats = startup_cleanup(force=True, quiet=True)
    assert stats["runs_repaired"] >= 1

    with session_scope() as s:
        z = s.get(RunRow, "run_zombie")
        ok = s.get(RunRow, "run_ok")
        assert z is not None and z.status == "error"
        assert z.error and "interrupted" in z.error
        assert ok is not None and ok.status == "success"


def test_cleanup_runs_once_by_default() -> None:
    s1 = startup_cleanup(force=True, quiet=True)
    assert "skipped" not in s1
    s2 = startup_cleanup(quiet=True)
    assert s2.get("skipped") is True


def test_cli_version_skips_cleanup_no_crash() -> None:
    from typer.testing import CliRunner

    from app.cli.main import app

    r = CliRunner().invoke(app, ["--version"])
    assert r.exit_code == 0


def test_cli_help_runs_cleanup() -> None:
    from typer.testing import CliRunner

    from app.cli.main import app

    reset_cleanup_flag()
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    # cleanup 应已执行且不炸
