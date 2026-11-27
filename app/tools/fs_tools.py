"""只读工具：read_file / grep / list_dir（全部经路径 jail）。"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from app.sandbox.jail import PathJailError, resolve_in_workspace
from app.tools.registry import Tier, ToolError, ToolRegistry, ToolSpec

DEFAULT_OUTPUT_LIMIT = 20_000


def _truncate(text: str, limit: int = DEFAULT_OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    head = text[:half]
    tail = text[-half:]
    return f"{head}\n...[截断 {len(text) - limit} 字符]...\n{tail}"


def make_read_file(workspace: Path, *, output_limit: int = DEFAULT_OUTPUT_LIMIT):
    def read_file(path: str, *, max_chars: int | None = None) -> str:
        try:
            target = resolve_in_workspace(workspace, path)
        except PathJailError as e:
            raise ToolError(str(e)) from e
        if not target.exists():
            raise ToolError(f"文件不存在: {path}")
        if target.is_dir():
            raise ToolError(f"是目录不是文件: {path}")
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ToolError(f"读取失败: {e}") from e
        limit = max_chars if max_chars is not None else output_limit
        return _truncate(text, limit)

    return read_file


def make_list_dir(workspace: Path, *, output_limit: int = DEFAULT_OUTPUT_LIMIT):
    def list_dir(path: str = ".", *, recursive: bool = False, max_entries: int = 500) -> str:
        try:
            target = resolve_in_workspace(workspace, path)
        except PathJailError as e:
            raise ToolError(str(e)) from e
        if not target.exists():
            raise ToolError(f"目录不存在: {path}")
        if not target.is_dir():
            raise ToolError(f"不是目录: {path}")

        lines: list[str] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        for count, entry in enumerate(sorted(iterator, key=lambda p: str(p).lower())):
            if count >= max_entries:
                lines.append(f"...（超过 {max_entries} 条，已截断）")
                break
            rel = entry.relative_to(target)
            prefix = str(rel).replace("\\", "/")
            if entry.is_dir():
                lines.append(f"{prefix}/")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = -1
                lines.append(f"{prefix}  ({size}B)")
        if not lines:
            return "(空目录)"
        return _truncate("\n".join(lines), output_limit)

    return list_dir


def make_grep(workspace: Path, *, output_limit: int = DEFAULT_OUTPUT_LIMIT):
    def grep(
        pattern: str,
        path: str = ".",
        *,
        glob: str = "*",
        max_matches: int = 200,
        ignore_case: bool = False,
    ) -> str:
        import re

        flags = re.IGNORECASE if ignore_case else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise ToolError(f"非法正则: {e}") from e
        try:
            root = resolve_in_workspace(workspace, path)
        except PathJailError as e:
            raise ToolError(str(e)) from e
        if not root.exists():
            raise ToolError(f"路径不存在: {path}")

        matches: list[str] = []
        files = [root] if root.is_file() else [
            p for p in root.rglob("*") if p.is_file() and not _is_skipped(p)
        ]
        for f in sorted(files, key=lambda p: str(p).lower()):
            if len(matches) >= max_matches:
                matches.append(f"...（超过 {max_matches} 条，已截断）")
                break
            if not fnmatch.fnmatch(f.name, glob):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if rx.search(line):
                    rel = f.relative_to(workspace).as_posix()
                    matches.append(f"{rel}:{i}:{line.rstrip()}")
                    if len(matches) >= max_matches:
                        break
        if not matches:
            return "(无匹配)"
        return _truncate("\n".join(matches), output_limit)

    return grep


def _is_skipped(p: Path) -> bool:
    parts = {part.lower() for part in p.parts}
    return bool(parts & {"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache"})


def register_fs_tools(registry: ToolRegistry, workspace: Path, *, output_limit: int = DEFAULT_OUTPUT_LIMIT) -> None:
    """把只读工具注册进 registry（tier=R）。"""
    registry.register(
        ToolSpec(
            name="read_file",
            description="读取 workspace 内单个文件内容（路径 jail）。",
            tier=Tier.R,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 workspace 的文件路径"},
                    "max_chars": {"type": "integer", "description": "可选，最大返回字符数"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            timeout_s=10.0,
            output_limit_chars=output_limit,
            handler=make_read_file(workspace, output_limit=output_limit),
        )
    )
    registry.register(
        ToolSpec(
            name="list_dir",
            description="列出 workspace 内目录条目（路径 jail）。",
            tier=Tier.R,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对目录，默认 '.'"},
                    "recursive": {"type": "boolean", "default": False},
                    "max_entries": {"type": "integer", "default": 500},
                },
                "additionalProperties": False,
            },
            timeout_s=10.0,
            output_limit_chars=output_limit,
            handler=make_list_dir(workspace, output_limit=output_limit),
        )
    )
    registry.register(
        ToolSpec(
            name="grep",
            description="在 workspace 内按正则搜索（路径 jail）。",
            tier=Tier.R,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python 正则"},
                    "path": {"type": "string", "default": "."},
                    "glob": {"type": "string", "default": "*"},
                    "max_matches": {"type": "integer", "default": 200},
                    "ignore_case": {"type": "boolean", "default": False},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            timeout_s=15.0,
            output_limit_chars=output_limit,
            handler=make_grep(workspace, output_limit=output_limit),
        )
    )


def fs_tool_handlers(workspace: Path, **kwargs: Any) -> dict[str, Any]:
    """测试便捷：直接拿 handler dict。"""
    return {
        "read_file": make_read_file(workspace, **kwargs),
        "list_dir": make_list_dir(workspace, **kwargs),
        "grep": make_grep(workspace, **kwargs),
    }
