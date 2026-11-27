"""tasks 子命令：套件与任务列表。"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("list")
def tasks_list(
    suite: str = typer.Option("smoke", "--suite", "-s"),
) -> None:
    """列出套件任务：devassist tasks list --suite smoke"""
    from app.harness.loader import SuiteError, load_tasks

    try:
        items = load_tasks(suite)
    except SuiteError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from None

    table = Table(title=f"suite={suite} ({len(items)})")
    for col in ("id", "title", "difficulty", "tags", "hidden", "max_iter"):
        table.add_column(col)
    for t in items:
        table.add_row(
            t.id,
            t.title,
            t.difficulty,
            ",".join(t.tags),
            str(len(t.hidden_tests)),
            str(t.max_iterations),
        )
    console.print(table)


@app.command("show")
def tasks_show(
    task_id: str = typer.Argument(...),
    suite: str = typer.Option("smoke", "--suite", "-s"),
) -> None:
    """查看单个任务定义（prompt 可见；hidden_tests 仅列路径名）。"""
    from app.harness.loader import SuiteError, load_task

    try:
        t = load_task(suite, task_id)
    except SuiteError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[bold]{t.id}[/bold] {t.title}")
    console.print(f"repo={t.repo} difficulty={t.difficulty} tags={t.tags}")
    console.print(f"max_iterations={t.max_iterations} timeout_s={t.timeout_s}")
    console.print(f"hidden_tests={t.hidden_tests}  (评分阶段注入，Agent 不可见)")
    console.print("--- prompt ---")
    console.print(t.prompt)
