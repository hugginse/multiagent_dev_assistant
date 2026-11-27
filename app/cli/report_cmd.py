"""report / compare 子命令（M1 骨架）。"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)
compare_app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback(invoke_without_command=True)
def report(
    ctx: typer.Context,
    eval_id: str | None = typer.Option(None, "--eval", "-e", help="eval id"),
    path: Path | None = typer.Option(None, "--path", help="报告 JSON 路径"),
) -> None:
    """查看单份评测报告。"""
    if ctx.invoked_subcommand is not None:
        return
    from app.cli.report_cmd_impl import show_report

    code = show_report(eval_id=eval_id, path=path)
    raise typer.Exit(code)


@compare_app.callback(invoke_without_command=True)
def compare(
    ctx: typer.Context,
    a: Path | None = typer.Argument(None, help="报告 A JSON"),
    b: Path | None = typer.Argument(None, help="报告 B JSON"),
) -> None:
    """对比两份评测报告（A/B delta）。"""
    if ctx.invoked_subcommand is not None:
        return
    if a is None or b is None:
        typer.echo("用法: devassist compare <a.json> <b.json>", err=True)
        raise typer.Exit(2)
    from app.cli.report_cmd_impl import compare_reports

    code = compare_reports(a, b)
    raise typer.Exit(code)
