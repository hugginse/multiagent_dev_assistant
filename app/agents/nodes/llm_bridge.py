"""把 LLMClient.stream 桥接为 Agent 节点可用的 LLMFn（真流式 → llm_delta）。"""

from __future__ import annotations

from collections.abc import Callable

from app.agents.state import AgentState
from app.harness.schema import TaskDefinition
from app.llm.client import LLMClient, Message

LLMDeltaEmitter = Callable[[str], None]


def make_streaming_llm(
    client: LLMClient,
    *,
    emit_delta: LLMDeltaEmitter | None = None,
    system_prompt: str | None = None,
) -> Callable[[str, TaskDefinition, AgentState], str]:
    """返回 LLMFn：组 prompt → client.stream → 逐 delta 回调 → 返回全文。

    返回函数带 ``streamed=True``，agent_node 不再重复切片发 llm_delta。
    """

    def llm(system: str, task: TaskDefinition, state: AgentState) -> str:
        sys_p = system_prompt or system or _default_system(task)
        user_parts = [f"任务: {task.title}", "", task.prompt]
        plan = state.get("plan") or []
        if plan:
            user_parts.append("\n当前计划:")
            for s in plan[:20]:
                user_parts.append(f"- {s.get('step')}. {s.get('action')}")
        scratch = state.get("scratch") or ""
        if scratch:
            user_parts.append(f"\n草稿:\n{scratch}")
        history = state.get("test_history") or []
        if history:
            user_parts.append("\n最近测试:")
            for h in history[-3:]:
                user_parts.append(
                    f"- iter={h.get('iteration')} passed={h.get('passed')} "
                    f"failed={h.get('failed')}"
                )
        messages = [
            Message(role="system", content=sys_p),
            Message(role="user", content="\n".join(user_parts)),
        ]

        parts: list[str] = []
        for delta in client.stream(messages, temperature=0.2, max_tokens=2048):
            parts.append(delta)
            if emit_delta is not None:
                emit_delta(delta)
        return "".join(parts)

    llm.streamed = True  # type: ignore[attr-defined]
    return llm


def _default_system(task: TaskDefinition) -> str:
    return (
        "你是仓库研发助手。按以下纯文本格式输出，不要用 Markdown 代码块：\n"
        "PLAN\n1. 步骤...\n"
        "SCRATCH\n你的思考草稿\n"
        "只输出这两段。"
    )
