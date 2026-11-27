"""沙箱 workspace：run 独立副本、路径 jail、子进程超时与输出截断。

architecture.md §5.2：
- 每 run：``data/workspaces/{run_id}/`` = 目标仓库完整副本
- 执行：subprocess，cwd=workspace，超时（默认 120s），stdout/stderr 截断（默认 20k，保头尾）
- 隐藏测试评分阶段才注入；Agent 期间 workspace 不含 hidden_tests
- 结束保留 workspace；启动清理 >7 天目录（CLI 生命周期，M4）
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings
from app.sandbox.jail import PathJailError, ensure_within, resolve_in_workspace

DEFAULT_TIMEOUT_S = 120.0
DEFAULT_OUTPUT_LIMIT = 20_000
# 不拷贝的目录名
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".mypy_cache",
        "data",
    }
)


class WorkspaceError(Exception):
    """workspace 创建/执行错误。"""


@dataclass(slots=True)
class ExecResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    wall_s: float
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def truncate_output(text: str, limit: int = DEFAULT_OUTPUT_LIMIT) -> tuple[str, bool]:
    """保头尾截断；返回 (text, was_truncated)。"""
    if len(text) <= limit:
        return text, False
    half = max(1, limit // 2)
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - (len(head) + len(tail))
    return f"{head}\n...[输出截断 {omitted} 字符]...\n{tail}", True


def workspace_root() -> Path:
    # 每次 load（不走 lru_cache），保证测试 monkeypatch WORKSPACE_ROOT 生效
    root = Path(load_settings().workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def workspace_path(run_id: str) -> Path:
    if not run_id or any(c in run_id for c in "/\\.."):
        raise WorkspaceError(f"非法 run_id: {run_id!r}")
    return workspace_root() / run_id


def copy_workspace(src: Path | str, run_id: str) -> Path:
    """把仓库完整副本到 ``data/workspaces/{run_id}/``。"""
    src_path = Path(src).resolve()
    if not src_path.is_dir():
        raise WorkspaceError(f"源仓库不存在或不是目录: {src_path}")
    dest = workspace_path(run_id)
    if dest.exists():
        raise WorkspaceError(f"workspace 已存在: {dest}")
    try:
        shutil.copytree(
            src_path,
            dest,
            ignore=shutil.ignore_patterns(*_SKIP_DIRS, "*.pyc"),
        )
    except OSError as e:
        raise WorkspaceError(f"复制 workspace 失败: {e}") from e
    return dest


def prepare_workspace(
    repo_path: Path | str,
    run_id: str,
    *,
    hidden_tests: Path | str | None = None,
) -> Path:
    """创建 workspace 副本；默认**不含**隐藏测试（评分阶段再注入）。"""
    ws = copy_workspace(repo_path, run_id)
    if hidden_tests is not None:
        inject_hidden_tests(ws, hidden_tests)
    return ws


def inject_hidden_tests(workspace: Path, hidden_tests: Path | str) -> list[str]:
    """评分阶段注入隐藏测试文件；返回注入的相对路径列表。"""
    src = Path(hidden_tests).resolve()
    if not src.exists():
        raise WorkspaceError(f"隐藏测试不存在: {src}")
    injected: list[str] = []
    files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]
    for f in files:
        rel = Path(f.name) if src.is_file() else f.relative_to(src)
        dest = workspace / rel
        ensure_within(workspace, dest.parent if dest.parent != dest else dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        injected.append(rel.as_posix())
    return injected


def cleanup_workspace(run_id: str) -> None:
    dest = workspace_path(run_id)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def cleanup_stale_workspaces(*, max_age_days: float = 7.0, now: float | None = None) -> list[str]:
    """删除超过 max_age_days 未修改的 workspace；返回被删 run_id。"""
    root = workspace_root()
    current = now if now is not None else time.time()
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = current - child.stat().st_mtime
        except OSError:
            continue
        if age > max_age_days * 86400:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def run_command(
    command: list[str],
    *,
    cwd: Path | str,
    timeout_s: float | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """在 workspace 内执行白名单命令；超时杀进程；输出保头尾截断。

    注意：command 必须是 argv 列表（无 shell），调用方负责白名单校验。
    """
    cwd_path = Path(cwd).resolve()
    if not cwd_path.is_dir():
        raise WorkspaceError(f"cwd 不存在: {cwd_path}")
    timeout = timeout_s if timeout_s is not None else load_settings().tool_timeout_s
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 — argv 白名单由上层保证，无 shell
            command,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        wall = time.monotonic() - started
        out, t1 = truncate_output((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), output_limit)
        err, t2 = truncate_output((e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""), output_limit)
        return ExecResult(
            command=list(command),
            returncode=-1,
            stdout=out,
            stderr=err or f"超时 {timeout}s",
            timed_out=True,
            wall_s=wall,
            truncated=t1 or t2,
        )
    except FileNotFoundError as e:
        raise WorkspaceError(f"命令不存在: {command[0] if command else '?'}") from e
    wall = time.monotonic() - started
    stdout, t1 = truncate_output(proc.stdout or "", output_limit)
    stderr, t2 = truncate_output(proc.stderr or "", output_limit)
    return ExecResult(
        command=list(command),
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
        wall_s=wall,
        truncated=t1 or t2,
    )


def read_in_workspace(workspace: Path, path: str) -> Path:
    """jail 内解析（供工具复用）。"""
    try:
        return resolve_in_workspace(workspace, path)
    except PathJailError:
        raise
