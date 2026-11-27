"""路径 jail：一切读写解析后必须落在 workspace 内。

覆盖（architecture.md §5.2、质量红线 1）：
- ``..`` 逃逸
- 绝对路径逃逸
- 符号链接逃逸（resolve 后仍在 root 外）
- 盘符 / UNC 异常

违例一律 ``PathJailError``，由工具层转为 ToolError 回灌。
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


class PathJailError(Exception):
    """路径越出 workspace。"""


def _normalize_root(root: Path) -> Path:
    # resolve(strict=False)：允许 root 尚未创建，但解析掉符号链接与 ..
    return root.resolve()


def resolve_in_workspace(root: Path | str, user_path: str | Path) -> Path:
    """把用户相对路径解析为 workspace 内绝对路径；越狱抛 PathJailError。

    - 禁止空路径
    - 拒绝含 NUL 的路径
    - 拒绝把 ``C:\\Windows`` 等绝对路径当作「相对子路径」绕过（绝对路径若不在 root 内则拒绝）
    - 符号链接：对已存在链路 ``resolve`` 后校验仍在 root 内
    """
    root_path = _normalize_root(Path(root))
    raw = str(user_path)
    if not raw or not raw.strip():
        raise PathJailError("路径为空")
    if "\x00" in raw:
        raise PathJailError("路径含 NUL")

    p = Path(user_path)

    # Windows 盘符/UNC 绝对路径：必须已位于 root 之下（一般应拒绝，除非显式在 root 内）
    if p.is_absolute() or PureWindowsPath(raw).is_absolute() or raw.startswith("\\\\"):
        try:
            resolved = Path(user_path).resolve()
        except (OSError, ValueError) as e:
            raise PathJailError(f"非法路径: {raw}") from e
        if not _is_within(root_path, resolved):
            raise PathJailError(f"绝对路径越出 workspace: {raw}")
        return resolved

    # 相对路径：拼到 root 后 resolve
    # 注意：不能先 resolve 不存在的相对路径时依赖 cwd——始终相对 root
    candidate = root_path / p
    try:
        resolved = candidate.resolve()
    except (OSError, ValueError) as e:
        raise PathJailError(f"非法路径: {raw}") from e

    # 若中间有符号链接指向外部，resolve 会落到外部 → 拒绝
    if not _is_within(root_path, resolved):
        raise PathJailError(f"路径越出 workspace: {raw}")
    return resolved


def _is_within(root: Path, target: Path) -> bool:
    """target 是否在 root 内（含 root 自身）。"""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_within(root: Path | str, target: Path) -> None:
    """对已存在路径二次校验（写入/执行前）。"""
    root_path = _normalize_root(Path(root))
    resolved = target.resolve()
    if not _is_within(root_path, resolved):
        raise PathJailError(f"路径越出 workspace: {target}")
