"""run 子命令：单任务运行（M1 骨架，M1 feature 15 接事件流）。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    task: str | None = typer.Option(None, "--task", "-t", help="任务 id，如 T001"),
    suite: str = typer.Option("smoke", "--suite", "-s", help="套件名"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="ollama|openai|anthropic"),
    memory: str = typer.Option("off", "--memory", help="on|off"),
) -> None:
    """运行单个任务，终端实时事件流。"""
    if ctx.invoked_subcommand is not None:
        return
    if not task:
        typer.echo("缺少 --task（例如 --task T001）", err=True)
        raise typer.Exit(2)

    from app.cli.run_cmd_impl import execute_run

    code = execute_run(
        task_id=task,
        suite=suite,
        provider=provider,
        memory=memory,
    )
    raise typer.Exit(code)
