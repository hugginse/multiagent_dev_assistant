"""报告：JSON / Markdown / 终端 rich 表，pass@k、对比。

产出：
- ``data/reports/{eval_id}.json``（机器）
- ``data/reports/{eval_id}.md``（人读）
- 终端 rich 表
- ``devassist compare a.json b.json`` → 逐任务 delta
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from math import comb
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass(slots=True)
class Report:
    eval_id: str
    suite: str
    k: int
    provider: str
    model: str
    memory_on: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    pass_at_k: dict[str, float] = field(default_factory=dict)
    resolve_rate: float = 0.0
    tool_calls_by_tier: dict[str, int] = field(default_factory=dict)
    max_hit_rate: float = 0.0
    created_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate_tool_calls_by_tier(items: list[dict[str, Any]]) -> dict[str, int]:
    """汇总全部 item 的 tool_calls（按 tier 相加）。"""
    out: dict[str, int] = {}
    for it in items:
        tc = it.get("tool_calls") or {}
        if not isinstance(tc, dict):
            continue
        for tier, n in tc.items():
            out[str(tier)] = out.get(str(tier), 0) + int(n or 0)
    return out


def max_hit_rate(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    hits = sum(1 for i in items if i.get("max_hit"))
    return hits / len(items)


def compute_pass_at_k(items: list[dict[str, Any]], tasks_ids: list[str], k: int) -> dict[str, float]:
    """标准无偏 pass@k = 1 - C(n-c, k) / C(n, k)。"""
    result: dict[str, float] = {}
    for tid in tasks_ids:
        rs = [1 if i.get("resolve") else 0 for i in items if i.get("task_id") == tid]
        n = len(rs)
        c = sum(rs)
        if n == 0:
            result[tid] = 0.0
            continue
        if n < k:
            result[tid] = 1.0 if c > 0 else 0.0
            continue
        p = 1.0 if n - c < k else 1.0 - comb(n - c, k) / comb(n, k)
        result[tid] = p
    return result


def build_report(
    *,
    eval_id: str,
    suite: str,
    k: int,
    provider: str,
    model: str,
    memory_on: bool,
    items: list[dict[str, Any]],
    notes: str = "",
) -> Report:
    task_ids = sorted({str(i.get("task_id")) for i in items})
    resolve_rate = sum(1 for i in items if i.get("resolve")) / max(1, len(items))
    return Report(
        eval_id=eval_id,
        suite=suite,
        k=k,
        provider=provider,
        model=model,
        memory_on=memory_on,
        items=items,
        pass_at_k=compute_pass_at_k(items, task_ids, k),
        resolve_rate=resolve_rate,
        tool_calls_by_tier=aggregate_tool_calls_by_tier(items),
        max_hit_rate=max_hit_rate(items),
        created_at=datetime.now(UTC).isoformat(),
        notes=notes,
    )


def save_report(report: Report, out_dir: Path | str = "data/reports") -> tuple[Path, Path]:
    """写 JSON + Markdown；返回 (json_path, md_path)。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"{report.eval_id}.json"
    mp = out / f"{report.eval_id}.md"
    jp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(render_markdown(report), encoding="utf-8")
    return jp, mp


def render_markdown(report: Report) -> str:
    lines = [
        f"# Eval Report — {report.eval_id}",
        "",
        f"- suite: `{report.suite}`",
        f"- k: {report.k}",
        f"- provider/model: `{report.provider}` / `{report.model}`",
        f"- memory_on: {report.memory_on}",
        f"- created_at: {report.created_at}",
        f"- resolve_rate: **{report.resolve_rate:.2%}**",
        f"- pass@k: `{report.pass_at_k}`",
        f"- tool_calls by tier: `{report.tool_calls_by_tier}`",
        f"- max_hit_rate: **{report.max_hit_rate:.2%}**",
        "",
        "| task | sample | resolve | pass_ratio | iterations | max_hit | tool_calls | tokens_in | tokens_out | wall_s | status |",
        "|---|---:|:---:|---:|---:|:---:|---|---:|---:|---:|---|",
    ]
    for it in report.items:
        tc = it.get("tool_calls") or {}
        tc_s = ",".join(f"{k}={v}" for k, v in sorted(tc.items())) if tc else ""
        lines.append(
            f"| {it.get('task_id')} | {it.get('sample')} | "
            f"{'✅' if it.get('resolve') else '❌'} | "
            f"{float(it.get('pass_ratio') or 0):.2f} | "
            f"{it.get('iterations')} | "
            f"{'Y' if it.get('max_hit') else 'N'} | "
            f"{tc_s} | {it.get('tokens_in')} | {it.get('tokens_out')} | "
            f"{float(it.get('wall_s') or 0):.1f} | {it.get('status')} |"
        )
    if report.notes:
        lines += ["", f"> {report.notes}"]
    lines.append("")
    return "\n".join(lines)


