"""Small adapters shared by graph nodes."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from langchain_core.runnables import RunnableConfig
from app.rag.retriever import get_retriever
from app.tools.context import ToolContext


def runtime_config(config: RunnableConfig | dict[str, Any] | None) -> dict[str, Any]:
    if not config:
        return {}
    configurable = config.get("configurable")
    return configurable if isinstance(configurable, dict) else config


def build_tool_context(state: dict[str, Any], config: RunnableConfig | None = None) -> ToolContext:
    """从已认证的运行时值构建上下文，绝不使用模型输出。"""
    runtime = runtime_config(config)
    supplied = runtime.get("tool_context")
    if isinstance(supplied, ToolContext):
        return replace(
            supplied,
            user_id=runtime.get("user_id") or supplied.user_id,
            thread_id=runtime.get("thread_id") or supplied.thread_id,
        )
    return ToolContext(
        user_id=runtime.get("user_id") or state.get("user_id", ""),
        thread_id=runtime.get("thread_id") or state.get("thread_id", ""),
        actor_role="customer",
        db_factory=runtime.get("db_factory") or ToolContext.__dataclass_fields__["db_factory"].default,
        retriever=runtime.get("retriever"),
    )


def resolve_retriever(ctx: ToolContext):
    if ctx.retriever is not None:
        return ctx.retriever
    persist = os.getenv("CHROMA_PERSIST_DIRECTORY")
    if not persist:
        return None
    try:
        return get_retriever(persist_directory=persist)
    except Exception:
        return None


def text_content(value: Any) -> str:
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return str(content)


__all__ = ["build_tool_context", "resolve_retriever", "runtime_config", "text_content"]
