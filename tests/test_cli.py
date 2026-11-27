"""CLI 骨架：入口、子命令注册、退出码。"""

from __future__ import annotations

from typer.testing import CliRunner

from app.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "devassist" in result.stdout


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("run", "eval", "report", "compare", "tasks", "runs", "memory"):
        assert name in result.stdout


def test_run_requires_task() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2


def test_tasks_list_smoke() -> None:
    result = runner.invoke(app, ["tasks", "list", "--suite", "smoke"])
    assert result.exit_code == 0
    assert "T001" in result.stdout
    assert "T002" in result.stdout
    assert "T003" in result.stdout


def test_tasks_show() -> None:
    result = runner.invoke(app, ["tasks", "show", "T001", "--suite", "smoke"])
    assert result.exit_code == 0
    assert "T001" in result.stdout
    # prompt 可见
    assert "折扣" in result.stdout or "discount" in result.stdout.lower()


def test_runs_list_empty_ok() -> None:
    result = runner.invoke(app, ["runs", "list", "--limit", "5"])
    assert result.exit_code == 0


def test_runs_show_missing() -> None:
    result = runner.invoke(app, ["runs", "show", "no_such_run"])
    assert result.exit_code == 1


def test_memory_list_ok() -> None:
    result = runner.invoke(app, ["memory", "list"])
    assert result.exit_code == 0


def test_memory_onboarding_placeholder() -> None:
    result = runner.invoke(app, ["memory", "onboarding", "--path", "sample_repo"])
    assert result.exit_code == 2


def test_compare_requires_two_paths() -> None:
    result = runner.invoke(app, ["compare"])
    assert result.exit_code == 2


def test_report_missing_eval() -> None:
    result = runner.invoke(app, ["report", "--eval", "no_such_eval_xyz"])
    assert result.exit_code == 2
