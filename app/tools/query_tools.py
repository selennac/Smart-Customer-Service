"""面向客户 Agent 的只读查询工具。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from app.db.models import OrderStatus, TicketStatus
from app.services import query_service
from app.tools.context import ToolContext, require_customer
from app.tools.result import failure, success
from app.tools.schemas import ListOrdersArgs, ListTicketsArgs, OrderIdArgs, RefundIdArgs


def _error_from_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PermissionError):
        return failure("FORBIDDEN", str(exc))
    return failure("INTERNAL_ERROR", "查询暂时不可用，请稍后再试")


def build_query_tools(ctx: ToolContext) -> list[BaseTool]:
    """为一次会话构造绑定当前用户身份的只读工具。"""
    require_customer(ctx)

    @tool(args_schema=ListOrdersArgs)
    def list_orders(status: OrderStatus | None = None, limit: int = 10) -> dict[str, Any]:
        """查询当前用户的订单列表，可按订单状态筛选。"""
        try:
            with ctx.db_factory() as session:
                rows = query_service.list_orders(session, user_id=ctx.user_id, status=status, limit=limit)
            return success(rows, message=f"已查询到{len(rows)}个订单")
        except Exception as exc:
            return _error_from_exception(exc)

    @tool(args_schema=OrderIdArgs)
    def get_order(order_id: str) -> dict[str, Any]:
        """查询当前用户指定订单的详情。"""
        try:
            with ctx.db_factory() as session:
                order = query_service.get_order(session, user_id=ctx.user_id, order_id=order_id)
                if order is None:
                    return failure("NOT_FOUND", "未找到该订单")
                return success(query_service.order_detail(order), message="已查询订单详情")
        except Exception as exc:
            return _error_from_exception(exc)

    @tool(args_schema=OrderIdArgs)
    def get_logistics(order_id: str) -> dict[str, Any]:
        """查询当前用户指定订单的完整物流轨迹。"""
        try:
            with ctx.db_factory() as session:
                result = query_service.get_logistics(session, user_id=ctx.user_id, order_id=order_id)
                if result is None:
                    return failure("NOT_FOUND", "未找到该订单")
                return success(result, message="已查询物流轨迹")
        except Exception as exc:
            return _error_from_exception(exc)

    @tool(args_schema=ListTicketsArgs)
    def list_tickets(status: TicketStatus | None = None, limit: int = 10) -> dict[str, Any]:
        """查询当前用户提交过的售后工单。"""
        try:
            with ctx.db_factory() as session:
                rows = query_service.list_tickets(session, user_id=ctx.user_id, status=status, limit=limit)
            return success(rows, message=f"已查询到{len(rows)}个工单")
        except Exception as exc:
            return _error_from_exception(exc)

    @tool(args_schema=RefundIdArgs)
    def get_refund_status(refund_id: str) -> dict[str, Any]:
        """查询当前用户指定退款申请的状态。"""
        try:
            with ctx.db_factory() as session:
                result = query_service.get_refund(session, user_id=ctx.user_id, refund_id=refund_id)
                if result is None:
                    return failure("NOT_FOUND", "未找到该退款申请")
                return success(result, message="已查询退款状态")
        except Exception as exc:
            return _error_from_exception(exc)

    return [list_orders, get_order, get_logistics, list_tickets, get_refund_status]


__all__ = ["build_query_tools"]
