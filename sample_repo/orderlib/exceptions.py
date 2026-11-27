"""orderlib 领域异常。"""

from __future__ import annotations


class OrderLibError(Exception):
    """库内所有异常的基类。"""


class ValidationError(OrderLibError):
    """入参不合法。"""


class NotFoundError(OrderLibError):
    """资源不存在。"""


class InvalidOrderStateError(OrderLibError):
    """订单状态机不允许当前操作。"""


class InsufficientStockError(OrderLibError):
    """库存不足。"""
