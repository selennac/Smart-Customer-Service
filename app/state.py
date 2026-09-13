"""Shared state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class CustomerServiceState(TypedDict, total=False):
    """用于单个 ``thread_id`` 会话的可序列化图状态。

    ``messages`` 使用 LangGraph 的 reducer，因此流式/工具节点可以追加
    消息而不会覆盖之前的轮次。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    user_id: str
    answer: str
    sources: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    last_message: str
    error: str
    intent: str
    after_sale_action: str
    confirmation: str
    order_id: str
    reason: str
    refund_id: str
    refund: dict[str, Any]
    after_sale_result: dict[str, Any]
    pending_action: dict[str, Any]


GraphState = CustomerServiceState

__all__ = ["CustomerServiceState", "GraphState"]
