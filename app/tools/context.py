"""注入工具的运行时上下文，不由 LLM 自行填写。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Literal

from langchain_core.retrievers import BaseRetriever
from sqlalchemy.orm import Session

ActorRole = Literal["customer", "admin"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _threshold_from_env() -> Decimal:
    raw = os.getenv("REFUND_APPROVAL_THRESHOLD", "500")
    try:
        return Decimal(raw)
    except Exception as exc:  # pragma: no cover - configuration error path
        raise ValueError("REFUND_APPROVAL_THRESHOLD 必须是数字") from exc


def _default_db_factory() -> Session:
    """只有真正使用默认工具时才初始化项目数据库连接。"""
    from app.db.session import SessionLocal

    return SessionLocal()


@dataclass(frozen=True)
class ToolContext:
    """一次图调用可使用的身份和基础设施。"""

    user_id: str
    thread_id: str
    actor_role: ActorRole = "customer"
    db_factory: Callable[[], Session] = _default_db_factory
    retriever: BaseRetriever | None = None
    now_factory: Callable[[], datetime] = _utcnow
    refund_approval_threshold: Decimal | None = None

    def now(self) -> datetime:
        return self.now_factory()

    def threshold(self) -> Decimal:
        return self.refund_approval_threshold or _threshold_from_env()


def require_customer(ctx: ToolContext) -> None:
    if ctx.actor_role != "customer":
        raise PermissionError("当前身份不能执行客户操作")


def require_admin(ctx: ToolContext) -> None:
    if ctx.actor_role != "admin":
        raise PermissionError("只有管理员可以执行审批操作")


__all__ = ["ActorRole", "ToolContext", "require_customer", "require_admin"]
