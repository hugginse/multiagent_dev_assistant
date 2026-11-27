"""eval 实现：遍历任务 × k 次 → JSON+MD+rich 表报告。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TimeElapsedColumn

console = Console()


def execute_eval(
    *,
    suite: str,
    k: int,
    provider: str | None,
    memory: str,
    limit: int | None,
    adapter: str = "local",
    data_path: str | None = None,
) -> tuple[int, str | None]:
    """返回 (exit_code, report_json_path|None)。"""
    if memory not in {"on", "off"}:
        console.print("[red]--memory 必须是 on 或 off[/red]")
        return 2, None
    memory_on = memory == "on"

    from app.config import load_settings
    from app.harness.adapters import get_adapter
    from app.harness.loader import SuiteError, load_tasks
    from app.harness.report import build_report, print_report_table, save_report
    from app.harness.runner import run_single_task

    settings = load_settings()
    prov = provider or settings.llm_provider
    try:
        if adapter == "local":
            tasks = load_tasks(suite)
            hidden_suite = suite
        else:
            ad = get_adapter(adapter, path=data_path) if data_path else get_adapter(adapter)
            tasks = ad.load_tasks()
            # 隐藏测试目录与 adapter 对齐（swe_bench → suites/swe_bench/hidden_tests）
            hidden_suite = "swe_bench" if adapter in {"swe_bench", "swe", "swebench"} else suite
            console.print(f"[dim]adapter={adapter} tasks={len(tasks)} hidden_suite={hidden_suite}[/dim]")
    except (SuiteError, ValueError, FileNotFoundError) as e:
        console.print(f"[red]任务加载失败:[/red] {e}")
        return 2, None
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]adapter 加载失败:[/red] {e}")
        return 2, None
    if limit is not None:
        tasks = tasks[:limit]
    if not tasks:
        console.print("[red]无任务可执行[/red]")
        return 2, None

    eval_id = f"eval_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    items: list[dict] = []
    any_fail = False
    total = len(tasks) * k

    progress = Progress(
        TaskProgressColumn(),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    with progress:
        task_prog = progress.add_task(f"eval {suite}", total=total)
        for task in tasks:
            for sample in range(1, k + 1):
                progress.update(
                    task_prog,
                    description=f"[cyan]{task.id}[/cyan] {task.title[:24]}",
                )
                progress.console.print(
                    f"[dim]{task.id}[/dim] {task.title[:40]} "
                    f"sample={sample}/{k} …",
                    end=" ",
                )
                try:
                    from app.agents.nodes.llm_bridge import make_streaming_llm
                    from app.config import Settings
                    from app.llm.client import create_llm_client

                    run_settings = Settings(
                        _env_file=None,
                        llm_provider=prov,
                        ollama_host=settings.ollama_host,
                        local_model=settings.local_model,
                        ollama_num_ctx=settings.ollama_num_ctx,
                        openai_api_key=settings.openai_api_key,
                        openai_base_url=settings.openai_base_url,
                        openai_model=settings.openai_model,
                        anthropic_api_key=settings.anthropic_api_key,
                        anthropic_model=settings.anthropic_model,
                    )
                    client = create_llm_client(run_settings)
                    holder: dict = {}

                    def _emit(text: str, _h=holder) -> None:
                        ev = _h.get("events")
                        if ev is not None:
                            from app.events import EventType

                            ev.emit(EventType.LLM_DELTA, {"node": "agent", "text": text})

                    llm_fn = make_streaming_llm(client, emit_delta=_emit)
                    outcome = run_single_task(
                        task,
                        suite=hidden_suite,
                        provider=prov,
                        memory_on=memory_on,
                        llm=llm_fn,
                        llm_emit_holder=holder,
                    )
                    client.close()
                except Exception as e:  # noqa: BLE001
                    progress.console.print(f"[red]error:[/red] {e}")
                    any_fail = True
                    items.append(
                        {
                            "task_id": task.id,
                            "sample": sample,
                            "resolve": False,
                            "pass_ratio": 0.0,
                            "iterations": 0,
                            "max_hit": False,
                            "tool_calls": {},
                            "tokens_in": 0,
                            "tokens_out": 0,
                            "wall_s": 0.0,
                            "status": "error",
                            "run_id": None,
                            "error": str(e),
                        }
                    )
                    progress.advance(task_prog)
                    continue
                m = outcome.metrics
                ok = m.resolve
                if not ok:
                    any_fail = True
                style = "green" if ok else "yellow"
                progress.console.print(
                    f"[{style}]{'resolve' if ok else 'miss'}[/{style}] "
                    f"ratio={m.test_pass_ratio:.2f} it={m.iterations} "
                    f"wall={m.wall_s:.1f}s"
                )
                items.append(
                    {
                        "task_id": task.id,
                        "sample": sample,
                        "resolve": m.resolve,
                        "pass_ratio": m.test_pass_ratio,
                        "iterations": m.iterations,
                        "max_hit": m.max_hit,
                        "tool_calls": m.tool_calls,
                        "tokens_in": m.tokens_in,
                        "tokens_out": m.tokens_out,
                        "wall_s": m.wall_s,
                        "status": m.status,
                        "run_id": outcome.run_id,
                        "error": m.error,
                    }
                )
                progress.advance(task_prog)

    report = build_report(
        eval_id=eval_id,
        suite=suite,
        k=k,
        provider=prov,
        model=settings.resolve_llm_model(),
        memory_on=memory_on,
        items=items,
        notes="tokens 本地模型可能为估算口径",
    )
    jp, mp = save_report(report, Path("data/reports"))
    print_report_table(report)
    console.print(f"报告: [bold]{jp}[/bold]")
    console.print(f"      [bold]{mp}[/bold]")

    try:
        from app.db.models import EvalItemRow, EvalRow
        from app.db.session import init_db, session_scope

        init_db()
        with session_scope() as s:
            s.add(
                EvalRow(
                    id=eval_id,
                    suite=suite,
                    k=k,
                    provider=prov,
                    model=report.model,
                    memory_on=memory_on,
                    status="done",
                    report_path=str(jp),
                    finished_at=datetime.now(UTC),
                )
            )
            for it in items:
                s.add(
                    EvalItemRow(
                        eval_id=eval_id,
                        task_id=it["task_id"],
                        sample=it["sample"],
                        run_id=it.get("run_id"),
                        resolve=it["resolve"],
                        pass_ratio=it["pass_ratio"],
                        iterations=it["iterations"],
                        tokens_in=it["tokens_in"],
                        tokens_out=it["tokens_out"],
                        wall_s=it["wall_s"],
                        status=it["status"],
                    )
                )
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]警告: eval 落库失败 {e}[/yellow]")

    return (1 if any_fail else 0), str(jp)


def execute_memory_ab(
    *,
    suite: str,
    k: int,
    provider: str | None,
    limit: int | None,
    adapter: str = "local",
    data_path: str | None = None,
) -> int:
    """记忆 A/B：同套件 memory on → off 双跑，自动 compare。

    返回进程退出码（双跑任一配置失败任务存在则 1；配置错误 2）。
    """
    console.print("[bold]记忆 A/B[/bold]：先 --memory on，再 --memory off，最后 compare")

    code_on, path_on = execute_eval(
        suite=suite,
        k=k,
        provider=provider,
        memory="on",
        limit=limit,
        adapter=adapter,
        data_path=data_path,
    )
    if path_on is None:
        return code_on if code_on != 0 else 2
    console.print(f"[green]memory ON[/green] 报告: {path_on}")

    code_off, path_off = execute_eval(
        suite=suite,
        k=k,
        provider=provider,
        memory="off",
        limit=limit,
        adapter=adapter,
        data_path=data_path,
    )
    if path_off is None:
        return code_off if code_off != 0 else 2
    console.print(f"[yellow]memory OFF[/yellow] 报告: {path_off}")

    from app.cli.report_cmd_impl import compare_reports_paths

    console.print("\n[bold]A/B 对比（ON vs OFF）[/bold]")
    cmp_code = compare_reports_paths(Path(path_on), Path(path_off))
    # 双跑均无失败任务才算完全成功
    if cmp_code != 0:
        return cmp_code
    return 0 if code_on == 0 and code_off == 0 else 1

