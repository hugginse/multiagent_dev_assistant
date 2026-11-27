"""planner 节点：任务理解 → 分步计划（tier R+M）。"""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentState, PlanStep
from app.events import EventType
from app.harness.schema import TaskDefinition


def parse_plan_text(text: str) -> list[PlanStep]:
    steps: list[PlanStep] = []
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "PLAN":
            start = i + 1
            break
    if start is None:
        # 无 PLAN 头：把每行编号句当步骤
        n = 0
        for line in lines:
            s = line.strip()
            if not s:
                continue
            n += 1
            steps.append(PlanStep(step=n, action=s))
        return steps
    n = 0
    for line in lines[start:]:
        s = line.strip()
        if s in {"SCRATCH", "DIFF", "TEST", "PLAN"}:
            break
        if not s:
            continue
        raw = s.lstrip("0123456789.、) ").strip() or s
        n += 1
        steps.append(PlanStep(step=n, action=raw))
    return steps


def planner_node(
    state: AgentState,
    *,
    llm: Any | None = None,
    events: Any | None = None,
    tools: Any | None = None,
    **_: Any,
) -> AgentState:
    task: TaskDefinition = state["task"]
    state["node"] = "planner"
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "planner", "iteration": state.get("iteration")})

    # planner 仅 R+M：尝试记忆检索（越权写/执行会 rejected）
    if tools is not None:
        from app.agents.nodes.tool_dispatch import dispatch_tool

        dispatch_tool(
            tools,
            events,
            node="planner",
            name="memory_search",
            args={"q": task.title},
        )

    if llm is not None:
        text = llm("", task, state)
    else:
        text = (
            f"PLAN\n"
            f"1. 理解任务: {task.title}\n"
            f"2. 定位相关模块\n"
            f"3. 修改实现\n"
            f"4. 补充/运行测试\n"
            f"SCRATCH\nplanner 草稿"
        )
        if events is not None:
            for line in text.splitlines(keepends=True):
                events.emit(EventType.LLM_DELTA, {"node": "planner", "text": line})

    plan = parse_plan_text(text)
    if plan:
        state["plan"] = [s.to_dict() for s in plan]

    if events is not None:
        events.emit(
            EventType.NODE_EXIT,
            {"node": "planner", "iteration": state.get("iteration"), "plan_steps": len(state.get("plan") or [])},
        )
    return state
