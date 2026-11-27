"""LangGraph 装配：M1 单节点 + 有界循环条件边；M2 扩五节点。

- StateGraph + 条件边 + MAX_ITERATIONS 有界
- SqliteSaver checkpointer，thread_id = run.id
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.agent_node import LLMFn, agent_node
from app.agents.state import AgentState, initial_state
from app.config import get_settings
from app.db.session import create_checkpointer
from app.harness.schema import TaskDefinition


def _should_continue(state: AgentState) -> Literal["agent", "__end__"]:
    """有界循环：成功 / 触顶 / 出错 → END，否则回 agent。"""
    status = state.get("status") or "running"
    if status in {"success", "timeout", "error"}:
        return "__end__"
    iteration = int(state.get("iteration") or 0)
    max_iter = int(state.get("max_iterations") or get_settings().max_iterations)
    if iteration >= max_iter:
        state["status"] = "timeout"
        return "__end__"
    return "agent"


def build_graph(
    *,
    llm: LLMFn | None = None,
    events: Any | None = None,
    on_test: Callable[[AgentState], Any] | None = None,
    checkpointer: Any | None = None,
):
    """组装可 invoke/stream 的编译图。"""
    graph = StateGraph(AgentState)

    def _agent(state: AgentState) -> AgentState:
        return agent_node(state, llm=llm, events=events, on_test=on_test)

    graph.add_node("agent", _agent)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"agent": "agent", "__end__": END},
    )
    return graph.compile(checkpointer=checkpointer)


def default_checkpointer():
    """SqliteSaver（同库）。"""
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
) -> AgentState:
    """端到端跑一个任务到终态；thread_id = run_id。"""
    cp = checkpointer if checkpointer is not None else default_checkpointer()
    graph = build_graph(llm=llm, events=events, on_test=on_test, checkpointer=cp)
    state = initial_state(task, memory_context=memory_context)
    config = {"configurable": {"thread_id": run_id}}
    final: AgentState = graph.invoke(state, config=config)
    return final


def graph_structure_summary() -> dict[str, Any]:
    """结构描述（测试/文档用）。"""
    return {
        "nodes": ["agent"],
        "entry": "agent",
        "loop": "agent -> condition -> agent | END",
        "max_iterations_default": get_settings().max_iterations,
    }
