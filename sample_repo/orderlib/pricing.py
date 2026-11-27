"""定价：小计、折扣、运费。金额均为分。"""

from __future__ import annotations

from orderlib.exceptions import ValidationError
from orderlib.models import OrderItem

# 折扣码表：code -> 百分比（0-100）
DISCOUNT_CODES: dict[str, int] = {
    "SAVE10": 10,
    "SAVE20": 20,
    "NEW5": 5,
}

FREE_SHIPPING_THRESHOLD_CENTS = 10_000  # 满 100 元包邮
BASE_SHIPPING_CENTS = 800


class ShippingError(Exception):
    """运费计算失败（保留独立类型，便于任务出题）。"""


def subtotal(items: list[OrderItem]) -> int:
    if not items:
        raise ValidationError("items must not be empty")
    return sum(i.line_total_cents() for i in items)


def discount_amount(subtotal_cents: int, discount_code: str | None) -> int:
    """返回折扣金额（分）。未知折扣码抛 ValidationError。"""
    if subtotal_cents < 0:
        raise ValidationError("subtotal must be non-negative")
    if not discount_code:
        return 0
    # BUG(供 T001): 未做大小写归一，小写码会走未知码分支
    code = discount_code.strip()
    if code not in DISCOUNT_CODES:
        raise ValidationError(f"unknown discount code: {discount_code}")
    pct = DISCOUNT_CODES[code]
    return subtotal_cents * pct // 100


def calculate_shipping(subtotal_after_discount_cents: int, *, express: bool = False) -> int:
    """运费：满额包邮；express 加收。负数入参抛 ShippingError。"""
    if subtotal_after_discount_cents < 0:
        raise ShippingError("subtotal must be non-negative")
    if express:
        return BASE_SHIPPING_CENTS * 2
    if subtotal_after_discount_cents >= FREE_SHIPPING_THRESHOLD_CENTS:
        return 0
    return BASE_SHIPPING_CENTS


def grand_total(items: list[OrderItem], discount_code: str | None = None, *, express: bool = False) -> int:
    """订单应付总额 = 小计 - 折扣 + 运费。"""
    sub = subtotal(items)
    disc = discount_amount(sub, discount_code)
    after = sub - disc
    ship = calculate_shipping(after, express=express)
    return after + ship
