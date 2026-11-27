"""coder 节点：按计划+探索生成/修改代码（tier R+W）。"""

from __future__ import annotations

from typing import Any

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
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "coder", "iteration": state.get("iteration")})

    # 展示当前 review 反馈（若有）
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
        # stub：记录思考，不自动改文件（真实修改由 M1 逐步/后续工具循环扩展）
        if not scratch:
            scratch = f"coder 草稿: 针对 {task.id} 计划执行，探索={len(state.get('exploration') or {})} 文件"
        if events is not None:
            events.emit(EventType.LLM_DELTA, {"node": "coder", "text": scratch[:200] + "\n"})

    state["scratch"] = scratch
    state["node"] = "coder"
    # diff 字段：若 workspace 有变化由 harness 在终态计算；此处保留已有
    if events is not None:
        events.emit(EventType.NODE_EXIT, {"node": "coder", "scratch_chars": len(scratch)})
    return state
