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

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents.graph import build_graph
from app.agents.nodes.agent_node import LLMFn
from app.agents.state import AgentState, TestRecord, initial_state
from app.config import load_settings
from app.db.models import RunRow
from app.db.session import create_checkpointer, session_scope
from app.events import EventStore, EventType, assert_seq_monotonic, load_events
from app.harness.loader import resolve_hidden_test_paths, suite_dir
from app.harness.schema import RunMetrics, TaskDefinition
from app.sandbox.workspace import (
    prepare_workspace,
    run_command,
)


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

    try:
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,sys;"
                    "from filecmp import dircmp;\n"
                    "def walk(dc, base_a, base_b, out):\n"
                    "    for name in dc.left_only:\n"
                    "        out.append(f'--- {base_a}/{name}\\n+++ /dev/null\\n');\n"
                    "    for name in dc.right_only:\n"
                    "        p=pathlib.Path(base_b)/name\n"
                    "        if p.is_file():\n"
                    "            out.append(f'--- /dev/null\\n+++ {base_b}/{name}\\n'+p.read_text(errors='replace'))\n"
                    "    for name in dc.same_files:\n"
                    "        pass\n"
                    "    for name in dc.diff_files:\n"
                    "        a=pathlib.Path(base_a)/name; b=pathlib.Path(base_b)/name\n"
                    "        out.append(f'--- {base_a}/{name}\\n+++ {base_b}/{name}\\n')\n"
                    "        import difflib\n"
                    "        out.extend(difflib.unified_diff(a.read_text(errors='replace').splitlines(True),\n"
                    "                                        b.read_text(errors='replace').splitlines(True),\n"
                    "                                        fromfile=str(a), tofile=str(b)))\n"
                    "    for sub in dc.subdirs.values():\n"
                    "        walk(sub, base_a+'/'+sub.left, base_b+'/'+sub.right, out)\n"
                    "out=[]\n"
                    "walk(dircmp(str(sys.argv[1]), str(sys.argv[2])), sys.argv[1], sys.argv[2], out)\n"
                    "print(''.join(out), end='')\n"
                ),
                str(baseline),
                str(workspace),
            ],
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

    # 注入到隐藏测试目录的相对结构
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

    cmd = ["python", "-m", "pytest", "-q", *rels]
    r = run_command(cmd, cwd=workspace, timeout_s=timeout_s, output_limit=20_000)
    out = (r.stdout + "\n" + r.stderr).strip()
    # 解析 pytest 摘要
    passed, failed = _parse_pytest_counts(out)
    if r.timed_out:
        return passed, max(failed, 1), out[-2000:], -1
    if r.returncode == 0 and failed == 0 and passed > 0:
        return passed, 0, out[-2000:], 0
    if r.returncode == 0 and passed == 0:
        # 没有收集到测试视为失败
        return 0, 1, out[-2000:], r.returncode
    return passed, max(failed, 1 if passed == 0 and failed == 0 else failed), out[-2000:], r.returncode


def _parse_pytest_counts(output: str) -> tuple[int, int]:
    """从 pytest 输出解析 passed/failed。"""
    import re

    passed = failed = 0
    # 形如: 12 passed, 3 failed in 0.5s  或  5 failed
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    # 纯点号 quiet 模式失败时可能只有 failed
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
) -> RunOutcome:
    """端到端执行一个任务。session 为 None 时自建事务。"""
    settings = load_settings()
    rid = run_id or new_run_id()
    prov = provider or settings.llm_provider
    mdl = model or settings.resolve_llm_model()

    owned_session = session is None
    if owned_session:
        # 确保表存在
        from app.db.session import init_db

        init_db()
        cm = session_scope()
        session = cm.__enter__()
    assert session is not None

    try:
        # 落库 run 行
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
        session.flush()

        events = EventStore(session, rid)
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
        if memory_on and memory_context:
            events.emit(
                EventType.MEMORY_INJECTED,
                {"chars": len(memory_context), "preview": memory_context[:200]},
            )

        # workspace（不含隐藏测试）
        repo_path = find_repo_root(task.repo)
        baseline = repo_path
        ws = prepare_workspace(repo_path, rid, hidden_tests=None)

        # 真实测试回调：Agent 运行期在 workspace 跑可见测试
        def _default_on_test(state: AgentState) -> TestRecord:
            it = int(state.get("iteration") or 0)
            r = run_command(
                ["python", "-m", "pytest", "-q", "tests"],
                cwd=ws,
                timeout_s=min(task.timeout_s, 120.0),
                output_limit=8000,
            )
            passed, failed = _parse_pytest_counts((r.stdout + r.stderr).strip())
            if r.returncode == 0 and passed == 0 and failed == 0:
                # 无 tests 目录等情况
                passed, failed = (0, 0) if r.returncode == 0 else (0, 1)
            return TestRecord(
                iteration=it,
                passed=passed,
                failed=failed,
                output_tail=(r.stdout + r.stderr)[-1500:],
                returncode=r.returncode,
            )

        on_test = on_node_test or _default_on_test

        cp = create_checkpointer()
        graph = build_graph(llm=llm, events=events, on_test=on_test, checkpointer=cp)
        state = initial_state(task, memory_context=memory_context)
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

        # 隐藏测试评分（Agent 不可见；评分阶段注入）
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
        status = "success" if resolve else (
            "timeout" if final.get("status") == "timeout" else "success"
        )
        # 即使 hidden 全过，图 timeout 也如实记录
        if final.get("status") == "timeout" and not resolve:
            status = "timeout"
        if final.get("status") == "error":
            status = "error"

        metrics = RunMetrics(
            resolve=resolve,
            test_pass_ratio=ratio,
            iterations=iteration,
            max_hit=max_hit,
            tool_calls={},  # M2 扩展
            tokens_in=0,
            tokens_out=0,
            wall_s=wall,
            status=status,
            error=final.get("error") or None,
        )
        if score_out and not resolve:
            metrics.error = (metrics.error or "") + f" | hidden: {score_out[-500:]}"

        # 保存 diff
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
        if owned_session:
            cm.__exit__(None, None, None)  # type: ignore[possibly-undefined]


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
    session.flush()
