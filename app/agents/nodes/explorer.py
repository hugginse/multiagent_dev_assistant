"""explorer 节点：按计划定位代码，产出文件摘要（tier R only）。"""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentState
from app.events import EventType
from app.harness.schema import TaskDefinition


def explorer_node(
    state: AgentState,
    *,
    llm: Any | None = None,
    events: Any | None = None,
    tools: Any | None = None,
    workspace: Any | None = None,
    **_: Any,
) -> AgentState:
    task: TaskDefinition = state["task"]
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "explorer", "iteration": state.get("iteration")})

    exploration: dict[str, str] = dict(state.get("exploration") or {})

    # 有工具时做一次只读探查（硬校验 node=explorer 仅 R）
    if tools is not None and workspace is not None:
        try:
            tools.call(
                "list_dir",
                {"path": ".", "recursive": False},
                node="explorer",
            )
            if events is not None:
                events.emit(
                    EventType.TOOL_CALL,
                    {"name": "list_dir", "args": {"path": "."}, "node": "explorer"},
                )
                events.emit(
                    EventType.TOOL_RESULT,
                    {"name": "list_dir", "ok": True, "summary": "workspace root listed"},
                )
        except Exception as e:  # noqa: BLE001 — 工具错误回灌
            if events is not None:
                events.emit(EventType.TOOL_RESULT, {"name": "list_dir", "ok": False, "summary": str(e)})

    if llm is not None:
        text = llm("", task, state)
        # 解析 EXPLORATION 段或按行 key: value
        for line in text.splitlines():
            if ":" in line and not line.startswith("PLAN"):
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip()
                if k and v and len(k) < 120:
                    exploration[k] = v
    else:
        # 确定性 stub：写入任务相关已知路径摘要
        exploration.setdefault("orderlib/pricing.py", "折扣与运费计算")
        exploration.setdefault("orderlib/orders.py", "下单服务")
        exploration.setdefault("tests/", "单元测试目录")
        if events is not None:
            note = "explorer stub: 已索引已知模块\n"
            events.emit(EventType.LLM_DELTA, {"node": "explorer", "text": note})

    state["exploration"] = exploration
    state["node"] = "explorer"
    if events is not None:
        events.emit(
            EventType.NODE_EXIT,
            {"node": "explorer", "files": len(exploration)},
        )
    return state
