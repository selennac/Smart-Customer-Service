"""Shared state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


Intent = Literal["faq", "order", "after_sale", "unknown"]
AfterSaleAction = Literal["refund", "ticket"]
PendingAction = Literal["user_confirm", "supervisor_approval"]


class CustomerServiceState(TypedDict, total=False):
    """用于单个 ``thread_id`` 会话的可序列化图状态。

    ``messages`` 使用 LangGraph 的 reducer，因此流式/工具节点可以追加
    消息而不会覆盖之前的轮次。审批标志与 ``threads`` 表对应，
    当图被 HITL（human-in-the-loop，人在环路）挂起时很有用。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    user_id: str
    intent: Intent
    intent_confidence: float
    after_sale_action: AfterSaleAction
    order_id: str
    answer: str
    retrieved_context: list[str]
    sources: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    last_message: str
    refund_id: str
    refund_amount: float
    pending_action: PendingAction
    requires_user_confirmation: bool
    requires_supervisor_approval: bool
    error: str


GraphState = CustomerServiceState

__all__ = ["CustomerServiceState", "GraphState", "Intent", "AfterSaleAction", "PendingAction"]
