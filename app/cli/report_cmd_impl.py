"""report / compare 实现。"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def _load_report(eval_id: str | None, path: Path | None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    if eval_id:
        p = Path("data/reports") / f"{eval_id}.json"
        if not p.exists():
            # 允许直接传 id 对应完整文件名
            alt = Path("data/reports") / eval_id
            if alt.exists():
                p = alt
            else:
                raise FileNotFoundError(f"报告不存在: {p}")
        return json.loads(p.read_text(encoding="utf-8"))
    raise ValueError("需要 --eval 或 --path")


def show_report(*, eval_id: str | None, path: Path | None) -> int:
    try:
        report = _load_report(eval_id, path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]{e}[/red]")
        return 2

    table = Table(title=f"report {report.get('eval_id', '?')}")
    for col in ("task_id", "sample", "resolve", "pass_ratio", "iterations", "wall_s", "status"):
        table.add_column(col)
    for it in report.get("items", []):
        table.add_row(
            str(it.get("task_id")),
            str(it.get("sample")),
            str(it.get("resolve")),
            f"{float(it.get('pass_ratio') or 0):.2f}",
            str(it.get("iterations")),
            f"{float(it.get('wall_s') or 0):.1f}",
            str(it.get("status")),
        )
    console.print(table)
    console.print(f"resolve_rate={report.get('resolve_rate')} pass@k={report.get('pass_at_k')}")
    return 0


def compare_reports(a_path: Path, b_path: Path) -> int:
    try:
        a = json.loads(a_path.read_text(encoding="utf-8"))
        b = json.loads(b_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[red]读取失败:[/red] {e}")
        return 2

    def key(item: dict) -> tuple[str, int]:
        return (str(item.get("task_id")), int(item.get("sample") or 0))

    amap = {key(i): i for i in a.get("items", [])}
    bmap = {key(i): i for i in b.get("items", [])}
    keys = sorted(set(amap) | set(bmap))

    table = Table(title=f"compare  A={a.get('eval_id', a_path.name)}  B={b.get('eval_id', b_path.name)}")
    table.add_column("task")
    table.add_column("sample")
    table.add_column("A resolve")
    table.add_column("B resolve")
    table.add_column("Δ resolve")
    table.add_column("A ratio")
    table.add_column("B ratio")
    table.add_column("Δ ratio")
    table.add_column("Δ wall_s")

    for k in keys:
        ai, bi = amap.get(k), bmap.get(k)
        ar = bool(ai.get("resolve")) if ai else False
        br = bool(bi.get("resolve")) if bi else False
        apr = float(ai.get("pass_ratio") or 0) if ai else 0.0
        bpr = float(bi.get("pass_ratio") or 0) if bi else 0.0
        aw = float(ai.get("wall_s") or 0) if ai else 0.0
        bw = float(bi.get("wall_s") or 0) if bi else 0.0
        dr = int(br) - int(ar)
        dstyle = "green" if dr > 0 else ("red" if dr < 0 else "dim")
        table.add_row(
            k[0],
            str(k[1]),
            str(ar),
            str(br),
            f"[{dstyle}]{dr:+d}[/{dstyle}]",
            f"{apr:.2f}",
            f"{bpr:.2f}",
            f"{bpr - apr:+.2f}",
            f"{bw - aw:+.1f}",
        )

    console.print(table)
    ra = float(a.get("resolve_rate") or 0)
    rb = float(b.get("resolve_rate") or 0)
    console.print(f"resolve_rate  A={ra:.2%}  B={rb:.2%}  Δ={rb - ra:+.2%}")
    return 0
