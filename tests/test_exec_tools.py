"""执行工具白名单与授权测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.exec_tools import _sanitize_pytest_args, exec_tool_handlers, register_exec_tools
from app.tools.registry import AuthorizationError, Tier, ToolError, ToolRegistry


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (root / "tests" / "test_b.py").write_text("def test_b():\n    assert 1 == 2\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths=['tests']\n", encoding="utf-8")
    return root


def test_run_tests_real_execution(ws: Path) -> None:
    h = exec_tool_handlers(ws, timeout_s=60)
    out = h["run_tests"]("tests")
    assert "exit=" in out or "TIMEOUT" in out
    # 有失败测试 → 非 0
    assert "exit=1" in out or "failed" in out.lower()


def test_run_tests_path_escape_rejected(ws: Path) -> None:
    h = exec_tool_handlers(ws)
    with pytest.raises(ToolError):
        h["run_tests"]("../etc")


def test_run_tests_rejects_dangerous_args(ws: Path) -> None:
    h = exec_tool_handlers(ws)
    with pytest.raises(ToolError, match="不允许的参数"):
        h["run_tests"]("tests", extra_args=["--capture=no", "-s"])
    with pytest.raises(ToolError, match="不允许的参数"):
        h["run_tests"]("tests", extra_args=["-c", "import os"])


def test_sanitize_pytest_args_allows_safe() -> None:
    assert _sanitize_pytest_args(["-q", "tests/test_a.py"]) == ["-q", "tests/test_a.py"]
    assert _sanitize_pytest_args(["-k", "foo", "--maxfail", "1"]) == [
        "-k",
        "foo",
        "--maxfail",
        "1",
    ]


def test_sanitize_rejects_abs_and_dotdot() -> None:
    with pytest.raises(ToolError):
        _sanitize_pytest_args(["/etc/passwd"])
    with pytest.raises(ToolError):
        _sanitize_pytest_args(["foo/../../bar"])


def test_run_lint_runs_ruff(ws: Path) -> None:
    h = exec_tool_handlers(ws, timeout_s=60)
    out = h["run_lint"](".")
    # sample 无 ruff 配置也能跑；exit 0 或 1 均算真实执行
    assert "ruff" in out or "exit=" in out


def test_exec_tools_auth_tester_only(ws: Path) -> None:
    reg = ToolRegistry()
    register_exec_tools(reg, ws)
    assert reg.get("run_tests").tier is Tier.X
    reg.call("run_tests", {"path": "tests"}, node="tester")
    with pytest.raises(AuthorizationError):
        reg.call("run_tests", {"path": "tests"}, node="coder")
    with pytest.raises(AuthorizationError):
        reg.call("run_lint", {"path": "."}, node="explorer")
    with pytest.raises(AuthorizationError):
        reg.call("run_tests", {"path": "tests"}, node="planner")
