"""coder 节点：按计划+探索生成/修改代码（tier R+W）。"""

from __future__ import annotations

from typing import Any

from app.agents.nodes.tool_dispatch import dispatch_tool
from app.agents.state import AgentState
from app.events import EventType
from app.harness.schema import TaskDefinition


def coder_node(
    state: AgentState,
    *,
    llm: Any | None = None,
    events: Any | None = None,
    tools: Any | None = None,
    workspace: Any | None = None,
    **_: Any,
) -> AgentState:
    task: TaskDefinition = state["task"]
    state["node"] = "coder"
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "coder", "iteration": state.get("iteration")})

    review = state.get("review") or {}
    if review.get("verdict") == "reject" and events is not None:
        events.emit(
            EventType.NODE_ENTER,
            {"node": "coder", "review_feedback": review.get("reason", "")[:200]},
        )

    scratch = state.get("scratch") or ""
    if llm is not None:
        text = llm("", task, state)
        if text:
            scratch = text
        if events is not None and not getattr(llm, "streamed", False):
            for line in text.splitlines(keepends=True):
                events.emit(EventType.LLM_DELTA, {"node": "coder", "text": line})
    else:
        if not scratch:
            scratch = (
                f"coder 草稿: 针对 {task.id} 计划执行，"
                f"探索={len(state.get('exploration') or {})} 文件"
            )
        if events is not None:
            events.emit(EventType.LLM_DELTA, {"node": "coder", "text": scratch[:200] + "\n"})

    # coder 可读（R）：读取关键文件摘要进 exploration
    if tools is not None:
        dispatch_tool(
            tools,
            events,
            node="coder",
            name="read_file",
            args={"path": "orderlib/pricing.py", "max_chars": 500},
        )
        # coder 不得执行（X）——若被误传 run_tests，事件记 rejected
        # （不主动调用；负向由测试覆盖）

    state["scratch"] = scratch
    if events is not None:
        events.emit(EventType.NODE_EXIT, {"node": "coder", "scratch_chars": len(scratch)})
    return state
