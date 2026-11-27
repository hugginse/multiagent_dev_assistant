"""报告生成、pass@k、compare 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.harness.report import (
    build_report,
    compare_reports,
    compute_pass_at_k,
    print_compare_console,
    print_report_table,
    render_markdown,
    save_report,
)


def _items() -> list[dict]:
    return [
        {
            "task_id": "T001",
            "sample": 1,
            "resolve": True,
            "pass_ratio": 1.0,
            "iterations": 2,
            "tokens_in": 10,
            "tokens_out": 20,
            "wall_s": 1.5,
            "status": "success",
        },
        {
            "task_id": "T002",
            "sample": 1,
            "resolve": False,
            "pass_ratio": 0.5,
            "iterations": 3,
            "tokens_in": 10,
            "tokens_out": 20,
            "wall_s": 2.0,
            "status": "success",
        },
    ]


def test_pass_at_k_k1_equals_resolve_rate() -> None:
    items = _items()
    p = compute_pass_at_k(items, ["T001", "T002"], k=1)
    assert p["T001"] == 1.0
    assert p["T002"] == 0.0


def test_pass_at_k_unbiased() -> None:
    # n=2, c=1, k=1 → 1 - C(1,1)/C(2,1) = 1 - 1/2 = 0.5
    items = [
        {"task_id": "T", "sample": 1, "resolve": True},
        {"task_id": "T", "sample": 2, "resolve": False},
    ]
    p = compute_pass_at_k(items, ["T"], k=1)
    assert abs(p["T"] - 0.5) < 1e-9
    # k=2, c=1, n=2 → 1 - C(1,2)/C(2,2)，C(1,2)=0 → 1
    p2 = compute_pass_at_k(items, ["T"], k=2)
    assert p2["T"] == 1.0


def test_build_and_save_report(tmp_path: Path) -> None:
    rep = build_report(
        eval_id="eval_x",
        suite="smoke",
        k=1,
        provider="ollama",
        model="qwen3.5:9b",
        memory_on=False,
        items=_items(),
    )
    assert rep.resolve_rate == 0.5
    jp, mp = save_report(rep, tmp_path)
    assert jp.exists() and mp.exists()
    data = json.loads(jp.read_text(encoding="utf-8"))
    assert data["eval_id"] == "eval_x"
    assert "pass_at_k" in data
    md = mp.read_text(encoding="utf-8")
    assert "Eval Report" in md
    assert "T001" in md and "T002" in md
    assert "✅" in md and "❌" in md


def test_render_markdown_fields() -> None:
    rep = build_report(
        eval_id="e",
        suite="s",
        k=3,
        provider="ollama",
        model="m",
        memory_on=True,
        items=_items(),
        notes="n",
    )
    md = render_markdown(rep)
    assert "k: 3" in md
    assert "memory_on: True" in md
    assert "pass@k" in md


def test_compare_markdown_and_console() -> None:
    a = build_report(
        eval_id="A",
        suite="smoke",
        k=1,
        provider="ollama",
        model="m",
        memory_on=False,
        items=_items(),
    ).to_dict()
    b_items = [
        {**_items()[0], "resolve": True},
        {**_items()[1], "resolve": True, "pass_ratio": 1.0},
    ]
    b = build_report(
        eval_id="B",
        suite="smoke",
        k=1,
        provider="ollama",
        model="m",
        memory_on=False,
        items=b_items,
    ).to_dict()
    md = compare_reports(a, b)
    assert "Δ resolve_rate" in md
    assert "+1" in md  # T002 从 miss→resolve
    print_compare_console(a, b)  # 不抛即通过


def test_print_report_table_runs() -> None:
    rep = build_report(
        eval_id="e",
        suite="s",
        k=1,
        provider="p",
        model="m",
        memory_on=False,
        items=_items(),
    )
    print_report_table(rep)
