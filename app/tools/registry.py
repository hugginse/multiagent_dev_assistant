"""工具注册表与 tier 授权**硬校验**（architecture.md §5.1）。

- Tier：``R`` 读 / ``W`` 写 / ``X`` 执行 / ``M`` 记忆
- 授权在 registry 层校验，**不是提示词约定**：越权 → ``AuthorizationError``（工具错误回灌，不抛崩图）
- 无任意 shell；执行类仅白名单
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Tier(StrEnum):
    R = "R"  # 读
    W = "W"  # 写
    X = "X"  # 执行
    M = "M"  # 记忆


# 节点 → 允许的 tier 集合（M2 起硬套用；M1 单节点桩可授全量只读+写+执行）
NODE_TIERS: dict[str, frozenset[Tier]] = {
    "planner": frozenset({Tier.R, Tier.M}),
    "explorer": frozenset({Tier.R}),
    "coder": frozenset({Tier.R, Tier.W}),
    "tester": frozenset({Tier.R, Tier.X}),
    "reviewer": frozenset({Tier.R, Tier.M}),
    # M1 单节点 Agent 循环占位（M2 拆成五节点）
    "agent": frozenset({Tier.R, Tier.W, Tier.X, Tier.M}),
}


class ToolError(Exception):
    """工具执行/校验失败：消息回灌给 Agent，不崩溃图。"""


class ToolNotFoundError(ToolError):
    pass


class AuthorizationError(ToolError):
    """越权调用：明确拒绝，事件中记为 rejected。"""

    def __init__(self, tool: str, node: str | None, tier: Tier) -> None:
        self.tool = tool
        self.node = node
        self.tier = tier
        msg = f"授权拒绝: 节点 {node or '?'} 无 {tier.value} 权限调用工具 {tool}"
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """单个工具的注册描述。"""

    name: str
    description: str
    tier: Tier
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False}
    )
    timeout_s: float = 120.0
    output_limit_chars: int = 20_000
    handler: Callable[..., Any] | None = None

    def json_schema(self) -> dict[str, Any]:
        """LLM tool-calling 用的 JSON Schema。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """注册、查询、按节点授权调用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ------------------------------------------------------------------ #
    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ToolError("工具名不得为空")
        if spec.name in self._tools:
            raise ToolError(f"工具重复注册: {spec.name}")
        if spec.handler is None:
            raise ToolError(f"工具 {spec.name} 缺少 handler")
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(f"未注册的工具: {name}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all_specs(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def schemas(self, tiers: Iterable[Tier] | None = None) -> list[dict[str, Any]]:
        """按 tier 过滤的工具 schema 列表（喂给 LLM）。"""
        allowed = set(tiers) if tiers is not None else None
        out = []
        for spec in self.all_specs():
            if allowed is None or spec.tier in allowed:
                out.append(spec.json_schema())
        return out

    # ------------------------------------------------------------------ #
    def check_authorization(self, tool_name: str, node: str | None) -> ToolSpec:
        """硬校验：节点是否允许该工具的 tier；越权抛 AuthorizationError。"""
        spec = self.get(tool_name)
        if node is None:
            # 未绑定节点：仅允许 R（最安全默认）
            if spec.tier is not Tier.R:
                raise AuthorizationError(tool_name, node, spec.tier)
            return spec
        allowed = NODE_TIERS.get(node)
        if allowed is None:
            raise ToolError(f"未知节点: {node}")
        if spec.tier not in allowed:
            raise AuthorizationError(tool_name, node, spec.tier)
        return spec

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        node: str | None = None,
        **ctx: Any,
    ) -> Any:
        """授权校验 → 执行 handler。越权/未注册抛 ToolError 子类。"""
        spec = self.check_authorization(tool_name, node)
        assert spec.handler is not None
        try:
            return spec.handler(**dict(arguments or {}), **ctx)
        except ToolError:
            raise
        except TypeError as e:
            raise ToolError(f"工具 {tool_name} 参数错误: {e}") from e
        except Exception as e:  # noqa: BLE001 — 工具错误回灌，不崩图
            raise ToolError(f"工具 {tool_name} 执行失败: {e}") from e


def default_registry() -> ToolRegistry:
    """空注册表；具体工具由各 feature 模块 register 进去。"""
    return ToolRegistry()
