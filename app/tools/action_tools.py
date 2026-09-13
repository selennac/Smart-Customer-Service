"""售后节点可选使用的轻量工具适配层。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from app.db.models import TicketType
from app.services import refund_service, ticket_service
from app.tools.context import ToolContext, require_customer
from app.tools.result import failure
from app.tools.schemas import CreateTicketArgs, EvaluateRefundArgs


def build_action_tools(ctx: ToolContext) -> list[BaseTool]:
    """构造售后工具。

    这些工具仅供售后子图的受控节点使用，不应注册给通用 ReAct Agent。
    用户确认退款和管理员审批由图节点、FastAPI 分别直接调用领域服务。
    """
    require_customer(ctx)

    @tool(args_schema=CreateTicketArgs)
    def create_ticket(ticket_type: TicketType, description: str, order_id: str | None = None) -> dict[str, Any]:
        """为当前用户创建退款、换货或投诉工单。"""
        try:
            with ctx.db_factory() as session:
                with session.begin():
                    return ticket_service.create_ticket(
                        session,
                        user_id=ctx.user_id,
                        ticket_type=ticket_type,
                        description=description,
                        order_id=order_id,
                    )
        except Exception:
            return failure("INTERNAL_ERROR", "工单创建失败，请稍后再试")

    @tool(args_schema=EvaluateRefundArgs)
    def create_refund_draft(order_id: str, reason: str) -> dict[str, Any]:
        """为当前用户创建待确认退款草稿，不会直接完成退款。"""
        try:
            with ctx.db_factory() as session:
                with session.begin():
                    return refund_service.create_refund_draft(
                        session,
                        user_id=ctx.user_id,
                        thread_id=ctx.thread_id,
                        order_id=order_id,
                        reason=reason,
                        now=ctx.now(),
                        approval_threshold=ctx.threshold(),
                    )
        except Exception:
            return failure("INTERNAL_ERROR", "退款申请创建失败，请稍后再试")

    return [create_ticket, create_refund_draft]


__all__ = ["build_action_tools"]
