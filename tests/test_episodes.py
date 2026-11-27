"""episode 沉淀测试（LLM mock + 规则降级）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import init_db, reset_engine_for_tests
from app.memory.episodes import _parse_llm_reply, save_episode
from app.memory.long_term import LongTermMemory


class _FakeEmbed:
    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * 16
        for tok in text.lower().split():
            v[hash(tok) % 16] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class FakeLLM:
    def __init__(self, content: str = "") -> None:
        self.content = content or (
            "TITLE: 折扣码修复经验\n"
            "SUMMARY: 修复了 discount 大小写问题。\n"
            "LESSON: 归一化输入后再查表。\n"
        )

    def complete(self, messages, **kwargs):  # noqa: ANN001, ANN003
        from types import SimpleNamespace

        return SimpleNamespace(content=self.content)

    def close(self) -> None:
        pass


class BrokenLLM:
    def complete(self, *a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("boom")

    def close(self) -> None:
        pass


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LongTermMemory:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ep.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    mem = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=_FakeEmbed())  # type: ignore[arg-type]
    yield mem
    reset_engine_for_tests()


def test_parse_llm_reply() -> None:
    t, c = _parse_llm_reply("TITLE: x\nSUMMARY: y\nLESSON: z\n")
    assert t == "x"
    assert "y" in c and "z" in c
    assert _parse_llm_reply("garbage") == ("", "")


def test_save_episode_with_llm(env: LongTermMemory) -> None:
    r = save_episode(
        repo_id="sample_repo",
        task_id="T001",
        task_title="修折扣码",
        prompt="修一下",
        resolve=True,
        iterations=2,
        llm=FakeLLM(),  # type: ignore[arg-type]
        memory=env,
    )
    assert r.status == "saved"
    assert r.memory_id
    assert r.title == "折扣码修复经验"
    assert env.count(repo_id="sample_repo", kind="episode") == 1
    row = env.get(r.memory_id or "")
    assert row is not None and row.task_ref == "T001"


def test_save_episode_rule_fallback_on_llm_failure(env: LongTermMemory) -> None:
    r = save_episode(
        repo_id="sample_repo",
        task_id="T002",
        task_title="做功能",
        prompt="实现 X",
        resolve=False,
        iterations=5,
        error="hidden failed",
        llm=BrokenLLM(),  # type: ignore[arg-type]
        memory=env,
    )
    assert r.status == "saved"
    assert r.title and "T002" in r.title
    row = env.get(r.memory_id or "")
    assert row is not None
    assert "未解" in row.title or "T002" in row.title
    assert "隐藏测试未全部通过" in row.content or "教训" in row.content


def test_save_episode_memory_off_skips(env: LongTermMemory) -> None:
    r = save_episode(
        repo_id="r",
        task_id="T",
        task_title="t",
        prompt="p",
        resolve=True,
        iterations=1,
        memory=env,
        memory_on=False,
    )
    assert r.status == "skipped"
    assert env.count() == 0


def test_save_episode_without_llm_uses_rules(env: LongTermMemory) -> None:
    # llm=None 且 create_llm_client 失败路径：直接传 memory，llm 尝试创建可能成功
    # 显式传 BrokenLLM 已覆盖失败；这里验证无 llm 时（create 失败）也可降级
    # 通过 monkeypatch 让 create 失败较复杂，直接测规则函数路径：
    from app.memory.episodes import _rule_based_content, _rule_based_title

    t = _rule_based_title("T9", "标题", True)
    assert "T9" in t and "成功" in t
    c = _rule_based_content(
        task_id="T9", title="标题", prompt="p", resolve=False, iterations=3, error="e"
    )
    assert "T9" in c and "未全部通过" in c


def test_episode_searchable(env: LongTermMemory) -> None:
    r = save_episode(
        repo_id="sample_repo",
        task_id="T001",
        task_title="折扣",
        prompt="p",
        resolve=True,
        iterations=1,
        llm=FakeLLM(),  # type: ignore[arg-type]
        memory=env,
    )
    assert r.status == "saved"
    hits = env.search("折扣 修复经验", repo_id="sample_repo", kind="episode", min_score=0.0)
    assert hits and hits[0].id == r.memory_id
