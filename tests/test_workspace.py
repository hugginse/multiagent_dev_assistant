"""沙箱 workspace：副本、jail、超时、输出截断。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.sandbox.workspace import (
    WorkspaceError,
    cleanup_stale_workspaces,
    cleanup_workspace,
    copy_workspace,
    inject_hidden_tests,
    prepare_workspace,
    run_command,
    truncate_output,
    workspace_path,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (r / "__pycache__").mkdir()
    (r / "__pycache__" / "j.pyc").write_text("junk", encoding="utf-8")
    return r


def test_copy_workspace_creates_isolated_copy(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    dest = copy_workspace(repo, "run_abc")
    assert dest == tmp_path / "wsroot" / "run_abc"
    assert (dest / "src" / "main.py").exists()
    # 不拷贝 __pycache__
    assert not (dest / "__pycache__").exists()
    # 隔离：改副本不影响源
    (dest / "src" / "main.py").write_text("changed", encoding="utf-8")
    assert "print" in (repo / "src" / "main.py").read_text(encoding="utf-8")


def test_copy_workspace_duplicate_run_id(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    copy_workspace(repo, "run_1")
    with pytest.raises(WorkspaceError, match="已存在"):
        copy_workspace(repo, "run_1")


def test_prepare_workspace_excludes_hidden_by_default(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text("def test_h():\n    assert True\n", encoding="utf-8")

    ws = prepare_workspace(repo, "run_no_hidden")
    assert not (ws / "test_hidden.py").exists()

    ws2 = prepare_workspace(repo, "run_with_hidden", hidden_tests=hidden)
    assert (ws2 / "test_hidden.py").exists()


def test_inject_hidden_tests_files(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    hidden = tmp_path / "ht"
    (hidden / "sub").mkdir(parents=True)
    (hidden / "sub" / "test_x.py").write_text("pass\n", encoding="utf-8")
    ws = prepare_workspace(repo, "run_inj")
    injected = inject_hidden_tests(ws, hidden)
    assert injected == ["sub/test_x.py"]
    assert (ws / "sub" / "test_x.py").exists()


def test_run_command_success_and_truncate(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    ws = prepare_workspace(repo, "run_exec")
    r = run_command(
        ["python", "-c", "print('A'*30000)"],
        cwd=ws,
        timeout_s=30,
        output_limit=1000,
    )
    assert r.ok
    assert r.truncated
    assert len(r.stdout) < 30_000
    assert "截断" in r.stdout


def test_run_command_timeout(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    ws = prepare_workspace(repo, "run_to")
    r = run_command(
        ["python", "-c", "import time; time.sleep(30)"],
        cwd=ws,
        timeout_s=1.0,
    )
    assert r.timed_out
    assert not r.ok
    assert r.wall_s >= 1.0


def test_run_command_nonzero_exit(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    ws = prepare_workspace(repo, "run_fail")
    r = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=ws, timeout_s=15)
    assert r.returncode == 3
    assert not r.ok


def test_truncate_output_keeps_head_tail() -> None:
    text = "H" * 500 + "M" * 5000 + "T" * 500
    out, truncated = truncate_output(text, 1000)
    assert truncated
    assert out.startswith("H")
    assert out.endswith("T")
    assert "输出截断" in out


def test_cleanup_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    copy_workspace(repo, "run_old")
    cleanup_workspace("run_old")
    assert not workspace_path("run_old").exists()


def test_cleanup_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    copy_workspace(repo, "run_stale")
    copy_workspace(repo, "run_fresh")
    # 把 stale 的 mtime 拨回 10 天前
    stale = workspace_path("run_stale")
    old = time.time() - 10 * 86400
    import os

    os.utime(stale, (old, old))
    removed = cleanup_stale_workspaces(max_age_days=7)
    assert "run_stale" in removed
    assert workspace_path("run_fresh").exists()
    assert not stale.exists()


def test_run_id_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsroot"))
    with pytest.raises(WorkspaceError):
        workspace_path("../evil")
    with pytest.raises(WorkspaceError):
        workspace_path("a/b")
