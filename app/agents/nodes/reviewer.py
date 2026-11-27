"""reviewer 节点：对照任务验收 + 约定审查（tier R+M）。"""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentState, ReviewRecord
from app.events import EventType
from app.harness.schema import TaskDefinition


def reviewer_node(
    state: AgentState,
    *,
    llm: Any | None = None,
    events: Any | None = None,
    **_: Any,
) -> AgentState:
    task: TaskDefinition = state["task"]
    state["node"] = "reviewer"  # 先置节点名，LLM mock 可据此分支
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "reviewer", "iteration": state.get("iteration")})

    history = state.get("test_history") or []
    last = history[-1] if history else {}
    tests_ok = bool(last.get("ok"))
    consecutive_rejects = int(state.get("_consecutive_rejects") or 0)

    verdict = "approve"
    reason = ""
    root_cause_plan = False

    if not tests_ok:
        verdict = "reject"
        reason = f"测试未通过: passed={last.get('passed')} failed={last.get('failed')}"
        root_cause_plan = consecutive_rejects + 1 >= 2
    elif llm is not None:
        # LLM 审查：仅输出 APPROVE 或 REJECT: 理由
        text = llm("", task, state)
        upper = text.strip().upper()
        if upper.startswith("REJECT") or " REJECT" in upper[:80]:
            verdict = "reject"
            reason = text.strip()[:500]
            root_cause_plan = consecutive_rejects + 1 >= 2
        else:
            verdict = "approve"
            reason = text.strip()[:200] or "LLM approve"
    else:
        # stub：测试过则 approve
        verdict = "approve"
        reason = "stub: tests green"
        if events is not None:
            events.emit(EventType.LLM_DELTA, {"node": "reviewer", "text": reason + "\n"})

    if verdict == "reject":
        state["_consecutive_rejects"] = consecutive_rejects + 1
    else:
        state["_consecutive_rejects"] = 0
        state["status"] = "success"

    rec = ReviewRecord(verdict=verdict, reason=reason, root_cause_plan=root_cause_plan)
    state["review"] = rec.to_dict()
    state["node"] = "reviewer"

    if events is not None:
        events.emit(
            EventType.NODE_EXIT,
            {
                "node": "reviewer",
                "verdict": verdict,
                "root_cause_plan": root_cause_plan,
                "reason": reason[:160],
            },
        )
    return state
