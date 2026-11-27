"""explorer 节点：按计划定位代码，产出文件摘要（tier R only）。"""

from __future__ import annotations

from typing import Any

from app.agents.nodes.tool_dispatch import dispatch_tool
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
    state["node"] = "explorer"
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "explorer", "iteration": state.get("iteration")})

    exploration: dict[str, str] = dict(state.get("exploration") or {})

    # 只读探查（硬校验：explorer 仅 R）
    if tools is not None:
        ok, summary = dispatch_tool(
            tools,
            events,
            node="explorer",
            name="list_dir",
            args={"path": ".", "recursive": False},
        )
        if ok:
            for line in summary.splitlines():
                if "/" in line or line.endswith("/"):
                    key = line.split()[0].rstrip("/")
                    if key and len(key) < 120:
                        exploration.setdefault(key, "listed")

    if llm is not None:
        text = llm("", task, state)
        for line in text.splitlines():
            if ":" in line and not line.startswith("PLAN"):
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip()
                if k and v and len(k) < 120:
                    exploration[k] = v
    else:
        exploration.setdefault("orderlib/pricing.py", "折扣与运费计算")
        exploration.setdefault("orderlib/orders.py", "下单服务")
        exploration.setdefault("tests/", "单元测试目录")
        if events is not None:
            events.emit(
                EventType.LLM_DELTA,
                {"node": "explorer", "text": "explorer stub: 已索引已知模块\n"},
            )

    # explorer **不得**写文件：若被误传 write 工具，dispatch 会记 rejected（负向覆盖）
    if tools is not None and workspace is not None:
        # 不主动调用；负向路径由测试保证
        pass

    state["exploration"] = exploration
    if events is not None:
        events.emit(
            EventType.NODE_EXIT,
            {"node": "explorer", "files": len(exploration)},
        )
    return state
