"""统一封装 API 与 LangGraph 交互的应用服务。"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)

ConversationEventType = Literal[
    "run.started",
    "message.delta",
    "message.completed",
    "run.failed",
    "stream.done",
]


class ConversationRunError(RuntimeError):
    """非流式图调用失败。"""

    def __init__(self, run_id: str) -> None:
        super().__init__("conversation run failed")
        self.run_id = run_id


@dataclass(frozen=True)
class ConversationResult:
    run_id: str
    thread_id: str
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ConversationMessage:
    """供前端展示的公开消息，不包含内部工具消息。"""

    message_id: str
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ConversationEvent:
    event_id: str
    run_id: str
    thread_id: str
    type: ConversationEventType
    data: dict[str, Any] = field(default_factory=dict)


class ConversationService:
    """通过稳定的运行时配置和事件边界调用已编译主图。"""

    def __init__(self, *, graph: Any, db_factory: Any, retriever: Any | None) -> None:
        self._graph = graph
        self._db_factory = db_factory
        self._retriever = retriever
        self._thread_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _config(self, *, user_id: str, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {
                "user_id": user_id,
                "thread_id": thread_id,
                "db_factory": self._db_factory,
                "retriever": self._retriever,
            }
        }

    @staticmethod
    def _input(message: str) -> dict[str, Any]:
        # 这些字段是单轮输出，不能沿用上一个 checkpoint 的值。
        return {
            "messages": [HumanMessage(content=message)],
            "answer": "",
            "sources": [],
            "tool_events": [],
            "error": "",
        }

    @staticmethod
    def _result(values: dict[str, Any], *, run_id: str, thread_id: str) -> ConversationResult:
        return ConversationResult(
            run_id=run_id,
            thread_id=thread_id,
            answer=str(values.get("answer") or ""),
            sources=list(values.get("sources") or []),
            tool_events=list(values.get("tool_events") or []),
        )

    @staticmethod
    def _event(
        event_type: ConversationEventType,
        *,
        run_id: str,
        thread_id: str,
        data: dict[str, Any] | None = None,
    ) -> ConversationEvent:
        return ConversationEvent(
            event_id=uuid4().hex,
            run_id=run_id,
            thread_id=thread_id,
            type=event_type,
            data=data or {},
        )

    @staticmethod
    def _chunk_text(chunk: Any) -> str:
        content = getattr(chunk, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            )
        return ""

    async def run(self, *, user_id: str, thread_id: str, message: str) -> ConversationResult:
        run_id = uuid4().hex
        config = self._config(user_id=user_id, thread_id=thread_id)
        try:
            async with self._thread_locks[thread_id]:
                values = await self._graph.ainvoke(self._input(message), config=config)
        except Exception as exc:
            logger.exception("Conversation run failed: run_id=%s thread_id=%s", run_id, thread_id)
            raise ConversationRunError(run_id) from exc
        return self._result(values, run_id=run_id, thread_id=thread_id)

    async def get_messages(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> list[ConversationMessage]:
        """读取 checkpoint 中当前会话的公开消息历史。"""
        config = self._config(user_id=user_id, thread_id=thread_id)
        async with self._thread_locks[thread_id]:
            snapshot = await self._graph.aget_state(config)

        messages: list[ConversationMessage] = []
        for index, message in enumerate(snapshot.values.get("messages", [])):
            if isinstance(message, HumanMessage):
                role: Literal["user", "assistant"] = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            else:
                continue
            content = self._chunk_text(message)
            if not content:
                continue
            messages.append(
                ConversationMessage(
                    message_id=str(getattr(message, "id", None) or f"{thread_id}-{index}"),
                    role=role,
                    content=content,
                )
            )
        return messages

    async def stream(
        self,
        *,
        user_id: str,
        thread_id: str,
        message: str,
    ) -> AsyncIterator[ConversationEvent]:
        run_id = uuid4().hex
        config = self._config(user_id=user_id, thread_id=thread_id)
        yield self._event("run.started", run_id=run_id, thread_id=thread_id)

        try:
            async with self._thread_locks[thread_id]:
                async for event in self._graph.astream_events(
                    self._input(message),
                    config=config,
                    version="v2",
                ):
                    if event.get("event") != "on_chat_model_stream":
                        continue
                    metadata = event.get("metadata") or {}
                    # 只有主客服节点的公开回复可以转换为客户端 token。
                    if metadata.get("langgraph_node") != "customer_service_agent":
                        continue
                    chunk = (event.get("data") or {}).get("chunk")
                    content = self._chunk_text(chunk) if chunk is not None else ""
                    if content:
                        yield self._event(
                            "message.delta",
                            run_id=run_id,
                            thread_id=thread_id,
                            data={"content": content},
                        )

                snapshot = await self._graph.aget_state(config)
                result = self._result(snapshot.values, run_id=run_id, thread_id=thread_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Conversation stream failed: run_id=%s thread_id=%s", run_id, thread_id)
            yield self._event(
                "run.failed",
                run_id=run_id,
                thread_id=thread_id,
                data={"code": "CONVERSATION_RUN_FAILED", "message": "客服服务暂时不可用，请稍后再试。"},
            )
            yield self._event("stream.done", run_id=run_id, thread_id=thread_id)
        else:
            yield self._event(
                "message.completed",
                run_id=run_id,
                thread_id=thread_id,
                data={
                    "answer": result.answer,
                    "sources": result.sources,
                    "tool_events": result.tool_events,
                },
            )
            yield self._event("stream.done", run_id=run_id, thread_id=thread_id)


__all__ = [
    "ConversationEvent",
    "ConversationEventType",
    "ConversationMessage",
    "ConversationResult",
    "ConversationRunError",
    "ConversationService",
]
