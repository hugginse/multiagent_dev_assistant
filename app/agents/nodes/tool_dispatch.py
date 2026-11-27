"""节点工具调用分发：授权硬校验 + 事件（含 rejected）回灌。

越权（AuthorizationError）不崩图：写入 ``tool_result {ok:false, rejected:true}``。
"""

from __future__ import annotations

from typing import Any

from app.events import EventType
from app.tools.registry import AuthorizationError, ToolError, ToolRegistry


def dispatch_tool(
    tools: ToolRegistry | None,
    events: Any | None,
    *,
    node: str,
    name: str,
    args: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """按节点授权调用工具；返回 (ok, summary)。

    事件：
    - 总是先 ``tool_call``
    - 成功/失败/越权 → ``tool_result``（越权带 ``rejected=true``）
    """
    args = args or {}
    if events is not None:
        events.emit(
            EventType.TOOL_CALL,
            {"name": name, "args": args, "node": node},
        )

    if tools is None:
        summary = "no registry"
        if events is not None:
            events.emit(
                EventType.TOOL_RESULT,
                {"name": name, "ok": False, "node": node, "summary": summary},
            )
        return False, summary

    try:
        result = tools.call(name, args, node=node)
        summary = _summarize(result)
        if events is not None:
            events.emit(
                EventType.TOOL_RESULT,
                {"name": name, "ok": True, "node": node, "summary": summary},
            )
        return True, summary
    except AuthorizationError as e:
        # 硬校验拒绝：事件可见为 rejected
        if events is not None:
            events.emit(
                EventType.TOOL_RESULT,
                {
                    "name": name,
                    "ok": False,
                    "rejected": True,
                    "node": node,
                    "tier": str(e.tier),
                    "summary": str(e),
                },
            )
        return False, str(e)
    except ToolError as e:
        if events is not None:
            events.emit(
                EventType.TOOL_RESULT,
                {"name": name, "ok": False, "node": node, "summary": str(e)},
            )
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        msg = f"{name} failed: {e}"
        if events is not None:
            events.emit(
                EventType.TOOL_RESULT,
                {"name": name, "ok": False, "node": node, "summary": msg},
            )
        return False, msg


def _summarize(result: Any) -> str:
    if result is None:
        return "ok"
    if isinstance(result, str):
        return result[:300]
    if isinstance(result, (int, float, bool)):
        return str(result)
    return repr(result)[:300]
