"""公开 API 使用的稳定 HTTP 与 SSE 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import ThreadStatus
from app.services.conversation_service import ConversationEventType


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(ApiModel):
    user_id: str = Field(min_length=1, max_length=64)

    @field_validator("user_id")
    @classmethod
    def strip_user_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_id 不能为空")
        return value


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            print(123)
            raise ValueError("message 不能为空")
        return value


class SourceItem(ApiModel):
    source: str | None = None
    section: str | None = None
    topic: str | None = None


class ToolEventItem(ApiModel):
    tool: str
    result: Any = None


class ChatResponse(ApiModel):
    run_id: str
    thread_id: str
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    tool_events: list[ToolEventItem] = Field(default_factory=list)


class MessageItem(ApiModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str


class ThreadMessagesResponse(ApiModel):
    thread_id: str
    messages: list[MessageItem]


class StreamEventEnvelope(ApiModel):
    schema_version: Literal["1"] = "1"
    event_id: str
    run_id: str
    thread_id: str
    type: ConversationEventType
    data: dict[str, Any] = Field(default_factory=dict)


class ThreadItem(ApiModel):
    thread_id: str
    status: ThreadStatus
    last_message: str | None
    created_at: datetime
    updated_at: datetime


class ThreadListResponse(ApiModel):
    items: list[ThreadItem]
    next_cursor: str | None = None


class ThreadCreatedResponse(ApiModel):
    thread_id: str
    status: ThreadStatus


class ErrorBody(ApiModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ErrorBody",
    "ErrorResponse",
    "LoginRequest",
    "MessageItem",
    "SourceItem",
    "StreamEventEnvelope",
    "ThreadCreatedResponse",
    "ThreadItem",
    "ThreadListResponse",
    "ThreadMessagesResponse",
    "TokenResponse",
    "ToolEventItem",
]
