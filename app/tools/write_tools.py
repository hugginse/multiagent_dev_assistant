"""写入工具：write_file / edit_file（workspace 路径 jail 约束）。

- 仅 tier=W，由 coder 节点授权
- 一切路径经 ``resolve_in_workspace``
- edit_file：精确唯一匹配 old_string，避免静默多处替换
"""

from __future__ import annotations

from pathlib import Path

from app.sandbox.jail import PathJailError, resolve_in_workspace
from app.tools.registry import Tier, ToolError, ToolRegistry, ToolSpec


def _resolve(workspace: Path, path: str) -> Path:
    try:
        return resolve_in_workspace(workspace, path)
    except PathJailError as e:
        raise ToolError(str(e)) from e


def make_write_file(workspace: Path):
    def write_file(path: str, content: str, *, create_parents: bool = True) -> str:
        target = _resolve(workspace, path)
        if target.exists() and target.is_dir():
            raise ToolError(f"目标是目录: {path}")
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            raise ToolError(f"写入失败: {e}") from e
        return f"wrote {path} ({len(content)} chars)"

    return write_file


def make_edit_file(workspace: Path):
    def edit_file(path: str, old_string: str, new_string: str, *, replace_all: bool = False) -> str:
        if old_string == new_string:
            raise ToolError("old_string 与 new_string 相同，无变化")
        if not old_string:
            raise ToolError("old_string 不得为空")
        target = _resolve(workspace, path)
        if not target.exists():
            raise ToolError(f"文件不存在: {path}")
        if target.is_dir():
            raise ToolError(f"是目录: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as e:
            raise ToolError(f"读取失败: {e}") from e

        count = text.count(old_string)
        if count == 0:
            raise ToolError(f"old_string 未在 {path} 中找到")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string 在 {path} 中出现 {count} 次；请提供更多上下文保证唯一，"
                f"或显式 replace_all=true"
            )
        new_text = text.replace(old_string, new_string) if replace_all else text.replace(
            old_string, new_string, 1
        )
        try:
            target.write_text(new_text, encoding="utf-8")
        except OSError as e:
            raise ToolError(f"写入失败: {e}") from e
        n = count if replace_all else 1
        return f"edited {path} ({n} replacement(s))"

    return edit_file


def register_write_tools(registry: ToolRegistry, workspace: Path) -> None:
    registry.register(
        ToolSpec(
            name="write_file",
            description="写入/覆盖 workspace 内文件（路径 jail，tier=W）。",
            tier=Tier.W,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 workspace 的文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                    "create_parents": {"type": "boolean", "default": True},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            timeout_s=15.0,
            handler=make_write_file(workspace),
        )
    )
    registry.register(
        ToolSpec(
            name="edit_file",
            description=(
                "精确替换 workspace 内文件片段（路径 jail，tier=W）。"
                "old_string 必须唯一，除非 replace_all=true。"
            ),
            tier=Tier.W,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
                "additionalProperties": False,
            },
            timeout_s=15.0,
            handler=make_edit_file(workspace),
        )
    )


def write_tool_handlers(workspace: Path) -> dict:
    return {
        "write_file": make_write_file(workspace),
        "edit_file": make_edit_file(workspace),
    }
