"""LangGraph assembly for the unified customer-service agent."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from app.db.models import Thread
from app.nodes.common import build_tool_context, runtime_config, text_content
from app.nodes.customer_service import customer_service_agent
from app.state import CustomerServiceState

logger = logging.getLogger(__name__)


def hydrate_context(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    """将已认证的标识符从运行时配置复制到图状态中。"""
    runtime = runtime_config(config)
    supplied_context = runtime.get("tool_context")
    user_id = runtime.get("user_id") or getattr(supplied_context, "user_id", None)
    thread_id = runtime.get("thread_id") or getattr(supplied_context, "thread_id", None)
    result: dict[str, Any] = {}
    if user_id:
        result["user_id"] = user_id
    if thread_id:
        result["thread_id"] = thread_id
    if not user_id or not thread_id:
        result["error"] = "user_id and thread_id are required"
    else:
        # 在处理新一轮对话之前，清除上一轮对话的临时错误。
        result["error"] = ""
    return result


def fallback_node(state: CustomerServiceState) -> dict[str, Any]:
    if state.get("error"):
        answer = "客服服务暂时不可用，请稍后再试。"
    else:
        answer = "我还不能确定您的需求。请说明是咨询政策、查询订单/物流，还是办理售后。"
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


def route_agent_result(state: CustomerServiceState) -> str:
    """仅在执行失败或智能体响应为空时使用兜底逻辑。"""
    if state.get("error") or not state.get("answer", "").strip():
        return "fallback"
    return "finalize_response"


def finalize_response(state: CustomerServiceState) -> dict[str, Any]:
    answer = state.get("answer", "").strip()
    if not answer and state.get("messages"):
        answer = text_content(state["messages"][-1])
    return {"answer": answer or "暂时没有可返回的结果。", "last_message": answer}


def update_thread(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    """当数据库工厂可用时，持久化对话摘要。"""
    thread_id = state.get("thread_id")
    user_id = state.get("user_id")
    if not thread_id or not user_id:
        return {}
    runtime = runtime_config(config)
    if "db_factory" not in runtime and "tool_context" not in runtime:
        return {}
    try:
        ctx = build_tool_context(state, config)
        with ctx.db_factory() as session:
            with session.begin():
                thread = session.scalar(
                    select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user_id)
                )
                if thread is not None:
                    thread.last_message = state.get("last_message") or state.get("answer")
    except Exception:
        # 持久化操作不应掩盖已成功生成的客户回复。
        logger.exception("Failed to update thread summary: thread_id=%s", thread_id)
        return {"error": state.get("error", "")}
    return {}


def build_graph(*, checkpointer: Any | None = None):
    """构建并编译主图。

    运行时值通过 ``configurable`` 提供（``user_id``、
    ``thread_id``、``db_factory``、``retriever`` 或 ``tool_context``）。
    """
    builder = StateGraph(CustomerServiceState)
    builder.add_node("hydrate_context", hydrate_context)
    builder.add_node("customer_service_agent", customer_service_agent)
    builder.add_node("fallback", fallback_node)
    builder.add_node("finalize_response", finalize_response)
    builder.add_node("update_thread", update_thread)

    builder.add_edge(START, "hydrate_context")
    builder.add_edge("hydrate_context", "customer_service_agent")
    builder.add_conditional_edges(
        "customer_service_agent",
        route_agent_result,
        {"fallback": "fallback", "finalize_response": "finalize_response"},
    )
    builder.add_edge("fallback", "finalize_response")
    builder.add_edge("finalize_response", "update_thread")
    builder.add_edge("update_thread", END)
    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "build_graph",
    "customer_service_agent",
    "fallback_node",
    "finalize_response",
    "hydrate_context",
    "route_agent_result",
    "update_thread",
]
