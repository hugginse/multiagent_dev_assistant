"""runs 子命令：历史列表、--events 回放、--diff 查看。"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("list")
def runs_list(
    limit: int = typer.Option(20, "--limit", "-n"),
    suite: str | None = typer.Option(None, "--suite"),
) -> None:
    """列出历史 run：devassist runs list"""
    from sqlalchemy import select

    from app.db.models import RunRow
    from app.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
        if suite:
            stmt = stmt.where(RunRow.suite == suite)
        rows = s.scalars(stmt).all()

    table = Table(title=f"runs ({len(rows)})")
    for col in ("id", "task", "suite", "status", "resolve", "iters", "wall_s", "created"):
        table.add_column(col)
    for r in rows:
        m = r.metrics_json or {}
        table.add_row(
            r.id,
            r.task_id,
            r.suite,
            r.status,
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
) -> None:
    """查看单个 run：devassist runs show <id> --events | --diff"""
    from app.db.models import RunRow
    from app.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        row = s.get(RunRow, run_id)
        if row is None:
            console.print(f"[red]run 不存在: {run_id}[/red]")
            raise typer.Exit(1) from None

        if events:
            from app.events import load_events

            evs = load_events(s, run_id)
            console.print(f"[bold]events[/bold] ({len(evs)}) run={run_id}")
            for e in evs:
                payload = e.payload
                if e.type.value == "llm_delta":
                    brief = repr(payload.get("text", ""))[:60]
                elif e.type.value in {"node_enter", "node_exit"}:
                    brief = f"node={payload.get('node')} status={payload.get('status', '')}"
                elif e.type.value == "tool_call":
                    brief = f"tool={payload.get('name')}"
                elif e.type.value == "test_result":
                    brief = (
                        f"passed={payload.get('passed')} failed={payload.get('failed')} "
                        f"phase={payload.get('phase', 'agent')}"
                    )
                else:
                    brief = str(payload)[:80]
                console.print(f"  [{e.seq:>4}] {e.type.value:<16} {brief}")
            return

        if diff:
            from pathlib import Path

            if row.diff_path and Path(row.diff_path).exists():
                text = Path(row.diff_path).read_text(encoding="utf-8")
                if not text.strip():
                    console.print("(空 diff — Agent 未修改文件)")
                else:
                    console.print(text)
            else:
                console.print("[yellow]无 diff 记录[/yellow]")
            return

        console.print(f"[bold]{row.id}[/bold] task={row.task_id} suite={row.suite}")
        console.print(
            f"status={row.status} provider={row.provider} model={row.model} "
            f"memory_on={row.memory_on} iteration={row.iteration}"
        )
        console.print(f"metrics={row.metrics_json}")
        if row.error:
            console.print(f"[red]error={row.error}[/red]")
        console.print(f"diff_path={row.diff_path}")
        console.print("提示: 加 --events 回放事件，或 --diff 查看补丁")
