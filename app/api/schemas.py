"""公开 API 使用的稳定 HTTP 与 SSE 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    is_admin: bool = False


class ChatRequest(ApiModel):
    message: str | None = Field(default=None, min_length=1, max_length=8000)
    resume: dict[str, Any] | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("message 不能为空")
        return value

    @field_validator("resume")
    @classmethod
    def validate_resume(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if value.get("kind") != "refund_confirmation":
            raise ValueError("resume.kind 不合法")
        if value.get("decision") not in {"confirm", "cancel"}:
            raise ValueError("resume.decision 不合法")
        return value

    @model_validator(mode="after")
    def validate_input(self) -> "ChatRequest":
        if (self.message is None) == (self.resume is None):
            raise ValueError("message 与 resume 必须二选一")
        return self


class AdminDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]


class SourceItem(ApiModel):
    source: str | None = None
    section: str | None = None
    topic: str | None = None
    content: str | None = None


class ToolEventItem(ApiModel):
    tool: str
    result: Any = None


class ChatResponse(ApiModel):
    run_id: str
    thread_id: str
    title: str | None = None
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    tool_events: list[ToolEventItem] = Field(default_factory=list)
    pending_action: dict[str, Any] | None = None


class MessageItem(ApiModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceItem] = Field(default_factory=list)


class ThreadMessagesResponse(ApiModel):
    thread_id: str
    title: str | None = None
    messages: list[MessageItem]
    pending_action: dict[str, Any] | None = None


class StreamEventEnvelope(ApiModel):
    schema_version: Literal["1"] = "1"
    event_id: str
    run_id: str
    thread_id: str
    type: ConversationEventType
    data: dict[str, Any] = Field(default_factory=dict)


class ThreadItem(ApiModel):
    thread_id: str
    title: str | None = None
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
    "AdminDecisionRequest",
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
