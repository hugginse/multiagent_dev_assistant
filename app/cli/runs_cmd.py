"""runs 子命令：历史列表、详情、--events 回放、--diff 查看。

退出码约定（architecture.md §8.2）：
- 0 成功
- 1 run 不存在 / 有失败任务
- 2 配置或环境错误
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("list")
def runs_list(
    limit: int = typer.Option(20, "--limit", "-n", help="最多显示条数"),
    suite: str | None = typer.Option(None, "--suite", help="按套件过滤"),
    task: str | None = typer.Option(None, "--task", "-t", help="按任务 id 过滤"),
    status: str | None = typer.Option(
        None, "--status", help="running|success|timeout|error"
    ),
) -> None:
    """列出历史 run：devassist runs list"""
    from sqlalchemy import select

    from app.db.models import RunRow
    from app.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(max(1, limit))
        if suite:
            stmt = stmt.where(RunRow.suite == suite)
        if task:
            stmt = stmt.where(RunRow.task_id == task)
        if status:
            stmt = stmt.where(RunRow.status == status)
        rows = s.scalars(stmt).all()

    if not rows:
        console.print("(无匹配的 run)")
        return

    table = Table(title=f"runs ({len(rows)})")
    for col in ("id", "task", "suite", "status", "resolve", "iters", "wall_s", "created"):
        table.add_column(col)
    for r in rows:
        m = r.metrics_json or {}
        style = {
            "success": "green",
            "timeout": "yellow",
            "error": "red",
            "running": "cyan",
        }.get(r.status, "white")
        table.add_row(
            r.id,
            r.task_id,
            r.suite,
            f"[{style}]{r.status}[/{style}]",
            str(m.get("resolve", "")),
            str(m.get("iterations", r.iteration)),
            f"{float(m.get('wall_s') or 0):.1f}",
            str(r.created_at or ""),
        )
    console.print(table)


@app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="run id"),
    events: bool = typer.Option(False, "--events", help="回放事件时间线"),
    diff: bool = typer.Option(False, "--diff", help="查看产出 diff"),
    limit: int = typer.Option(0, "--limit", help="events 最多显示条数（0=全部）"),
) -> None:
    """查看单个 run：devassist runs show <id> [--events|--diff]

    退出码：0 成功；1 run 不存在；2 环境错误。
    """
    from app.db.models import RunRow
    from app.db.session import init_db, session_scope

    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]数据库初始化失败:[/red] {e}")
        raise typer.Exit(2) from None

    with session_scope() as s:
        row = s.get(RunRow, run_id)
        if row is None:
            console.print(f"[red]run 不存在: {run_id}[/red]")
            raise typer.Exit(1) from None

        if events:
            from app.events import load_events

            evs = load_events(s, run_id)
            shown = evs if limit <= 0 else evs[:limit]
            console.print(
                f"[bold]events[/bold] ({len(evs)}"
                + (f", 显示前 {len(shown)}" if limit > 0 else "")
                + f") run={run_id}"
            )
            for e in shown:
                console.print(f"  [{e.seq:>4}] {e.type.value:<16} {_brief(e.payload, e.type.value)}")
            if limit > 0 and len(evs) > len(shown):
                console.print(f"  … 其余 {len(evs) - len(shown)} 条省略（--limit 0 查看全部）")
            return

        if diff:
            if row.diff_path and Path(row.diff_path).exists():
                text = Path(row.diff_path).read_text(encoding="utf-8")
                if not text.strip():
                    console.print("(空 diff — Agent 未修改文件)")
                else:
                    console.print(text)
            else:
                console.print("[yellow]无 diff 记录[/yellow]")
            return

        # 默认详情
        m = row.metrics_json or {}
        console.print(f"[bold]{row.id}[/bold] task={row.task_id} suite={row.suite}")
        console.print(
            f"status={row.status} provider={row.provider} model={row.model} "
            f"memory_on={row.memory_on} iteration={row.iteration}"
        )
        console.print(f"metrics={m}")
        if row.error:
            console.print(f"[red]error={row.error}[/red]")
        console.print(f"diff_path={row.diff_path}")
        # workspace 提示
        ws = Path("data") / "workspaces" / row.id
        if ws.is_dir():
            console.print(f"workspace={ws}")
        console.print("提示: 加 --events 回放事件，或 --diff 查看补丁")


def _brief(payload: dict, etype: str) -> str:
    if etype == "llm_delta":
        return repr(payload.get("text", ""))[:60]
    if etype in {"node_enter", "node_exit"}:
        return f"node={payload.get('node')} status={payload.get('status', '')}"
    if etype == "tool_call":
        return f"tool={payload.get('name')} tier={payload.get('tier', '?')}"
    if etype == "tool_result":
        rej = " rejected" if payload.get("rejected") else ""
        return f"tool={payload.get('name')} ok={payload.get('ok')}{rej}"
    if etype == "test_result":
        return (
            f"passed={payload.get('passed')} failed={payload.get('failed')} "
            f"phase={payload.get('phase', 'agent')}"
        )
    return str(payload)[:80]
