"""eval 实现：遍历任务 × k 次 → 报告 JSON（M1 骨架）。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def execute_eval(
    *,
    suite: str,
    k: int,
    provider: str | None,
    memory: str,
    limit: int | None,
) -> int:
    if memory not in {"on", "off"}:
        console.print("[red]--memory 必须是 on 或 off[/red]")
        return 2
    memory_on = memory == "on"

    from app.config import load_settings
    from app.harness.loader import SuiteError, load_tasks
    from app.harness.runner import run_single_task

    settings = load_settings()
    prov = provider or settings.llm_provider
    try:
        tasks = load_tasks(suite)
    except SuiteError as e:
        console.print(f"[red]套件加载失败:[/red] {e}")
        return 2
    if limit is not None:
        tasks = tasks[:limit]

    eval_id = f"eval_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    items: list[dict] = []
    any_fail = False

    for task in tasks:
        for sample in range(1, k + 1):
            console.print(f"[cyan]{task.id}[/cyan] sample={sample}/{k} …", end=" ")
            try:
                outcome = run_single_task(
                    task,
                    suite=suite,
                    provider=prov,
                    memory_on=memory_on,
                )
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]error:[/red] {e}")
                any_fail = True
                items.append(
                    {
                        "task_id": task.id,
                        "sample": sample,
                        "resolve": False,
                        "pass_ratio": 0.0,
                        "iterations": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "wall_s": 0.0,
                        "status": "error",
                        "run_id": None,
                        "error": str(e),
                    }
                )
                continue
            m = outcome.metrics
            ok = m.resolve
            if not ok:
                any_fail = True
            console.print(
                f"{'[green]resolve[/green]' if ok else '[yellow]miss[/yellow]'} "
                f"ratio={m.test_pass_ratio:.2f} it={m.iterations} wall={m.wall_s:.1f}s"
            )
            items.append(
                {
                    "task_id": task.id,
                    "sample": sample,
                    "resolve": m.resolve,
                    "pass_ratio": m.test_pass_ratio,
                    "iterations": m.iterations,
                    "tokens_in": m.tokens_in,
                    "tokens_out": m.tokens_out,
                    "wall_s": m.wall_s,
                    "status": m.status,
                    "run_id": outcome.run_id,
                    "error": m.error,
                }
            )

    # pass@k（标准无偏估计）
    pass_at_k = _pass_at_k(items, tasks_ids=[t.id for t in tasks], k=k)

    report = {
        "eval_id": eval_id,
        "suite": suite,
        "k": k,
        "provider": prov,
        "model": settings.resolve_llm_model(),
        "memory_on": memory_on,
        "created_at": datetime.now(UTC).isoformat(),
        "items": items,
        "pass_at_k": pass_at_k,
        "resolve_rate": sum(1 for i in items if i["resolve"]) / max(1, len(items)),
    }

    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{eval_id}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_table(report)
    console.print(f"报告: [bold]{out_path}[/bold]")

    # 落 evals/eval_items
    try:
        from app.db.models import EvalItemRow, EvalRow
        from app.db.session import init_db, session_scope

        init_db()
        with session_scope() as s:
            s.add(
                EvalRow(
                    id=eval_id,
                    suite=suite,
                    k=k,
                    provider=prov,
                    model=report["model"],
                    memory_on=memory_on,
                    status="done",
                    report_path=str(out_path),
                    finished_at=datetime.now(UTC),
                )
            )
            for it in items:
                s.add(
                    EvalItemRow(
                        eval_id=eval_id,
                        task_id=it["task_id"],
                        sample=it["sample"],
                        run_id=it.get("run_id"),
                        resolve=it["resolve"],
                        pass_ratio=it["pass_ratio"],
                        iterations=it["iterations"],
                        tokens_in=it["tokens_in"],
                        tokens_out=it["tokens_out"],
                        wall_s=it["wall_s"],
                        status=it["status"],
                    )
                )
    except Exception as e:  # noqa: BLE001 — 落库失败不吞报告
        console.print(f"[yellow]警告: eval 落库失败 {e}[/yellow]")

    if any_fail:
        return 1
    return 0


def _pass_at_k(items: list[dict], *, tasks_ids: list[str], k: int) -> dict[str, float]:
    """标准无偏 pass@k：1 - C(n-c, k)/C(n, k)。"""
    from math import comb

    result: dict[str, float] = {}
    for tid in tasks_ids:
        rs = [1 if i["resolve"] else 0 for i in items if i["task_id"] == tid]
        n = len(rs)
        c = sum(rs)
        if n < k:
            result[tid] = float(c >= 1) if c else 0.0
            continue
        p = 1.0 if n - c < k else 1.0 - comb(n - c, k) / comb(n, k)
        result[tid] = p
    return result


def _print_table(report: dict) -> None:
    table = Table(title=f"eval {report['eval_id']} · suite={report['suite']} · k={report['k']}")
    table.add_column("task")
    table.add_column("sample")
    table.add_column("resolve")
    table.add_column("pass_ratio", justify="right")
    table.add_column("iters", justify="right")
    table.add_column("wall_s", justify="right")
    table.add_column("status")
    for it in report["items"]:
        style = "green" if it["resolve"] else "red"
        table.add_row(
            it["task_id"],
            str(it["sample"]),
            f"[{style}]{it['resolve']}[/{style}]",
            f"{it['pass_ratio']:.2f}",
            str(it["iterations"]),
            f"{it['wall_s']:.1f}",
            it["status"],
        )
    console.print(table)
    console.print(
        f"resolve_rate={report['resolve_rate']:.2%}  pass@k={report['pass_at_k']}"
    )
