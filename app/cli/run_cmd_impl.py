"""run 命令实现：harness runner + 终端事件订阅（真流式）。"""

from __future__ import annotations

from rich.console import Console

from app.cli.events_view import TerminalEventSubscriber

console = Console()


def execute_run(
    *,
    task_id: str,
    suite: str,
    provider: str | None,
    memory: str,
    show_llm: bool = True,
) -> int:
    """返回进程退出码：0 成功，1 失败，2 配置错误。"""
    from app.config import load_settings
    from app.harness.loader import SuiteError, load_task
    from app.harness.runner import run_single_task

    settings = load_settings()
    prov = provider or settings.llm_provider
    if memory not in {"on", "off"}:
        console.print("[red]--memory 必须是 on 或 off[/red]")
        return 2
    memory_on = memory == "on"

    try:
        task = load_task(suite, task_id)
    except SuiteError as e:
        console.print(f"[red]任务加载失败:[/red] {e}")
        return 2

    try:
        settings.resolve_llm_model()
        if prov in {"openai", "anthropic"}:
            settings.require_api_key()
    except ValueError as e:
        console.print(f"[red]配置错误:[/red] {e}")
        return 2

    viewer = TerminalEventSubscriber(show_llm_delta=show_llm, console_=console)

    try:
        outcome = run_single_task(
            task,
            suite=suite,
            provider=prov,
            memory_on=memory_on,
            event_subscribers=[viewer],
        )
    except Exception as e:  # noqa: BLE001
        viewer.finish()
        console.print(f"[red]运行失败:[/red] {e}")
        return 2
    viewer.finish()

    m = outcome.metrics
    style = "green" if m.resolve else "yellow"
    console.print(
        f"[{style}]run {outcome.run_id}[/{style}] task={outcome.task_id} "
        f"status={outcome.status} resolve={m.resolve} "
        f"pass_ratio={m.test_pass_ratio:.2f} iterations={m.iterations} "
        f"wall={m.wall_s:.1f}s"
    )
    console.print(f"回放: uv run devassist runs show {outcome.run_id} --events")
    if m.resolve:
        return 0
    return 1
