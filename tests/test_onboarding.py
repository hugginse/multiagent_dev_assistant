"""onboarding 约定抽取测试（LLM mock）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import init_db, reset_engine_for_tests
from app.memory.long_term import LongTermMemory
from app.memory.onboarding import (
    _parse_conventions,
    run_onboarding,
    scan_repo,
)


class FakeLLM:
    """返回固定 CONVENTION 文本的 mock。"""

    def __init__(self, content: str | None = None) -> None:
        self.content = content or (
            "CONVENTION: 金额用分\n所有金额用整数分存储。\n"
            "CONVENTION: 错误处理\n领域错误抛 ValidationError。\n"
            "CONVENTION: 测试\npytest 单测覆盖核心路径。\n"
        )
        self.closed = False

    def complete(self, messages, **kwargs):  # noqa: ANN001, ANN003
        from dataclasses import dataclass

        @dataclass
        class R:
            content: str

        return R(self.content)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ob.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def _fake_repo(tmp_path: Path) -> Path:
    r = tmp_path / "demo_repo"
    r.mkdir()
    (r / "README.md").write_text("# demo\n金额用分\n", encoding="utf-8")
    (r / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_f.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    return r


def test_scan_repo_returns_tree_and_files(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    repo_id, corpus, n = scan_repo(repo)
    assert repo_id == "demo_repo"
    assert "README.md" in corpus
    assert "app.py" in corpus
    assert n >= 2


def test_scan_missing_path() -> None:
    with pytest.raises(FileNotFoundError):
        scan_repo(Path("/nonexistent/xyz"))


def test_parse_conventions() -> None:
    text = "CONVENTION: A\nbody a\nCONVENTION: B\nbody b\n"
    out = _parse_conventions(text)
    assert len(out) == 2
    assert out[0] == {"title": "A", "content": "body a"}
    assert _parse_conventions("no markers") == []


def test_run_onboarding_persists_conventions(env: None, tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    mem = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=_FakeEmbed())  # type: ignore[arg-type]
    result = run_onboarding(repo, llm=FakeLLM(), memory=mem)  # type: ignore[arg-type]
    assert result.status == "done"
    assert len(result.conventions) >= 3
    assert len(result.memory_ids) == len(result.conventions)
    assert mem.count(repo_id="demo_repo", kind="convention") >= 3


    from app.db.models import RepoRow
    from app.db.session import session_scope

    with session_scope() as s:
        row = s.get(RepoRow, "demo_repo")
        assert row is not None and row.onboarding_status == "done"


def test_run_onboarding_llm_empty_conventions(env: None, tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    mem = LongTermMemory(chroma_dir=tmp_path / "chroma", embed=_FakeEmbed())  # type: ignore[arg-type]
    result = run_onboarding(repo, llm=FakeLLM("nothing useful"), memory=mem)  # type: ignore[arg-type]
    assert result.status == "failed"
    assert result.error is not None


def test_run_onboarding_bad_path(env: None) -> None:
    result = run_onboarding(Path("/no/such/repo"), llm=FakeLLM())  # type: ignore[arg-type]
    assert result.status == "failed"


class _FakeEmbed:
    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * 16
        for tok in text.lower().split():
            v[hash(tok) % 16] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]
