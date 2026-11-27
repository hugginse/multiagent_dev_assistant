"""沙箱：路径 jail 与 workspace 管理。"""

from app.sandbox.jail import PathJailError, ensure_within, resolve_in_workspace
from app.sandbox.workspace import (
    ExecResult,
    WorkspaceError,
    cleanup_stale_workspaces,
    cleanup_workspace,
    copy_workspace,
    inject_hidden_tests,
    prepare_workspace,
    run_command,
    truncate_output,
    workspace_path,
    workspace_root,
)

__all__ = [
    "ExecResult",
    "PathJailError",
    "WorkspaceError",
    "cleanup_stale_workspaces",
    "cleanup_workspace",
    "copy_workspace",
    "ensure_within",
    "inject_hidden_tests",
    "prepare_workspace",
    "resolve_in_workspace",
    "run_command",
    "truncate_output",
    "workspace_path",
    "workspace_root",
]
