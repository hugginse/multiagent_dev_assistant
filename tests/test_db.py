"""数据层：建表、CRUD、事件 seq 单调、checkpointer 冒烟。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import (
    Base,
    EvalItemRow,
    EvalRow,
    MemoryRow,
    RepoRow,
    RunEventRow,
    RunRow,
    utcnow,
)
from app.db.session import (
    create_checkpointer,
    get_engine,
    init_db,
    reset_engine_for_tests,
    session_scope,
)


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    reset_engine_for_tests()
    url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(url=url)
    yield url
    reset_engine_for_tests()


def test_init_db_creates_tables(db_url: str) -> None:
    engine = get_engine(url=db_url)
    names = set(Base.metadata.tables)
    assert {
        "runs",
        "run_events",
        "evals",
        "eval_items",
        "memories",
        "repos",
    } <= names
    # 实际库内表存在
    from sqlalchemy import inspect

    actual = set(inspect(engine).get_table_names())
    assert "runs" in actual and "run_events" in actual


def test_run_and_event_seq_monotonic(db_url: str) -> None:
    with session_scope(url=db_url) as s:
        run = RunRow(
            id="run_1",
            task_id="T001",
            suite="smoke",
            status="running",
            provider="ollama",
            model="qwen3.5:9b",
            memory_on=False,
        )
        s.add(run)
        for i in range(1, 4):
            s.add(
                RunEventRow(
                    run_id="run_1", seq=i, type="node_enter", payload_json={"node": "planner"}
                )
            )
        s.flush()
        assert run.created_at is not None

    with session_scope(url=db_url) as s:
        events = s.query(RunEventRow).filter_by(run_id="run_1").order_by(RunEventRow.seq).all()
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)
        assert seqs == [1, 2, 3]


def test_unique_run_event_seq(db_url: str) -> None:
    from sqlalchemy.exc import IntegrityError

    with session_scope(url=db_url) as s:
        s.add(
            RunRow(
                id="run_x",
                task_id="T001",
                suite="smoke",
                status="running",
                provider="ollama",
                model="m",
            )
        )
        s.add(RunEventRow(run_id="run_x", seq=1, type="run_started", payload_json={}))

    with pytest.raises(IntegrityError), session_scope(url=db_url) as s:
        s.add(RunEventRow(run_id="run_x", seq=1, type="run_started", payload_json={}))


def test_eval_item_roundtrip(db_url: str) -> None:
    with session_scope(url=db_url) as s:
        s.add(
            EvalRow(
                id="eval_1",
                suite="smoke",
                k=1,
                provider="ollama",
                model="qwen3.5:9b",
                status="running",
            )
        )
        s.add(
            EvalItemRow(
                eval_id="eval_1",
                task_id="T001",
                sample=1,
                resolve=True,
                pass_ratio=1.0,
                iterations=3,
                tokens_in=100,
                tokens_out=200,
                wall_s=12.5,
                status="success",
            )
        )

    with session_scope(url=db_url) as s:
        item = s.query(EvalItemRow).one()
        assert item.resolve is True
        assert item.pass_ratio == 1.0
        assert item.wall_s == 12.5


def test_memory_and_repo(db_url: str) -> None:
    with session_scope(url=db_url) as s:
        s.add(RepoRow(id="sample_repo", name="sample_repo", path="./sample_repo"))
        s.add(
            MemoryRow(
                id="mem_1",
                repo_id="sample_repo",
                kind="convention",
                title="错误处理",
                content="统一使用自定义异常",
            )
        )

    with session_scope(url=db_url) as s:
        mem = s.query(MemoryRow).one()
        assert mem.kind == "convention"
        assert mem.repo.name == "sample_repo"


def test_checkpointer_creates_tables(db_url: str) -> None:
    checkpointer = create_checkpointer(url=db_url)
    assert checkpointer is not None
    # 写入一条 checkpoint
    config = {"configurable": {"thread_id": "run_cp_1", "checkpoint_ns": ""}}
    checkpointer.put(
        config,
        {
            "v": 1,
            "ts": utcnow().isoformat(),
            "id": "step1",
            "channel_values": {"iteration": 0},
            "channel_versions": {},
            "versions_seen": {},
        },
        {"source": "test", "step": 0, "writes": {}},
        {},
    )
    got = checkpointer.get_tuple(config)
    assert got is not None
