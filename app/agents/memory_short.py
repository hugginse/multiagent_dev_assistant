"""短期记忆压缩（黑板有界化，architecture.md §4.3 / M2 feature 6）。

- exploration：按路径去重，超过上限保留最新 + 摘要合并
- test_history：保留最近 N 条 + 历史失败摘要（不无限增长）
- plan / scratch：可选截断

在节点写入后或图边上调用，保证 state 体积有界。
"""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentState, normalize_state

# 默认上限（可通过 settings 覆盖的常量；M2 先固定）
DEFAULT_MAX_EXPLORATION = 40
DEFAULT_MAX_TEST_HISTORY = 8
DEFAULT_MAX_SCRATCH_CHARS = 8_000
DEFAULT_MAX_DIFF_CHARS = 100_000
DEFAULT_FAILURE_SUMMARY_MAX = 5


def compress_exploration(
    exploration: dict[str, str],
    *,
    max_files: int = DEFAULT_MAX_EXPLORATION,
) -> dict[str, str]:
    """路径去重 + 超限截断（保留插入序尾部 = 较新）。"""
    if len(exploration) <= max_files:
        return dict(exploration)
    items = list(exploration.items())
    return dict(items[-max_files:])


def compress_test_history(
    history: list[dict[str, Any]],
    *,
    keep_last: int = DEFAULT_MAX_TEST_HISTORY,
    failure_summary_max: int = DEFAULT_FAILURE_SUMMARY_MAX,
) -> list[dict[str, Any]]:
    """保留最近 keep_last 条；更早的失败压缩为一条 summary 记录。

    summary 记录形状：``{"iteration": -1, "kind": "failure_summary", "failed_total": N, ...}``
    """
    if len(history) <= keep_last:
        return list(history)

    head = history[:-keep_last] if keep_last > 0 else list(history)
    tail = history[-keep_last:] if keep_last > 0 else []

    failures = [h for h in head if not h.get("ok", h.get("failed", 0) == 0)]
    if not failures:
        # 旧记录全过：仅保留计数摘要
        summary = {
            "iteration": -1,
            "kind": "history_summary",
            "passed_total": sum(int(h.get("passed") or 0) for h in head),
            "failed_total": 0,
            "dropped": len(head),
            "ok": True,
            "output_tail": f"(压缩前 {len(head)} 条全过，已折叠)",
        }
        return [summary, *tail]

    # 失败摘要：最多 failure_summary_max 条代表
    sample = failures[-failure_summary_max:]
    summary = {
        "iteration": -1,
        "kind": "failure_summary",
        "failed_total": len(failures),
        "passed_total": sum(int(h.get("passed") or 0) for h in head),
        "dropped": len(head),
        "ok": False,
        "samples": [
            {
                "iteration": h.get("iteration"),
                "failed": h.get("failed"),
                "passed": h.get("passed"),
                "returncode": h.get("returncode"),
            }
            for h in sample
        ],
        "output_tail": (sample[-1].get("output_tail") or "")[-400:],
    }
    return [summary, *tail]


def compress_scratch(scratch: str, *, max_chars: int = DEFAULT_MAX_SCRATCH_CHARS) -> str:
    if len(scratch) <= max_chars:
        return scratch
    half = max_chars // 2
    return (
        scratch[:half]
        + f"\n...[scratch 截断 {len(scratch) - max_chars} 字符]...\n"
        + scratch[-half:]
    )


def compress_diff(diff: str, *, max_chars: int = DEFAULT_MAX_DIFF_CHARS) -> str:
    if len(diff) <= max_chars:
        return diff
    return diff[: max_chars // 2] + "\n...[diff 截断]...\n" + diff[-max_chars // 2 :]


def compress_state(
    state: AgentState,
    *,
    max_exploration: int = DEFAULT_MAX_EXPLORATION,
    keep_test_history: int = DEFAULT_MAX_TEST_HISTORY,
) -> AgentState:
    """就地压缩黑板并归一化；返回同一 state。"""
    state["exploration"] = compress_exploration(
        dict(state.get("exploration") or {}), max_files=max_exploration
    )
    state["test_history"] = compress_test_history(
        list(state.get("test_history") or []), keep_last=keep_test_history
    )
    state["scratch"] = compress_scratch(str(state.get("scratch") or ""))
    state["diff"] = compress_diff(str(state.get("diff") or ""))
    return normalize_state(state)
