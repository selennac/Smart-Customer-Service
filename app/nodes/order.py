"""Read-only order lookup ReAct node."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from app.llm import build_chat_model
from app.nodes.common import build_tool_context, runtime_config, text_content
from app.state import CustomerServiceState
from app.tools.query_tools import build_query_tools


def order_agent(
    state: CustomerServiceState,
    config: RunnableConfig = None,
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    try:
        ctx = build_tool_context(state, config)
        if not ctx.user_id:
            raise ValueError("user_id is required")
        llm = build_chat_model(model=model or runtime_config(config).get("model"))
        agent = create_react_agent(
            llm,
            build_query_tools(ctx),
            prompt=(
                "You are a customer service order assistant. Use only the read-only tools provided. "
                "Never invent order IDs or statuses. Ask for an order ID when needed, and answer in Chinese."
            ),
        )
        existing = state.get("messages", [])
        result = agent.invoke({"messages": existing})
        all_messages = result.get("messages", [])
        new_messages = all_messages[len(existing):] if len(all_messages) >= len(existing) else all_messages
        answer = ""
        events: list[dict[str, Any]] = []
        for message in new_messages:
            if isinstance(message, ToolMessage):
                raw = text_content(message)
                try:
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    payload = raw
                events.append({"tool": message.name, "result": payload})
            elif isinstance(message, AIMessage) and text_content(message).strip():
                answer = text_content(message)
        if not answer and all_messages:
            answer = text_content(all_messages[-1])
        return {"messages": new_messages, "answer": answer, "tool_events": events, "error": ""}
    except Exception as exc:
        return {
            "answer": "订单查询暂时不可用，请稍后再试。",
            "tool_events": [],
            "error": f"order agent failed: {exc}",
        }


__all__ = ["order_agent"]
