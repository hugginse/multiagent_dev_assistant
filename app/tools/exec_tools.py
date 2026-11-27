"""执行工具：run_tests / run_lint（白名单命令，无任意 shell）。

architecture.md §5.1：
- 仅 tier=X，授予 tester
- 执行白名单只有 pytest / ruff 子集，参数受限
- 实际 subprocess 由 sandbox.run_command 完成（cwd=workspace、超时、截断）
"""

from __future__ import annotations

from pathlib import Path

from app.sandbox.workspace import ExecResult, run_command
from app.tools.registry import Tier, ToolError, ToolRegistry, ToolSpec

# 白名单：可执行的可执行文件名（不含路径逃逸）
ALLOWED_EXECUTABLES = frozenset({"pytest", "python", "ruff", "uv"})

# run_tests 允许的 pytest 参数前缀（禁止 -c 执行任意代码、禁止 -p 加载任意插件路径）
_PYTEST_ALLOWED_FLAGS = frozenset(
    {
        "-q",
        "-v",
        "-x",
        "--tb=auto",
        "--tb=short",
        "--tb=line",
        "--no-header",
        "--no-color",
        "-k",
        "--maxfail",
        "-p",
        "no:cacheprovider",
    }
)
_PYTEST_VALUE_FLAGS = frozenset({"-k", "--maxfail", "-p"})


def _format_result(r: ExecResult) -> str:
    status = "TIMEOUT" if r.timed_out else f"exit={r.returncode}"
    parts = [
        f"$ {' '.join(r.command)}",
        f"[{status}] wall={r.wall_s:.2f}s" + (" (输出已截断)" if r.truncated else ""),
    ]
    if r.stdout:
        parts.append("--- stdout ---")
        parts.append(r.stdout)
    if r.stderr:
        parts.append("--- stderr ---")
        parts.append(r.stderr)
    return "\n".join(parts)


def _sanitize_pytest_args(args: list[str]) -> list[str]:
    """过滤 pytest 参数：拒绝可疑 flag，只保留白名单。"""
    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        # 允许测试路径（相对、无 ..）
        if not a.startswith("-"):
            if a.startswith("/") or (len(a) > 1 and a[1] == ":") or ".." in a.split("/"):
                raise ToolError(f"非法测试路径: {a}")
            out.append(a)
            i += 1
            continue
        # -k expr / --maxfail n 等带值 flag
        base = a.split("=", 1)[0]
        if base in _PYTEST_VALUE_FLAGS or base in _PYTEST_ALLOWED_FLAGS:
            if "=" in a:
                out.append(a)
                i += 1
            elif base in _PYTEST_VALUE_FLAGS:
                if i + 1 >= len(args):
                    raise ToolError(f"参数 {a} 缺少值")
                out.append(a)
                out.append(args[i + 1])
                i += 2
            else:
                out.append(a)
                i += 1
            continue
        # -p no:xxx 形式已在 value 分支；其他一律拒绝
        raise ToolError(f"run_tests 不允许的参数: {a}")
    return out


def make_run_tests(workspace: Path, *, timeout_s: float | None = None, output_limit: int = 20_000):
    def run_tests(
        path: str = "tests",
        *,
        extra_args: list[str] | None = None,
        verbose: bool = False,
    ) -> str:
        # 固定使用 python -m pytest（避免 PATH 上任意 pytest 二进制）
        cmd: list[str] = ["python", "-m", "pytest", path]
        if verbose:
            cmd.append("-v")
        else:
            cmd.append("-q")
        if extra_args:
            cmd.extend(_sanitize_pytest_args(list(extra_args)))
        # 确保 path 不越狱
        from app.sandbox.jail import PathJailError, resolve_in_workspace

        try:
            resolve_in_workspace(workspace, path)
        except PathJailError as e:
            raise ToolError(str(e)) from e

        r = run_command(cmd, cwd=workspace, timeout_s=timeout_s, output_limit=output_limit)
        return _format_result(r)

    return run_tests


def make_run_lint(workspace: Path, *, timeout_s: float | None = None, output_limit: int = 20_000):
    def run_lint(path: str = ".") -> str:
        from app.sandbox.jail import PathJailError, resolve_in_workspace

        try:
            resolve_in_workspace(workspace, path)
        except PathJailError as e:
            raise ToolError(str(e)) from e
        # 白名单：仅 ruff check
        cmd = ["python", "-m", "ruff", "check", path]
        r = run_command(cmd, cwd=workspace, timeout_s=timeout_s, output_limit=output_limit)
        return _format_result(r)

    return run_lint


def register_exec_tools(
    registry: ToolRegistry,
    workspace: Path,
    *,
    timeout_s: float | None = None,
    output_limit: int = 20_000,
) -> None:
    registry.register(
        ToolSpec(
            name="run_tests",
            description=(
                "在 workspace 内真实执行 pytest（白名单参数，tier=X，仅 tester）。"
                "返回退出码与输出尾部。"
            ),
            tier=Tier.X,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "tests", "description": "测试路径"},
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "附加 pytest 参数（白名单）",
                    },
                    "verbose": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            timeout_s=timeout_s or 120.0,
            output_limit_chars=output_limit,
            handler=make_run_tests(workspace, timeout_s=timeout_s, output_limit=output_limit),
        )
    )
    registry.register(
        ToolSpec(
            name="run_lint",
            description="在 workspace 内执行 ruff check（白名单，tier=X，仅 tester）。",
            tier=Tier.X,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": ".", "description": "检查路径"},
                },
                "additionalProperties": False,
            },
            timeout_s=timeout_s or 60.0,
            output_limit_chars=output_limit,
            handler=make_run_lint(workspace, timeout_s=timeout_s, output_limit=output_limit),
        )
    )


def exec_tool_handlers(workspace: Path, **kwargs) -> dict:
    return {
        "run_tests": make_run_tests(workspace, **kwargs),
        "run_lint": make_run_lint(workspace, **kwargs),
    }
