"""单任务执行 + 评分 + 落库（产出事件流）。

流程（architecture.md §6.2）：
1. 加载任务 → 创建 workspace 副本（**不含**隐藏测试）
2. 组装 AgentState + 记忆注入（按开关）→ 跑图至终态
3. 注入隐藏测试 → 真实执行 pytest → 评分
4. 记录指标 → 落库（runs + run_events）
5. 汇总为报告条目

核心不依赖 CLI（展示层只订阅 EventStore）。
"""

from __future__ import annotations

import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agents.graph import build_graph
from app.agents.nodes.agent_node import LLMFn
from app.agents.state import AgentState, TestRecord, initial_state
from app.config import load_settings
from app.db.models import RunRow
from app.db.session import create_checkpointer, session_scope
from app.events import (
    EventStore,
    EventType,
    assert_seq_monotonic,
    count_tool_calls_by_tier,
    load_events,
)
from app.harness.loader import resolve_hidden_test_paths, suite_dir
from app.harness.schema import RunMetrics, TaskDefinition
from app.sandbox.workspace import prepare_workspace, run_command


def new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def find_repo_root(repo_name: str) -> Path:
    """定位仓库：优先项目根下同名目录。"""
    root = Path(__file__).resolve().parents[2]
    candidate = root / repo_name
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(f"仓库不存在: {candidate}")


@dataclass(slots=True)
class RunOutcome:
    run_id: str
    task_id: str
    status: str
    metrics: RunMetrics
    diff: str
    final_state: AgentState
    workspace: Path


def compute_diff(workspace: Path, baseline: Path) -> str:
    """相对 baseline 的 unified diff（文本）。"""
    import subprocess
    import sys

    script = r"""
import difflib, pathlib, sys

def walk(a: pathlib.Path, b: pathlib.Path, out: list[str]) -> None:
    if a.is_file() and b.is_file():
        if a.read_bytes() != b.read_bytes():
            al = a.read_text(errors="replace").splitlines(True)
            bl = b.read_text(errors="replace").splitlines(True)
            out.extend(difflib.unified_diff(al, bl, fromfile=str(a), tofile=str(b)))
        return
    if a.is_dir() and b.is_dir():
        names = sorted(set(p.name for p in a.iterdir()) | set(p.name for p in b.iterdir()))
        for name in names:
            if name in {"__pycache__", ".git", ".pytest_cache", ".venv"}:
                continue
            walk(a / name, b / name, out)
        return
    if a.is_file() and (not b.exists()):
        out.append(f"--- {a}\n+++ /dev/null\n")
        out.extend(f"-{line}" for line in a.read_text(errors="replace").splitlines(True))
    if (not a.exists()) and b.is_file():
        out.append(f"--- /dev/null\n+++ {b}\n")
        out.extend(f"+{line}" for line in b.read_text(errors="replace").splitlines(True))

out: list[str] = []
walk(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), out)
print("".join(out), end="")
"""
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script, str(baseline), str(workspace)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def score_hidden_tests(
    workspace: Path,
    task: TaskDefinition,
    suite: str,
    *,
    timeout_s: float = 120.0,
) -> tuple[int, int, str, int]:
    """注入隐藏测试并真实执行；返回 (passed, failed, output_tail, returncode)。"""
    paths = resolve_hidden_test_paths(suite, task)
    if not paths:
        return 0, 0, "(no hidden tests)", 0

    rels: list[str] = []
    hidden_root = suite_dir(suite) / "hidden_tests"
    for p in paths:
        try:
            rel = p.relative_to(hidden_root)
        except ValueError:
            rel = Path(p.name)
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
        rels.append(rel.as_posix())

    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *rels]
    r = run_command(cmd, cwd=workspace, timeout_s=timeout_s, output_limit=20_000)
    out = (r.stdout + "\n" + r.stderr).strip()
    passed, failed = _parse_pytest_counts(out)
    if r.timed_out:
        return passed, max(failed, 1), out[-2000:], -1
    if r.returncode == 0:
        if passed == 0 and failed == 0:
            # -q 全绿可能只有点号：按收集到的隐藏测试文件数计
            passed = max(1, len(rels))
        return passed, 0, out[-2000:], 0
    if passed == 0 and failed == 0:
        failed = 1
    return passed, failed, out[-2000:], r.returncode


