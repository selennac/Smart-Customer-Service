"""退款草稿、确认和管理员审批的事务性业务服务。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Order, OrderStatus, Refund, RefundStatus, Thread, ThreadStatus, User
from app.services import policy_service, query_service
from app.tools.result import failure, success


ACTIVE_REFUND_STATUSES = (
    RefundStatus.PENDING_USER,
    RefundStatus.PENDING_SUPERVISOR,
    RefundStatus.APPROVED,
)
ApprovalDecision = Literal["approve", "reject"]


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


def refund_data(refund: Refund) -> dict[str, Any]:
    """将退款 ORM 实例转换为 API 与图状态可用的数据。"""
    return {
        "refund_id": refund.refund_id,
        "thread_id": refund.thread_id,
        "order_id": refund.order_id,
        "amount": str(refund.amount),
        "reason": refund.reason,
        "status": _enum_value(refund.status),
        "reviewed_by": refund.reviewed_by,
        "reviewed_at": refund.reviewed_at.isoformat() if refund.reviewed_at else None,
    }


def create_refund_draft(
    session: Session,
    *,
    user_id: str,
    thread_id: str,
    order_id: str,
    reason: str,
    now: datetime,
    approval_threshold: Decimal,
) -> dict[str, Any]:
    """创建待用户确认的退款草稿；调用方必须在事务中执行此函数。"""
    order = query_service.get_order(session, user_id=user_id, order_id=order_id)
    if order is None:
        return failure("NOT_FOUND", "未找到该订单")

    evaluation = policy_service.evaluate_refund_order(
        order,
        now=now,
        approval_threshold=approval_threshold,
    )
    if not evaluation["eligible"]:
        return failure("POLICY_REJECTED", "当前订单不符合退款政策", data=evaluation)

    existing = session.scalar(
        select(Refund)
        .where(Refund.order_id == order_id, Refund.status.in_(ACTIVE_REFUND_STATUSES))
        .order_by(Refund.created_at.desc())
    )
    if existing:
        return success(
            refund_data(existing),
            code="DUPLICATE_REQUEST",
            message="该订单已有未完成退款申请",
            next_action=(
                "supervisor_approval"
                if _enum_value(existing.status) == RefundStatus.PENDING_SUPERVISOR.value
                else "refund_confirmation"
            ),
        )

    refund = Refund(thread_id=thread_id, order_id=order_id, amount=order.total_amount, reason=reason.strip())
    session.add(refund)
    session.flush()
    thread = session.get(Thread, thread_id)
    if thread is not None:
        thread.status = ThreadStatus.PENDING_USER
        thread.last_message = "退款申请等待用户确认"
    return success(
        refund_data(refund),
        message="退款申请已准备，请确认退款金额和原因",
        next_action="refund_confirmation",
    )


def confirm_refund(
    session: Session,
    *,
    user_id: str,
    thread_id: str,
    refund_id: str,
    now: datetime,
    approval_threshold: Decimal,
) -> dict[str, Any]:
    """确认退款草稿并再次校验政策；调用方必须在事务中执行此函数。"""
    refund = session.scalar(
        select(Refund)
        .join(Order, Refund.order_id == Order.order_id)
        .where(Refund.refund_id == refund_id, Order.user_id == user_id)
        .with_for_update()
    )
    if refund is None:
        return failure("NOT_FOUND", "未找到该退款申请")
    status = _enum_value(refund.status)
    if status == RefundStatus.COMPLETED.value:
        return success(refund_data(refund), code="IDEMPOTENT_REPLAY", message="退款已经完成")
    if status == RefundStatus.PENDING_SUPERVISOR.value:
        return success(
            refund_data(refund),
            code="APPROVAL_REQUIRED",
            message="退款已提交，等待管理员审批",
            next_action="supervisor_approval",
        )
    if status != RefundStatus.PENDING_USER.value:
        return failure("INVALID_STATE", "当前退款状态不能确认")

    order = session.get(Order, refund.order_id)
    if order is None:
        return failure("NOT_FOUND", "关联订单不存在")
    evaluation = policy_service.evaluate_refund_order(
        order,
        now=now,
        approval_threshold=approval_threshold,
    )
    if not evaluation["eligible"]:
        return failure("POLICY_REJECTED", "订单状态已变化，不再符合退款政策", data=evaluation)

    order.status = OrderStatus.REFUNDING
    if evaluation["approval_required"]:
        refund.status = RefundStatus.PENDING_SUPERVISOR
        thread = session.get(Thread, thread_id)
        if thread is not None:
            thread.status = ThreadStatus.PENDING_SUPERVISOR
            thread.last_message = "退款申请等待管理员审批"
        return success(
            refund_data(refund),
            code="APPROVAL_REQUIRED",
            message="退款已提交，等待管理员审批",
            next_action="supervisor_approval",
        )

    refund.status = RefundStatus.COMPLETED
    order.status = OrderStatus.COMPLETED
    thread = session.get(Thread, thread_id)
    if thread is not None:
        thread.status = ThreadStatus.ACTIVE
    return success(refund_data(refund), message="小额退款已完成")


def cancel_refund(
    session: Session,
    *,
    user_id: str,
    refund_id: str,
) -> dict[str, Any]:
    """取消待用户确认的退款草稿；调用方必须在事务中执行此函数。"""
    refund = session.scalar(
        select(Refund)
        .join(Order, Refund.order_id == Order.order_id)
        .where(Refund.refund_id == refund_id, Order.user_id == user_id)
        .with_for_update()
    )
    if refund is None:
        return failure("NOT_FOUND", "未找到该退款申请")
    status = _enum_value(refund.status)
    if status == RefundStatus.CANCELLED.value:
        return success(refund_data(refund), code="IDEMPOTENT_REPLAY", message="退款申请已经取消")
    if status != RefundStatus.PENDING_USER.value:
        return failure("INVALID_STATE", "当前退款状态不能取消")
    refund.status = RefundStatus.CANCELLED
    if refund.thread_id:
        thread = session.get(Thread, refund.thread_id)
        if thread is not None and thread.status == ThreadStatus.PENDING_USER:
            thread.status = ThreadStatus.ACTIVE
    return success(refund_data(refund), message="已取消退款申请")


def list_pending_refunds(session: Session, *, admin_user_id: str, limit: int = 50) -> dict[str, Any]:
    """查询待审批退款，并在服务层再次验证管理员身份。"""
    admin = session.get(User, admin_user_id)
    if admin is None or not admin.is_admin:
        return failure("FORBIDDEN", "只有管理员可以查询待审批退款")
    if not 1 <= limit <= 100:
        return failure("INVALID_ARGUMENT", "limit 必须在1到100之间")
    rows = session.scalars(
        select(Refund)
        .where(Refund.status == RefundStatus.PENDING_SUPERVISOR)
        .order_by(Refund.created_at.asc())
        .limit(limit)
    ).all()
    return success([refund_data(row) for row in rows], message=f"已查询到{len(rows)}条待审批退款")


def approve_refund(
    session: Session,
    *,
    admin_user_id: str,
    refund_id: str,
    decision: ApprovalDecision,
    now: datetime,
) -> dict[str, Any]:
    """通过或拒绝大额退款；调用方必须在事务中执行此函数。"""
    admin = session.get(User, admin_user_id)
    if admin is None or not admin.is_admin:
        return failure("FORBIDDEN", "只有管理员可以审批退款")

    refund = session.scalar(select(Refund).where(Refund.refund_id == refund_id).with_for_update())
    if refund is None:
        return failure("NOT_FOUND", "未找到该退款申请")
    status = _enum_value(refund.status)
    if status in (RefundStatus.COMPLETED.value, RefundStatus.REJECTED.value):
        return success(refund_data(refund), code="IDEMPOTENT_REPLAY", message="该退款已经完成审批")
    if status != RefundStatus.PENDING_SUPERVISOR.value:
        return failure("INVALID_STATE", "当前退款状态不在待审批状态")

    refund.reviewed_by = admin_user_id
    refund.reviewed_at = now
    order = session.get(Order, refund.order_id)
    if decision == "approve":
        refund.status = RefundStatus.COMPLETED
        if order is not None:
            order.status = OrderStatus.COMPLETED
    else:
        refund.status = RefundStatus.REJECTED
        if order is not None and _enum_value(order.status) == OrderStatus.REFUNDING.value:
            order.status = OrderStatus.DELIVERED
    return success(refund_data(refund), message="退款审批已完成")


__all__ = [
    "ApprovalDecision",
    "refund_data",
    "create_refund_draft",
    "confirm_refund",
    "cancel_refund",
    "list_pending_refunds",
    "approve_refund",
]
