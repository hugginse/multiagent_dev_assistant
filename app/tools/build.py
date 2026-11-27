"""按 workspace 组装默认工具注册表（节点授权硬校验用）。"""

from __future__ import annotations

from pathlib import Path

from app.tools.exec_tools import register_exec_tools
from app.tools.fs_tools import register_fs_tools
from app.tools.memory_tools import register_memory_tools
from app.tools.registry import ToolRegistry
from app.tools.write_tools import register_write_tools


def build_registry(workspace: Path | str, *, timeout_s: float | None = None) -> ToolRegistry:
    """注册 R/W/X/M 全量工具；节点授权由 registry.call(node=...) 硬校验。"""
    reg = ToolRegistry()
    ws = Path(workspace)
    register_fs_tools(reg, ws)
    register_write_tools(reg, ws)
    register_exec_tools(reg, ws, timeout_s=timeout_s)
    register_memory_tools(reg)
    return reg
