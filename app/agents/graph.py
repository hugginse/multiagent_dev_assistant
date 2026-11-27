"""LangGraph 五节点装配：planner → explorer → coder ⇄ tester → reviewer 有界循环。

条件边（architecture.md §4.2）：
- tester fail → coder（迭代 ≤ MAX_ITERATIONS）
- tester pass → reviewer
- reviewer reject → coder（连续 reject 2 次且回 planner 仅一次）
- reviewer approve → END
- 循环触顶 → status=timeout，仍产出当前 diff 与报告
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

# 兼容 M1 导入
from app.agents.nodes.agent_node import LLMFn, agent_node  # noqa: F401
from app.agents.nodes.coder import coder_node
from app.agents.nodes.explorer import explorer_node
from app.agents.nodes.planner import planner_node
from app.agents.nodes.reviewer import reviewer_node
from app.agents.nodes.tester import tester_node
from app.agents.state import AgentState, initial_state
from app.config import get_settings
from app.db.session import create_checkpointer
from app.harness.schema import TaskDefinition


def _hit_max(state: AgentState) -> bool:
    iteration = int(state.get("iteration") or 0)
    max_iter = int(state.get("max_iterations") or get_settings().max_iterations)
    return iteration >= max_iter


def _after_tester(state: AgentState) -> str:
    """tester → pass: reviewer | fail: coder | 触顶: END。

    注意：条件边函数的返回值才是路由；对 state 的就地修改**不会**写回图状态，
    因此 status 触顶写在 tester 节点内（见 graph._tester）。
    """
    if state.get("status") == "error":
        return "__end__"
    if _hit_max(state):
        return "__end__"
    history = state.get("test_history") or []
    last = history[-1] if history else {}
    if last.get("ok"):
        return "reviewer"
    return "coder"


def _after_reviewer(state: AgentState) -> str:
    """reviewer → approve: END | reject→coder | 连续 reject→planner（仅一次）。"""
    if _hit_max(state):
        return "__end__"
    review = state.get("review") or {}
    if review.get("verdict") == "approve":
        return "__end__"
    # reject：连续 2 次且回 planner 仅一次（_replanned 在节点内置位）
    if review.get("root_cause_plan") and not state.get("_replanned"):
        return "planner"
    return "coder"


def _after_coder(state: AgentState) -> str:
    return "tester"


def build_graph(
    *,
    llm: LLMFn | None = None,
    events: Any | None = None,
    on_test: Callable[[AgentState], Any] | None = None,
    checkpointer: Any | None = None,
    tools: Any | None = None,
    workspace: Any | None = None,
    five_node: bool = True,
):
    """组装编译图。

    - ``five_node=True``（M2 默认）：五节点 + 条件边
    - ``five_node=False``：M1 单节点桩（兼容）
    """
    if not five_node:
        return _build_single(llm=llm, events=events, on_test=on_test, checkpointer=checkpointer)

    graph = StateGraph(AgentState)

    def _planner(s: AgentState) -> AgentState:
        return planner_node(s, llm=llm, events=events, tools=tools, workspace=workspace)

    def _explorer(s: AgentState) -> AgentState:
        return explorer_node(s, llm=llm, events=events, tools=tools, workspace=workspace)

    def _coder(s: AgentState) -> AgentState:
        return coder_node(s, llm=llm, events=events, tools=tools, workspace=workspace)

    def _tester(s: AgentState) -> AgentState:
        out = tester_node(s, llm=llm, events=events, on_test=on_test)
        out["iteration"] = int(out.get("iteration") or 0) + 1
        # 触顶时在节点内写 status（条件边改 state 不生效）
        if out["iteration"] >= int(out.get("max_iterations") or get_settings().max_iterations):
            out["status"] = "timeout"
        return out

    def _reviewer(s: AgentState) -> AgentState:
        out = reviewer_node(s, llm=llm, events=events)
        # 连续 reject 回 planner 仅一次：在节点内标记
        review = out.get("review") or {}
        if (
            review.get("verdict") == "reject"
            and review.get("root_cause_plan")
            and not out.get("_replanned")
        ):
            out["_replanned"] = True
        if out["iteration"] >= int(out.get("max_iterations") or get_settings().max_iterations):
            out["status"] = "timeout"
        return out

    graph.add_node("planner", _planner)
    graph.add_node("explorer", _explorer)
    graph.add_node("coder", _coder)
    graph.add_node("tester", _tester)
    graph.add_node("reviewer", _reviewer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "explorer")
    graph.add_edge("explorer", "coder")
    graph.add_edge("coder", "tester")
    graph.add_conditional_edges(
        "tester",
        _after_tester,
        {"reviewer": "reviewer", "coder": "coder", "__end__": END},
    )
    graph.add_conditional_edges(
        "reviewer",
        _after_reviewer,
        {"coder": "coder", "planner": "planner", "__end__": END},
    )
    return graph.compile(checkpointer=checkpointer)


def _build_single(*, llm, events, on_test, checkpointer):
    """M1 单节点兼容路径。"""
    graph = StateGraph(AgentState)

    def _agent(state: AgentState) -> AgentState:
        return agent_node(state, llm=llm, events=events, on_test=on_test)

    graph.add_node("agent", _agent)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue_single,
        {"agent": "agent", "__end__": END},
    )
    return graph.compile(checkpointer=checkpointer)


def _should_continue_single(state: AgentState) -> Literal["agent", "__end__"]:
    status = state.get("status") or "running"
    if status in {"success", "timeout", "error"}:
        return "__end__"
    if _hit_max(state):
        state["status"] = "timeout"
        return "__end__"
    return "agent"


def default_checkpointer():
    return create_checkpointer()


def run_agent_task(
    task: TaskDefinition,
    *,
    run_id: str,
    llm: LLMFn | None = None,
    events: Any | None = None,
    on_test: Callable[[AgentState], Any] | None = None,
    memory_context: str = "",
    checkpointer: Any | None = None,
    five_node: bool = True,
    tools: Any | None = None,
    workspace: Any | None = None,
) -> AgentState:
    """端到端跑一个任务到终态；thread_id = run_id。"""
    cp = checkpointer if checkpointer is not None else default_checkpointer()
    graph = build_graph(
        llm=llm,
        events=events,
        on_test=on_test,
        checkpointer=cp,
        five_node=five_node,
        tools=tools,
        workspace=workspace,
    )
    state = initial_state(task, memory_context=memory_context)
    config = {"configurable": {"thread_id": run_id}}
    final: AgentState = graph.invoke(state, config=config)
    return final


def graph_structure_summary() -> dict[str, Any]:
    return {
        "nodes": ["planner", "explorer", "coder", "tester", "reviewer"],
        "entry": "planner",
        "edges": [
            "START -> planner -> explorer -> coder -> tester",
            "tester --pass--> reviewer",
            "tester --fail--> coder",
            "tester --max--> END",
            "reviewer --approve--> END",
            "reviewer --reject--> coder",
            "reviewer --reject×2 plan--> planner",
        ],
        "max_iterations_default": get_settings().max_iterations,
    }
