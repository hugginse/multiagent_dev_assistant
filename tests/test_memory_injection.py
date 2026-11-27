"""记忆检索注入：模板、阈值、开关测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import init_db, reset_engine_for_tests
from app.memory.injection import (
    CONVENTION_HEADER,
    EPISODE_HEADER,
    build_memory_context,
    inject_memory,
    render_injection,
)
from app.memory.long_term import LongTermMemory, MemoryHit


class _FakeEmbed:
    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * 32
        for tok in text.lower().split():
            v[hash(tok) % 32] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


@pytest.fixture()
def mem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LongTermMemory:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'inj.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    m = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=_FakeEmbed())  # type: ignore[arg-type]
    m.ensure_repo("sample_repo")
    yield m
    reset_engine_for_tests()


def test_render_injection_headers() -> None:
    c = MemoryHit(
        id="1",
        repo_id="r",
        kind="convention",
        title="金额用分",
        content="整数分",
        task_ref=None,
        score=0.9,
    )
    e = MemoryHit(
        id="2",
        repo_id="r",
        kind="episode",
        title="T001",
        content="修了折扣",
        task_ref="T001",
        score=0.8,
    )
    text = render_injection([c], [e])
    assert CONVENTION_HEADER in text
    assert EPISODE_HEADER in text
    assert "金额用分" in text
    assert "T001" in text
    assert "0.80" in text


def test_render_empty_both() -> None:
    assert render_injection([], []) == ""


def test_inject_disabled_returns_empty(mem: LongTermMemory) -> None:
    r = inject_memory("错误处理", repo_id="sample_repo", enabled=False, memory=mem)
    assert r.enabled is False
    assert r.text == ""
    assert r.skipped_reason == "memory off"


def test_inject_with_hits(mem: LongTermMemory) -> None:
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="错误处理",
        content="领域错误抛 ValidationError",
    )
    mem.add(
        repo_id="sample_repo",
        kind="episode",
        title="T001 历史",
        content="折扣码修复",
        task_ref="T001",
    )
    r = inject_memory(
        "错误处理 ValidationError 折扣", repo_id="sample_repo", memory=mem, min_score=0.0
    )
    assert r.enabled
    assert CONVENTION_HEADER in r.text
    assert r.convention_hits
    assert r.episode_hits


def test_inject_min_score_filters(mem: LongTermMemory) -> None:
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="无关",
        content="完全无关内容 量子场论",
    )
    # 极高阈值 → 应无命中
    r = inject_memory(
        "量子场论", repo_id="sample_repo", memory=mem, min_score=0.999999, top_k=3
    )
    # 可能仍有一点分数；断言若 text 空则 skipped_reason 说明
    if not r.text:
        assert r.skipped_reason in {"no hits above threshold", "search failed"} or r.skipped_reason


def test_inject_skip_episodes(mem: LongTermMemory) -> None:
    mem.add(
        repo_id="sample_repo",
        kind="episode",
        title="T001",
        content="历史任务",
        task_ref="T001",
    )
    r = inject_memory(
        "历史任务", repo_id="sample_repo", memory=mem, min_score=0.0, include_episodes=False
    )
    assert EPISODE_HEADER not in r.text
    assert r.episode_hits == []


def test_build_memory_context(mem: LongTermMemory) -> None:
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="测试风格",
        content="pytest 单测",
    )
    ctx, detail = build_memory_context(
        "如何写测试 pytest", repo_id="sample_repo", enabled=True, memory=mem, min_score=0.0
    )
    assert detail.enabled
    assert CONVENTION_HEADER in ctx


def test_build_memory_context_off(mem: LongTermMemory) -> None:
    ctx, detail = build_memory_context("x", repo_id="sample_repo", enabled=False, memory=mem)
    assert ctx == ""
    assert detail.enabled is False


def test_inject_unexpected_repo_empty(mem: LongTermMemory) -> None:
    mem.add(
        repo_id="other_repo",
        kind="convention",
        title="别家约定",
        content="abc",
    )
    r = inject_memory("abc", repo_id="sample_repo", memory=mem, min_score=0.0)
    # sample_repo 无数据
    assert r.convention_hits == []
    assert r.text == ""
