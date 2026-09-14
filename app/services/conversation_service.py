"""统一封装 API 与 LangGraph 交互的应用服务。"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from sqlalchemy import select

from app.db.models import Thread
from app.services.title_service import generate_title

logger = logging.getLogger(__name__)

ConversationEventType = Literal[
    "run.started",
    "message.delta",
    "message.completed",
    "run.failed",
    "stream.done",
    "run.interrupted",
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
    title: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConversationMessage:
    """供前端展示的公开消息，不包含内部工具消息。"""

    message_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ConversationEvent:
    event_id: str
    run_id: str
    thread_id: str
    type: ConversationEventType
    data: dict[str, Any] = field(default_factory=dict)


class ConversationService:
    """通过稳定的运行时配置和事件边界调用已编译主图。"""

    def __init__(self, *, graph: Any, db_factory: Any, retriever: Any | None, title_model: Any | None = None) -> None:
        self._graph = graph
        self._db_factory = db_factory
        self._retriever = retriever
        self._title_model = title_model
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
    def _command_input(resume: dict[str, Any]) -> Command:
        return Command(resume=resume)

    @staticmethod
    def _pending(snapshot: Any) -> dict[str, Any] | None:
        values = getattr(snapshot, "values", {}) or {}
        pending = values.get("pending_action")
        if isinstance(pending, dict) and pending:
            return pending
        for task in getattr(snapshot, "tasks", ()) or ():
            for interrupt in getattr(task, "interrupts", ()) or ():
                value = getattr(interrupt, "value", None)
                if isinstance(value, dict):
                    return value
        return None

    @staticmethod
    def _result(values: dict[str, Any], *, run_id: str, thread_id: str, title: str | None = None) -> ConversationResult:
        return ConversationResult(
            run_id=run_id,
            thread_id=thread_id,
            title=title,
            answer=str(values.get("answer") or ""),
            sources=list(values.get("sources") or []),
            tool_events=list(values.get("tool_events") or []),
            pending_action=values.get("pending_action") if isinstance(values.get("pending_action"), dict) and values.get("pending_action") else None,
        )

    def _read_title(self, *, user_id: str, thread_id: str) -> str | None:
        with self._db_factory() as session:
            row = session.scalar(select(Thread.title).where(Thread.thread_id == thread_id, Thread.user_id == user_id))
            return str(row) if row else None

    def _save_title(self, *, user_id: str, thread_id: str, title: str) -> str | None:
        with self._db_factory() as session:
            with session.begin():
                thread = session.scalar(
                    select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user_id)
                )
                if thread is None:
                    return None
                if not thread.title:
                    thread.title = title
                return thread.title

    async def _ensure_title(self, *, user_id: str, thread_id: str, messages: list[Any]) -> str | None:
        """Generate and persist a title once the first user/assistant pair exists."""
        existing = await asyncio.to_thread(self._read_title, user_id=user_id, thread_id=thread_id)
        if existing:
            return existing
        generated = await asyncio.to_thread(generate_title, messages, model=self._title_model)
        if not generated:
            return None
        return await asyncio.to_thread(self._save_title, user_id=user_id, thread_id=thread_id, title=generated)

    async def ensure_title(self, *, user_id: str, thread_id: str, messages: list[Any]) -> str | None:
        """Generate a title while loading an older thread, when needed."""
        async with self._thread_locks[thread_id]:
            return await self._ensure_title(user_id=user_id, thread_id=thread_id, messages=messages)

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

    async def run(self, *, user_id: str, thread_id: str, message: str | None = None, resume: dict[str, Any] | None = None) -> ConversationResult:
        run_id = uuid4().hex
        config = self._config(user_id=user_id, thread_id=thread_id)
        try:
            async with self._thread_locks[thread_id]:
                values = await self._graph.ainvoke(
                    self._command_input(resume) if resume is not None else self._input(message or ""),
                    config=config,
                )
        except Exception as exc:
            logger.exception("Conversation run failed: run_id=%s thread_id=%s", run_id, thread_id)
            raise ConversationRunError(run_id) from exc
        if not values.get("pending_action") and values.get("__interrupt__"):
            interrupt_items = values.get("__interrupt__") or []
            first = interrupt_items[0] if interrupt_items else None
            value = getattr(first, "value", None)
            if isinstance(value, dict):
                values = {**values, "pending_action": value}
        title = await self._ensure_title(
            user_id=user_id,
            thread_id=thread_id,
            messages=list(values.get("messages") or []),
        )
        return self._result(values, run_id=run_id, thread_id=thread_id, title=title)

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
            # Interrupts inside the after-sale subgraph checkpoint separately.
            # Include that task state so its pending message survives reload.
            snapshots = [snapshot]
            for task in getattr(snapshot, "tasks", ()) or ():
                task_config = getattr(task, "state", None)
                if task_config:
                    try:
                        snapshots.append(await self._graph.aget_state(task_config))
                    except Exception:
                        logger.exception("Failed to read interrupted task state: thread_id=%s", thread_id)

        messages: list[ConversationMessage] = []
        seen_ids: set[str] = set()
        for state_snapshot in snapshots:
            for index, message in enumerate((getattr(state_snapshot, "values", {}) or {}).get("messages", [])):
                if isinstance(message, HumanMessage):
                    role: Literal["user", "assistant"] = "user"
                elif isinstance(message, AIMessage):
                    role = "assistant"
                else:
                    continue
                content = self._chunk_text(message)
                if not content:
                    continue
                message_id = str(getattr(message, "id", None) or f"{thread_id}-{index}")
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                raw_sources = (getattr(message, "additional_kwargs", {}) or {}).get("sources", [])
                sources = [source for source in raw_sources if isinstance(source, dict)] if isinstance(raw_sources, list) else []
                messages.append(
                    ConversationMessage(
                        message_id=message_id,
                        role=role,
                        content=content,
                        sources=sources,
                    )
                )
        return messages

    async def get_pending_action(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """Return the action currently waiting for a user or supervisor."""
        config = self._config(user_id=user_id, thread_id=thread_id)
        async with self._thread_locks[thread_id]:
            snapshot = await self._graph.aget_state(config)
        return self._pending(snapshot)

    async def delete_thread(self, *, thread_id: str) -> None:
        """Remove all LangGraph checkpoints for a thread after ownership is checked by the API."""
        checkpointer = getattr(self._graph, "checkpointer", None)
        if checkpointer is None:
            return
        delete = getattr(checkpointer, "adelete_thread", None)
        if delete is None:
            raise RuntimeError("configured checkpointer does not support thread deletion")
        async with self._thread_locks[thread_id]:
            await delete(thread_id)

    async def stream(
        self,
        *,
        user_id: str,
        thread_id: str,
        message: str | None = None,
        resume: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConversationEvent]:
        run_id = uuid4().hex
        config = self._config(user_id=user_id, thread_id=thread_id)
        yield self._event("run.started", run_id=run_id, thread_id=thread_id)

        try:
            async with self._thread_locks[thread_id]:
                async for event in self._graph.astream_events(
                    self._command_input(resume) if resume is not None else self._input(message or ""),
                    config=config,
                    version="v2",
                ):
                    if event.get("event") != "on_chat_model_stream":
                        continue
                    metadata = event.get("metadata") or {}
                    # 只有主客服节点的公开回复可以转换为客户端 token。
                    # ReAct 智能体是一个嵌套图，因此其模型事件
                    # 可能会被标记为外层节点或嵌套的 ``agent`` 节点，
                    # 具体取决于 LangGraph 的版本。
                    if metadata.get("langgraph_node") not in {"customer_service_agent", "agent"}:
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
                values = snapshot.values or {}
                pending = self._pending(snapshot)
            title = await self._ensure_title(
                user_id=user_id,
                thread_id=thread_id,
                messages=list(values.get("messages") or []),
            )
            result = self._result(values, run_id=run_id, thread_id=thread_id, title=title)
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
            if pending:
                yield self._event(
                    "run.interrupted",
                    run_id=run_id,
                    thread_id=thread_id,
                    data={"answer": result.answer, "title": result.title, **pending},
                )
            else:
                yield self._event(
                    "message.completed",
                    run_id=run_id,
                    thread_id=thread_id,
                    data={
                        "answer": result.answer,
                        "title": result.title,
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
