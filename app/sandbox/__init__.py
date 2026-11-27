"""沙箱：路径 jail 与 workspace 管理。"""

from app.sandbox.jail import PathJailError, resolve_in_workspace

__all__ = ["PathJailError", "resolve_in_workspace"]
