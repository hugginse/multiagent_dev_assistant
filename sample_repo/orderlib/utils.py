"""工具函数：id 与时间。"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone

_counter = itertools.count(1)


def new_order_id(prefix: str = "ord") -> str:
    """生成订单号：prefix + 序号 + 短 uuid，保证进程内可读且全局大致唯一。"""
    if not prefix or not prefix.isalnum():
        raise ValueError("prefix must be alphanumeric")
    n = next(_counter)
    return f"{prefix}-{n:06d}-{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def reset_id_counter() -> None:
    """测试用：重置序号。"""
    global _counter
    _counter = itertools.count(1)
