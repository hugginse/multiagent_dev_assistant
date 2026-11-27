"""CLI 生命周期：启动清理 workspace 死状态 / 僵尸 run。

- 清理超过 max_age_days 的 data/workspaces 子目录（默认 7 天）
- 将残留 status=running 的 run 标为 error（进程被杀后的死状态）
- 幂等、失败不阻断 CLI
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.console import Console

console = Console(stderr=True)

_CLEANED = False


def startup_cleanup(
    *,
    max_age_days: float = 7.0,
    force: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    """执行一次启动清理；返回统计。进程内默认只跑一次。"""
    global _CLEANED
    if _CLEANED and not force:
        return {"skipped": True}
    stats: dict[str, Any] = {
        "workspaces_removed": [],
        "runs_repaired": 0,
        "error": None,
    }
    try:
        from app.sandbox.workspace import cleanup_stale_workspaces

        stats["workspaces_removed"] = cleanup_stale_workspaces(max_age_days=max_age_days)
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"workspace cleanup: {e}"

    try:
        from sqlalchemy import update

        from app.db.models import RunRow
        from app.db.session import init_db, session_scope

        init_db()
        with session_scope() as s:
            res = s.execute(
                update(RunRow)
                .where(RunRow.status == "running")
                .values(
                    status="error",
                    error="interrupted: process exited before run_finished",
                    finished_at=datetime.now(UTC),
                )
            )
            stats["runs_repaired"] = int(res.rowcount or 0)
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{stats['error'] or ''} runs repair: {e}".strip()

    _CLEANED = True
    if not quiet and (
        stats["workspaces_removed"] or stats["runs_repaired"] or stats["error"]
    ):
        if stats["workspaces_removed"]:
            console.print(
                f"[dim]cleanup: removed {len(stats['workspaces_removed'])} stale workspaces[/dim]"
            )
        if stats["runs_repaired"]:
            console.print(
                f"[dim]cleanup: repaired {stats['runs_repaired']} interrupted runs[/dim]"
            )
        if stats["error"]:
            console.print(f"[yellow]cleanup warning: {stats['error']}[/yellow]")
    return stats


def reset_cleanup_flag() -> None:
    """测试用。"""
    global _CLEANED
    _CLEANED = False
