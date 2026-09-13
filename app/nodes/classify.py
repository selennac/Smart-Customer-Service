"""统一客服入口的结构化意图分类。"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.llm import build_chat_model
from app.nodes.common import runtime_config, text_content
from app.state import CustomerServiceState


class IntentDecision(BaseModel):
    """分类器只描述意图，不授权任何写操作。"""

    intent: Literal["general", "after_sale"] = Field(
        default="general",
        description="用户明确要求办理售后写操作时返回 after_sale，否则返回 general。",
    )
    action: Literal["refund", "exchange", "complaint"] | None = Field(
        default=None,
        description="仅当 intent=after_sale 时填写；否则为 null。",
    )
    order_id: str | None = Field(
        default=None,
        max_length=64,
        description="对话原文中出现的订单号，不得编造；无则为 null。",
    )
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="用户明确表达的售后原因；非售后请求为 null，不得补充。",
    )


CLASSIFY_PROMPT = """
你是电商客服系统的意图分类器，只判断意图，不执行任何操作。

分类规则：
1. general：商品/平台政策咨询、订单或物流查询、普通问候、规则说明，以及其他非售后写操作请求。
2. after_sale：用户明确要求办理退款、投诉、换货或创建售后工单。
3. 缺少订单号不影响 after_sale 判定；订单号只能来自对话原文，不得编造。
4. 意图不明确时，一律归为 general。
""".strip()


def _recent_context(state: CustomerServiceState) -> str:
    messages = state.get("messages", [])[-8:]
    lines: list[str] = []
    for message in messages:
        role = "用户" if isinstance(message, HumanMessage) else "客服"
        content = text_content(message).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def classify_intent(
        state: CustomerServiceState,
        config: RunnableConfig = None,
        *,
        model: Any | None = None,
) -> dict[str, Any]:
    """使用结构化 LLM 输出决定进入普通客服还是售后子图。"""
    if state.get("error"):
        return {"intent": "general"}
    try:
        llm = build_chat_model(model=model or runtime_config(config).get("model"))
        classifier = llm.with_structured_output(IntentDecision)
        decision = classifier.invoke(
            [
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": _recent_context(state)},
            ]
        )
        if isinstance(decision, IntentDecision):
            parsed = decision
        else:
            parsed = IntentDecision.model_validate(decision)
        result = parsed.model_dump()
        result["after_sale_action"] = result.pop("action")
        if parsed.intent == "after_sale" and parsed.action in {"refund", "ticket", "exchange", "complaint"}:
            return result
        result["intent"] = "general"
        result["after_sale_action"] = None
        result["order_id"] = None
        result["reason"] = None
        return result
    except Exception:
        # 分类失败时不冒险执行写操作，交给主图的普通兜底回复。
        return {"intent": "general", "after_sale_action": None, "order_id": None, "reason": None}


def route_intent(state: CustomerServiceState) -> str:
    if state.get("error"):
        return "general"
    if state.get("intent") == "after_sale":
        return "after_sale"
    return "general"


__all__ = ["IntentDecision", "CLASSIFY_PROMPT", "classify_intent", "route_intent"]
