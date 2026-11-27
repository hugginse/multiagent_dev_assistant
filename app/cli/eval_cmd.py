"""eval 子命令：批量评测 + 记忆 A/B 模式。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback(invoke_without_command=True)
def evaluate(
    ctx: typer.Context,
    suite: str = typer.Option("smoke", "--suite", "-s"),
    k: int = typer.Option(1, "--k", "-k", min=1, max=16, help="pass@k 采样次数"),
    provider: str | None = typer.Option(None, "--provider", "-p"),
    memory: str = typer.Option("off", "--memory", help="on|off"),
    limit: int | None = typer.Option(None, "--limit", help="仅跑前 N 条任务"),
    ab: bool = typer.Option(
        False,
        "--ab",
        help="记忆 A/B：同套件 memory on/off 双跑并自动 compare（忽略 --memory）",
    ),
) -> None:
    """批量评测套件并产出报告。"""
    if ctx.invoked_subcommand is not None:
        return
    from app.cli.eval_cmd_impl import execute_eval, execute_memory_ab

    if ab:
        code = execute_memory_ab(suite=suite, k=k, provider=provider, limit=limit)
        raise typer.Exit(code)

    code, _path = execute_eval(
        suite=suite, k=k, provider=provider, memory=memory, limit=limit
    )
    raise typer.Exit(code)
