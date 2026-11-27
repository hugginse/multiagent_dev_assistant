"""report / compare 实现。"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from app.harness.report import Report as _Report  # noqa: F401 — re-export aid
from app.harness.report import (
    compare_reports,
    print_compare_console,
    print_report_table,
)

console = Console()


def _load_report(eval_id: str | None, path: Path | None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    if eval_id:
        p = Path("data/reports") / f"{eval_id}.json"
        if not p.exists():
            alt = Path("data/reports") / eval_id
            if alt.exists():
                p = alt
            else:
                raise FileNotFoundError(f"报告不存在: {p}")
        return json.loads(p.read_text(encoding="utf-8"))
    raise ValueError("需要 --eval 或 --path")


def show_report(*, eval_id: str | None, path: Path | None) -> int:
    try:
        data = _load_report(eval_id, path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]{e}[/red]")
        return 2

    # 组装为 Report 结构打印
    from app.harness.report import Report

    rep = Report(
        eval_id=data.get("eval_id", "?"),
        suite=data.get("suite", "?"),
        k=int(data.get("k") or 1),
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        memory_on=bool(data.get("memory_on")),
        items=data.get("items", []),
        pass_at_k=data.get("pass_at_k") or {},
        resolve_rate=float(data.get("resolve_rate") or 0),
        created_at=data.get("created_at", ""),
        notes=data.get("notes", ""),
    )
    print_report_table(rep)
    md_path = Path("data/reports") / f"{rep.eval_id}.md"
    if md_path.exists():
        console.print(f"markdown: [bold]{md_path}[/bold]")
    return 0


def compare_reports_paths(a_path: Path, b_path: Path) -> int:
    try:
        a = json.loads(a_path.read_text(encoding="utf-8"))
        b = json.loads(b_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[red]读取失败:[/red] {e}")
        return 2

    print_compare_console(a, b)

    # 同时落一份对比 md，便于贴报告
    out = Path("data/reports") / f"compare_{a.get('eval_id', 'A')}_vs_{b.get('eval_id', 'B')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(compare_reports(a, b), encoding="utf-8")
    console.print(f"对比报告: [bold]{out}[/bold]")
    return 0
