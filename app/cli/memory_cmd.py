"""memory 子命令：onboarding / list / search 调试。"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("onboarding")
def onboarding(
    path: str = typer.Option(..., "--path", help="仓库路径，如 sample_repo"),
    repo_id: str | None = typer.Option(
        None, "--repo-id", help="默认取目录名；用于与已有 memories 对齐"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="只抽取不落库"),
) -> None:
    """仓库约定抽取（LLM → convention 记忆）。"""
    from app.memory.onboarding import run_onboarding

    p = Path(path)
    if not p.exists():
        console.print(f"[red]路径不存在:[/red] {path}")
        raise typer.Exit(2)

    console.print(f"扫描 {p.resolve()} …")
    result = run_onboarding(p, memory_on=not dry_run)

    if result.status != "done":
        console.print(f"[red]onboarding 失败:[/red] {result.error}")
        raise typer.Exit(1)

    console.print(
        f"[green]done[/green] repo={result.repo_id} files={result.scanned_files} "
        f"conventions={len(result.conventions)} memories={len(result.memory_ids)}"
    )
    table = Table(title="conventions")
    table.add_column("title")
    table.add_column("content")
    for c in result.conventions:
        table.add_row(c["title"], c["content"][:120])
    console.print(table)
    if dry_run:
        console.print("[yellow]dry-run：未写入数据库[/yellow]")


@app.command("list")
def list_memories(
    kind: str | None = typer.Option(None, "--kind", help="convention|episode"),
    repo: str | None = typer.Option(None, "--repo", help="repo_id 过滤"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """列出长期记忆。"""
    from app.memory.long_term import LongTermMemory

    mem = LongTermMemory()
    rows = mem.list(repo_id=repo, kind=kind, limit=limit)
    if not rows:
        console.print("(无记忆记录)")
        return
    table = Table(title=f"memories ({len(rows)})")
    for col in ("id", "kind", "repo", "title", "task_ref", "updated"):
        table.add_column(col)
    for m in rows:
        table.add_row(m.id, m.kind, m.repo_id, m.title, m.task_ref or "", str(m.updated_at))
    console.print(table)
    console.print(
        f"total={mem.count()} convention={mem.count(kind='convention')} "
        f"episode={mem.count(kind='episode')}"
    )


@app.command("search")
def search(
    query: str = typer.Argument(..., help="检索文本"),
    k: int = typer.Option(5, "--k", "-k"),
    repo: str = typer.Option("sample_repo", "--repo"),
    kind: str | None = typer.Option(None, "--kind"),
    min_score: float | None = typer.Option(None, "--min-score"),
) -> None:
    """向量检索调试（cosine top-k + 阈值）。"""
    from app.memory.long_term import LongTermMemory

    mem = LongTermMemory()
    try:
        hits = mem.search(
            query, repo_id=repo, kind=kind, top_k=k, min_score=min_score
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]检索失败:[/red] {e}")
        raise typer.Exit(1) from None

    if not hits:
        console.print("(无命中，可能低于阈值或 repo 无数据)")
        return
    table = Table(title=f"search: {query!r}")
    for col in ("score", "kind", "title", "content"):
        table.add_column(col)
    for h in hits:
        table.add_row(
            f"{h.score:.3f}",
            h.kind,
            h.title,
            h.content[:100].replace("\n", " "),
        )
    console.print(table)
