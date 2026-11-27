"""工具注册表与 tier 授权负向测试。"""

from __future__ import annotations

import pytest

from app.tools.registry import (
    NODE_TIERS,
    AuthorizationError,
    Tier,
    ToolError,
    ToolNotFoundError,
    ToolRegistry,
    ToolSpec,
    default_registry,
)


def _make_registry() -> ToolRegistry:
    reg = default_registry()
    reg.register(
        ToolSpec(
            name="read_file",
            description="read",
            tier=Tier.R,
            handler=lambda path: f"contents:{path}",
        )
    )
    reg.register(
        ToolSpec(
            name="write_file",
            description="write",
            tier=Tier.W,
            handler=lambda path, content: len(content),
        )
    )
    reg.register(
        ToolSpec(
            name="run_tests",
            description="exec",
            tier=Tier.X,
            handler=lambda: "ok",
        )
    )
    reg.register(
        ToolSpec(
            name="memory_search",
            description="mem",
            tier=Tier.M,
            handler=lambda q: [q],
        )
    )
    return reg


def test_register_and_get() -> None:
    reg = _make_registry()
    assert reg.get("read_file").tier is Tier.R
    assert set(reg.names()) == {"read_file", "write_file", "run_tests", "memory_search"}


def test_duplicate_register_rejected() -> None:
    reg = _make_registry()
    with pytest.raises(ToolError, match="重复"):
        reg.register(ToolSpec(name="read_file", description="x", tier=Tier.R, handler=lambda: None))


def test_missing_handler_rejected() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolError, match="handler"):
        reg.register(ToolSpec(name="nope", description="x", tier=Tier.R, handler=None))


def test_unknown_tool() -> None:
    reg = _make_registry()
    with pytest.raises(ToolNotFoundError):
        reg.get("does_not_exist")


def test_explorer_cannot_write_or_exec() -> None:
    reg = _make_registry()
    with pytest.raises(AuthorizationError) as ei:
        reg.call("write_file", {"path": "a.py", "content": "x"}, node="explorer")
    assert ei.value.tier is Tier.W
    with pytest.raises(AuthorizationError):
        reg.call("run_tests", {}, node="explorer")


def test_explorer_can_read() -> None:
    reg = _make_registry()
    out = reg.call("read_file", {"path": "a.py"}, node="explorer")
    assert out == "contents:a.py"


def test_coder_cannot_exec() -> None:
    reg = _make_registry()
    with pytest.raises(AuthorizationError, match="run_tests"):
        reg.call("run_tests", {}, node="coder")
    # coder 可写
    assert reg.call("write_file", {"path": "a.py", "content": "hi"}, node="coder") == 2


def test_tester_cannot_write() -> None:
    reg = _make_registry()
    with pytest.raises(AuthorizationError, match="write_file"):
        reg.call("write_file", {"path": "a.py", "content": "x"}, node="tester")
    assert reg.call("run_tests", {}, node="tester") == "ok"


def test_planner_memory_and_read_only() -> None:
    reg = _make_registry()
    assert reg.call("memory_search", {"q": "约定"}, node="planner") == ["约定"]
    with pytest.raises(AuthorizationError):
        reg.call("write_file", {"path": "a", "content": "b"}, node="planner")
    with pytest.raises(AuthorizationError):
        reg.call("run_tests", {}, node="planner")


def test_unknown_node_rejected() -> None:
    reg = _make_registry()
    with pytest.raises(ToolError, match="未知节点"):
        reg.call("read_file", {"path": "a"}, node="hacker")


def test_handler_exception_wrapped_as_tool_error() -> None:
    reg = ToolRegistry()

    def boom() -> None:
        raise RuntimeError("kaput")

    reg.register(ToolSpec(name="boom", description="", tier=Tier.R, handler=boom))
    with pytest.raises(ToolError, match="执行失败"):
        reg.call("boom", {}, node="explorer")


def test_node_tiers_match_architecture() -> None:
    assert NODE_TIERS["explorer"] == frozenset({Tier.R})
    assert NODE_TIERS["coder"] == frozenset({Tier.R, Tier.W})
    assert NODE_TIERS["tester"] == frozenset({Tier.R, Tier.X})
    assert Tier.W not in NODE_TIERS["explorer"]
    assert Tier.X not in NODE_TIERS["coder"]


def test_schemas_filter_by_tier() -> None:
    reg = _make_registry()
    only_r = reg.schemas(tiers={Tier.R})
    names = {s["name"] for s in only_r}
    assert names == {"read_file"}
    all_names = {s["name"] for s in reg.schemas()}
    assert all_names == {"read_file", "write_file", "run_tests", "memory_search"}
