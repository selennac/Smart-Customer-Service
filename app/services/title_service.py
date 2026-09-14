"""Generate stable conversation titles from the first exchange."""

from __future__ import annotations

import re
from typing import Any, Iterable

from langchain_core.messages import AIMessage, HumanMessage

from app.llm import build_chat_model
from app.nodes.common import text_content


TITLE_PROMPT = """
你负责为电商客服会话生成标题。根据用户的第一条消息和客服对这条消息的回复，
提炼一个准确、简洁的中文标题。只输出标题本身，不要引号、序号、前缀或解释。
标题控制在 6 到 20 个汉字以内，突出用户要解决的主要问题。
""".strip()


def _first_exchange(messages: Iterable[Any]) -> tuple[str, str] | None:
    first_user: str | None = None
    first_assistant: str | None = None
    for message in messages:
        content = text_content(message).strip()
        if not content:
            continue
        role = getattr(message, "role", None)
        is_user = isinstance(message, HumanMessage) or role == "user"
        is_assistant = isinstance(message, AIMessage) or role == "assistant"
        if first_user is None and is_user:
            first_user = content
        elif first_user is not None and is_assistant:
            first_assistant = content
            break
    if not first_user or not first_assistant:
        return None
    return first_user, first_assistant


def _clean_title(value: str) -> str:
    title = value.strip().splitlines()[0] if value.strip() else ""
    title = re.sub(r"^标题\s*[:：]\s*", "", title)
    title = title.strip(" `\"'“”‘’《》")
    title = re.sub(r"\s+", " ", title)
    return title[:200].strip()


def generate_title(messages: Iterable[Any], *, model: Any | None = None) -> str | None:
    """Return an AI title, with a local fallback when the model is unavailable."""
    exchange = _first_exchange(messages)
    if exchange is None:
        return None
    user_text, assistant_text = exchange
    try:
        llm = build_chat_model(model=model)
        response = llm.invoke(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": f"用户：{user_text}\n客服：{assistant_text}"},
            ]
        )
        title = _clean_title(text_content(response))
        if title:
            return title
    except Exception:
        # A title must never make an otherwise successful customer reply fail.
        pass

    fallback = _clean_title(user_text)
    return fallback[:80] if fallback else None


__all__ = ["TITLE_PROMPT", "generate_title"]
