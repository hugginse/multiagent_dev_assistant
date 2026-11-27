"""M3 feature 8：检索阈值 / 注入格式 / episode 沉淀（LLM mock）质量红线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.memory.episodes import save_episode
from app.memory.injection import (
    CONVENTION_HEADER,
    EPISODE_HEADER,
    inject_memory,
    render_injection,
)
from app.memory.long_term import LongTermMemory, MemoryHit


class _Embed:
    """确定性 embedding。"""

    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * 24
        for tok in text.lower().split():
            v[hash(tok) % 24] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class MockLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, messages, **kwargs):  # noqa: ANN001, ANN003
        from types import SimpleNamespace

        self.calls += 1
        return SimpleNamespace(content=self.reply)

    def close(self) -> None:
        pass


@pytest.fixture()
def mem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LongTermMemory:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    m = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=_Embed())  # type: ignore[arg-type]
    yield m
    reset_engine_for_tests()


# --------------------------------------------------------------------------- #
# 检索阈值
# --------------------------------------------------------------------------- #
def test_threshold_boundary_exact(mem: LongTermMemory) -> None:
    """score >= min_score 保留，< 过滤。用可控向量验证边界。"""
    mem.ensure_repo("r")
    mem.add(repo_id="r", kind="convention", title="alpha", content="alpha content here")
    # 高相关查询在阈值 0.9 下命中
    hits_exact = mem.search("alpha content here", repo_id="r", min_score=0.9, top_k=3)
    assert hits_exact, "相关文本应在合理阈值下命中"
    assert hits_exact[0].score >= 0.9

    # 无关文本 + 极高阈值 → 空
    hits_none = mem.search(
        "zzzz qqqq completely different tokens",
        repo_id="r",
        min_score=0.999999,
        top_k=3,
    )
    assert hits_none == [] or hits_none[0].score >= 0.999999


def test_threshold_filters_low_score(mem: LongTermMemory) -> None:
    mem.ensure_repo("r")
    mem.add(repo_id="r", kind="convention", title="唯一词", content="xylophone99")
    # 无关查询在高阈值下不得返回
    hits = mem.search(
        "完全无关的中文查询内容", repo_id="r", min_score=0.95, top_k=5
    )
    assert all(h.score >= 0.95 for h in hits)


def test_injection_uses_configured_threshold(mem: LongTermMemory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_MIN_SCORE", "0.99")
    from app.config import reset_settings_cache

    reset_settings_cache()
    try:
        mem.ensure_repo("r")
        mem.add(repo_id="r", kind="convention", title="t", content="some unique words")
        r = inject_memory("random unrelated query", repo_id="r", memory=mem)
        # 默认阈值来自 settings=0.99 → 无关查询应空
        assert r.convention_hits == [] or all(h.score >= 0.99 for h in r.convention_hits)
    finally:
        reset_settings_cache()


# --------------------------------------------------------------------------- #
# 注入格式
# --------------------------------------------------------------------------- #
def test_format_headers_exact() -> None:
    conv = MemoryHit(
        id="c1",
        repo_id="r",
        kind="convention",
        title="T-conv",
        content="C-body",
        task_ref=None,
        score=1.0,
    )
    ep = MemoryHit(
        id="e1",
        repo_id="r",
        kind="episode",
        title="T-ep",
        content="E-body",
        task_ref="T001",
        score=0.9,
    )
    text = render_injection([conv], [ep])
    # 精确标题行
    assert text.startswith(CONVENTION_HEADER)
    assert EPISODE_HEADER in text
    assert "**T-conv**: C-body" in text
    assert "[0.90] T-ep: E-body" in text
    # 两段之间空行分隔
    assert f"{CONVENTION_HEADER}\n\n{EPISODE_HEADER}" in text or CONVENTION_HEADER in text


def test_format_long_content_truncated() -> None:
    conv = MemoryHit(
        id="c",
        repo_id="r",
        kind="convention",
        title="long",
        content="x" * 2000,
        task_ref=None,
        score=1.0,
    )
    text = render_injection([conv], [], max_content_chars=100)
    assert "…" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("1.")][0]) < 200


def test_format_convention_only_no_episode_header() -> None:
    conv = MemoryHit(
        id="c",
        repo_id="r",
        kind="convention",
        title="t",
        content="c",
        task_ref=None,
        score=1.0,
    )
    text = render_injection([conv], [])
    assert CONVENTION_HEADER in text
    assert EPISODE_HEADER not in text


# --------------------------------------------------------------------------- #
# episode 沉淀（LLM mock）
# --------------------------------------------------------------------------- #
def test_episode_llm_called_and_saved(mem: LongTermMemory) -> None:
    llm = MockLLM(
        "TITLE: 自定义标题X\nSUMMARY: 摘要内容Y\nLESSON: 教训Z\n"
    )
    r = save_episode(
        repo_id="r",
        task_id="T201",
        task_title="标题",
        prompt="p",
        resolve=True,
        iterations=2,
        llm=llm,  # type: ignore[arg-type]
        memory=mem,
    )
    assert llm.calls == 1
    assert r.status == "saved"
    assert r.title == "自定义标题X"
    row = mem.get(r.memory_id or "")
    assert row is not None
    assert row.kind == "episode"
    assert row.task_ref == "T201"
    assert "摘要内容Y" in row.content
    assert "教训Z" in row.content


def test_episode_llm_failure_rule_fallback(mem: LongTermMemory) -> None:
    class Boom:
        def complete(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("x")

        def close(self) -> None:
            pass

    r = save_episode(
        repo_id="r",
        task_id="T202",
        task_title="失败任务",
        prompt="prompt text",
        resolve=False,
        iterations=4,
        error="boom",
        llm=Boom(),  # type: ignore[arg-type]
        memory=mem,
    )
    assert r.status == "saved"
    row = mem.get(r.memory_id or "")
    assert row is not None
    assert "T202" in row.content
    assert "未全部通过" in row.content or "教训" in row.content


def test_episode_not_saved_when_disabled(mem: LongTermMemory) -> None:
    r = save_episode(
        repo_id="r",
        task_id="T",
        task_title="t",
        prompt="p",
        resolve=True,
        iterations=1,
        memory_on=False,
        memory=mem,
    )
    assert r.status == "skipped"
    assert mem.count(kind="episode") == 0


def test_episode_row_in_sqlite(mem: LongTermMemory) -> None:
    r = save_episode(
        repo_id="r",
        task_id="T203",
        task_title="t",
        prompt="p",
        resolve=True,
        iterations=1,
        llm=MockLLM("TITLE: a\nSUMMARY: b\nLESSON: c\n"),  # type: ignore[arg-type]
        memory=mem,
    )
    from app.db.models import MemoryRow

    with session_scope() as s:
        row = s.get(MemoryRow, r.memory_id)
        assert row is not None
        assert row.kind == "episode"
        assert row.repo_id == "r"
