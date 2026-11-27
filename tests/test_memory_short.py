"""短期记忆压缩测试。"""

from __future__ import annotations

from app.agents.memory_short import (
    compress_exploration,
    compress_scratch,
    compress_state,
    compress_test_history,
)
from app.agents.state import initial_state
from app.harness.schema import TaskDefinition


def test_exploration_dedup_and_cap() -> None:
    e = {f"f{i}.py": f"s{i}" for i in range(50)}
    out = compress_exploration(e, max_files=10)
    assert len(out) == 10
    # 保留较新（尾部）
    assert "f49.py" in out
    assert "f0.py" not in out


def test_exploration_under_cap_unchanged() -> None:
    e = {"a.py": "1", "b.py": "2"}
    assert compress_exploration(e, max_files=10) == e


def test_test_history_keeps_recent_and_summary() -> None:
    history = [
        {"iteration": i, "passed": 1, "failed": 0 if i % 3 else 2, "ok": i % 3 != 0, "returncode": 0 if i % 3 else 1}
        for i in range(20)
    ]
    out = compress_test_history(history, keep_last=5, failure_summary_max=3)
    assert len(out) <= 6  # summary + 5
    # 最近 5 条保留
    assert out[-1]["iteration"] == 19
    assert out[-5]["iteration"] == 15
    # 有 summary
    assert out[0].get("kind") in {"failure_summary", "history_summary"}


def test_test_history_all_pass_summary() -> None:
    history = [{"iteration": i, "passed": 1, "failed": 0, "ok": True} for i in range(12)]
    out = compress_test_history(history, keep_last=4)
    assert out[0]["kind"] == "history_summary"
    assert out[0]["failed_total"] == 0
    assert out[0]["dropped"] == 8
    assert len(out) == 5


def test_test_history_under_limit_unchanged() -> None:
    history = [{"iteration": 0, "ok": True}]
    assert compress_test_history(history, keep_last=8) == history


def test_scratch_truncated() -> None:
    s = "x" * 20_000
    out = compress_scratch(s, max_chars=1000)
    assert len(out) < 20_000
    assert "截断" in out


def test_compress_state_bounds() -> None:
    task = TaskDefinition(id="T", title="t", prompt="p")
    state = initial_state(task)
    state["exploration"] = {f"f{i}.py": "s" for i in range(100)}
    state["test_history"] = [
        {"iteration": i, "passed": 0, "failed": 1, "ok": False, "returncode": 1, "output_tail": "e"}
        for i in range(30)
    ]
    state["scratch"] = "y" * 50_000
    out = compress_state(state, max_exploration=10, keep_test_history=5)
    assert len(out["exploration"]) == 10
    assert len(out["test_history"]) <= 6
    assert len(out["scratch"]) < 50_000
    # 压缩后仍通过 schema 校验
    from app.agents.state import validate_state

    assert validate_state(out) == []


def test_failure_summary_keeps_failure_signal() -> None:
    history = [
        {"iteration": i, "passed": 0, "failed": 3, "ok": False, "returncode": 1, "output_tail": f"fail{i}"}
        for i in range(10)
    ]
    out = compress_test_history(history, keep_last=3, failure_summary_max=2)
    summary = out[0]
    assert summary["kind"] == "failure_summary"
    assert summary["failed_total"] == 7  # 10-3 条旧失败
    assert len(summary["samples"]) == 2
    assert summary["ok"] is False
