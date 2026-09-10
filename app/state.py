"""Shared state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


Intent = Literal["faq", "order", "after_sale"]
AfterSaleAction = Literal["refund", "ticket"]
PendingAction = Literal["user_confirm", "supervisor_approval"]


class CustomerServiceState(TypedDict, total=False):
    """Serializable graph state for one ``thread_id`` conversation.

    ``messages`` uses LangGraph's reducer so streaming/tool nodes can append
    messages without overwriting earlier turns. Approval flags mirror the
    ``threads`` table and are useful when the graph is suspended by HITL.
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
    tool_events: list[dict[str, Any]]
    refund_id: str
    refund_amount: float
    pending_action: PendingAction
    requires_user_confirmation: bool
    requires_supervisor_approval: bool
    error: str


GraphState = CustomerServiceState

__all__ = ["CustomerServiceState", "GraphState", "Intent", "AfterSaleAction", "PendingAction"]
