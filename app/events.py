"""事件类型定义 + run_events 落库（architecture.md §8）。

顺序固定，seq 单调；**先落库再展示**（DB 为事实源）。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunEventRow


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    LLM_DELTA = "llm_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEST_RESULT = "test_result"
    MEMORY_INJECTED = "memory_injected"
    RUN_FINISHED = "run_finished"
    ERROR = "error"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    seq: int = 0
    ts: datetime = field(default_factory=utcnow)

    def to_row(self) -> RunEventRow:
        return RunEventRow(
            run_id=self.run_id,
            seq=self.seq,
            type=str(self.type),
            payload_json=self.payload,
            ts=self.ts,
        )


class EventStore:
    """事件先落库；支持进程内订阅（CLI 实时打印）。"""

    def __init__(self, session: Session, run_id: str) -> None:
        self._session = session
        self._run_id = run_id
        self._seq = 0
        self._subscribers: list[Any] = []  # Callable[[Event], None]
        self._buffer: list[Event] = []

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def seq(self) -> int:
        return self._seq

    def subscribe(self, fn: Any) -> None:
        """订阅实时事件（CLI）；已缓冲事件立即回放给新订阅者。"""
        self._subscribers.append(fn)
        for ev in self._buffer:
            fn(ev)

    def emit(self, event_type: EventType | str, payload: dict[str, Any] | None = None) -> Event:
        """分配 seq → 落库（flush）→ 通知订阅者。"""
        self._seq += 1
        et = EventType(event_type) if not isinstance(event_type, EventType) else event_type
        ev = Event(type=et, payload=payload or {}, run_id=self._run_id, seq=self._seq, ts=utcnow())
        self._session.add(ev.to_row())
        self._session.flush()  # 先落库
        self._buffer.append(ev)
        for fn in self._subscribers:
            with contextlib.suppress(Exception):  # 展示层错误不阻断核心
                fn(ev)
        return ev


def load_events(session: Session, run_id: str) -> list[Event]:
    """按 seq 升序读取（回放）。"""
    rows = session.scalars(
        select(RunEventRow).where(RunEventRow.run_id == run_id).order_by(RunEventRow.seq)
    ).all()
    return [
        Event(
            type=EventType(r.type),
            payload=r.payload_json or {},
            run_id=r.run_id,
            seq=r.seq,
            ts=r.ts,
        )
        for r in rows
    ]


def assert_seq_monotonic(events: list[Event]) -> None:
    seqs = [e.seq for e in events]
    if seqs != sorted(seqs):
        raise ValueError(f"事件 seq 非单调: {seqs}")
    if len(seqs) != len(set(seqs)):
        raise ValueError(f"事件 seq 重复: {seqs}")
