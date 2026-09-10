"""售后工单的事务性业务服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ticket, TicketStatus, TicketType
from app.services import query_service
from app.tools.result import failure, success


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


def create_ticket(
    session: Session,
    *,
    user_id: str,
    ticket_type: TicketType,
    description: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    """创建工单；调用方必须在事务中执行此函数。"""
    description = description.strip()
    if order_id and query_service.get_order(session, user_id=user_id, order_id=order_id) is None:
        return failure("NOT_FOUND", "未找到该订单")

    duplicate = session.scalar(
        select(Ticket).where(
            Ticket.user_id == user_id,
            Ticket.order_id == order_id,
            Ticket.type == ticket_type,
            Ticket.description == description,
            Ticket.status.in_((TicketStatus.OPEN, TicketStatus.IN_PROGRESS)),
        )
    )
    if duplicate:
        return success(
            {"ticket_id": duplicate.ticket_id, "status": _enum_value(duplicate.status)},
            code="DUPLICATE_REQUEST",
            message="相同工单已存在，无需重复创建",
        )

    ticket = Ticket(user_id=user_id, order_id=order_id, type=ticket_type, description=description)
    session.add(ticket)
    session.flush()
    return success(
        {
            "ticket_id": ticket.ticket_id,
            "order_id": ticket.order_id,
            "type": _enum_value(ticket.type),
            "status": _enum_value(ticket.status),
        },
        message="工单创建成功",
    )


__all__ = ["create_ticket"]
