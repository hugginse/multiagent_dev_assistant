"""M1 单节点 Agent 循环：plan → code → test 雏形。

结构预留（M2 拆 explorer/coder/tester/reviewer）：
- 读黑板 → 调 LLM（可 mock）→ 写 plan/diff → 触发一轮工具/测试 → 写 test_history
- 由图的条件边根据 iteration / test 结果决定继续或结束
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.state import AgentState, PlanStep, TestRecord
from app.events import EventType
from app.harness.schema import TaskDefinition

# LLM 调用注入点：默认 None 时走确定性 stub（无网络，测试友好）
LLMFn = Callable[[str, TaskDefinition, AgentState], str]


def _default_llm(system: str, task: TaskDefinition, state: AgentState) -> str:
    """确定性 stub：不访问网络，生成可解析的计划文本。"""
    return (
        f"PLAN\n"
        f"1. 阅读任务: {task.title}\n"
        f"2. 定位相关代码\n"
        f"3. 修改并补充测试\n"
        f"4. 运行 pytest 验证\n"
        f"SCRATCH\n针对 {task.id} 的处理草稿"
    )


def agent_node(
    state: AgentState,
    *,
    llm: LLMFn | None = None,
    events: Any | None = None,
    on_test: Callable[[AgentState], TestRecord] | None = None,
) -> AgentState:
    """单节点：推进一轮 plan/code/test。

    - ``events``: EventStore，发出 node_enter / llm_delta / node_exit
    - ``on_test``: 注入真实测试执行（harness 传入）；默认生成空记录
    """
    task: TaskDefinition = state["task"]
    iteration = int(state.get("iteration") or 0)
    max_iter = int(state.get("max_iterations") or task.max_iterations)

    if events is not None:
        events.emit(
            EventType.NODE_ENTER,
            {"node": "agent", "iteration": iteration, "task_id": task.id},
        )

    # --- LLM：生成/更新计划与草稿 ---
    llm_fn = llm or _default_llm
    text = llm_fn("", task, state)
    if events is not None:
        # 逐段 delta（stub 无真实 token 流时按行模拟；真实 LLM 在 runner 里接真流式）
        for line in text.splitlines(keepends=True):
            events.emit(EventType.LLM_DELTA, {"node": "agent", "text": line})

    plan = _parse_plan(text)
    if plan:
        state["plan"] = [s.to_dict() for s in plan]

    scratch = _extract_section(text, "SCRATCH")
    if scratch:
        state["scratch"] = scratch

    # --- 测试轮 ---
    if on_test is not None:
        record = on_test(state)
    else:
        record = TestRecord(iteration=iteration, passed=0, failed=0, output_tail="", returncode=0)

    history = list(state.get("test_history") or [])
    history.append(record.to_dict())
    state["test_history"] = history

    if events is not None:
        events.emit(
            EventType.TEST_RESULT,
            {
                "iteration": iteration,
                "passed": record.passed,
                "failed": record.failed,
                "returncode": record.returncode,
                "ok": record.ok,
            },
        )

    state["iteration"] = iteration + 1
    state["node"] = "agent"

    # 终态判断（条件边也可再包一层；M1 在节点内给出 status 建议）
    if record.ok:
        state["status"] = "success"
    elif state["iteration"] >= max_iter:
        state["status"] = "timeout"
    else:
        state["status"] = "running"

    if events is not None:
        events.emit(
            EventType.NODE_EXIT,
            {
                "node": "agent",
                "iteration": state["iteration"],
                "status": state["status"],
            },
        )
    return state


def _parse_plan(text: str) -> list[PlanStep]:
    steps: list[PlanStep] = []
    section = _extract_section(text, "PLAN")
    if not section:
        return steps
    n = 0
    for line in section.splitlines():
        line = line.strip()
        if not line:
            continue
        # 去掉序号前缀
        raw = line.lstrip("0123456789.、) ").strip() or line
        n += 1
        steps.append(PlanStep(step=n, action=raw))
    return steps


def _extract_section(text: str, header: str) -> str:
    """提取 ``HEADER`` 到下一个全大写标题之间的文本。"""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if s in {"PLAN", "SCRATCH", "DIFF", "TEST"} and out:
            break
        out.append(line)
    return "\n".join(out).strip()
