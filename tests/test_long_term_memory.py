"""memories 数据层 + Chroma 向量（cosine、repo_id 过滤）测试。

Embedding 用确定性 mock，不打真实网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import init_db, reset_engine_for_tests, session_scope
from app.memory.long_term import LongTermMemory


class FakeEmbed:
    """确定性 embedding：词袋 hash → 固定维向量，保证相似文本分数高。"""

    def embed_one(self, text: str) -> list[float]:
        return _vec(text)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vec(t) for t in texts]


def _vec(text: str, dim: int = 32) -> list[float]:
    v = [0.0] * dim
    for tok in text.lower().split():
        v[hash(tok) % dim] += 1.0
    # L2 归一化（cosine 下与未归一等价，但避免零向量）
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / norm for x in v]


@pytest.fixture()
def ltm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LongTermMemory:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mem.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    mem = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=FakeEmbed())  # type: ignore[arg-type]
    yield mem
    reset_engine_for_tests()


def test_ensure_repo_idempotent(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("sample_repo", name="sample_repo")
    ltm.ensure_repo("sample_repo")
    from app.db.models import RepoRow

    with session_scope() as s:
        rows = list(s.scalars(__import__("sqlalchemy").select(RepoRow)).all())
    assert len(rows) == 1


def test_add_convention_and_episode(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("sample_repo")
    c_id = ltm.add(
        repo_id="sample_repo",
        kind="convention",
        title="金额单位",
        content="金额一律用分（int）存储，禁止 float",
    )
    ltm.add(
        repo_id="sample_repo",
        kind="episode",
        title="T001 折扣码",
        content="修复折扣码大小写：discount_amount 需要 upper 归一",
        task_ref="T001",
    )
    assert c_id.startswith("mem_")
    assert ltm.count(repo_id="sample_repo") == 2
    assert ltm.count(repo_id="sample_repo", kind="convention") == 1
    row = ltm.get(c_id)
    assert row is not None and row.kind == "convention"


def test_add_invalid_kind_rejected(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("r")
    with pytest.raises(ValueError, match="kind"):
        ltm.add(repo_id="r", kind="note", title="t", content="c")


def test_search_filters_repo_and_kind(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("repo_a")
    ltm.ensure_repo("repo_b")
    ltm.add(
        repo_id="repo_a",
        kind="convention",
        title="错误处理约定",
        content="领域错误抛自定义异常不用返回 None",
    )
    ltm.add(
        repo_id="repo_b",
        kind="convention",
        title="无关仓库",
        content="完全不同的主题 星际旅行火箭",
    )
    ltm.add(
        repo_id="repo_a",
        kind="episode",
        title="历史任务",
        content="错误处理 相似历史修复异常",
    )

    hits_a = ltm.search("错误处理 异常约定", repo_id="repo_a", top_k=5, min_score=0.0)
    assert hits_a
    assert all(h.repo_id == "repo_a" for h in hits_a)
    # kind 过滤
    hits_conv = ltm.search(
        "错误处理", repo_id="repo_a", kind="convention", top_k=5, min_score=0.0
    )
    assert hits_conv and all(h.kind == "convention" for h in hits_conv)
    # repo_b 检索不得串库
    hits_b = ltm.search("错误处理", repo_id="repo_b", top_k=5, min_score=0.0)
    assert all(h.repo_id == "repo_b" for h in hits_b)
    # repo_a 相关查询不应命中 repo_b 的内容
    assert not any("星际" in h.content for h in hits_a)


def test_search_min_score_threshold(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("r")
    ltm.add(repo_id="r", kind="convention", title="Python 风格", content="使用 type hints")
    # 高阈值：无关查询可能被滤掉
    high = ltm.search("量子引力波方程", repo_id="r", top_k=5, min_score=0.99)
    # 相关查询低阈值应命中
    low = ltm.search("type hints Python", repo_id="r", top_k=5, min_score=0.0)
    assert low
    assert all(h.score >= 0.0 for h in low)
    assert all(h.score >= 0.99 for h in high)


def test_search_top_k_limits(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("r")
    for i in range(10):
        ltm.add(
            repo_id="r",
            kind="convention",
            title=f"c{i}",
            content=f"约定内容 number {i} about testing patterns",
        )
    hits = ltm.search("testing patterns", repo_id="r", top_k=3, min_score=0.0)
    assert len(hits) <= 3
    # 分数降序
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_delete_removes_sqlite_and_vector(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("r")
    mid = ltm.add(repo_id="r", kind="convention", title="t", content="c unique_token_xyz")
    assert ltm.delete(mid) is True
    assert ltm.get(mid) is None
    hits = ltm.search("unique_token_xyz", repo_id="r", top_k=5, min_score=0.0)
    assert all(h.id != mid for h in hits)


def test_list_filter(ltm: LongTermMemory) -> None:
    ltm.ensure_repo("r")
    ltm.add(repo_id="r", kind="convention", title="a", content="x")
    ltm.add(repo_id="r", kind="episode", title="b", content="y", task_ref="T1")
    conv = ltm.list(repo_id="r", kind="convention")
    assert len(conv) == 1 and conv[0].title == "a"


def test_collection_uses_cosine(ltm: LongTermMemory) -> None:
    coll = ltm._get_collection()
    # chroma metadata 中 space 为 cosine
    meta = coll.metadata or {}
    assert meta.get("hnsw:space") == "cosine"
