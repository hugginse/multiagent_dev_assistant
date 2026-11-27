"""记忆 A/B 模式与 episode 沉淀接线测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.eval_cmd_impl import execute_eval, execute_memory_ab
from app.db.session import init_db, reset_engine_for_tests


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ab.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()
    yield
    reset_engine_for_tests()


def test_execute_eval_returns_path(tmp_path: Path) -> None:
    # 用 limit=1 + smoke，不跑 LLM 会很慢——这里只验证签名与错误路径
    code, path = execute_eval(
        suite="no_such_suite", k=1, provider="ollama", memory="off", limit=None
    )
    assert code == 2
    assert path is None


def test_execute_eval_bad_memory() -> None:
    code, path = execute_eval(
        suite="smoke", k=1, provider="ollama", memory="maybe", limit=0
    )
    assert code == 2
    assert path is None


def test_memory_ab_rejects_bad_suite() -> None:
    # 套件不存在 → 第一次 execute_eval 返回 2, None
    code = execute_memory_ab(suite="nope", k=1, provider="ollama", limit=None)
    assert code in {1, 2}


def test_ab_flag_registered(plain) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app

    r = CliRunner().invoke(app, ["eval", "--help"])
    assert r.exit_code == 0
    assert "--ab" in plain(r.stdout)


def test_runner_emits_episode_when_memory_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """memory_on 时应产生 memory_injected（注入或 episode）。

    CI 无 Ollama：mock embedding，预置 convention，保证注入与沉淀可走通。
    """
    from app.agents.state import AgentState, TestRecord
    from app.db.session import session_scope
    from app.events import EventType, load_events
    from app.harness.loader import load_task
    from app.harness.runner import run_single_task
    from app.memory.long_term import LongTermMemory

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ep_run.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    reset_engine_for_tests()
    init_db()

    class _Embed:
        def embed_one(self, text: str) -> list[float]:
            v = [0.0] * 24
            for tok in text.lower().split():
                v[hash(tok) % 24] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            return [x / n for x in v]

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [self.embed_one(t) for t in texts]

    import app.memory.long_term as lt

    monkeypatch.setattr(lt, "create_embed_client", lambda: _Embed())

    # 预置约定，保证注入非空 → MEMORY_INJECTED
    mem = LongTermMemory(embed=_Embed())  # type: ignore[arg-type]
    mem.ensure_repo("sample_repo")
    mem.add(
        repo_id="sample_repo",
        kind="convention",
        title="折扣码大小写",
        content="discount_amount 需对 save10 等小写码大小写不敏感",
    )

    task = load_task("smoke", "T001")

    def on_test(state: AgentState) -> TestRecord:
        return TestRecord(iteration=0, passed=1, failed=0, returncode=0)

    out = run_single_task(
        task,
        suite="smoke",
        on_node_test=on_test,
        with_hidden_scoring=False,
        memory_on=True,
    )
    with session_scope() as s:
        evs = load_events(s, out.run_id)
    mem_events = [e for e in evs if e.type is EventType.MEMORY_INJECTED]
    assert mem_events, (
        "memory_on 应产生 memory_injected 事件; types="
        + str([e.type.value for e in evs[:20]])
    )
    phases = {e.payload.get("phase") for e in mem_events}
    assert "episode" in phases or any(e.payload.get("chars") for e in mem_events)
