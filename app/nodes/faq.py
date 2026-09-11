"""RAG-backed FAQ node."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.llm import build_chat_model
from app.nodes.common import build_tool_context, resolve_retriever, runtime_config, text_content
from app.state import CustomerServiceState


def _latest_question(state: CustomerServiceState) -> str:
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) in {"human", "user"}:
            return text_content(message)
    return text_content(state.get("messages", [])[-1]) if state.get("messages") else ""


def faq_node(
    state: CustomerServiceState,
    config: RunnableConfig = None,
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    question = _latest_question(state)
    ctx = build_tool_context(state, config)
    retriever = resolve_retriever(ctx)
    if retriever is None:
        return {
            "answer": "知识库暂未配置，暂时无法回答该问题。",
            "messages": [AIMessage(content="知识库暂未配置，暂时无法回答该问题。")],
            "retrieved_context": [],
            "sources": [],
            "error": "FAQ retriever is not configured",
        }
    try:
        documents = retriever.invoke(question)
        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        for document in documents:
            metadata = document.metadata or {}
            context_parts.append(document.page_content)
            sources.append(
                {
                    "source": metadata.get("source"),
                    "section": metadata.get("section_path") or metadata.get("section_title"),
                    "topic": metadata.get("topic"),
                }
            )
        if not context_parts:
            return {
                "answer": "知识库中没有找到相关内容，请补充一些细节。",
                "messages": [AIMessage(content="知识库中没有找到相关内容，请补充一些细节。")],
                "retrieved_context": [],
                "sources": [],
            }
        llm = build_chat_model(model=model or runtime_config(config).get("model"), temperature=0.2)
        response = llm.invoke(
            [
                SystemMessage(
                    content="仅依据给定知识库内容回答。找不到依据时明确说明，不要编造政策、金额或时效。"
                ),
                HumanMessage(
                    content=f"问题：{question}\n\n知识库：\n" + "\n\n---\n\n".join(context_parts)
                ),
            ]
        )
        return {
            "answer": text_content(response),
            "messages": [AIMessage(content=text_content(response))],
            "retrieved_context": context_parts,
            "sources": sources,
            "error": "",
        }
    except Exception as exc:
        return {
            "answer": "知识库服务暂时不可用，请稍后再试。",
            "messages": [AIMessage(content="知识库服务暂时不可用，请稍后再试。")],
            "retrieved_context": [],
            "sources": [],
            "error": f"FAQ failed: {exc}",
        }


__all__ = ["faq_node"]
