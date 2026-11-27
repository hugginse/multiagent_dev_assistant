"""tester 节点：真实执行 pytest / ruff（tier R+X）。"""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentState, TestRecord
from app.events import EventType
from app.harness.schema import TaskDefinition


def tester_node(
    state: AgentState,
    *,
    llm: Any | None = None,
    events: Any | None = None,
    on_test: Any | None = None,
    **_: Any,
) -> AgentState:
    task: TaskDefinition = state["task"]
    if events is not None:
        events.emit(EventType.NODE_ENTER, {"node": "tester", "iteration": state.get("iteration")})

    if on_test is not None:
        record: TestRecord = on_test(state)
    else:
        # 无注入回调且无显式 workspace 时：不得在项目根跑 pytest（会递归拉起全量测试）
        import re
        import sys
        from pathlib import Path

        from app.sandbox.workspace import run_command

        it = int(state.get("iteration") or 0)
        ws_raw = state.get("workspace")
        if not ws_raw:
            # 单元测试/无 harness 场景：确定性空记录，避免副作用
            record = TestRecord(
                iteration=it,
                passed=0,
                failed=0,
                output_tail="(no workspace/on_test injected)",
                returncode=0,
            )
        else:
            ws = Path(ws_raw)
            if not ws.is_dir():
                raise ValueError(f"workspace 不存在: {ws}")
            if events is not None:
                events.emit(
                    EventType.TOOL_CALL,
                    {"name": "run_tests", "args": {"path": "tests"}, "node": "tester", "tier": "X"},
                )
            r = run_command(
                [sys.executable, "-m", "pytest", "-q", "tests"],
                cwd=ws,
                timeout_s=min(task.timeout_s, 120.0),
            )
            out = (r.stdout + r.stderr).strip()
            passed = failed = 0
            m = re.search(r"(\d+)\s+passed", out)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", out)
            if m:
                failed = int(m.group(1))
            if passed == 0 and failed == 0 and r.returncode == 0:
                for line in out.splitlines():
                    s = line.strip()
                    if s and set(s) <= set(".FEsx"):
                        failed += s.count("F") + s.count("E")
                        passed += s.count(".")
                        break
            record = TestRecord(
                iteration=it,
                passed=passed,
                failed=failed,
                output_tail=out[-1500:],
                returncode=r.returncode,
            )
            if events is not None:
                events.emit(
                    EventType.TOOL_RESULT,
                    {
                        "name": "run_tests",
                        "ok": r.returncode == 0,
                        "summary": f"passed={passed} failed={failed}",
                    },
                )

    history = list(state.get("test_history") or [])
    history.append(record.to_dict())
    state["test_history"] = history
    state["node"] = "tester"

    if events is not None:
        events.emit(
            EventType.TEST_RESULT,
            {
                "iteration": record.iteration,
                "passed": record.passed,
                "failed": record.failed,
                "returncode": record.returncode,
                "ok": record.ok,
                "phase": "agent",
            },
        )
        events.emit(
            EventType.NODE_EXIT,
            {"node": "tester", "ok": record.ok, "iteration": state.get("iteration")},
        )
    return state