def print_report_table(report: Report) -> None:
    table = Table(title=f"eval {report.eval_id} · suite={report.suite} · k={report.k}")
    for col in ("task", "sample", "resolve", "pass_ratio", "iters", "max_hit", "tools", "wall_s", "status"):
        table.add_column(col)
    for it in report.items:
        style = "green" if it.get("resolve") else "red"
        tc = it.get("tool_calls") or {}
        tc_s = ",".join(f"{k}:{v}" for k, v in sorted(tc.items())) if tc else ""
        table.add_row(
            str(it.get("task_id")),
            str(it.get("sample")),
            f"[{style}]{it.get('resolve')}[/{style}]",
            f"{float(it.get('pass_ratio') or 0):.2f}",
            str(it.get("iterations")),
            "Y" if it.get("max_hit") else "N",
            tc_s,
            f"{float(it.get('wall_s') or 0):.1f}",
            str(it.get("status")),
        )
    console.print(table)
    console.print(
        f"resolve_rate={report.resolve_rate:.2%}  pass@k={report.pass_at_k}  "
        f"tool_calls={report.tool_calls_by_tier}  max_hit_rate={report.max_hit_rate:.2%}"
    )


def compare_reports(a: dict[str, Any], b: dict[str, Any]) -> str:
    """生成 A/B 对比 Markdown（delta 表）。"""

    def key(item: dict) -> tuple[str, int]:
        return (str(item.get("task_id")), int(item.get("sample") or 0))

    amap = {key(i): i for i in a.get("items", [])}
    bmap = {key(i): i for i in b.get("items", [])}
    keys = sorted(set(amap) | set(bmap))

    lines = [
        f"# Compare — A={a.get('eval_id')} vs B={b.get('eval_id')}",
        "",
        f"- A resolve_rate: {float(a.get('resolve_rate') or 0):.2%}",
        f"- B resolve_rate: {float(b.get('resolve_rate') or 0):.2%}",
        f"- Δ resolve_rate: {float(b.get('resolve_rate') or 0) - float(a.get('resolve_rate') or 0):+.2%}",
        "",
        "| task | sample | A resolve | B resolve | Δ resolve | A ratio | B ratio | Δ ratio | Δ wall_s |",
        "|---|---:|:---:|:---:|:---:|---:|---:|---:|---:|",
    ]
    for k in keys:
        ai, bi = amap.get(k), bmap.get(k)
        ar = bool(ai.get("resolve")) if ai else False
        br = bool(bi.get("resolve")) if bi else False
        apr = float(ai.get("pass_ratio") or 0) if ai else 0.0
        bpr = float(bi.get("pass_ratio") or 0) if bi else 0.0
        aw = float(ai.get("wall_s") or 0) if ai else 0.0
        bw = float(bi.get("wall_s") or 0) if bi else 0.0
        dr = int(br) - int(ar)
        lines.append(
            f"| {k[0]} | {k[1]} | {ar} | {br} | {dr:+d} | "
            f"{apr:.2f} | {bpr:.2f} | {bpr - apr:+.2f} | {bw - aw:+.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def print_compare_console(a: dict[str, Any], b: dict[str, Any]) -> None:
    md = compare_reports(a, b)
    # 终端版用 rich 表
    def key(item: dict) -> tuple[str, int]:
        return (str(item.get("task_id")), int(item.get("sample") or 0))

    amap = {key(i): i for i in a.get("items", [])}
    bmap = {key(i): i for i in b.get("items", [])}
    keys = sorted(set(amap) | set(bmap))
    table = Table(
        title=f"compare A={a.get('eval_id')} B={b.get('eval_id')}"
    )
    for col in ("task", "sample", "A", "B", "Δ", "A ratio", "B ratio", "Δ ratio", "Δ wall"):
        table.add_column(col)
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
    ra, rb = float(a.get("resolve_rate") or 0), float(b.get("resolve_rate") or 0)
    console.print(f"resolve_rate  A={ra:.2%}  B={rb:.2%}  Δ={rb - ra:+.2%}")
    # 保留 md 生成路径供测试
    _ = md
