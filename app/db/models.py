"""SQLAlchemy 模型：runs / run_events / evals / eval_items / memories / repos。

表结构对齐 architecture.md §7。向量不在 SQLite（memories.id ↔ Chroma id）。
LangGraph checkpoint 走 SqliteSaver 独立表（同库）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """全部 ORM 模型基类。"""


class RepoRow(Base):
    """目标仓库登记。"""

    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    onboarding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | done | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memories: Mapped[list[MemoryRow]] = relationship(back_populates="repo")


class RunRow(Base):
    """单次 Agent 执行。"""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    suite: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running"
    )  # running | success | timeout | error
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    diff_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[RunEventRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEventRow.seq"
    )


class RunEventRow(Base):
    """事件流：seq 单调递增，先落库再展示（DB 为事实源）。"""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        Index("ix_run_events_run_id_ts", "run_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[RunRow] = relationship(back_populates="events")


class EvalRow(Base):
    """一次批量评测。"""

    __tablename__ = "evals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    k: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[EvalItemRow]] = relationship(
        back_populates="eval", cascade="all, delete-orphan"
    )


class EvalItemRow(Base):
    """评测单条结果。"""

    __tablename__ = "eval_items"
    __table_args__ = (UniqueConstraint("eval_id", "task_id", "sample", name="uq_eval_task_sample"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sample: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # pass@k 的第几次
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    resolve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pass_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")

    eval: Mapped[EvalRow] = relationship(back_populates="items")


class MemoryRow(Base):
    """长期记忆元数据（向量在 Chroma）。"""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_repo_kind", "repo_id", "kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # convention | episode
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    task_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    repo: Mapped[RepoRow] = relationship(back_populates="memories")


# 便捷导出
__all__ = [
    "Base",
    "EvalItemRow",
    "EvalRow",
    "MemoryRow",
    "RepoRow",
    "RunEventRow",
    "RunRow",
    "utcnow",
]
