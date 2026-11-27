"""记忆工具：memory_search / memory_save（tier M）。

M2：接口与授权就位；向量检索/持久化在 M3 接 Chroma。
当前为进程内空实现，保证图可跑、越权可测。
"""

from __future__ import annotations

from typing import Any

from app.tools.registry import Tier, ToolError, ToolRegistry, ToolSpec

# 进程内简易存储（M3 替换为 memories 表 + Chroma）
_STORE: list[dict[str, str]] = []


def memory_search(query: str, *, k: int = 5) -> list[dict[str, str]]:
    if not query:
        raise ToolError("query 不得为空")
    q = query.lower()
    hits = [m for m in _STORE if q in m.get("content", "").lower() or q in m.get("title", "").lower()]
    return hits[: max(1, k)]


def memory_save(title: str, content: str, *, kind: str = "convention") -> dict[str, str]:
    if not title or not content:
        raise ToolError("title/content 不得为空")
    if kind not in {"convention", "episode"}:
        raise ToolError(f"kind 必须是 convention|episode，收到 {kind!r}")
    rec = {"title": title, "content": content, "kind": kind}
    _STORE.append(rec)
    return rec


def clear_memory_store() -> None:
    _STORE.clear()


def register_memory_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="memory_search",
            description="检索长期记忆（top-k，tier=M，planner/reviewer）。",
            tier=Tier.M,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            timeout_s=5.0,
            handler=lambda query, k=5: memory_search(query, k=k),
        )
    )
    registry.register(
        ToolSpec(
            name="memory_save",
            description="写入长期记忆（tier=M）。",
            tier=Tier.M,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "kind": {"type": "string", "enum": ["convention", "episode"]},
                },
                "required": ["title", "content"],
                "additionalProperties": False,
            },
            timeout_s=5.0,
            handler=lambda title, content, kind="convention": memory_save(
                title, content, kind=kind
            ),
        )
    )


def memory_tool_handlers() -> dict[str, Any]:
    return {"memory_search": memory_search, "memory_save": memory_save}