def _parse_pytest_counts(output: str) -> tuple[int, int]:
    """从 pytest 输出解析 passed/failed；-q 点号模式用点数兜底。"""
    import re

    passed = failed = 0
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    if passed == 0 and failed == 0:
        # -q 纯点号：. = passed, F = failed
        # 只统计进度行中的字符
        for line in output.splitlines():
            stripped = line.strip()
            if stripped and set(stripped) <= set(".FEsx") and len(stripped) >= 1:
                failed += stripped.count("F") + stripped.count("E")
                passed += stripped.count(".")
                break
    return passed, failed


def run_single_task(
    task: TaskDefinition,
    *,
    suite: str,
    provider: str | None = None,
    model: str | None = None,
    memory_on: bool = False,
    memory_context: str = "",
    run_id: str | None = None,
    llm: LLMFn | None = None,
    session: Session | None = None,
    on_node_test: Callable[[AgentState], TestRecord] | None = None,
    with_hidden_scoring: bool = True,
    event_subscribers: list[Callable[[Any], None]] | None = None,
    llm_emit_holder: dict[str, Any] | None = None,
) -> RunOutcome:
    """端到端执行一个任务。session 为 None 时自建事务。

    ``event_subscribers``: 展示层回调（CLI 实时打印）；事件仍先落库再通知。
    """
    settings = load_settings()
    rid = run_id or new_run_id()
    prov = provider or settings.llm_provider
    mdl = model or settings.resolve_llm_model()

    owned_session = session is None
    cm = None
    if owned_session:
        from app.db.session import init_db

        init_db()
        cm = session_scope()
        session = cm.__enter__()
    assert session is not None

    try:
        run_row = RunRow(
            id=rid,
            task_id=task.id,
            suite=suite,
            status="running",
            provider=prov,
            model=mdl,
            memory_on=memory_on,
            iteration=0,
        )
        session.add(run_row)
        session.commit()

        events = EventStore(session, rid)
        for sub in event_subscribers or []:
            events.subscribe(sub)
        if llm_emit_holder is not None:
            llm_emit_holder["events"] = events

        events.emit(
            EventType.RUN_STARTED,
            {
                "task_id": task.id,
                "suite": suite,
                "provider": prov,
                "model": mdl,
                "memory_on": memory_on,
            },
        )
        # 记忆注入：memory_on 且未显式传 context 时按任务 prompt 检索
        if memory_on and not memory_context:
            try:
                from app.memory.injection import build_memory_context

                memory_context, _inj = build_memory_context(
                    task.prompt,
                    repo_id=task.repo,
                    enabled=True,
                )
            except Exception as e:  # noqa: BLE001 — 注入失败不阻断
                memory_context = ""
                events.emit(
                    EventType.ERROR,
                    {"message": f"memory inject failed: {e}", "phase": "memory"},
                )
        if memory_on and memory_context:
            events.emit(
                EventType.MEMORY_INJECTED,
                {"chars": len(memory_context), "preview": memory_context[:200]},
            )

        repo_path = find_repo_root(task.repo)
        baseline = repo_path
        ws = prepare_workspace(repo_path, rid, hidden_tests=None)

        def _default_on_test(state: AgentState) -> TestRecord:
            it = int(state.get("iteration") or 0)
            events.emit(
                EventType.TOOL_CALL,
                {"name": "run_tests", "args": {"path": "tests"}, "node": "agent", "tier": "X"},
            )
            r = run_command(
                [sys.executable, "-m", "pytest", "-q", "tests"],
                cwd=ws,
                timeout_s=min(task.timeout_s, 120.0),
                output_limit=8000,
            )
            passed, failed = _parse_pytest_counts((r.stdout + r.stderr).strip())
            tail = (r.stdout + r.stderr)[-1500:]
            events.emit(
                EventType.TOOL_RESULT,
                {
                    "name": "run_tests",
                    "ok": r.returncode == 0,
                    "summary": f"passed={passed} failed={failed} rc={r.returncode}",
                    "output_tail": tail,
                },
            )
            return TestRecord(
                iteration=it,
                passed=passed,
                failed=failed,
                output_tail=tail,
                returncode=r.returncode,
            )

        on_test = on_node_test or _default_on_test

        # 节点级工具授权硬校验（registry 层）
        from app.tools.build import build_registry

        tool_registry = build_registry(ws, timeout_s=min(task.timeout_s, 120.0))

        cp = create_checkpointer()
        graph = build_graph(
            llm=llm,
            events=events,
            on_test=on_test,
            checkpointer=cp,
            five_node=True,
            tools=tool_registry,
            workspace=ws,
        )
        state = initial_state(task, memory_context=memory_context)
        state["workspace"] = str(ws)
        started = time.monotonic()
        try:
            final: AgentState = graph.invoke(
                state, config={"configurable": {"thread_id": rid}}
            )
        except Exception as e:  # noqa: BLE001
            events.emit(EventType.ERROR, {"message": str(e)})
            wall = time.monotonic() - started
            metrics = RunMetrics(status="error", error=str(e), wall_s=wall)
            _finalize_run(session, run_row, events, metrics, status="error")
            return RunOutcome(
                run_id=rid,
                task_id=task.id,
                status="error",
                metrics=metrics,
                diff="",
                final_state=state,
                workspace=ws,
            )

        passed = failed = 0
        score_out = ""
        score_rc = 0
        if with_hidden_scoring:
            passed, failed, score_out, score_rc = score_hidden_tests(ws, task, suite)
            events.emit(
                EventType.TEST_RESULT,
                {
                    "phase": "hidden_scoring",
                    "passed": passed,
                    "failed": failed,
                    "returncode": score_rc,
                    "ok": failed == 0 and passed > 0,
                },
            )

        diff = compute_diff(baseline, ws)
        wall = time.monotonic() - started
        total = passed + failed
        ratio = (passed / total) if total else 0.0
        resolve = failed == 0 and passed > 0
        iteration = int(final.get("iteration") or 0)
        max_hit = iteration >= int(final.get("max_iterations") or task.max_iterations)

        status = "success"
        if final.get("status") == "timeout" and not resolve:
            status = "timeout"
        if final.get("status") == "error":
            status = "error"

        # 先落库再统计（含 hidden_scoring 前的 tool_call）
        evs_so_far = load_events(session, rid)
        tool_calls = count_tool_calls_by_tier(evs_so_far)

        metrics = RunMetrics(
            resolve=resolve,
            test_pass_ratio=ratio,
            iterations=iteration,
            max_hit=max_hit,
            tool_calls=tool_calls,
            tokens_in=0,
            tokens_out=0,
            wall_s=wall,
            status=status,
            error=final.get("error") or None,
        )
        if score_out and not resolve:
            metrics.error = ((metrics.error or "") + f" | hidden: {score_out[-500:]}").strip(
                " |"
            )

        diff_dir = Path("data") / "runs" / rid
        diff_dir.mkdir(parents=True, exist_ok=True)
        diff_path = diff_dir / "diff.patch"
        diff_path.write_text(diff, encoding="utf-8")

        _finalize_run(session, run_row, events, metrics, status=status, diff_path=str(diff_path))
        evs = load_events(session, rid)
        assert_seq_monotonic(evs)

        return RunOutcome(
            run_id=rid,
            task_id=task.id,
            status=status,
            metrics=metrics,
            diff=diff,
            final_state=final,
            workspace=ws,
        )
    finally:
        if owned_session and cm is not None:
            cm.__exit__(None, None, None)


def _finalize_run(
    session: Session,
    run_row: RunRow,
    events: EventStore,
    metrics: RunMetrics,
    *,
    status: str,
    diff_path: str | None = None,
) -> None:
    run_row.status = status
    run_row.metrics_json = metrics.to_dict()
    run_row.iteration = metrics.iterations
    run_row.diff_path = diff_path
    run_row.error = metrics.error
    run_row.finished_at = datetime.now(UTC)
    events.emit(
        EventType.RUN_FINISHED,
        {"status": status, "metrics": metrics.to_dict()},
    )
    session.commit()
