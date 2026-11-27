"""devassist CLI 入口：挂载子命令。

退出码：0 全部成功，1 存在失败任务，2 配置/环境错误。
"""

from __future__ import annotations

import sys

import typer

from app import __version__

app = typer.Typer(
    name="devassist",
    help="仓库级智能研发助手：多 Agent + 双层记忆 + 评测 harness（CLI）",
    no_args_is_help=True,
    add_completion=False,
)

# 子命令模块（M1 骨架：先注册，M1 后续 feature 填充实现）
from app.cli import eval_cmd, memory_cmd, report_cmd, run_cmd, runs_cmd, tasks_cmd  # noqa: E402

app.add_typer(run_cmd.app, name="run")
app.add_typer(eval_cmd.app, name="eval")
app.add_typer(report_cmd.app, name="report")
app.add_typer(report_cmd.compare_app, name="compare")
app.add_typer(tasks_cmd.app, name="tasks")
app.add_typer(runs_cmd.app, name="runs")
app.add_typer(memory_cmd.app, name="memory")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"devassist {__version__}")
        raise typer.Exit(0)


@app.callback()
def root(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="显示版本"
    ),
) -> None:
    """devassist — 多 Agent 仓库级研发助手."""


def main() -> None:
    """console script 入口。"""
    try:
        app()
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("中断", err=True)
        raise SystemExit(130) from None
    except Exception as e:  # noqa: BLE001 — 顶层统一错误 → 退出码 2
        typer.echo(f"错误: {e}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
