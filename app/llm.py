"""Shared OpenAI-compatible chat model construction."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def build_chat_model(*, model: Any | None = None, temperature: float = 0, streaming: bool = False) -> Any:
    """返回注入的模型，或一个延迟配置的 OpenAI 兼容模型。"""
    if model is not None:
        return model
    load_dotenv()
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.startswith("replace-with-"):
        raise ValueError("LLM_API_KEY is not configured")
    kwargs: dict[str, Any] = {
        "model": os.getenv("LLM_MODEL", "qwen3.7-plus"),
        "api_key": api_key,
        "temperature": temperature,
        "streaming": streaming,
    }
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


__all__ = ["build_chat_model"]
