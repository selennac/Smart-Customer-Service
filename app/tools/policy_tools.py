"""策略评估和知识库检索工具。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from app.services import policy_service, query_service
from app.tools.context import ToolContext, require_customer
from app.tools.result import failure, success
from app.tools.schemas import EvaluateRefundArgs, SearchPolicyArgs


def build_policy_tools(ctx: ToolContext) -> list[BaseTool]:
    """构造绑定当前客户身份的策略和知识库工具。"""
    require_customer(ctx)

    @tool(args_schema=SearchPolicyArgs)
    def search_policy(query: str) -> dict[str, Any]:
        """检索退款、物流、会员等知识库内容并返回来源引用。"""
        if ctx.retriever is None:
            return failure("NOT_CONFIGURED", "知识库检索器尚未配置")
        try:
            documents = ctx.retriever.invoke(query)
            hits = []
            for document in documents:
                metadata = document.metadata or {}
                hits.append(
                    {
                        "content": document.page_content,
                        "source": metadata.get("source"),
                        "section": metadata.get("section_path") or metadata.get("section_title"),
                        "topic": metadata.get("topic"),
                    }
                )
            return success(hits, message=f"已检索到{len(hits)}条知识库内容")
        except Exception:
            return failure("INTERNAL_ERROR", "知识库检索暂时不可用，请稍后再试")

    @tool(args_schema=EvaluateRefundArgs)
    def evaluate_refund(order_id: str, reason: str) -> dict[str, Any]:
        """根据订单和固定政策评估是否可以退款，不会创建退款记录。"""
        try:
            with ctx.db_factory() as session:
                order = query_service.get_order(session, user_id=ctx.user_id, order_id=order_id)
                if order is None:
                    return failure("NOT_FOUND", "未找到该订单")
                evaluation = policy_service.evaluate_refund_order(
                    order,
                    now=ctx.now(),
                    approval_threshold=ctx.threshold(),
                )
            evaluation["reason"] = reason.strip()
            if not evaluation["eligible"]:
                return failure("POLICY_REJECTED", "当前订单不符合退款政策", data=evaluation)
            return success(evaluation, message="订单符合退款条件")
        except Exception as exc:
            if isinstance(exc, PermissionError):
                return failure("FORBIDDEN", str(exc))
            return failure("INTERNAL_ERROR", "退款政策评估暂时不可用，请稍后再试")

    return [search_policy, evaluate_refund]


__all__ = ["build_policy_tools"]
