"""只读工具与路径 jail 负向测试。"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from app.sandbox.jail import PathJailError, resolve_in_workspace
from app.tools.fs_tools import fs_tool_handlers, register_fs_tools
from app.tools.registry import Tier, ToolError, ToolRegistry


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "hello.py").write_text("print('hi')\n# TODO fix\n", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    # 真实文件用于符号链接测试
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET", encoding="utf-8")
    link = root / "escape_link.txt"
    with contextlib.suppress(OSError):
        link.symlink_to(outside)  # 某些环境禁 symlink
    return root


# --------------------------------------------------------------------------- #
# 路径 jail
# --------------------------------------------------------------------------- #
def test_jail_blocks_dotdot_escape(ws: Path) -> None:
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "../secret.txt")
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "pkg/../../outside.txt")


def test_jail_blocks_absolute_outside(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, str(outside))
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "C:/Windows/System32/drivers/etc/hosts")


def test_jail_allows_inside_paths(ws: Path) -> None:
    p = resolve_in_workspace(ws, "pkg/mod.py")
    assert p.is_absolute()
    assert str(p).startswith(str(ws.resolve()))
    # 绝对路径若已在 root 内也允许
    p2 = resolve_in_workspace(ws, str(ws / "hello.py"))
    assert p2 == (ws / "hello.py").resolve()


def test_jail_blocks_symlink_escape(ws: Path, tmp_path: Path) -> None:
    link = ws / "escape_link.txt"
    if not link.is_symlink():
        pytest.skip("当前环境无法创建符号链接")
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "escape_link.txt")


def test_jail_rejects_empty_and_nul(ws: Path) -> None:
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "")
    with pytest.raises(PathJailError):
        resolve_in_workspace(ws, "a\x00b")


# --------------------------------------------------------------------------- #
# 只读工具
# --------------------------------------------------------------------------- #
def test_read_file_ok(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    assert "print" in h["read_file"]("hello.py")


def test_read_file_escape_rejected(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    with pytest.raises(ToolError, match="越出"):
        h["read_file"]("../secret.txt")


def test_read_file_missing(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    with pytest.raises(ToolError, match="不存在"):
        h["read_file"]("nope.py")


def test_list_dir(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    out = h["list_dir"](".")
    assert "hello.py" in out
    assert "pkg/" in out


def test_list_dir_escape(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    with pytest.raises(ToolError):
        h["list_dir"]("../..")


def test_grep_finds_match(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    out = h["grep"]("TODO", path=".", glob="*.py")
    assert "hello.py" in out
    assert "TODO" in out


def test_grep_escape(ws: Path) -> None:
    h = fs_tool_handlers(ws)
    with pytest.raises(ToolError):
        h["grep"]("x", path="../")


def test_read_file_output_truncated(ws: Path) -> None:
    big = ws / "big.txt"
    big.write_text("A" * 50_000, encoding="utf-8")
    h = fs_tool_handlers(ws, output_limit=1000)
    out = h["read_file"]("big.txt")
    assert len(out) < 50_000
    assert "截断" in out


# --------------------------------------------------------------------------- #
# 注册 + 授权
# --------------------------------------------------------------------------- #
def test_register_fs_tools_tier_r(ws: Path) -> None:
    reg = ToolRegistry()
    register_fs_tools(reg, ws)
    assert set(reg.names()) == {"read_file", "list_dir", "grep"}
    for name in reg.names():
        assert reg.get(name).tier is Tier.R
    # explorer（仅 R）可读
    reg.call("read_file", {"path": "hello.py"}, node="explorer")
    # coder（R+W）也可读
    reg.call("grep", {"pattern": "hi"}, node="coder")


def test_fs_tools_unknown_node_rejected(ws: Path) -> None:
    from app.tools.registry import ToolError

    reg = ToolRegistry()
    register_fs_tools(reg, ws)
    with pytest.raises(ToolError, match="未知节点"):
        reg.call("read_file", {"path": "hello.py"}, node="unknown_node")
