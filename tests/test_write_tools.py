"""写入工具 workspace 约束与 edit 唯一性测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.registry import AuthorizationError, Tier, ToolError, ToolRegistry
from app.tools.write_tools import register_write_tools, write_tool_handlers


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "dup.txt").write_text("X\nX\n", encoding="utf-8")
    return root


def test_write_file_inside_workspace(ws: Path) -> None:
    h = write_tool_handlers(ws)
    msg = h["write_file"]("new/mod.py", "a = 1\n")
    assert "wrote" in msg
    assert (ws / "new" / "mod.py").read_text(encoding="utf-8") == "a = 1\n"


def test_write_file_escape_rejected(ws: Path, tmp_path: Path) -> None:
    h = write_tool_handlers(ws)
    with pytest.raises(ToolError, match="越出"):
        h["write_file"]("../evil.py", "x")
    with pytest.raises(ToolError, match="越出"):
        h["write_file"](str(tmp_path / "evil.py"), "x")


def test_write_file_cannot_overwrite_dir(ws: Path) -> None:
    h = write_tool_handlers(ws)
    (ws / "adir").mkdir()
    with pytest.raises(ToolError, match="目录"):
        h["write_file"]("adir", "x")


def test_edit_file_unique_replace(ws: Path) -> None:
    h = write_tool_handlers(ws)
    msg = h["edit_file"]("app.py", "return 1", "return 42")
    assert "1 replacement" in msg
    assert "return 42" in (ws / "app.py").read_text(encoding="utf-8")


def test_edit_file_ambiguous_requires_unique(ws: Path) -> None:
    h = write_tool_handlers(ws)
    with pytest.raises(ToolError, match="出现 2 次"):
        h["edit_file"]("dup.txt", "X", "Y")


def test_edit_file_replace_all(ws: Path) -> None:
    h = write_tool_handlers(ws)
    h["edit_file"]("dup.txt", "X", "Y", replace_all=True)
    assert (ws / "dup.txt").read_text(encoding="utf-8") == "Y\nY\n"


def test_edit_file_old_not_found(ws: Path) -> None:
    h = write_tool_handlers(ws)
    with pytest.raises(ToolError, match="未在"):
        h["edit_file"]("app.py", "NOPE", "x")


def test_edit_file_escape(ws: Path) -> None:
    h = write_tool_handlers(ws)
    with pytest.raises(ToolError):
        h["edit_file"]("../outside.txt", "a", "b")


def test_write_tools_auth_coder_only(ws: Path) -> None:
    reg = ToolRegistry()
    register_write_tools(reg, ws)
    assert reg.get("write_file").tier is Tier.W
    # coder 可写
    reg.call("write_file", {"path": "z.py", "content": "1"}, node="coder")
    # explorer / tester 不可写
    with pytest.raises(AuthorizationError):
        reg.call("write_file", {"path": "z2.py", "content": "1"}, node="explorer")
    with pytest.raises(AuthorizationError):
        reg.call("edit_file", {"path": "z.py", "old_string": "1", "new_string": "2"}, node="tester")
