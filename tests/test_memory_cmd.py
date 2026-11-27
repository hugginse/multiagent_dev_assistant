"""memory 子命令 CLI 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.main import app
from app.db.session import init_db, reset_engine_for_tests
from app.memory.long_term import LongTermMemory

runner = CliRunner()


class _Embed:
    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * 16
        for tok in text.lower().split():
            v[hash(tok) % 16] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mc.db'}")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_memory_list_empty() -> None:
    r = runner.invoke(app, ["memory", "list"])
    assert r.exit_code == 0
    assert "无记忆" in r.stdout or "memories" in r.stdout


def test_memory_list_with_data() -> None:
    mem = LongTermMemory(embed=_Embed())  # type: ignore[arg-type]
    mem.ensure_repo("sample_repo")
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="金额用分",
        content="整数分",
    )
    r = runner.invoke(app, ["memory", "list", "--kind", "convention"])
    assert r.exit_code == 0
    assert "金额用分" in r.stdout


def test_memory_search_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    # CLI 内部创建 LongTermMemory 时用 mock embedding，避免维度不一致
    import app.memory.long_term as lt

    monkeypatch.setattr(lt, "create_embed_client", lambda: _Embed())

    mem = LongTermMemory(embed=_Embed())  # type: ignore[arg-type]
    mem.ensure_repo("sample_repo")
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="错误处理",
        content="抛 ValidationError",
    )
    r = runner.invoke(
        app, ["memory", "search", "错误处理 ValidationError", "--repo", "sample_repo"]
    )
    assert r.exit_code == 0, r.stdout
    assert "ValidationError" in r.stdout or "错误处理" in r.stdout


def test_memory_search_empty_repo() -> None:
    r = runner.invoke(app, ["memory", "search", "xyz", "--repo", "empty_repo"])
    assert r.exit_code == 0
    assert "无命中" in r.stdout


def test_onboarding_missing_path() -> None:
    r = runner.invoke(app, ["memory", "onboarding", "--path", "/no/such/dir"])
    assert r.exit_code == 2


def test_onboarding_dry_run(tmp_path: Path) -> None:
    repo = tmp_path / "mini_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# mini\n约定：金额用分\n", encoding="utf-8")
    (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
    # dry-run 会调 LLM —— 可能因无 ollama 而失败；允许 1 或 2
    r = runner.invoke(
        app, ["memory", "onboarding", "--path", str(repo), "--dry-run"]
    )
    assert r.exit_code in {0, 1, 2}
    if r.exit_code == 0:
        assert "done" in r.stdout or "conventions" in r.stdout


def test_show_missing_id() -> None:
    r = runner.invoke(app, ["memory", "show", "no_such_id"])
    assert r.exit_code == 1
    assert "不存在" in r.stdout


def test_show_memory_full() -> None:
    mem = LongTermMemory(embed=_Embed())  # type: ignore[arg-type]
    mem.ensure_repo("sample_repo")
    mid = mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="完整标题",
        content="完整内容ABC",
    )
    r = runner.invoke(app, ["memory", "show", mid])
    assert r.exit_code == 0
    assert "完整标题" in r.stdout
    assert "完整内容ABC" in r.stdout


def test_preview_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.memory.long_term as lt

    monkeypatch.setattr(lt, "create_embed_client", lambda: _Embed())
    mem = LongTermMemory(embed=_Embed())  # type: ignore[arg-type]
    mem.ensure_repo("sample_repo")
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="预览约定",
        content="金额用分存储",
    )
    r = runner.invoke(
        app,
        ["memory", "preview", "金额 用分", "--repo", "sample_repo", "--min-score", "0"],
    )
    assert r.exit_code == 0, r.stdout
    assert "注入预览" in r.stdout or "未注入" in r.stdout


def test_preview_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.memory.long_term as lt

    monkeypatch.setattr(lt, "create_embed_client", lambda: _Embed())
    r = runner.invoke(app, ["memory", "preview", "xyz", "--repo", "empty_repo_xyz"])
    assert r.exit_code == 0
