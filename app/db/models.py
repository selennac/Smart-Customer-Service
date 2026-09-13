"""
用于模拟客户服务领域的 SQLAlchemy 2.0 模型。

这些模型特意将业务标识符保留为字符串（例如 ``ORD-...``），
以便可以直接在聊天 UI 和演示脚本中显示。
枚举使用稳定的英文值，而标签可以在 API/UI 边界进行本地化。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import JSON as SqlJSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship


def _utcnow() -> datetime:
    """获取当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    """生成带有指定前缀的唯一 ID。"""
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _json_type() -> Any:
    """在 PostgreSQL 上使用 JSONB，在本地 SQLite 测试中使用通用 JSON。"""
    return SqlJSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """所有业务模型共享的声明式基类。"""


class VipLevel(str, Enum):
    """用户 VIP 等级枚举。"""
    REGULAR = "regular"
    SILVER = "silver"
    GOLD = "gold"


class OrderStatus(str, Enum):
    """订单状态枚举。"""
    PENDING_SHIPMENT = "pending_shipment"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    REFUNDING = "refunding"
    COMPLETED = "completed"


class TicketType(str, Enum):
    """工单类型枚举。"""
    REFUND = "refund"
    EXCHANGE = "exchange"
    COMPLAINT = "complaint"


class TicketStatus(str, Enum):
    """工单处理状态枚举。"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class RefundStatus(str, Enum):
    """退款审批状态枚举。"""
    PENDING_USER = "pending_user"
    PENDING_SUPERVISOR = "pending_supervisor"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ThreadStatus(str, Enum):
    """对话线程状态枚举。"""
    ACTIVE = "active"
    PENDING_USER = "pending_user"
    PENDING_SUPERVISOR = "pending_supervisor"
    CLOSED = "closed"


def _enum(enum_type: type[Enum]) -> SqlEnum:
    # 使用非原生枚举可以使本地 SQLite 开发和迁移更加可预测。
    return SqlEnum(enum_type, native_enum=False, name=f"{enum_type.__name__.lower()}_enum")


class User(Base):
    """用户模型。"""
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("USR"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vip_level: Mapped[VipLevel] = mapped_column(_enum(VipLevel), default=VipLevel.REGULAR, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    orders: Mapped[list[Order]] = relationship(back_populates="user")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="user")
    threads: Mapped[list[Thread]] = relationship(back_populates="user")


class Product(Base):
    """商品模型。"""
    __tablename__ = "products"

    sku_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Order(Base):
    """订单模型。"""
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ORD"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(_json_type(), nullable=False, default=list)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.PENDING_SHIPMENT, index=True,
                                                nullable=False)
    tracking_no: Mapped[str | None] = mapped_column(String(80), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
                                                 nullable=False)

    user: Mapped[User] = relationship(back_populates="orders")
    logistics_events: Mapped[list[LogisticsEvent]] = relationship(
        primaryjoin=lambda: foreign(LogisticsEvent.tracking_no) == Order.tracking_no,
        viewonly=True,
        order_by="LogisticsEvent.event_time",
    )
    tickets: Mapped[list[Ticket]] = relationship(back_populates="order")
    refunds: Mapped[list[Refund]] = relationship(back_populates="order")


class LogisticsEvent(Base):
    """物流事件模型。"""
    __tablename__ = "logistics_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracking_no: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(120), nullable=False)


class Ticket(Base):
    """客服工单模型。"""
    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("TKT"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.order_id"), index=True)
    type: Mapped[TicketType] = mapped_column(_enum(TicketType), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus), default=TicketStatus.OPEN, index=True,
                                                 nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
                                                 nullable=False)

    user: Mapped[User] = relationship(back_populates="tickets")
    order: Mapped[Order | None] = relationship(back_populates="tickets")


class Refund(Base):
    """退款记录模型。"""
    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("RFD"))
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("threads.thread_id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(_enum(RefundStatus), default=RefundStatus.PENDING_USER, index=True,
                                                 nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
                                                 nullable=False)

    order: Mapped[Order] = relationship(back_populates="refunds")
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])


class Thread(Base):
    """对话线程模型。"""
    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    status: Mapped[ThreadStatus] = mapped_column(_enum(ThreadStatus), default=ThreadStatus.ACTIVE, index=True,
                                                 nullable=False)
    last_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
                                                 nullable=False)

    user: Mapped[User] = relationship(back_populates="threads")


__all__ = [
    "Base",
    "User",
    "Product",
    "Order",
    "LogisticsEvent",
    "Ticket",
    "Refund",
    "Thread",
    "VipLevel",
    "OrderStatus",
    "TicketType",
    "TicketStatus",
    "RefundStatus",
    "ThreadStatus",
]
