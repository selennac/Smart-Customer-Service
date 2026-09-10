"""订单、物流、工单和退款的只读查询。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    LogisticsEvent,
    Order,
    Refund,
    Ticket,
    TicketStatus,
)


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


def order_summary(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "status": _enum_value(order.status),
        "total_amount": str(order.total_amount),
        "tracking_no": order.tracking_no,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
    }


def order_detail(order: Order) -> dict[str, Any]:
    result = order_summary(order)
    result["items"] = order.items
    return result


def list_orders(session: Session, *, user_id: str, status: Any = None, limit: int = 10) -> list[dict[str, Any]]:
    query = select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(Order.status == status)
    return [order_summary(order) for order in session.scalars(query).all()]


def get_order(session: Session, *, user_id: str, order_id: str) -> Order | None:
    return session.scalar(select(Order).where(Order.order_id == order_id, Order.user_id == user_id))


def get_logistics(session: Session, *, user_id: str, order_id: str) -> dict[str, Any] | None:
    order = get_order(session, user_id=user_id, order_id=order_id)
    if order is None:
        return None
    events = []
    if order.tracking_no:
        rows = session.scalars(
            select(LogisticsEvent)
            .where(LogisticsEvent.tracking_no == order.tracking_no)
            .order_by(LogisticsEvent.event_time.asc())
        ).all()
        events = [
            {
                "event_time": event.event_time.isoformat(),
                "location": event.location,
                "status": event.status,
            }
            for event in rows
        ]
    return {"order_id": order.order_id, "tracking_no": order.tracking_no, "events": events}


def list_tickets(session: Session, *, user_id: str, status: Any = None, limit: int = 10) -> list[dict[str, Any]]:
    query = select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(Ticket.status == status)
    return [
        {
            "ticket_id": ticket.ticket_id,
            "order_id": ticket.order_id,
            "type": _enum_value(ticket.type),
            "status": _enum_value(ticket.status),
            "description": ticket.description,
            "resolution": ticket.resolution,
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
        }
        for ticket in session.scalars(query).all()
    ]


def get_refund(session: Session, *, user_id: str, refund_id: str) -> dict[str, Any] | None:
    row = session.scalar(
        select(Refund)
        .join(Order, Refund.order_id == Order.order_id)
        .where(Refund.refund_id == refund_id, Order.user_id == user_id)
    )
    if row is None:
        return None
    return {
        "refund_id": row.refund_id,
        "order_id": row.order_id,
        "amount": str(row.amount),
        "reason": row.reason,
        "status": _enum_value(row.status),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


__all__ = [
    "order_summary",
    "order_detail",
    "list_orders",
    "get_order",
    "get_logistics",
    "list_tickets",
    "get_refund",
]
