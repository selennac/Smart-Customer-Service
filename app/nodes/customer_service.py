"""Unified customer-service agent for conversational and read-only requests."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from app.llm import build_chat_model
from app.nodes.common import build_tool_context, runtime_config, text_content
from app.state import CustomerServiceState
from app.tools import build_faq_tools, build_query_tools

logger = logging.getLogger(__name__)


CUSTOMER_SERVICE_PROMPT = """
你是一个白熊电商客服助手。

你可以：
1. 回答商品、平台政策和服务规则问题；
2. 查询当前用户的订单、物流、工单和退款状态；
3. 介绍自己能够提供的客服服务；
4. 自然回应问候、感谢和告别。

工具规则：
1. 涉及商品或平台政策时，必须先使用 FAQ 知识库工具。
2. 涉及订单、物流、工单或退款状态时，使用对应的只读查询工具。
3. 只能根据工具返回的数据回答，不能编造订单号、状态、金额或政策。
4. 信息不足时，向用户询问必要细节。
5. 不要执行未提供工具支持的操作。
6. 当前只提供查询工具；对于提交退款、创建工单等写请求，不得声称操作已经完成。

范围限制：
1. 你只处理客服相关问题。
2. 对写代码、写论文等非客服请求，说明自己是客服助手，并引导用户咨询客服业务。
3. 对“你会做什么”“你能帮我什么”，介绍你的客服能力。
4. 问候、感谢和告别可以直接回复，不需要调用工具。

始终使用中文，语气自然、简洁、准确。
""".strip()


def customer_service_agent(
    state: CustomerServiceState,
    config: RunnableConfig = None,
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    """运行对话智能体及其只读工具，处理一轮对话。"""
    if state.get("error"):
        return {"error": state["error"]}
    try:
        ctx = build_tool_context(state, config)
        if not ctx.user_id:
            raise ValueError("user_id is required")
        llm = build_chat_model(model=model or runtime_config(config).get("model"), streaming=True)
        agent = create_react_agent(
            llm,
            [*build_faq_tools(ctx), *build_query_tools(ctx)],
            prompt=SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
        )
        existing = state.get("messages", [])
        # Pass the graph config through so nested model token events reach the
        # outer ConversationService stream.
        result = agent.invoke({"messages": existing}, config=config)
        all_messages = result.get("messages", [])
        new_messages = all_messages[len(existing):] if len(all_messages) >= len(existing) else all_messages
        answer = ""
        events: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for message in new_messages:
            if isinstance(message, ToolMessage):
                raw = text_content(message)
                try:
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    payload = raw
                events.append({"tool": message.name, "result": payload})
                if isinstance(payload, dict):
                    data = payload.get("data")
                    if isinstance(data, dict) and isinstance(data.get("sources"), list):
                        documents = data.get("documents")
                        for index, source in enumerate(data["sources"]):
                            if not isinstance(source, dict):
                                continue
                            item = dict(source)
                            if isinstance(documents, list) and index < len(documents):
                                item["content"] = str(documents[index])
                            sources.append(item)
            elif isinstance(message, AIMessage) and text_content(message).strip():
                answer = text_content(message)
        if not answer and all_messages:
            answer = text_content(all_messages[-1])
        if answer and sources:
            for message in reversed(new_messages):
                if isinstance(message, AIMessage) and text_content(message).strip() == answer.strip():
                    message.additional_kwargs = {
                        **(message.additional_kwargs or {}),
                        "sources": sources,
                    }
                    break
        return {
            "messages": new_messages,
            "answer": answer,
            "sources": sources,
            "tool_events": events,
            "error": "",
        }
    except Exception as exc:
        logger.exception("Customer service agent failed")
        return {
            "answer": "客服服务暂时不可用，请稍后再试。",
            "sources": [],
            "tool_events": [],
            "error": "customer_service_agent_failed",
        }


__all__ = ["CUSTOMER_SERVICE_PROMPT", "customer_service_agent"]
