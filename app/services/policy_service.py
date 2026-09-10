"""退款政策的确定性判断。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.db.models import Order, OrderStatus


REFUND_WINDOW_DAYS = 7


def _as_status_value(status: Any) -> str:
    return getattr(status, "value", str(status))


def evaluate_refund_order(
    order: Order,
    *,
    now: datetime,
    approval_threshold: Decimal,
) -> dict[str, Any]:
    """根据订单状态、签收时间和金额计算退款资格。"""
    reasons: list[str] = []
    eligible = True

    if _as_status_value(order.status) != OrderStatus.DELIVERED.value:
        eligible = False
        reasons.append("只有已签收订单可以申请退款")
    if order.delivered_at is None:
        eligible = False
        reasons.append("订单缺少签收时间，无法计算退款时效")

    delivered_days: int | None = None
    if order.delivered_at is not None:
        delivered_at = order.delivered_at
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        delivered_days = max(0, (now - delivered_at).days)
        if delivered_days > REFUND_WINDOW_DAYS:
            eligible = False
            reasons.append(f"签收已超过{REFUND_WINDOW_DAYS}天退款时效")

    amount = Decimal(order.total_amount)
    return {
        "eligible": eligible,
        "order_id": order.order_id,
        "amount": str(amount.quantize(Decimal("0.01"))),
        "delivered_days": delivered_days,
        "approval_required": amount > approval_threshold,
        "approval_threshold": str(approval_threshold.quantize(Decimal("0.01"))),
        "reasons": reasons,
    }


__all__ = ["REFUND_WINDOW_DAYS", "evaluate_refund_order"]
