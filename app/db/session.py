"""数据库引擎 / session 工厂与 SqliteSaver checkpointer。

- DATABASE_URL 默认 ``sqlite:///./data/app.db``
- 建表：``init_db()``
- LangGraph checkpointer：``create_checkpointer()``（thread_id = run.id）
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings, reset_settings_cache
from app.db.models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _sqlite_path_from_url(url: str) -> Path | None:
    """从 sqlite URL 提取文件路径（非内存库）。"""
    if not url.startswith("sqlite"):
        return None
    # sqlite:///./data/app.db 或 sqlite:////abs/path 或 sqlite:///:memory:
    if url in {"sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
        return None
    if ":///" in url:
        path_part = url.split(":///", 1)[1]
        if path_part in {":memory:", ""}:
            return None
        return Path(path_part)
    return None


def _enable_sqlite_fks(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine(url: str | None = None, *, create_dirs: bool = True) -> Engine:
    """进程内共享引擎。"""
    global _engine, _SessionFactory
    resolved = url or load_settings().database_url
    if _engine is not None and url is None:
        return _engine

    if create_dirs:
        db_path = _sqlite_path_from_url(resolved)
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        resolved,
        connect_args={"check_same_thread": False} if resolved.startswith("sqlite") else {},
        future=True,
    )
    if resolved.startswith("sqlite"):
        _enable_sqlite_fks(engine)

    if url is None:
        _engine = engine
        _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def init_db(*, url: str | None = None) -> None:
    """创建全部表（含 checkpointer 表由 SqliteSaver 自行 ensure）。"""
    engine = get_engine(url=url)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(*, url: str | None = None) -> Iterator[Session]:
    """事务 session：正常提交，异常回滚。"""
    factory = get_session_factory() if url is None else sessionmaker(
        bind=get_engine(url=url), expire_on_commit=False, future=True
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests() -> None:
    """测试隔离：释放引擎并清空配置缓存（保证 monkeypatch env 生效）。"""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
    reset_settings_cache()


def create_checkpointer(*, url: str | None = None):
    """LangGraph SqliteSaver checkpointer（同库独立表）。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    engine = get_engine(url=url)
    # SqliteSaver 需要 sqlite3 connection；从 URL 再开一条独立连接更稳妥
    import sqlite3

    resolved = url or load_settings().database_url
    db_path = _sqlite_path_from_url(resolved)
    if db_path is None:
        # 内存库：共享 engine 的 connection
        conn = engine.raw_connection()
        return SqliteSaver(conn)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    return SqliteSaver(conn)
