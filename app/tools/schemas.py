"""暴露给语言模型的 Pydantic 输入参数模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.models import OrderStatus, TicketStatus, TicketType


class ListOrdersArgs(BaseModel):
    status: OrderStatus | None = None
    limit: int = Field(default=10, ge=1, le=50)


class OrderIdArgs(BaseModel):
    order_id: str = Field(min_length=3, max_length=64)


class ListTicketsArgs(BaseModel):
    status: TicketStatus | None = None
    limit: int = Field(default=10, ge=1, le=50)


class RefundIdArgs(BaseModel):
    refund_id: str = Field(min_length=3, max_length=64)


class CreateTicketArgs(BaseModel):
    ticket_type: TicketType
    description: str = Field(min_length=5, max_length=2000)
    order_id: str | None = Field(default=None, min_length=3, max_length=64)


class EvaluateRefundArgs(BaseModel):
    order_id: str = Field(min_length=3, max_length=64)
    reason: str = Field(min_length=2, max_length=500)


__all__ = [
    "ListOrdersArgs",
    "OrderIdArgs",
    "ListTicketsArgs",
    "RefundIdArgs",
    "CreateTicketArgs",
    "EvaluateRefundArgs",
]
