"""主图的结构化意图分类。"""

from __future__ import annotations

import os
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import build_chat_model
from app.state import CustomerServiceState


class IntentResult(BaseModel):
    intent: Literal["faq", "order", "after_sale", "unknown"]
    confidence: float = Field(ge=0, le=1)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return str(content)


def _last_user_text(state: CustomerServiceState) -> str:
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) in {"human", "user"}:
            return _message_text(message)
    messages = state.get("messages", [])
    return _message_text(messages[-1]) if messages else ""


def classify_intent(
    state: CustomerServiceState,
) -> dict[str, Any]:
    """对最新的用户轮次进行分类；模型失败时有意路由到兜底逻辑。"""
    text = _last_user_text(state)
    existing_error = state.get("error", "")
    if existing_error:
        return {"intent": "unknown", "intent_confidence": 0.0, "error": existing_error}
    if not text.strip():
        return {"intent": "unknown", "intent_confidence": 0.0, "error": "empty user message"}
    try:
        llm = build_chat_model()
        structured = llm.with_structured_output(IntentResult)
        result = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "将客户请求分类为 faq、order、after_sale 或 unknown。"
                        "仅在涉及退款、换货、投诉或其他售后操作时使用 after_sale。"
                        "订单详情或物流跟踪使用 order。只返回符合 schema 的结果。"
                    )
                ),
                HumanMessage(content=text),
            ]
        )
        parsed = result if isinstance(result, IntentResult) else IntentResult.model_validate(result)
        return {
            "intent": parsed.intent,
            "intent_confidence": parsed.confidence,
            "error": existing_error,
        }
    except Exception as exc:
        return {
            "intent": "unknown",
            "intent_confidence": 0.0,
            "error": existing_error or f"intent classification failed: {exc}",
        }


def route_intent(state: CustomerServiceState) -> str:
    """返回图节点名称，低置信度和错误情况保持在兜底逻辑上。"""
    if state.get("error"):
        return "fallback"
    try:
        threshold = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.65"))
    except ValueError:
        threshold = 0.65
    intent = state.get("intent", "unknown")
    if state.get("intent_confidence", 0.0) < threshold or intent == "unknown":
        return "fallback"
    return intent


__all__ = ["IntentResult", "classify_intent", "route_intent"]
