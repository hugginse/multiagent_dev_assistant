"""main 套件：10–15 条、难度分层、bugfix/feature/refactor 覆盖。"""

from __future__ import annotations

from app.harness.loader import load_tasks, resolve_hidden_test_paths, suite_dir


def test_main_suite_exists() -> None:
    d = suite_dir("main")
    assert (d / "tasks").is_dir()
    assert (d / "hidden_tests").is_dir()


def test_main_suite_10_to_15_tasks() -> None:
    tasks = load_tasks("main")
    assert 10 <= len(tasks) <= 15, f"main 套件任务数 {len(tasks)} 不在 10-15"


def test_coverage_tags_and_difficulty() -> None:
    tasks = load_tasks("main")
    tags = set()
    diffs = set()
    for t in tasks:
        tags.update(t.tags)
        diffs.add(t.difficulty)
    # 三类任务
    assert {"bugfix", "feature", "refactor"} <= tags, f"tags={tags}"
    # 难度分层至少两档（目标三档）
    assert len(diffs) >= 2, f"difficulties={diffs}"
    assert diffs <= {"easy", "medium", "hard"}


def test_all_hidden_tests_resolve() -> None:
    tasks = load_tasks("main")
    for t in tasks:
        assert t.hidden_tests, f"{t.id} 缺少 hidden_tests"
        paths = resolve_hidden_test_paths("main", t)
        assert paths, t.id
        for p in paths:
            assert p.exists()


def test_unique_ids() -> None:
    tasks = load_tasks("main")
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))


def test_prompts_nonempty_and_no_hidden_leak() -> None:
    tasks = load_tasks("main")
    for t in tasks:
        assert t.prompt.strip()
        # prompt 正文不应出现隐藏测试文件名
        body = t.prompt
        for h in t.hidden_tests:
            assert h not in body, f"{t.id} prompt 泄漏 {h}"
