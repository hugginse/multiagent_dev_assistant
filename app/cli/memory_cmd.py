"""memory 子命令：onboarding / list / search（M1 骨架，M3 完善）。"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("onboarding")
def onboarding(
    path: str = typer.Option(..., "--path", help="仓库路径"),
) -> None:
    """仓库约定抽取（M1 占位；M3 接 LLM）。"""
    console.print(f"[yellow]onboarding 尚未实现（M3）:[/yellow] path={path}")
    raise typer.Exit(2)


@app.command("list")
def list_memories(
    kind: str | None = typer.Option(None, "--kind", help="convention|episode"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """列出长期记忆。"""
    from sqlalchemy import select

    from app.db.models import MemoryRow
    from app.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        stmt = select(MemoryRow).order_by(MemoryRow.created_at.desc()).limit(limit)
        if kind:
            stmt = stmt.where(MemoryRow.kind == kind)
        rows = s.scalars(stmt).all()

    if not rows:
        console.print("(无记忆记录)")
        return
    table = Table(title=f"memories ({len(rows)})")
    for col in ("id", "kind", "repo", "title", "task_ref", "updated"):
        table.add_column(col)
    for m in rows:
        table.add_row(m.id, m.kind, m.repo_id, m.title, m.task_ref or "", str(m.updated_at))
    console.print(table)


@app.command("search")
def search(
    query: str = typer.Argument(..., help="检索文本"),
    k: int = typer.Option(5, "--k", "-k"),
) -> None:
    """向量检索（M1 占位；M3 接 Chroma）。"""
    console.print(f"[yellow]memory search 尚未实现（M3）:[/yellow] q={query!r} k={k}")
    raise typer.Exit(2)
