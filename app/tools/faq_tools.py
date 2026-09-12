"""Knowledge-base search tool exposed to the customer-service agent."""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.rag.retriever import get_retriever
from app.tools.context import ToolContext
from app.tools.result import failure, success


def _resolve_retriever(ctx: ToolContext):
    if ctx.retriever is not None:
        return ctx.retriever
    persist_directory = os.getenv("CHROMA_PERSIST_DIRECTORY")
    if not persist_directory:
        return None
    try:
        return get_retriever(persist_directory=persist_directory)
    except Exception:
        return None


def build_faq_tools(ctx: ToolContext) -> list[BaseTool]:
    """Build FAQ search tools for one request's injected runtime context."""

    @tool
    def search_faq(query: str) -> dict[str, Any]:
        """Search the customer-service knowledge base for policy and product information."""
        retriever = _resolve_retriever(ctx)
        if retriever is None:
            return failure("NOT_CONFIGURED", "知识库暂未配置")
        try:
            documents = retriever.invoke(query)
            sources: list[dict[str, Any]] = []
            results: list[str] = []
            for document in documents:
                metadata = document.metadata or {}
                results.append(document.page_content)
                sources.append(
                    {
                        "source": metadata.get("source"),
                        "section": metadata.get("section_path") or metadata.get("section_title"),
                        "topic": metadata.get("topic"),
                    }
                )
            if not results:
                return success([], message="知识库中没有找到相关内容")
            return success(
                {"documents": results, "sources": sources},
                message=f"已找到{len(results)}条相关知识",
            )
        except Exception:
            return failure("INTERNAL_ERROR", "知识库搜索暂时不可用，请稍后再试")

    return [search_faq]


__all__ = ["build_faq_tools"]
